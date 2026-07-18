"""
Conversation Manager
====================
Orchestrates conversation flow: history tracking, context windowing,
turn management, and interruption signal handling.
"""

from __future__ import annotations

import time
from typing import Optional

from ..config import VoiceConfig
from ..logger import VoiceLogger
from .history import ConversationHistory


class ConversationManager:
    """Manages the multi-turn conversation lifecycle.

    Responsibilities:
    - Track conversation turns (user + assistant).
    - Enforce max history length (FIFO eviction).
    - Signal interruptions (barge-in).
    - Coordinate speech/not-speaking states.
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self.history = ConversationHistory(config, log)

        # Turn tracking
        self._turn_count = 0
        self._last_user_text: str = ""
        self._last_assistant_text: str = ""
        self._session_start: float = time.time()
        self._last_activity: float = time.time()

        # Interruption / barge-in
        self._interrupted = False
        self._interruption_enabled = config.interruption_enabled

        # Speaking state
        self._is_speaking = False
        self._is_processing = False

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def last_user_text(self) -> str:
        return self._last_user_text

    @property
    def last_assistant_text(self) -> str:
        return self._last_assistant_text

    @property
    def session_duration(self) -> float:
        return time.time() - self._session_start

    @property
    def idle_duration(self) -> float:
        return time.time() - self._last_activity

    @property
    def is_interrupted(self) -> bool:
        return self._interrupted

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @is_speaking.setter
    def is_speaking(self, value: bool) -> None:
        self._is_speaking = value

    @property
    def is_processing(self) -> bool:
        return self._is_processing

    # ── Interruption (Barge-in) ─────────────────────────────────────────

    def signal_interruption(self) -> None:
        """Signal that the user started speaking during playback."""
        if not self._interruption_enabled:
            return
        self._interrupted = True
        self.log.info("Interruption signalled (barge-in)")

    def clear_interruption(self) -> None:
        """Reset interruption flag."""
        self._interrupted = False

    def consume_interruption(self) -> bool:
        """Check and clear the interruption flag.

        Returns ``True`` if there was an active interruption.
        """
        if self._interrupted:
            self._interrupted = False
            return True
        return False

    # ── Turn Management ─────────────────────────────────────────────────

    def add_user_turn(self, text: str) -> None:
        """Register a user utterance and append to history."""
        text = text.strip()
        if not text:
            return

        self._last_user_text = text
        self._last_activity = time.time()
        self._turn_count += 1

        self.history.add_user(text)

    def add_assistant_turn(self, text: str) -> None:
        """Register an assistant response and append to history."""
        text = text.strip()
        if not text:
            return

        self._last_assistant_text = text
        self._last_activity = time.time()

        self.history.add_assistant(text)

    def get_context(self) -> list[dict]:
        """Get conversation context for Friday AI (list of turns)."""
        return self.history.get_context()

    def get_recent_context(self, n: int = 10) -> list[dict]:
        """Get the last N turns for context window."""
        return self.history.get_recent(n)

    # ── State ───────────────────────────────────────────────────────────

    def mark_processing_start(self) -> None:
        self._is_processing = True

    def mark_processing_end(self) -> None:
        self._is_processing = False

    def reset_session(self) -> None:
        """Reset entire conversation session."""
        self.history.clear()
        self._turn_count = 0
        self._last_user_text = ""
        self._last_assistant_text = ""
        self._session_start = time.time()
        self._last_activity = time.time()
        self._interrupted = False
        self._is_speaking = False
        self._is_processing = False
        self.log.info("Conversation session reset")

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist conversation history to disk."""
        self.history.save()

    def load(self, session_id: Optional[str] = None) -> None:
        """Load conversation history from disk."""
        self.history.load(session_id)

    def list_sessions(self) -> list[dict]:
        """List available historical sessions."""
        return self.history.list_sessions()
