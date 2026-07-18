"""
Text-to-Speech Engine (Kokoro)
===============================
Synthesises natural speech from text using Kokoro TTS.
"""

from __future__ import annotations

import threading
import time
from typing import Generator, Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger
from .cache import TTSCache


class TTSError(Exception):
    """Raised when TTS synthesis fails."""


class TextToSpeech:
    """Kokoro TTS wrapper with streaming, queue management, and caching.

    Model is loaded lazily on first use. Supports:
    - Multiple voice profiles
    - Configurable speed
    - Sentence-level streaming
    - Audio caching for repeated phrases
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._pipeline = None
        self._lock = threading.Lock()
        self._loaded = False
        self._load_time: Optional[float] = None
        self._cache = TTSCache(config, log) if config.tts_cache_enabled else None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def voice(self) -> str:
        return self.cfg.tts_voice

    @voice.setter
    def voice(self, value: str) -> None:
        self.cfg.tts_voice = value
        self.log.info(f"TTS voice switched to '{value}'")

    # ── Model Management ────────────────────────────────────────────────

    def load_model(self) -> None:
        """Lazy-load Kokoro pipeline (thread-safe)."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            try:
                from kokoro import KPipeline  # type: ignore
            except ImportError:
                raise TTSError(
                    "kokoro not installed. "
                    "Run: pip install kokoro"
                )

            self.log.info(
                f"Loading Kokoro TTS (lang={self.cfg.tts_lang_code}, "
                f"voice='{self.cfg.tts_voice}')"
            )

            t0 = time.perf_counter()
            try:
                self._pipeline = KPipeline(lang_code=self.cfg.tts_lang_code)
            except Exception as exc:
                raise TTSError(f"Failed to load Kokoro pipeline: {exc}")

            self._load_time = time.perf_counter() - t0
            self._loaded = True
            self.log.info(f"Kokoro loaded in {self._load_time*1000:.0f}ms")

    def unload_model(self) -> None:
        """Release TTS model memory."""
        with self._lock:
            self._pipeline = None
            self._loaded = False
            self._load_time = None
            if self._cache:
                self._cache.clear()
            self.log.info("TTS model unloaded")

    # ── Synthesis ───────────────────────────────────────────────────────

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """Synthesise full text and return concatenated audio.

        Args:
            text: Input text to speak.

        Returns:
            Float32 mono audio array, or ``None`` if empty/failed.
        """
        if not text or not text.strip():
            return None

        self.load_model()

        # Check cache first
        if self._cache:
            cached = self._cache.get(text)
            if cached is not None:
                self.log.debug(f"TTS cache hit ({len(text)} chars)")
                return cached

        t0 = time.perf_counter()
        chunks: list[np.ndarray] = []

        try:
            gen = self._pipeline(
                text,
                voice=self.cfg.tts_voice,
                speed=self.cfg.tts_speed,
            )
            for result in gen:
                if result.audio is not None and len(result.audio) > 0:
                    chunks.append(result.audio)

        except Exception as exc:
            self.log.error(f"TTS synthesis failed: {exc}")
            raise TTSError(f"Kokoro synthesis error: {exc}") from exc

        if not chunks:
            return None

        audio = np.concatenate(chunks)
        elapsed = time.perf_counter() - t0
        audio_dur = len(audio) / 24000  # Kokoro outputs at 24 kHz

        self.log.info(
            f"Synthesised {len(text)} chars → {audio_dur:.1f}s audio "
            f"in {elapsed*1000:.0f}ms "
            f"(RTF={elapsed/audio_dur:.2f}x)",
            tts_latency_ms=round(elapsed * 1000, 1),
            audio_duration=round(audio_dur, 2),
            chars=len(text),
        )

        # Cache result
        if self._cache:
            self._cache.put(text, audio)

        return audio

    def synthesize_stream(
        self, text: str
    ) -> Generator[np.ndarray, None, None]:
        """Yield audio chunks as they are synthesised (sentence-level).

        Useful for low-latency streaming playback.
        """
        if not text or not text.strip():
            return

        self.load_model()

        try:
            gen = self._pipeline(
                text,
                voice=self.cfg.tts_voice,
                speed=self.cfg.tts_speed,
            )
            for result in gen:
                if result.audio is not None and len(result.audio) > 0:
                    yield result.audio

        except Exception as exc:
            self.log.error(f"TTS streaming failed: {exc}")
            raise TTSError(f"Kokoro streaming error: {exc}") from exc

    def synthesize_batch(self, texts: list[str]) -> list[Optional[np.ndarray]]:
        """Synthesise multiple texts in batch.

        Returns list of audio arrays (one per input), preserving order.
        """
        return [self.synthesize(t) for t in texts]

    # ── Utility ─────────────────────────────────────────────────────────

    @staticmethod
    def resample_to_rate(
        audio: np.ndarray,
        orig_rate: int,
        target_rate: int,
    ) -> np.ndarray:
        """Resample audio to target rate using linear interpolation.

        Kokoro outputs at 24 kHz; playback may need 16 kHz or 44.1 kHz.
        """
        if orig_rate == target_rate:
            return audio

        dur = len(audio) / orig_rate
        new_len = int(dur * target_rate)
        return np.interp(
            np.linspace(0, len(audio) - 1, new_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)
