"""Context builder — assembles RAG context for LLM prompt injection.

Takes retrieved chunks + memory records and builds an optimized context block
that fits within token limits, prioritizing most relevant content.
"""

import time
from typing import Dict, List, Optional

from core.rag.models import QueryAnalysis, RAGContext, SearchResult


class ContextBuilder:
    """Builds optimized context blocks for LLM prompt injection from search results."""

    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens

    def build(self, results: List[SearchResult],
              query_analysis: Optional[QueryAnalysis] = None,
              memory_records: Optional[List] = None,
              max_tokens: Optional[int] = None) -> RAGContext:
        """Build context from search results within token budget."""
        t0 = time.time()
        max_tok = max_tokens or self.max_tokens
        context_parts = []
        total_tokens = 0
        source_counts: Dict[str, int] = {}

        for r in results:
            # Estimate tokens
            chunk_tokens = len(r.content) // 4 + 50  # +50 for formatting overhead

            if total_tokens + chunk_tokens > max_tok:
                break

            source_type = r.metadata.source_type.value if hasattr(r.metadata.source_type, 'value') else str(r.metadata.source_type)
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

            source_tag = f"[Source: {source_type}"
            if r.metadata.heading:
                source_tag += f" | {r.metadata.heading}"
            if r.metadata.filename:
                source_tag += f" | {r.metadata.filename}"
            source_tag += f" | relevance: {r.score:.2f}]"

            entry = f"{source_tag}\n{r.content}\n"
            context_parts.append(entry)
            total_tokens += chunk_tokens

        # Build final context text
        if context_parts:
            context_text = (
                "## RAG Context (Retrieved Knowledge)\n\n"
                + "\n".join(context_parts)
                + "\n---\n"
            )
        else:
            context_text = ""

        return RAGContext(
            chunks=results[:len(context_parts)],
            query_analysis=query_analysis,
            context_text=context_text,
            total_tokens=total_tokens,
            retrieval_time_ms=(time.time() - t0) * 1000,
            source_counts=source_counts,
        )

    def build_for_prompt(self, query: str, context: RAGContext,
                          include_analysis: bool = True) -> str:
        """Build the final context string to inject into LLM prompts."""
        parts = []

        # Query analysis section
        if include_analysis and context.query_analysis:
            qa = context.query_analysis
            parts.append(
                f"## Query Analysis\n"
                f"- Original: {qa.original_query}\n"
                f"- Rewritten: {qa.rewritten_query}\n"
                f"- Type: {qa.query_type}\n"
                f"- Intent: {qa.intent}\n"
                f"- Keywords: {', '.join(qa.keywords)}\n"
            )

        # Retrieved context
        if context.context_text:
            parts.append(context.context_text)

        # Memory context
        if context.memory_records:
            memory_text = "\n".join(
                f"[Memory: {m.memory_type.value} | importance: {m.importance:.2f}]\n{m.content}"
                for m in context.memory_records[:5]
            )
            parts.append(f"## Relevant Memories\n{memory_text}\n")

        return "\n".join(parts)

    def build_minimal(self, results: List[SearchResult],
                       max_chunks: int = 3) -> RAGContext:
        """Build minimal context (for low-latency responses)."""
        top = results[:max_chunks]
        context_text = "\n".join(
            f"[Relevance: {r.score:.2f}]\n{r.content}"
            for r in top
        )

        total_tokens = sum(len(r.content) // 4 for r in top)

        return RAGContext(
            chunks=top,
            context_text=context_text,
            total_tokens=total_tokens,
        )
