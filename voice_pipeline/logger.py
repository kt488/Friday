"""
Voice Pipeline Logger
=====================
Structured logging with timing metrics, level control, and optional file output.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional


class VoiceLogger:
    """Central logger for the voice pipeline.

    Provides:
    - Standard logging at configurable levels.
    - Timing context manager for measuring latency of each stage.
    - Metric emission for observability.
    """

    def __init__(
        self,
        name: str = "voice_pipeline",
        level: str = "INFO",
        log_file: str = "",
        log_metrics: bool = True,
    ):
        self._name = name
        self._logger = logging.getLogger(name)

        numeric_level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(numeric_level)
        self._logger.handlers.clear()

        fmt = logging.Formatter(
            "[%(asctime)s.%(msecs)03d] %(levelname)-6s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        self._logger.addHandler(console)

        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            self._logger.addHandler(fh)

        self._log_metrics = log_metrics
        self._stage_timers: dict[str, float] = {}

    # ── Public API ───────────────────────────────────────────────────────

    def debug(self, msg: str, **extra):
        self._logger.debug(self._fmt(msg, extra))

    def info(self, msg: str, **extra):
        self._logger.info(self._fmt(msg, extra))

    def warning(self, msg: str, **extra):
        self._logger.warning(self._fmt(msg, extra))

    def error(self, msg: str, **extra):
        self._logger.error(self._fmt(msg, extra))

    def exception(self, msg: str, **extra):
        self._logger.exception(self._fmt(msg, extra))

    # ── Timing / Metrics ─────────────────────────────────────────────────

    def mark_stage_start(self, stage: str):
        """Record wall-clock start for a pipeline stage."""
        self._stage_timers[stage] = time.perf_counter()

    def mark_stage_end(self, stage: str, log: bool = True) -> float:
        """Record end for a stage, return elapsed seconds."""
        start = self._stage_timers.pop(stage, None)
        if start is None:
            return 0.0
        elapsed = time.perf_counter() - start
        if log and self._log_metrics:
            self.info(f"[METRIC] {stage} took {elapsed*1000:.1f}ms", metric=stage, value_ms=round(elapsed*1000, 1))
        return elapsed

    class _Timer:
        def __init__(self, logger: "VoiceLogger", stage: str):
            self.logger = logger
            self.stage = stage

        def __enter__(self):
            self.logger.mark_stage_start(self.stage)
            return self

        def __exit__(self, *args):
            self.logger.mark_stage_end(self.stage)

    def timer(self, stage: str) -> "_Timer":
        """Context manager that measures stage duration::

            with log.timer("stt_transcribe"):
                result = stt.transcribe(audio)
        """
        return self._Timer(self, stage)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(msg: str, extra: dict) -> str:
        if not extra:
            return msg
        parts = [msg]
        for k, v in extra.items():
            parts.append(f"  [{k}={v}]")
        return "".join(parts)
