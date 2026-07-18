"""
Audio Playback Module
=====================
Plays synthesized audio through system speakers/sound device.
"""

from __future__ import annotations

import io
import os
import queue
import subprocess
import threading
import tempfile
import time
from typing import Callable, Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class PlaybackError(Exception):
    """Raised when audio playback fails."""


class AudioPlayback:
    """Plays audio chunks with support for cancellation (barge-in).

    Three backends:
    1. ``sounddevice`` — primary (lowest latency)
    2. ``pyaudio`` — secondary
    3. ``termux-media-player`` — Termux Android fallback
    """

    @staticmethod
    def _command_exists(cmd: str) -> bool:
        return any(
            os.access(os.path.join(p, cmd), os.X_OK)
            for p in os.environ.get("PATH", "").split(os.pathsep)
            if os.path.exists(os.path.join(p, cmd))
        )

    def __init__(
        self,
        config: VoiceConfig,
        log: Optional[VoiceLogger] = None,
        on_playback_start: Optional[Callable] = None,
        on_playback_end: Optional[Callable] = None,
    ):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._on_playback_start = on_playback_start
        self._on_playback_end = on_playback_end

        self._queue: queue.Queue = queue.Queue(maxsize=config.tts_queue_maxsize)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._cancel = threading.Event()
        self._playing = False
        self._stream = None
        self._pyaudio_instance = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the playback worker thread."""
        if self._running:
            return
        self._running = True
        self._cancel.clear()
        self._thread = threading.Thread(target=self._playback_loop, name="audio-playback", daemon=True)
        self._thread.start()
        self.log.info("Playback started")

    def stop(self) -> None:
        """Stop playback and join the worker."""
        self._running = False
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._cleanup()
        self.log.info("Playback stopped")

    def play(self, audio: np.ndarray, sample_rate: Optional[int] = None) -> None:
        """Enqueue audio for playback (non-blocking)."""
        try:
            self._queue.put((audio, sample_rate or self.cfg.sample_rate), timeout=2)
        except queue.Full:
            self.log.warning("Playback queue full, dropping audio")

    def cancel(self) -> None:
        """Cancel current playback immediately (barge-in)."""
        self._cancel.set()
        self._playing = False

    def clear_queue(self) -> None:
        """Drop all pending audio."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    # ── Internal ────────────────────────────────────────────────────────

    def _playback_loop(self) -> None:
        """Background loop: pull audio chunks from queue and play them."""
        backends = [
            ("sounddevice", self._play_sounddevice),
            ("pyaudio", self._play_pyaudio),
            ("termux", self._play_termux),
        ]

        while self._running:
            try:
                audio, sr = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if audio is None or len(audio) == 0:
                continue

            # Try each backend
            for name, func in backends:
                if not self._running:
                    return
                try:
                    self._playing = True
                    if self._on_playback_start:
                        self._on_playback_start()
                    func(audio, sr)
                    break
                except PlaybackError:
                    self.log.warning(f"Playback backend '{name}' unavailable")
                    continue
                except Exception as exc:
                    self.log.warning(f"Playback backend '{name}' failed: {exc}")
                    continue
            else:
                self.log.error("All playback backends failed")

            self._playing = False
            if self._on_playback_end:
                self._on_playback_end()

    def _cleanup(self) -> None:
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

    # ── Backend: sounddevice ─────────────────────────────────────────────

    def _play_sounddevice(self, audio: np.ndarray, sr: int) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            raise PlaybackError("sounddevice not installed")

        self._cancel.clear()
        audio = audio.flatten()

        def callback(outdata, _frames, _time_info, _status):
            if self._cancel.is_set():
                raise sd.CallbackStop()
            nonlocal audio
            n = len(outdata)
            if n > len(audio):
                n = len(audio)
                outdata[:n] = audio[:n].reshape(-1, 1)
                outdata[n:] = 0
                raise sd.CallbackStop()
            outdata[:] = audio[:n].reshape(-1, 1)
            audio = audio[n:]

        self._stream = sd.OutputStream(
            samplerate=sr,
            device=self.cfg.output_device,
            channels=1,
            callback=callback,
            blocksize=int(sr * 0.1),
        )
        self._stream.start()
        while self._stream.active:
            time.sleep(0.05)
        self._stream = None

    # ── Backend: pyaudio ─────────────────────────────────────────────────

    def _play_pyaudio(self, audio: np.ndarray, sr: int) -> None:
        try:
            import pyaudio  # type: ignore
        except ImportError:
            raise PlaybackError("pyaudio not installed")

        p = pyaudio.PyAudio()
        self._pyaudio_instance = p

        # Convert float32 to int16
        int_audio = (audio.flatten() * 32767).astype(np.int16).tobytes()

        def callback(in_data, _frame_count, _time_info, _status):
            nonlocal int_audio
            if self._cancel.is_set():
                return (b"", pyaudio.paComplete)
            chunk = int_audio[:4096]
            int_audio = int_audio[4096:]
            if not int_audio:
                return (chunk, pyaudio.paComplete)
            return (chunk, pyaudio.paContinue)

        self._stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sr,
            output=True,
            frames_per_buffer=4096,
            stream_callback=callback,
        )
        self._stream.start_stream()
        while self._stream.is_active():
            time.sleep(0.05)
            if self._cancel.is_set():
                self._stream.stop_stream()
                break
        self._stream = None

    # ── Backend: Termux CLI ──────────────────────────────────────────────

    def _play_termux(self, audio: np.ndarray, sr: int) -> None:
        """Write audio to temp WAV file and play via termux-media-player."""
        import wave

        cmd = self.cfg.termux_player_command
        if not self._command_exists(cmd):
            raise PlaybackError(f"{cmd} not found on PATH")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()

        try:
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sr)
                int_audio = (audio.flatten() * 32767).astype(np.int16)
                wf.writeframes(int_audio.tobytes())

            proc = subprocess.Popen(
                [cmd, "play", tmp.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait with cancel support
            while proc.poll() is None:
                if self._cancel.is_set():
                    proc.terminate()
                    subprocess.run([cmd, "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                time.sleep(0.05)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    # ── State query ──────────────────────────────────────────────────────

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Block until the queue is empty and playback finishes.

        Returns ``True`` if completed, ``False`` on timeout.
        """
        start = time.time()
        while self._playing or not self._queue.empty():
            if timeout and (time.time() - start) > timeout:
                return False
            time.sleep(0.05)
        return True
