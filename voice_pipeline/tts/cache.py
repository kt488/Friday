"""
TTS Audio Cache
===============
LRU cache for frequently-synthesised phrases to reduce latency.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class TTSCache:
    """Thread-safe LRU cache for TTS audio outputs.

    Two-tier storage:
    1. In-memory dict for hot phrases (fastest).
    2. Optional on-disk numpy cache for persistence across restarts.
    """

    def __init__(
        self,
        config: VoiceConfig,
        log: Optional[VoiceLogger] = None,
    ):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._max_entries = config.tts_cache_max_entries

        # Memory cache: {text_hash: (audio_bytes, access_time)}
        self._mem_cache: dict[str, tuple[bytes, float]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

        # Disk cache directory (lazy-created)
        self._disk_dir: Optional[str] = None
        if config.history_dir:
            self._disk_dir = os.path.join(config.history_dir, "..", "tts_cache")
        self._disk_enabled = config.tts_cache_enabled and bool(self._disk_dir)

    # ── Public API ──────────────────────────────────────────────────────

    def get(self, text: str) -> Optional[np.ndarray]:
        """Retrieve cached audio for a text string.

        Returns ``None`` on cache miss.
        """
        key = self._key(text)

        with self._lock:
            if key in self._mem_cache:
                data, _ = self._mem_cache[key]
                self._mem_cache[key] = (data, time.time())
                self._hits += 1
                audio = np.frombuffer(data, dtype=np.float32)
                self.log.debug(f"Cache HIT '{text[:30]}...' ({len(data)} bytes)")
                return audio

        self._misses += 1

        # Check disk cache (lock-free read)
        if self._disk_enabled:
            path = self._disk_path(key)
            if os.path.exists(path):
                try:
                    audio = np.load(path)
                    data = audio.tobytes()
                    with self._lock:
                        self._mem_cache[key] = (data, time.time())
                        self._hits += 1
                    self.log.debug(f"Disk cache HIT '{text[:30]}...'")
                    return audio
                except Exception:
                    pass

        return None

    def put(self, text: str, audio: np.ndarray) -> None:
        """Store audio in cache."""
        key = self._key(text)
        data = audio.tobytes()

        with self._lock:
            # Evict LRU if at capacity
            if len(self._mem_cache) >= self._max_entries:
                self._evict_lru()

            self._mem_cache[key] = (data, time.time())

        # Write to disk (async-friendly, just best-effort)
        if self._disk_enabled:
            try:
                path = self._disk_path(key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                np.save(path, audio)
            except Exception as exc:
                self.log.debug(f"Disk cache write failed: {exc}")

    def clear(self) -> None:
        """Clear all cached audio."""
        with self._lock:
            self._mem_cache.clear()
            self._hits = 0
            self._misses = 0

        if self._disk_enabled:
            try:
                import shutil
                shutil.rmtree(self._disk_dir, ignore_errors=True)
            except Exception:
                pass

        self.log.info("TTS cache cleared")

    @property
    def stats(self) -> dict:
        """Return cache hit/miss statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._mem_cache),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
            }

    # ── Internal ────────────────────────────────────────────────────────

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.strip().lower().encode()).hexdigest()

    def _disk_path(self, key: str) -> str:
        return os.path.join(self._disk_dir, f"{key}.npy")

    def _evict_lru(self) -> None:
        """Remove the single least-recently-used entry."""
        if not self._mem_cache:
            return
        oldest = min(self._mem_cache.items(), key=lambda x: x[1][1])
        del self._mem_cache[oldest[0]]
