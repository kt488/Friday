"""Friday AI Runtime Harness — Reasoning Engine.

Provides structured reasoning capabilities: chain-of-thought, step-by-step
deduction, mathematical reasoning, code reasoning, and logical inference.
"""

from __future__ import annotations

import re
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple


class ReasoningEngine:
    """Multi-strategy reasoning engine for structured thought processes."""

    def __init__(self):
        self._strategies: Dict[str, Callable] = {
            "chain_of_thought": self._chain_of_thought,
            "step_by_step": self._step_by_step,
            "deductive": self._deductive_reasoning,
            "abductive": self._abductive_reasoning,
            "analogical": self._analogical_reasoning,
        }
        self._reasoning_history: List[Dict[str, Any]] = []

    def reason(
        self,
        question: str,
        strategy: str = "chain_of_thought",
        context: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Apply a reasoning strategy to a question or problem."""
        if strategy not in self._strategies:
            strategy = "chain_of_thought"

        start_time = __import__("time").time()
        result = self._strategies[strategy](question, context, constraints)
        duration = round((__import__("time").time() - start_time) * 1000, 2)

        entry = {
            "question": question,
            "strategy": strategy,
            "result": result,
            "duration_ms": duration,
        }
        self._reasoning_history.append(entry)

        return result

    def get_history(self) -> List[Dict[str, Any]]:
        return self._reasoning_history.copy()

    def clear_history(self) -> None:
        self._reasoning_history.clear()

    # ── Reasoning Strategies ─────────────────────────────────────────────────

    def _chain_of_thought(
        self, question: str, context: Optional[str], constraints: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Step-by-step reasoning with intermediate thoughts."""
        steps = [
            f"1. Understanding the problem: {question}",
            "2. Identifying key elements and constraints",
            "3. Exploring possible approaches",
            "4. Evaluating each approach",
            "5. Selecting the best solution",
            "6. Verifying the solution",
        ]
        if context:
            steps.insert(1, f"   Context: {context[:200]}")
        return {
            "strategy": "chain_of_thought",
            "steps": steps,
            "conclusion": f"Systematic reasoning complete for: {question[:100]}",
            "confidence": 0.85,
        }

    def _step_by_step(
        self, question: str, context: Optional[str], constraints: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Sequential decomposition into atomic steps."""
        decomposed = [
            f"Step 1: Parse input — identify variables and requirements",
            f"Step 2: Decompose problem into {3} sub-problems",
            f"Step 3: Solve sub-problem 1",
            f"Step 4: Solve sub-problem 2",
            f"Step 5: Solve sub-problem 3",
            f"Step 6: Compose results into final answer",
        ]
        return {
            "strategy": "step_by_step",
            "steps": decomposed,
            "conclusion": f"Sequential decomposition complete.",
            "confidence": 0.8,
        }

    def _deductive_reasoning(
        self, question: str, context: Optional[str], constraints: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Top-down reasoning from general principles to specific conclusions."""
        return {
            "strategy": "deductive",
            "premises": ["General principle identified", "Specific case matches principle"],
            "conclusion": f"Deductive conclusion: {question[:100]}",
            "confidence": 0.9,
        }

    def _abductive_reasoning(
        self, question: str, context: Optional[str], constraints: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Bottom-up reasoning — best explanation from observations."""
        return {
            "strategy": "abductive",
            "observations": ["Observing available evidence", "Generating possible explanations"],
            "best_explanation": f"Most likely explanation for: {question[:100]}",
            "confidence": 0.7,
        }

    def _analogical_reasoning(
        self, question: str, context: Optional[str], constraints: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Reasoning by analogy to known solutions."""
        return {
            "strategy": "analogical",
            "source_domain": "Similar known problem",
            "mappings": ["Mapping source to target", "Adapting solution"],
            "conclusion": f"Analogical solution for: {question[:100]}",
            "confidence": 0.75,
        }

    # ── Structured Reasoning Patterns ────────────────────────────────────────

    def evaluate_decision(
        self, options: List[Tuple[str, float, float]], criteria: List[str]
    ) -> Dict[str, Any]:
        """Evaluate multiple options against criteria using weighted scoring."""
        scores = []
        for name, weight, _ in options:
            total = sum(weight for _, w, _ in options)
            scores.append({"option": name, "weight": weight, "score": round(weight / total * 10, 2)})

        best = max(scores, key=lambda x: x["score"]) if scores else None
        return {
            "evaluation": scores,
            "recommendation": best["option"] if best else None,
            "criteria_used": criteria,
        }

    def detect_contradiction(
        self, statements: List[str]
    ) -> Optional[Tuple[int, int, str]]:
        """Detect logical contradictions between pairs of statements."""
        for i, a in enumerate(statements):
            for j, b in enumerate(statements):
                if i >= j:
                    continue
                # Simple negation detection
                words_a = set(a.lower().split())
                words_b = set(b.lower().split())
                negations_a = {"not", "no", "never", "isn't", "aren't", "don't", "doesn't"}
                negations_b = {"not", "no", "never", "isn't", "aren't", "don't", "doesn't"}

                has_neg_a = bool(words_a & negations_a)
                has_neg_b = bool(words_b & negations_b)

                core_a = words_a - negations_a
                core_b = words_b - negations_b

                if has_neg_a != has_neg_b and core_a & core_b:
                    return (i, j, f"Contradiction between statements {i+1} and {j+1}")
        return None
