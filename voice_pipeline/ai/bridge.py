"""
Friday AI Bridge
================
Interfaces the voice pipeline with Friday AI core (brain + executive).
Handles streaming response generation from the LLM backend.
"""

from __future__ import annotations

import sys
import time
from typing import Generator, Optional

from ..config import VoiceConfig
from ..logger import VoiceLogger


class FridayBridgeError(Exception):
    """Raised when communication with Friday AI fails."""


class FridayBridge:
    """Bridges voice pipeline output to Friday AI core for response generation.

    Uses the existing ``FridayCore.process_message_stream()`` API for
    streaming text responses. Supports conversation context injection.
    """

    def __init__(
        self,
        config: VoiceConfig,
        log: Optional[VoiceLogger] = None,
    ):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._friday = None  # Lazy-imported FridayCore
        self._initialised = False
        self._conversation_context: list[dict] = []

    # ── Lifecycle ───────────────────────────────────────────────────────

    def initialise(self) -> None:
        """Lazy-import and initialise FridayCore.

        Raises ``FridayBridgeError`` if Friday can't be loaded.
        """
        if self._initialised:
            return

        try:
            # Add project root to sys.path
            root = self.cfg.project_root or self._find_project_root()
            if root and root not in sys.path:
                sys.path.insert(0, root)

            from core.friday import FridayCore  # type: ignore

            t0 = time.perf_counter()
            self._friday = FridayCore()
            elapsed = time.perf_counter() - t0

            self._initialised = True
            self.log.info(f"Friday AI core initialised ({elapsed*1000:.0f}ms)")
        except ImportError as exc:
            raise FridayBridgeError(f"Failed to import FridayCore: {exc}")
        except Exception as exc:
            raise FridayBridgeError(f"Failed to initialise Friday: {exc}")

    @staticmethod
    def _find_project_root() -> Optional[str]:
        """Walk up from voice_pipeline/ to find the project root."""
        import os
        path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.exists(os.path.join(path, "core", "friday.py")):
            return path
        return None

    # ── Conversation Context ────────────────────────────────────────────

    def set_context(self, context: list[dict]) -> None:
        """Set the full conversation history for context injection.

        Each entry: ``{"role": "user"|"friday", "message": "..."}``
        """
        self._conversation_context = context

    def add_to_context(self, role: str, message: str) -> None:
        """Append a single turn to conversation context."""
        self._conversation_context.append({"role": role, "message": message})

    def clear_context(self) -> None:
        """Reset conversation context."""
        self._conversation_context.clear()

    # ── Response Generation ─────────────────────────────────────────────

    def get_response(self, text: str) -> str:
        """Get a full (non-streaming) response from Friday.

        Args:
            text: Cleaned user input text.

        Returns:
            Friday's response as a string.

        Raises:
            FridayBridgeError: If Friday is not available.
        """
        self.initialise()

        if self._friday is None:
            raise FridayBridgeError("Friday AI not available")

        try:
            self.log.info(f"Sending to Friday ({len(text)} chars): '{text[:100]}'")
            t0 = time.perf_counter()

            response = self._friday.process_message(
                user_text=text,
                conversation_context=self._conversation_context,
                agent_name=self.cfg.friday_agent,
            )

            elapsed = time.perf_counter() - t0
            self.log.info(
                f"Friday responded ({len(response)} chars) in {elapsed*1000:.0f}ms",
                ai_latency_ms=round(elapsed * 1000, 1),
            )

            return response

        except Exception as exc:
            self.log.error(f"Friday AI request failed: {exc}")
            raise FridayBridgeError(f"Friday AI error: {exc}") from exc

    def get_response_stream(self, text: str) -> Generator[str, None, None]:
        """Stream response chunks from Friday.

        Yields partial text chunks as they arrive for real-time playback.
        """
        self.initialise()

        if self._friday is None:
            raise FridayBridgeError("Friday AI not available")

        try:
            self.log.info(f"Streaming to Friday ({len(text)} chars): '{text[:100]}'")
            t0 = time.perf_counter()
            total_chars = 0

            for chunk in self._friday.process_message_stream(
                user_text=text,
                conversation_context=self._conversation_context,
                agent_name=self.cfg.friday_agent,
            ):
                total_chars += len(chunk)
                yield chunk

            elapsed = time.perf_counter() - t0
            self.log.info(
                f"Friday streamed {total_chars} chars in {elapsed*1000:.0f}ms",
                ai_latency_ms=round(elapsed * 1000, 1),
            )

        except Exception as exc:
            self.log.error(f"Friday AI stream failed: {exc}")
            raise FridayBridgeError(f"Friday AI stream error: {exc}") from exc

    # ── Utility ─────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Check if Friday AI is reachable and responsive."""
        status = {"available": False, "latency_ms": 0, "error": None}
        try:
            self.initialise()
            t0 = time.perf_counter()
            _ = self.get_response("Hello")
            status["available"] = True
            status["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception as exc:
            status["error"] = str(exc)
        return status
