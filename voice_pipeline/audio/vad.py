"""
Voice Activity Detection (VAD)
===============================
Detects speech segments in raw audio using WebRTC VAD (primary)
or Silero VAD (optional torch-based fallback).
"""

from __future__ import annotations

import collections
import struct
from typing import Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class VADError(Exception):
    """Raised when VAD initialisation fails."""


class VoiceActivityDetector:
    """Detects when someone is speaking in a raw audio stream.

    Two backends:
    1. ``webrtcvad`` — lightweight, no ML dependencies (primary)
    2. ``Silero VAD`` (torch) — more accurate, heavier (fallback)

    Produces speech segments with configurable padding.
    """

    def __init__(
        self,
        config: VoiceConfig,
        log: Optional[VoiceLogger] = None,
        on_speech_start: Optional[callable] = None,
        on_speech_end: Optional[callable] = None,
    ):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end
        self._vad = None
        self._backend: Optional[str] = None

        # Internal state
        self._buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._speaking = False
        self._speech_frames: collections.deque = collections.deque()
        self._silence_frames = 0
        self._speech_detected = False

        # Compute frame sizes
        self._frame_ms = config.vad_frame_ms
        self._frame_samples = int(config.sample_rate * self._frame_ms / 1000)

        # Silence counters (in frames)
        self._min_speech_frames = max(1, int(config.min_speech_duration_ms / self._frame_ms))
        self._min_silence_frames = max(1, int(config.min_silence_duration_ms / self._frame_ms))
        self._pad_frames = max(0, int(config.speech_pad_ms / self._frame_ms))

        # Pre-allocate ring buffer for speech
        self._max_pad_samples = self._pad_frames * self._frame_samples
        self._pre_speech_buffer = collections.deque(maxlen=self._max_pad_samples)

    # ── Initialisation ──────────────────────────────────────────────────

    def start(self) -> None:
        """Initialise the VAD backend (lazy-load)."""
        if self._vad is not None:
            return

        # Try webrtcvad first
        try:
            import webrtcvad  # type: ignore

            self._vad = webrtcvad.Vad(self.cfg.vad_mode)
            self._backend = "webrtcvad"
            self.log.info(f"VAD initialised: webrtcvad (mode={self.cfg.vad_mode})")
            return
        except ImportError:
            self.log.info("webrtcvad not available, trying Silero VAD")

        # Fallback to Silero VAD
        try:
            self._init_silero()
            self._backend = "silero"
            self.log.info("VAD initialised: Silero VAD")
            return
        except Exception as exc:
            raise VADError(f"Failed to load any VAD backend: {exc}")

    def _init_silero(self) -> None:
        """Load Silero VAD model."""
        import torch  # type: ignore
        import torchaudio  # type: ignore

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
        )
        (self._get_speech_timestamps, self._save_audio, self._read_audio, self._validate, self._collect_chunks) = utils

        self._silero_model = model
        self._silero_utils = utils

    # ── Detection ────────────────────────────────────────────────────────

    def is_speech(self, frame: np.ndarray) -> bool:
        """Check if a single audio frame contains speech.

        ``frame`` must be 16-bit PCM 16 kHz mono — resampling is done internally.
        """
        if self._vad is None:
            self.start()

        if self._backend == "webrtcvad":
            return self._is_speech_webrtc(frame)
        elif self._backend == "silero":
            return self._is_speech_silero(frame)
        return False

    def is_speaking(self) -> bool:
        """Whether VAD currently detects active speech."""
        return self._speaking

    def process_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Process one audio frame and return a speech segment if speech ended.

        This is the main high-level API:

        * Accumulates frames while speech is detected.
        * Returns a complete speech segment (with padding) once silence is detected.
        * Returns ``None`` while still building the segment.
        """
        if self._vad is None:
            self.start()

        # Keep pre-speech buffer
        self._pre_speech_buffer.append(frame.copy())

        speaking = self.is_speech(frame)

        if speaking and not self._speaking:
            # Speech just started
            self._speaking = True
            self._silence_frames = 0
            # Add pre-speech padding
            for f in self._pre_speech_buffer:
                self._speech_frames.append(f)
            self._speech_frames.append(frame)
            if self._on_speech_start:
                self._on_speech_start()
            return None

        if speaking and self._speaking:
            # Continuing speech
            self._silence_frames = 0
            self._speech_frames.append(frame)
            return None

        if not speaking and self._speaking:
            # Possible end of speech — count silence
            self._silence_frames += 1
            self._speech_frames.append(frame)  # keep trailing silence for padding

            if self._silence_frames >= self._min_silence_frames:
                # Speech ended — extract segment
                self._speaking = False
                segment = self._extract_segment()
                if self._on_speech_end:
                    self._on_speech_end()
                return segment

            return None

        # Idle
        return None

    # ── Segment extraction ──────────────────────────────────────────────

    def _extract_segment(self) -> Optional[np.ndarray]:
        """Concatenate buffered speech frames."""
        if not self._speech_frames:
            return None

        # Trim trailing silence to just the padding amount
        total = len(self._speech_frames)
        keep = total - max(0, self._silence_frames - self._pad_frames)
        keep = max(keep, 1)

        frames = list(self._speech_frames)[:keep]
        segment = np.concatenate(frames, axis=0) if len(frames) > 1 else frames[0]

        # Apply min speech duration check
        min_samples = int(self.cfg.min_speech_duration_ms * self.cfg.sample_rate / 1000)
        if len(segment) < min_samples:
            self._speech_frames.clear()
            self._buffer_samples = 0
            return None

        self._speech_frames.clear()
        self._buffer_samples = 0
        return segment

    # ── Backend: WebRTC ──────────────────────────────────────────────────

    def _is_speech_webrtc(self, frame: np.ndarray) -> bool:
        """WebRTC VAD expects 16-bit PCM at 8/16/32 kHz."""
        # Webrtcvad requires 16-bit PCM
        if frame.dtype != np.int16:
            int_frame = (frame * 32768).astype(np.int16)
        else:
            int_frame = frame

        raw = int_frame.tobytes()

        # Ensure correct frame length
        expected = self._frame_samples * 2  # 16-bit = 2 bytes
        if len(raw) < expected:
            return False

        try:
            return self._vad.is_speech(raw[:expected], self.cfg.sample_rate)
        except Exception:
            return False

    # ── Backend: Silero ──────────────────────────────────────────────────

    def _is_speech_silero(self, frame: np.ndarray) -> bool:
        """Silero VAD using torch."""
        import torch

        if not hasattr(self, "_silero_model"):
            return False

        # Ensure float32, mono, 16kHz
        if frame.dtype != np.float32:
            frame = frame.astype(np.float32)

        tensor = torch.from_numpy(frame).unsqueeze(0)
        with torch.no_grad():
            prob = self._silero_model(tensor, self.cfg.sample_rate).item()
        return prob >= self.cfg.vad_threshold

    # ── Reset ───────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear internal state for a fresh start."""
        self._buffer.clear()
        self._buffer_samples = 0
        self._speaking = False
        self._speech_frames.clear()
        self._silence_frames = 0
        self._pre_speech_buffer.clear()
