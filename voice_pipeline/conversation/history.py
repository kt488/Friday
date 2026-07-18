"""
Conversation History
====================
Persistent, capped conversation history with JSON storage.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from ..config import VoiceConfig
from ..logger import VoiceLogger


class ConversationHistory:
    """Capped, persistent conversation history.

    Stores turns as ``{"role": "user"|"assistant", "message": "..."}``.
    Automatically evicts oldest turns when ``max_turns`` is exceeded.
    Persists to JSON files in a configured history directory.
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)

        self._max_turns = config.max_history_turns
        self._turns: list[dict] = []
        self._session_id: str = ""
        self._dirty = False

        # History storage
        self._history_dir = config.history_dir
        if self._history_dir:
            os.makedirs(self._history_dir, exist_ok=True)

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def turns(self) -> list[dict]:
        return list(self._turns)

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    @property
    def max_turns(self) -> int:
        return self._max_turns

    # ── Public API ──────────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        self._turns.append({"role": "user", "message": text})
        self._dirty = True
        self._evict()

    def add_assistant(self, text: str) -> None:
        self._turns.append({"role": "assistant", "message": text})
        self._dirty = True
        self._evict()

    def add_turn(self, role: str, message: str) -> None:
        """Add an arbitrary turn.

        Args:
            role: ``"user"`` or ``"assistant"`` (or ``"friday"`` — normalised).
        """
        normalized_role = "assistant" if role in ("assistant", "friday") else "user"
        self._turns.append({"role": normalized_role, "message": message})
        self._dirty = True
        self._evict()

    def get_context(self) -> list[dict]:
        """Return all turns in the format Friday AI expects."""
        result = []
        for t in self._turns:
            role = "friday" if t["role"] == "assistant" else "user"
            result.append({"role": role, "message": t["message"]})
        return result

    def get_recent(self, n: int) -> list[dict]:
        """Return last *n* turns in Friday AI format."""
        subset = self._turns[-n:] if n < len(self._turns) else self._turns
        result = []
        for t in subset:
            role = "friday" if t["role"] == "assistant" else "user"
            result.append({"role": role, "message": t["message"]})
        return result

    def clear(self) -> None:
        self._turns.clear()
        self._dirty = True

    def __len__(self) -> int:
        return len(self._turns)

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist to JSON file."""
        if not self._history_dir or not self._dirty:
            return

        if not self._session_id:
            self._session_id = str(uuid.uuid4())

        path = os.path.join(self._history_dir, f"{self._session_id}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session_id": self._session_id,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "turns": self._turns,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            self._dirty = False
        except Exception as exc:
            self.log.error(f"Failed to save history: {exc}")

    def load(self, session_id: Optional[str] = None) -> bool:
        """Load history from JSON file.

        Args:
            session_id: ID to load. If ``None``, generates new session.

        Returns:
            ``True`` if loaded successfully, ``False`` otherwise.
        """
        if not self._history_dir:
            return False

        if session_id is None:
            self._session_id = str(uuid.uuid4())
            return True

        path = os.path.join(self._history_dir, f"{session_id}.json")
        if not os.path.exists(path):
            self.log.warning(f"Session not found: {session_id}")
            self._session_id = str(uuid.uuid4())
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._turns = data.get("turns", [])
            self._session_id = session_id
            self._dirty = False
            self.log.info(f"Loaded session {session_id} ({len(self._turns)} turns)")
            return True
        except Exception as exc:
            self.log.error(f"Failed to load history: {exc}")
            self._session_id = str(uuid.uuid4())
            return False

    def list_sessions(self) -> list[dict]:
        """List all saved sessions with metadata."""
        if not self._history_dir or not os.path.isdir(self._history_dir):
            return []

        sessions = []
        for fname in sorted(os.listdir(self._history_dir)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._history_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", fname[:-5]),
                    "created_at": data.get("created_at", ""),
                    "turn_count": len(data.get("turns", [])),
                })
            except Exception:
                continue
        return sorted(sessions, key=lambda s: s.get("created_at", ""), reverse=True)

    # ── Internal ────────────────────────────────────────────────────────

    def _evict(self) -> None:
        """Remove oldest turns if over max_turns (FIFO eviction)."""
        while len(self._turns) > self._max_turns:
            self._turns.pop(0)
