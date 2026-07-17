"""Friday AI Runtime Harness — Context Manager.

Manages working memory, conversation context, context compression,
isolation between tasks, and efficient token usage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import ContextFrame


class ContextManager:
    """Manages conversation and task context with compression and isolation."""

    def __init__(self, max_tokens: int = 32000, compression_threshold: int = 28000):
        self._max_tokens = max_tokens
        self._compression_threshold = compression_threshold
        self._frames: Dict[str, ContextFrame] = {}
        self._active_id: Optional[str] = None

    def create_frame(
        self,
        conversation_id: Optional[str] = None,
        initial_message: Optional[Dict[str, Any]] = None,
    ) -> ContextFrame:
        """Create a new context frame."""
        frame = ContextFrame(
            id=uuid.uuid4().hex[:12],
            conversation_id=conversation_id,
        )
        if initial_message:
            frame.messages.append(initial_message)
        self._frames[frame.id] = frame
        return frame

    def get_frame(self, frame_id: Optional[str] = None) -> Optional[ContextFrame]:
        """Get a context frame by ID or active frame."""
        frame_id = frame_id or self._active_id
        return self._frames.get(frame_id) if frame_id else None

    def set_active(self, frame_id: str) -> bool:
        """Set the active context frame."""
        if frame_id in self._frames:
            self._active_id = frame_id
            return True
        return False

    def add_message(
        self,
        message: Dict[str, Any],
        frame_id: Optional[str] = None,
    ) -> bool:
        """Add a message to a context frame, with auto-compression."""
        frame = self.get_frame(frame_id)
        if not frame:
            return False

        frame.messages.append(message)
        frame.updated_at = datetime.utcnow()

        # Estimate tokens (rough: 4 chars per token)
        total_chars = sum(len(m.get("content", "")) for m in frame.messages)
        frame.tokens = total_chars // 4

        if frame.tokens > self._compression_threshold and not frame.compressed:
            self._compress_frame(frame.id)

        return True

    def get_recent_messages(
        self,
        count: int = 10,
        frame_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get the most recent messages from a frame."""
        frame = self.get_frame(frame_id)
        if not frame:
            return []
        return frame.messages[-count:]

    def get_context_text(
        self,
        frame_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Compile context into a text block for LLM consumption."""
        frame = self.get_frame(frame_id)
        if not frame:
            return ""

        limit = max_tokens or self._max_tokens
        parts: List[str] = []

        if frame.summary:
            parts.append(f"[Context Summary: {frame.summary}]")

        for msg in frame.messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))
            parts.append(f"{role}: {content}")

        text = "\n".join(parts)
        # Truncate to token limit
        chars_limit = limit * 4
        if len(text) > chars_limit:
            text = text[-chars_limit:]
            text = "[...truncated]\n" + text

        return text

    def compress_frame(
        self,
        frame_id: Optional[str] = None,
        strategy: str = "summary",
    ) -> bool:
        """Compress a context frame to reduce token usage."""
        return self._compress_frame(frame_id, strategy)

    def _compress_frame(
        self,
        frame_id: Optional[str] = None,
        strategy: str = "summary",
    ) -> bool:
        """Internal compression implementation."""
        frame = self.get_frame(frame_id)
        if not frame:
            return False

        if strategy == "summary":
            early_messages = frame.messages[:-10] if len(frame.messages) > 10 else []
            if early_messages:
                frame.summary = f"[{len(early_messages)} earlier messages summarized]"
                frame.messages = frame.messages[-10:]
                frame.compressed = True
        elif strategy == "drop":
            # Keep only last N messages
            if len(frame.messages) > 20:
                frame.summary = f"[{len(frame.messages) - 20} messages dropped]"
                frame.messages = frame.messages[-20:]
                frame.compressed = True

        frame.tokens = sum(len(m.get("content", "")) for m in frame.messages) // 4
        frame.updated_at = datetime.utcnow()
        return True

    def clone_frame(self, frame_id: str) -> Optional[ContextFrame]:
        """Clone an existing context frame."""
        original = self._frames.get(frame_id)
        if not original:
            return None
        clone = ContextFrame(
            id=uuid.uuid4().hex[:12],
            conversation_id=original.conversation_id,
            messages=original.messages.copy(),
            tokens=original.tokens,
            summary=original.summary,
            compressed=original.compressed,
        )
        self._frames[clone.id] = clone
        return clone

    def delete_frame(self, frame_id: str) -> bool:
        """Delete a context frame."""
        if frame_id in self._frames:
            del self._frames[frame_id]
            if self._active_id == frame_id:
                self._active_id = None
            return True
        return False

    def list_frames(self) -> List[Dict[str, Any]]:
        """List all context frames with metadata."""
        return [
            {
                "id": f.id,
                "conversation_id": f.conversation_id,
                "messages": len(f.messages),
                "tokens": f.tokens,
                "compressed": f.compressed,
                "has_summary": f.summary is not None,
                "created": f.created_at.isoformat(),
                "active": f.id == self._active_id,
            }
            for f in self._frames.values()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get context manager statistics."""
        frames = self._frames.values()
        return {
            "total_frames": len(frames),
            "active_id": self._active_id,
            "total_messages": sum(len(f.messages) for f in frames),
            "total_tokens": sum(f.tokens for f in frames),
            "compressed_frames": sum(1 for f in frames if f.compressed),
        }
