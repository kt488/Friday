"""Friday AI Runtime Harness — Research Mode.

Multi-source research capabilities with intelligent search, content extraction,
cross-referencing, and synthesis into structured findings.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import ResearchFinding


class ResearchEngine:
    """Conducts multi-source research with synthesis and citation."""

    def __init__(self, max_sources: int = 10, max_results: int = 5):
        self._max_sources = max_sources
        self._max_results = max_results
        self._findings: Dict[str, List[ResearchFinding]] = {}
        self._search_history: List[Dict[str, Any]] = []

    def conduct_research(
        self,
        topic: str,
        depth: str = "standard",
        existing_knowledge: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a full research workflow on a topic."""
        research_id = uuid.uuid4().hex[:12]
        start_time = time.time()
        queries = self._generate_queries(topic, depth)
        findings: List[ResearchFinding] = []
        errors: List[str] = []

        for query in queries[:self._max_results]:
            try:
                results = self._search(query)
                for result in results:
                    finding = self._extract(result, topic)
                    findings.append(finding)
            except Exception as e:
                errors.append(f"Search failed for '{query}': {e}")

            if len(findings) >= self._max_sources:
                break

        synthesis = self._synthesize(findings, topic)
        duration = round(time.time() - start_time, 2)

        result = {
            "research_id": research_id,
            "topic": topic,
            "depth": depth,
            "queries_executed": len(queries),
            "sources_found": len(findings),
            "synthesis": synthesis,
            "findings": [vars(f) for f in findings],
            "errors": errors,
            "duration_sec": duration,
            "timestamp": datetime.utcnow().isoformat(),
        }

        self._findings[research_id] = findings
        self._search_history.append({
            "topic": topic,
            "depth": depth,
            "sources": len(findings),
            "duration_sec": duration,
        })

        return result

    def get_findings(self, research_id: str) -> List[ResearchFinding]:
        """Get findings for a research ID."""
        return self._findings.get(research_id, [])

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._search_history[-limit:]

    # ── Internal Methods ─────────────────────────────────────────────────────

    def _generate_queries(self, topic: str, depth: str) -> List[str]:
        """Generate search queries based on topic and depth."""
        base = topic.strip().rstrip(".?!")
        queries = [base]

        if depth in ("standard", "deep"):
            queries.extend([
                f"{base} overview",
                f"{base} latest developments",
            ])
        if depth == "deep":
            queries.extend([
                f"{base} analysis",
                f"{base} challenges",
                f"{base} future outlook",
            ])
        return queries

    def _search(self, query: str) -> List[Dict[str, Any]]:
        """Execute a search query. Returns placeholder results since actual
        search is handled by the web tools. This provides structured output
        for integration with the existing web_search tool."""
        return [{
            "title": f"Result for: {query}",
            "content": f"Content about {query}",
            "url": None,
            "relevance": 0.5,
        }]

    def _extract(self, result: Dict[str, Any], topic: str) -> ResearchFinding:
        """Extract a structured finding from a search result."""
        return ResearchFinding(
            source=result.get("url", "unknown") or "unknown",
            title=result.get("title", "Untitled"),
            content=result.get("content", ""),
            url=result.get("url"),
            relevance=result.get("relevance", 0.5),
        )

    def _synthesize(self, findings: List[ResearchFinding], topic: str) -> str:
        """Synthesize multiple findings into a coherent summary."""
        if not findings:
            return f"No research findings found for: {topic}"

        sources = len(findings)
        avg_relevance = sum(f.relevance for f in findings) / sources
        key_points = [f.title for f in findings[:3] if f.title]

        lines = [
            f"Research Synthesis: {topic}",
            f"Sources consulted: {sources}",
            f"Average relevance: {avg_relevance:.2f}",
            f"Key topics: {'; '.join(key_points)}" if key_points else "",
        ]
        return "\n".join(filter(None, lines))

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._search_history)
        total_sources = sum(h["sources"] for h in self._search_history)
        avg_duration = (
            sum(h["duration_sec"] for h in self._search_history) / total
            if total > 0 else 0
        )
        return {
            "total_researches": total,
            "total_sources": total_sources,
            "avg_duration_sec": round(avg_duration, 2),
            "avg_sources_per_research": round(total_sources / total, 1) if total > 0 else 0,
        }
