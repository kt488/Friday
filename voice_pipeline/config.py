"""
Voice Pipeline Configuration
=============================
Centralized, env-var-driven settings for all pipeline stages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Helper ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


# ── Voice Pipeline Config ───────────────────────────────────────────────────

@dataclass
class VoiceConfig:
    """Singleton-ish config dataclass. Instantiate with ``VoiceConfig.from_env()``."""

    # ── Audio ────────────────────────────────────────────────────────────
    sample_rate: int = _env_int("VOICE_SAMPLE_RATE", 16000)
    channels: int = _env_int("VOICE_CHANNELS", 1)
    dtype: str = _env("VOICE_DTYPE", "float32")
    frame_seconds: float = _env_float("VOICE_FRAME_SECONDS", 0.032)  # 32 ms per VAD frame
    input_device: Optional[int] = None  # None = system default
    output_device: Optional[int] = None

    # ── Voice Activity Detection ─────────────────────────────────────────
    vad_mode: int = _env_int("VAD_MODE", 1)  # 0-3 (3 = most aggressive)
    vad_threshold: float = _env_float("VAD_THRESHOLD", 0.5)
    vad_frame_ms: int = _env_int("VAD_FRAME_MS", 32)  # 32 | 64 | 128
    min_speech_duration_ms: int = _env_int("VAD_MIN_SPEECH_MS", 250)
    min_silence_duration_ms: int = _env_int("VAD_MIN_SILENCE_MS", 600)
    speech_pad_ms: int = _env_int("VAD_SPEECH_PAD_MS", 200)
    pre_speech_pad: float = _env_float("VAD_PRE_SPEECH_PAD", 0.5)  # seconds to keep before speech

    # ── Noise Reduction ──────────────────────────────────────────────────
    noise_reduce_enabled: bool = _env_bool("NOISE_REDUCE_ENABLED", True)
    noise_sample_duration: float = _env_float("NOISE_SAMPLE_DURATION", 0.5)  # seconds to profile noise
    noise_reduce_strength: float = _env_float("NOISE_REDUCE_STRENGTH", 0.7)

    # ── Speech-to-Text (Faster-Whisper) ──────────────────────────────────
    whisper_model_size: str = _env("WHISPER_MODEL_SIZE", "tiny")  # tiny|base|small|medium|large
    whisper_device: str = _env("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = _env("WHISPER_COMPUTE_TYPE", "int8")  # int8|float16|float32
    whisper_beam_size: int = _env_int("WHISPER_BEAM_SIZE", 3)
    whisper_language: Optional[str] = None  # None = auto-detect
    whisper_vad_filter: bool = _env_bool("WHISPER_VAD_FILTER", True)
    whisper_word_timestamps: bool = _env_bool("WHISPER_WORD_TIMESTAMPS", False)
    whisper_confidence_threshold: float = _env_float("WHISPER_CONFIDENCE_THRESHOLD", 0.0)
    whisper_max_audio_seconds: Optional[int] = _env_int("WHISPER_MAX_AUDIO_SECONDS", 30)
    whisper_num_workers: int = _env_int("WHISPER_NUM_WORKERS", 1)
    whisper_cpu_threads: int = _env_int("WHISPER_CPU_THREADS", 4)

    # ── Text Cleaning ────────────────────────────────────────────────────
    clean_filler_words: bool = _env_bool("CLEAN_FILLER_WORDS", True)
    clean_repairs: bool = _env_bool("CLEAN_REPAIRS", True)
    clean_disfluencies: bool = _env_bool("CLEAN_DISFLUENCIES", True)
    normalize_numbers: bool = _env_bool("NORMALIZE_NUMBERS", True)
    fix_punctuation: bool = _env_bool("FIX_PUNCTUATION", True)
    capitalize: bool = _env_bool("CAPITALIZE", True)

    # ── Text-to-Speech (Kokoro) ──────────────────────────────────────────
    tts_voice: str = _env("TTS_VOICE", "af_heart")  # Kokoro voice pack
    tts_lang_code: str = _env("TTS_LANG_CODE", "a")  # a=American English
    tts_speed: float = _env_float("TTS_SPEED", 1.0)
    tts_pitch: float = _env_float("TTS_PITCH", 1.0)  # Not used by Kokoro, reserved
    tts_volume: float = _env_float("TTS_VOLUME", 1.0)
    tts_cache_enabled: bool = _env_bool("TTS_CACHE_ENABLED", True)
    tts_cache_max_entries: int = _env_int("TTS_CACHE_MAX_ENTRIES", 500)
    tts_sentence_split: bool = _env_bool("TTS_SENTENCE_SPLIT", True)  # split on sentence boundaries
    tts_streaming: bool = _env_bool("TTS_STREAMING", True)

    # ── Friday AI Bridge ─────────────────────────────────────────────────
    friday_stream: bool = _env_bool("FRIDAY_STREAM", True)
    friday_timeout: int = _env_int("FRIDAY_TIMEOUT", 60)
    friday_system_prompt_override: Optional[str] = None
    friday_agent: Optional[str] = None

    # ── Conversation ─────────────────────────────────────────────────────
    max_history_turns: int = _env_int("MAX_HISTORY_TURNS", 50)
    persist_history: bool = _env_bool("PERSIST_HISTORY", True)
    history_dir: str = _env("HISTORY_DIR", "")
    interruption_enabled: bool = _env_bool("INTERRUPTION_ENABLED", True)  # barge-in

    # ── Performance ──────────────────────────────────────────────────────
    vad_thread_pool_size: int = _env_int("VAD_THREAD_POOL_SIZE", 2)
    stt_queue_maxsize: int = _env_int("STT_QUEUE_MAXSIZE", 10)
    tts_queue_maxsize: int = _env_int("TTS_QUEUE_MAXSIZE", 10)
    pipeline_queue_maxsize: int = _env_int("PIPELINE_QUEUE_MAXSIZE", 20)

    # ── Logging ──────────────────────────────────────────────────────────
    log_level: str = _env("VOICE_LOG_LEVEL", "INFO")
    log_file: str = _env("VOICE_LOG_FILE", "")
    log_metrics: bool = _env_bool("VOICE_LOG_METRICS", True)
    log_audio_levels: bool = _env_bool("VOICE_LOG_AUDIO_LEVELS", False)

    # ── Termux-specific ──────────────────────────────────────────────────
    termux_audio: bool = _env_bool("TERMUX_AUDIO", True)
    termux_mic_command: str = _env("TERMUX_MIC_CMD", "termux-microphone-record")
    termux_player_command: str = _env("TERMUX_PLAYER_CMD", "termux-media-player")

    # ── Paths ────────────────────────────────────────────────────────────
    project_root: str = _env("VOICE_PROJECT_ROOT", "")

    def __post_init__(self):
        if not self.history_dir:
            root = self.project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.history_dir = os.path.join(root, "voice_pipeline", "conversation", "history")
        if not self.log_file:
            root = self.project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.log_file = os.path.join(root, "voice_pipeline", "logs", "voice_pipeline.log")

    def validate(self) -> tuple[bool, str]:
        """Basic config validation."""
        if self.vad_mode not in (0, 1, 2, 3):
            return False, f"VAD mode must be 0-3, got {self.vad_mode}"
        if self.sample_rate not in (8000, 16000, 44100, 48000):
            return False, f"Unsupported sample rate: {self.sample_rate}"
        if self.whisper_model_size not in ("tiny", "base", "small", "medium", "large", "large-v3"):
            return False, f"Unknown whisper model: {self.whisper_model_size}"
        if self.tts_lang_code not in ("a", "b", "e", "f", "h", "i", "j", "p", "z"):
            return False, f"Unknown TTS lang code: {self.tts_lang_code}"
        return True, "OK"

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        return cls()
