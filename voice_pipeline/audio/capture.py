"""
Audio Capture Module
====================
Captures audio from microphone — supports sounddevice, pyaudio, and Termux CLI fallback.
"""

from __future__ import annotations

import io
import os
import queue
import subprocess
import threading
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class AudioCaptureError(Exception):
    """Raised when audio capture fails."""


class AudioCapture:
    """Captures raw audio frames from the microphone.

    Three backends are supported, tried in order:
    1. ``sounddevice`` — primary (portaudio-based, lowest latency)
    2. ``pyaudio`` — secondary
    3. ``termux-microphone-record`` — Termux Android fallback (file-based)
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frames_queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=config.pipeline_queue_maxsize
        )
        self._backend: Optional[str] = None
        self._stream = None
        self._pyaudio_instance = None
        self._termux_process: Optional[subprocess.Popen] = None
        self._termux_temp: Optional[str] = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def sample_rate(self) -> int:
        return self.cfg.sample_rate

    @property
    def channels(self) -> int:
        return self.cfg.channels

    @property
    def frames_queue(self) -> queue.Queue[np.ndarray]:
        return self._frames_queue

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start capturing audio in a background thread."""
        if self._running:
            self.log.warning("Audio capture already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="audio-capture",
            daemon=True,
        )
        self._thread.start()
        self.log.info(f"Audio capture started (backend={self._backend or 'probing'})")

    def stop(self) -> None:
        """Stop capture and join the background thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._cleanup()
        self.log.info("Audio capture stopped")

    def read(self, block: bool = True, timeout: Optional[float] = None) -> Optional[np.ndarray]:
        """Read one frame from the capture queue.

        Returns ``None`` on timeout / empty.
        """
        try:
            return self._frames_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def clear_queue(self) -> None:
        """Drop all pending frames."""
        while not self._frames_queue.empty():
            try:
                self._frames_queue.get_nowait()
            except queue.Empty:
                break

    # ── Internal ─────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Main capture loop — tries backends in order."""
        backends = [
            ("sounddevice", self._capture_sounddevice),
            ("pyaudio", self._capture_pyaudio),
            ("termux", self._capture_termux),
        ]

        for name, func in backends:
            if not self._running:
                return
            try:
                self.log.info(f"Trying audio backend: {name}")
                func()
                self._backend = name
                self.log.info(f"Audio backend active: {name}")
                return  # exited normally (stream ended)
            except AudioCaptureError:
                self.log.warning(f"Audio backend '{name}' unavailable, skipping")
                continue
            except Exception as exc:
                self.log.warning(f"Audio backend '{name}' failed: {exc}")
                continue

        self.log.error("All audio backends failed — no microphone available")

    def _cleanup(self) -> None:
        """Release backend resources."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pyaudio_instance is not None:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None

        if self._termux_process is not None:
            try:
                self._termux_process.terminate()
                self._termux_process.wait(timeout=3)
            except Exception:
                self._termux_process.kill()
            self._termux_process = None

        if self._termux_temp and os.path.exists(self._termux_temp):
            try:
                os.unlink(self._termux_temp)
            except Exception:
                pass
            self._termux_temp = None

    # ── Backend: sounddevice ─────────────────────────────────────────────

    def _capture_sounddevice(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            raise AudioCaptureError("sounddevice not installed")

        device = self.cfg.input_device

        def callback(indata: np.ndarray, _frames: int, _time_info, _status):
            if self._running:
                # indata shape: (frames, channels)
                mono = indata.mean(axis=1, keepdims=True) if indata.shape[1] > 1 else indata
                self._frames_queue.put(mono.copy(), timeout=2)

        self._stream = sd.InputStream(
            samplerate=self.cfg.sample_rate,
            device=device,
            channels=self.cfg.channels,
            dtype=self.cfg.dtype,
            callback=callback,
            blocksize=int(self.cfg.sample_rate * self.cfg.frame_seconds),
        )
        self._stream.start()

        # Block until stopped
        while self._running:
            time.sleep(0.1)

    # ── Backend: pyaudio ─────────────────────────────────────────────────

    def _capture_pyaudio(self) -> None:
        try:
            import pyaudio  # type: ignore
        except ImportError:
            raise AudioCaptureError("pyaudio not installed")

        p = pyaudio.PyAudio()
        self._pyaudio_instance = p

        frames_per_buffer = int(self.cfg.sample_rate * self.cfg.frame_seconds)

        def callback(in_data, _frame_count, _time_info, _status):
            if self._running:
                arr = np.frombuffer(in_data, dtype=np.float32).reshape(-1, 1)
                try:
                    self._frames_queue.put(arr, timeout=2)
                except queue.Full:
                    pass
            return (None, pyaudio.paContinue)

        self._stream = p.open(
            format=pyaudio.paFloat32,
            channels=self.cfg.channels,
            rate=self.cfg.sample_rate,
            input=True,
            frames_per_buffer=frames_per_buffer,
            stream_callback=callback,
        )
        self._stream.start_stream()

        while self._running:
            time.sleep(0.1)

    # ── Backend: Termux CLI ──────────────────────────────────────────────

    def _capture_termux(self) -> None:
        """Use ``termux-microphone-record`` to capture audio via temp file polling."""
        cmd = self.cfg.termux_mic_command
        if not self._command_exists(cmd):
            raise AudioCaptureError(f"{cmd} not found on PATH")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        self._termux_temp = tmp.name

        proc = subprocess.Popen(
            [cmd, "--rate", str(self.cfg.sample_rate), "--channels", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._termux_process = proc

        # Poll the temp file for new data
        last_size = 0
        import struct
        import wave

        while self._running:
            time.sleep(0.1)
            if proc.poll() is not None:
                raise AudioCaptureError("termux-microphone-record exited unexpectedly")

            try:
                with wave.open(self._termux_temp, "rb") as wf:
                    data = wf.readframes(wf.getnframes())
                    if len(data) > last_size:
                        new_data = data[last_size:]
                        last_size = len(data)
                        arr = np.frombuffer(new_data, dtype=np.int16).astype(np.float32) / 32768.0
                        self._frames_queue.put(arr.reshape(-1, 1), timeout=2)
            except (FileNotFoundError, wave.Error, struct.error):
                # File not ready yet
                pass

    # ── Utils ────────────────────────────────────────────────────────────

    @staticmethod
    def _command_exists(cmd: str) -> bool:
        return any(
            os.access(os.path.join(p, cmd), os.X_OK)
            for p in os.environ.get("PATH", "").split(os.pathsep)
            if os.path.exists(os.path.join(p, cmd))
        )
