"""
Speech-to-Text Engine (Faster-Whisper)
=======================================
Transcribes audio segments using Faster-Whisper with automatic
language detection, confidence scoring, and configurable model sizes.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class STTError(Exception):
    """Raised when transcription fails."""


class SpeechToText:
    """Faster-Whisper wrapper for efficient CPU/GPU transcription.

    Model is loaded lazily on first use. Supports:
    - Automatic language detection
    - Configurable beam size and compute type
    - Word-level timestamps (optional)
    - VAD filtering for cleaner segments
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._model = None
        self._model_lock = threading.Lock()
        self._model_loaded = False
        self._load_time: Optional[float] = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded

    @property
    def model_size(self) -> str:
        return self.cfg.whisper_model_size

    # ── Model Management ────────────────────────────────────────────────

    def load_model(self) -> None:
        """Lazy-load the Faster-Whisper model (thread-safe)."""
        if self._model_loaded:
            return

        with self._model_lock:
            if self._model_loaded:
                return

            try:
                from faster_whisper import WhisperModel  # type: ignore
            except ImportError:
                raise STTError(
                    "faster-whisper not installed. "
                    "Run: pip install faster-whisper"
                )

            self.log.info(
                f"Loading Faster-Whisper model '{self.cfg.whisper_model_size}' "
                f"(device={self.cfg.whisper_device}, "
                f"compute={self.cfg.whisper_compute_type})"
            )

            t0 = time.perf_counter()
            try:
                self._model = WhisperModel(
                    model_size_or_path=self.cfg.whisper_model_size,
                    device=self.cfg.whisper_device,
                    compute_type=self.cfg.whisper_compute_type,
                    cpu_threads=self.cfg.whisper_cpu_threads,
                    num_workers=self.cfg.whisper_num_workers,
                )
            except Exception as exc:
                raise STTError(f"Failed to load Whisper model: {exc}")

            self._load_time = time.perf_counter() - t0
            self._model_loaded = True
            self.log.info(
                f"Whisper model loaded in {self._load_time*1000:.0f}ms"
            )

    def unload_model(self) -> None:
        """Release model memory."""
        with self._model_lock:
            self._model = None
            self._model_loaded = False
            self._load_time = None
            self.log.info("Whisper model unloaded")

    # ── Transcription ───────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe an audio segment and return the text.

        Args:
            audio: Float32 mono audio array (values in [-1, 1]).

        Returns:
            Transcribed text string, or empty string on failure.

        Raises:
            STTError: If the model fails to load or transcribe.
        """
        self.load_model()

        if len(audio) == 0:
            return ""

        # Ensure float32, mono, flatten
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.flatten()

        # Clamp duration if configured
        if self.cfg.whisper_max_audio_seconds:
            max_samples = self.cfg.whisper_max_audio_seconds * self.cfg.sample_rate
            if len(audio) > max_samples:
                self.log.warning(
                    f"Audio truncated from {len(audio)/self.cfg.sample_rate:.1f}s "
                    f"to {self.cfg.whisper_max_audio_seconds}s"
                )
                audio = audio[: int(max_samples)]

        try:
            t0 = time.perf_counter()

            segments, info = self._model.transcribe(
                audio,
                beam_size=self.cfg.whisper_beam_size,
                language=self.cfg.whisper_language,
                vad_filter=self.cfg.whisper_vad_filter,
                word_timestamps=self.cfg.whisper_word_timestamps,
                condition_on_previous_text=True,
                no_speech_threshold=0.6,
            )

            # Collect all segment text
            text_parts: list[str] = []
            for seg in segments:
                text_parts.append(seg.text.strip())

            elapsed = time.perf_counter() - t0
            full_text = " ".join(text_parts).strip()

            self.log.info(
                f"Transcribed {len(audio)/self.cfg.sample_rate:.1f}s audio "
                f"in {elapsed*1000:.0f}ms "
                f"(lang={info.language}, prob={info.language_probability:.2f})"
                + (f" → '{full_text[:80]}...'" if len(full_text) > 80 else f" → '{full_text}'")
                if full_text else " → (empty)",
                stt_latency_ms=round(elapsed * 1000, 1),
                audio_duration=f"{len(audio)/self.cfg.sample_rate:.1f}s",
                detected_language=info.language,
                confidence=round(info.language_probability, 3),
            )

            # Apply confidence threshold
            if self.cfg.whisper_confidence_threshold > 0 and info.language_probability < self.cfg.whisper_confidence_threshold:
                self.log.warning(f"Low confidence ({info.language_probability:.2f}), discarding")
                return ""

            return full_text

        except Exception as exc:
            self.log.error(f"Transcription failed: {exc}")
            raise STTError(f"Transcription error: {exc}") from exc

    def transcribe_with_details(self, audio: np.ndarray) -> dict:
        """Transcribe and return metadata alongside the text.

        Returns::
            {
                "text": "...",
                "language": "en",
                "language_probability": 0.95,
                "duration_seconds": 2.5,
                "latency_ms": 150,
                "segments": [...]
            }
        """
        self.load_model()

        if len(audio) == 0:
            return {"text": "", "language": "", "language_probability": 0.0, "duration_seconds": 0, "latency_ms": 0, "segments": []}

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.flatten()

        try:
            t0 = time.perf_counter()
            segments, info = self._model.transcribe(
                audio,
                beam_size=self.cfg.whisper_beam_size,
                language=self.cfg.whisper_language,
                vad_filter=self.cfg.whisper_vad_filter,
                word_timestamps=self.cfg.whisper_word_timestamps,
                condition_on_previous_text=True,
            )

            seg_list = []
            text_parts = []
            for seg in segments:
                seg_list.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "avg_logprob": getattr(seg, "avg_logprob", None),
                    "no_speech_prob": getattr(seg, "no_speech_prob", None),
                })
                text_parts.append(seg.text.strip())

            elapsed = time.perf_counter() - t0
            return {
                "text": " ".join(text_parts).strip(),
                "language": info.language,
                "language_probability": info.language_probability,
                "duration_seconds": len(audio) / self.cfg.sample_rate,
                "latency_ms": round(elapsed * 1000, 1),
                "segments": seg_list,
            }

        except Exception as exc:
            self.log.error(f"Detailed transcription failed: {exc}")
            return {"text": "", "error": str(exc)}
