"""Query understanding — classification, decomposition, expansion, intent detection.

Analyzes user queries to improve retrieval quality through rewriting,
decomposition, and intelligent filtering.
"""

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from core.rag.models import QueryAnalysis


class QueryUnderstanding:
    """Query understanding and analysis layer.

    Performs:
    - Query classification (factual, conversational, instructional, exploratory)
    - Intent detection (retrieve, generate, analyze, compare)
    - Query rewriting for better retrieval
    - Query decomposition into sub-queries
    - Keyword and entity extraction
    - Language detection
    """

    # Intent patterns
    COMPARE_PATTERNS = [
        r"\b(compare|difference|versus|vs\.?|similar|different)\b",
        r"\b(which is better|how does .* compare)\b",
    ]
    ANALYZE_PATTERNS = [
        r"\b(analyze|explain|why|how does|what causes|reason)\b",
        r"\b(summarize|break down|evaluate)\b",
    ]
    INSTRUCTIONAL_PATTERNS = [
        r"\b(how (to|do|can|would)|steps|guide|tutorial)\b",
        r"\b(teach me|show me|walk me through)\b",
    ]

    # Question word patterns for factual queries
    FACTUAL_PATTERNS = [
        r"\b(what is|who is|where is|when did|what are)\b",
        r"\b(define|definition|meaning|what does)\b",
    ]

    def __init__(self, llm_rewrite: bool = False):
        self.llm_rewrite = llm_rewrite

    def analyze(self, query: str,
                conversation_context: Optional[List[dict]] = None) -> QueryAnalysis:
        """Full query analysis pipeline."""
        t0 = time.time()

        query = query.strip()

        analysis = QueryAnalysis(
            original_query=query,
            rewritten_query=query,
            query_type=self._classify_query(query),
            intent=self._detect_intent(query),
            keywords=self._extract_keywords(query),
            entities=self._extract_entities(query),
            language=self._detect_language(query),
            needs_web_search=self._needs_web_search(query),
            confidence=1.0,
        )

        # Query rewriting for retrieval
        analysis.rewritten_query = self._rewrite_query(query, analysis.query_type)

        # Query decomposition (for complex queries)
        analysis.sub_queries = self._decompose_query(query)

        # Query expansion
        analysis.expanded_queries = self._expand_query(query, analysis.keywords)

        # Apply conversation context if available
        if conversation_context:
            analysis.rewritten_query = self._apply_context(
                query, conversation_context
            )

        return analysis

    def _classify_query(self, query: str) -> str:
        """Classify query type."""
        lower = query.lower()

        if re.search(r"\b(compare|difference|versus|vs)\b", lower):
            return "comparative"
        if re.search(r"\b(why|how does|what causes|reason|explain)\b", lower):
            return "exploratory"
        if re.search(r"\b(how (to|do|can)|steps|guide|tutorial)\b", lower):
            return "instructional"
        if query.endswith("?") and len(query.split()) < 15:
            return "factual"
        if any(word in lower for word in ["hello", "hi", "hey", "thanks"]):
            return "conversational"

        return "factual"

    def _detect_intent(self, query: str) -> str:
        """Detect user intent."""
        lower = query.lower()

        for pat in self.COMPARE_PATTERNS:
            if re.search(pat, lower):
                return "compare"
        for pat in self.ANALYZE_PATTERNS:
            if re.search(pat, lower):
                return "analyze"
        for pat in self.INSTRUCTIONAL_PATTERNS:
            if re.search(pat, lower):
                return "generate"
        for pat in self.FACTUAL_PATTERNS:
            if re.search(pat, lower):
                return "retrieve"

        return "retrieve"

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query."""
        # Remove common stop words
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "and", "or", "but", "if", "so", "as", "what", "which", "who",
            "whom", "where", "when", "why", "how", "does", "do", "did",
            "can", "could", "will", "would", "shall", "should", "may",
            "might", "has", "have", "had", "not", "no", "nor", "it",
            "its", "this", "that", "these", "those", "i", "me", "my",
            "you", "your", "he", "she", "we", "they", "am",
        }
        words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
        return [w for w in words if w not in stop_words][:10]

    def _extract_entities(self, query: str) -> List[str]:
        """Simple entity extraction (capitalized words, numbers, etc.)."""
        entities = []

        # Capitalized words (proper nouns)
        entities.extend(re.findall(r'\b[A-Z][a-z]+\b', query))

        # Numbers
        entities.extend(re.findall(r'\b\d+\b', query))

        # Quoted phrases
        entities.extend(re.findall(r'"([^"]+)"', query))
        entities.extend(re.findall(r"'([^']+)'", query))

        return entities

    def _detect_language(self, query: str) -> str:
        """Detect language (simple heuristic — English by default)."""
        # Check for non-ASCII characters
        non_ascii = sum(1 for c in query if ord(c) > 127)
        if non_ascii > len(query) * 0.3:
            return "unknown"
        return "en"

    def _needs_web_search(self, query: str) -> bool:
        """Determine if query needs web search for fresh data."""
        freshness_indicators = [
            r"\b(current|latest|recent|today|this (week|month|year))\b",
            r"\b(new|updates|news|trending|breaking)\b",
            r"\b(weather|stock|price|rate|score|result)\b",
            r"\b(202[4-9]|2030)\b",
        ]
        return any(re.search(pat, query.lower()) for pat in freshness_indicators)

    def _rewrite_query(self, query: str, query_type: str) -> str:
        """Rewrite query for optimal retrieval."""
        # Remove conversational filler
        cleaned = re.sub(r'\b(hey|hello|hi|please|thanks)\b', '', query, flags=re.I)
        cleaned = cleaned.strip().strip(",.!?")

        # Strip leading question words for search
        if query_type == "factual":
            cleaned = re.sub(
                r'^(what|who|where|when|why|how)\s+(is|are|was|were|does|do|did|can)\s+',
                '', cleaned, flags=re.I
            ).strip()

        # Ensure it's not empty
        return cleaned.strip() or query

    def _decompose_query(self, query: str) -> List[str]:
        """Split complex queries into sub-queries."""
        sub_queries = []

        # Split on "and" between questions
        parts = re.split(r'\band\b', query)

        # Split on question marks
        questions = re.split(r'[?]', query)

        for p in parts + questions:
            p = p.strip()
            if len(p) > 10 and p != query:
                sub_queries.append(p)

        return sub_queries[:3]

    def _expand_query(self, query: str, keywords: List[str]) -> List[str]:
        """Generate query expansions for broader retrieval."""
        expansions = [query]

        # Synonym expansion: add key terms without modifiers
        if len(keywords) >= 2:
            expansions.append(" ".join(keywords[:3]))

        # Remove stop words version
        stop_words = {"the", "a", "an", "is", "are", "was", "were",
                       "in", "on", "at", "to", "for", "of", "with"}
        compact = " ".join(w for w in query.split() if w.lower() not in stop_words)
        if compact and compact != query:
            expansions.append(compact)

        return expansions[:3]

    def _apply_context(self, query: str,
                        context: List[dict]) -> str:
        """Apply conversation context for query rewriting.

        Detects pronouns and references to prior messages.
        """
        if not context:
            return query

        # Check if query has no clear subject (pronouns etc)
        has_subject = bool(re.search(
            r'\b(AI|Friday|you|it|they|this|that|these|those)\b', query, re.I
        ))

        if has_subject and context:
            # Get last user message for reference
            for msg in reversed(context):
                if msg.get("role") in ("user", "human"):
                    last_user = msg.get("message", "")
                    # If query seems to reference something recent
                    if re.match(r"^(and|but|so|also|then|what about)", query.strip(), re.I):
                        # Extract main subject from last query
                        subject = self._extract_main_subject(last_user)
                        if subject:
                            return f"{query} ({subject})"
                    break

        return query

    def _extract_main_subject(self, text: str) -> Optional[str]:
        """Extract the main noun/subject from a text."""
        # Simple heuristic: first noun phrase after question words
        patterns = [
            r"(?:what|who|which|how about)\s+(?:is|are|was|were|does|do)?\s*(?:the|a|an|my|our)?\s*(\w+(?:\s+\w+){0,3})",
            r"^(?:the|a|an|my|our)\s+(\w+(?:\s+\w+){0,3})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip()
        return None
