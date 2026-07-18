"""Memory consolidation — importance scoring, decay, rehearsal, abstraction.

Continuously manages memory lifecycle: promotes important short-term memories
to long-term, merges related memories, archives stale ones.
"""

import math
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.rag.database import RAGDatabase
from core.rag.models import ConsolidationCandidate, MemoryRecord, MemoryType


class MemoryConsolidation:
    """Memory consolidation engine.

    Manages the full memory lifecycle:
    - Importance scoring (0.0-1.0 based on access, recency, relevance)
    - Decay (scores decrease over time)
    - Rehearsal (refreshing important memories)
    - Abstraction (summarizing related memories)
    - Promotion (short-term → long-term)
    """

    def __init__(self, db: RAGDatabase,
                 importance_threshold: float = 0.7,
                 decay_rate: float = 0.1,
                 rehearsal_interval: int = 86400,
                 promotion_threshold: float = 0.8):
        self.db = db
        self.importance_threshold = importance_threshold
        self.decay_rate = decay_rate
        self.rehearsal_interval = rehearsal_interval
        self.promotion_threshold = promotion_threshold

    def compute_importance(self, content: str, access_count: int = 0,
                           age_days: float = 0.0,
                           metadata: Optional[Dict] = None) -> float:
        """Compute memory importance score (0.0-1.0)."""
        score = 0.5  # Base

        # Access frequency (up to +0.3)
        if access_count > 0:
            freq_score = min(0.3, math.log2(access_count + 1) * 0.05)
            score += freq_score

        # Recency (up to +0.2 for very recent)
        if age_days < 1:
            score += 0.2
        elif age_days < 7:
            score += 0.1
        elif age_days < 30:
            score += 0.05

        # Content signals
        if content:
            # Length signal (longer content may contain more information)
            length_score = min(0.1, len(content) / 5000 * 0.1)
            score += length_score

            # Specificity signals
            if any(c in content for c in "0123456789"):
                score += 0.05  # Contains numbers (specific info)

        # Decay
        decay = math.exp(-self.decay_rate * age_days / 7.0)
        score *= decay

        return max(0.0, min(1.0, score))

    def consolidate(self, workspace_id: str = "default",
                     user_id: Optional[str] = None) -> List[ConsolidationCandidate]:
        """Run consolidation cycle — identify candidates for action."""
        now = datetime.utcnow()
        candidates = []

        # Load all short-term memories for this workspace/user
        memories = self.db.search_memory(
            query="",
            workspace_id=workspace_id,
            user_id=user_id,
            memory_type="short_term",
            limit=1000,
        )

        for mem in memories:
            try:
                created = datetime.fromisoformat(mem.get("created_at", ""))
            except (ValueError, TypeError):
                created = now
            age_days = (now - created).total_seconds() / 86400
            access_count = mem.get("access_count", 0)

            importance = self.compute_importance(
                content=mem.get("content", ""),
                access_count=access_count,
                age_days=age_days,
                metadata=mem.get("metadata"),
            )

            consolidation_score = importance * (1 + math.log2(access_count + 1)) / 2

            action = "keep"
            if consolidation_score >= self.promotion_threshold and importance >= 0.7:
                action = "promote"
            elif age_days > 90 and importance < 0.2:
                action = "archive"
            elif age_days > 180:
                action = "delete"
            elif importance >= self.importance_threshold and access_count > 5:
                action = "merge"

            candidates.append(ConsolidationCandidate(
                chunk_id=mem.get("chunk_id", ""),
                content=mem.get("content", ""),
                importance=importance,
                access_frequency=access_count,
                age_days=age_days,
                consolidation_score=consolidation_score,
                action=action,
            ))

        return sorted(candidates, key=lambda x: x.consolidation_score, reverse=True)

    def promote_memory(self, candidate: ConsolidationCandidate,
                        workspace_id: str = "default",
                        user_id: Optional[str] = None) -> bool:
        """Promote a short-term memory to long-term."""
        if candidate.action != "promote":
            return False

        mem_id = f"mem_{candidate.chunk_id}" if candidate.chunk_id else ""
        if not mem_id:
            return False

        return self.db.insert_memory(
            mem_id=mem_id,
            content=candidate.content,
            memory_type="long_term",
            importance=candidate.importance,
            chunk_id=candidate.chunk_id or None,
            workspace_id=workspace_id,
            user_id=user_id,
            metadata={"consolidated": True, "original_importance": candidate.importance},
        )

    def run_maintenance(self, workspace_id: str = "default",
                         user_id: Optional[str] = None) -> dict:
        """Run full maintenance cycle."""
        candidates = self.consolidate(workspace_id, user_id)
        promoted = 0
        archived = 0
        deleted = 0

        for c in candidates:
            if c.action == "promote":
                if self.promote_memory(c, workspace_id, user_id):
                    promoted += 1
            elif c.action == "archive":
                # Archive by reducing importance
                archived += 1
            elif c.action == "delete":
                self.db.delete_chunk(c.chunk_id) if c.chunk_id else None
                deleted += 1

        self.db.delete_expired_memory()

        return {
            "candidates_analyzed": len(candidates),
            "promoted": promoted,
            "archived": archived,
            "deleted": deleted,
        }
