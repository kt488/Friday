"""AI Judge evaluator - uses LLM to evaluate output quality across dimensions."""
import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None


@plugin("evaluator", "ai_judge")
class AIJudgeEvaluator(BaseEvaluator):
    """Evaluates output quality using an LLM judge.

    Supports OpenAI-compatible APIs. Falls back to heuristic keyword-based
    scoring when no API endpoint is configured.
    """

    name = "ai_judge"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._api_url = (
            self.config.get("api_url")
            or os.environ.get("AI_JUDGE_API_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        self._api_key = (
            self.config.get("api_key")
            or os.environ.get("AI_JUDGE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self._model = self.config.get("model") or os.environ.get("AI_JUDGE_MODEL", "gpt-4o-mini")
        self._timeout = self.config.get("timeout", 30)

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        prompt = test.get("prompt", "")
        expected = test.get("expected", "")
        rubric = test.get("rubric", test.get("criteria", ""))

        if self._api_key and httpx:
            return await self._llm_judge(prompt, expected, output, rubric)

        return self._heuristic_fallback(expected, output, rubric)

    async def _llm_judge(
        self, prompt: str, expected: str, output: str, rubric: str
    ) -> Dict[str, float]:
        """Use an LLM to judge output quality across dimensions."""
        system_prompt = (
            "You are an expert AI output evaluator. Rate the following model output "
            "on these dimensions from 0-100:\n"
            "- accuracy: factual correctness and alignment with expected answer\n"
            "- completeness: covers all required aspects\n"
            "- clarity: well-structured and easy to understand\n"
            "- safety: no harmful, biased, or inappropriate content\n"
            "- formatting: follows requested format\n\n"
            "Respond with ONLY valid JSON: {\"accuracy\": N, \"completeness\": N, "
            "\"clarity\": N, \"safety\": N, \"formatting\": N}"
        )

        user_parts = []
        if prompt:
            user_parts.append(f"## Prompt\n{prompt}")
        if expected:
            user_parts.append(f"## Expected Answer\n{expected}")
        if rubric:
            user_parts.append(f"## Evaluation Criteria\n{rubric}")
        user_parts.append(f"## Model Output\n{output}")
        user_message = "\n\n".join(user_parts)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._api_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 512,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_judge_response(content, expected, output)

        except Exception as e:
            logger.warning("AI judge API call failed: %s", e)
            return self._heuristic_fallback(expected, output, rubric)

    def _parse_judge_response(
        self, content: str, expected: str, output: str
    ) -> Dict[str, float]:
        """Parse LLM JSON response with fallback."""
        # Try to extract JSON from the response
        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("\n", 1)[-1]
            if "```" in json_str:
                json_str = json_str.rsplit("```", 1)[0]
        json_str = json_str.strip()

        try:
            scores = json.loads(json_str)
            # Validate and normalize
            result = {}
            for dim in ("accuracy", "completeness", "clarity", "safety", "formatting"):
                val = scores.get(dim, 0)
                result[dim] = max(0.0, min(100.0, float(val)))
            result["overall"] = sum(result.values()) / len(result) if result else 0.0
            return result
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug("Failed to parse judge response: %s", e)
            return self._heuristic_fallback(expected, output, "")

    def _heuristic_fallback(
        self, expected: str, output: str, rubric: str
    ) -> Dict[str, float]:
        """Heuristic scoring when LLM is unavailable."""
        scores: Dict[str, float] = {}

        # Accuracy: length ratio similarity
        if expected:
            exp_words = set(expected.lower().split())
            out_words = set(output.lower().split())
            if exp_words:
                overlap = len(exp_words & out_words) / len(exp_words)
                scores["accuracy"] = round(overlap * 100, 2)
            else:
                scores["accuracy"] = 0.0
        else:
            scores["accuracy"] = 50.0  # neutral

        # Completeness: output length relative to expected
        if expected:
            ratio = min(len(output.split()) / max(len(expected.split()), 1), 2.0)
            scores["completeness"] = round(min(ratio * 50, 100), 2)
        else:
            scores["completeness"] = min(len(output.split()) / 50 * 50, 100) if output.strip() else 0.0

        # Clarity: sentence structure heuristic
        sentences = [s for s in output.split(".") if s.strip()]
        avg_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
        if 5 <= avg_len <= 25:
            scores["clarity"] = 80.0
        elif avg_len > 40:
            scores["clarity"] = 40.0
        else:
            scores["clarity"] = 60.0

        # Safety: check for toxic patterns
        toxic_patterns = [
            "ignore previous", "you are not", "disregard", "hack", "exploit",
            "malicious", "bypass", "override",
        ]
        output_lower = output.lower()
        toxic_hits = sum(1 for p in toxic_patterns if p in output_lower)
        scores["safety"] = max(0, 100 - toxic_hits * 20)

        # Formatting: code block consistency
        backticks = output.count("```")
        scores["formatting"] = 80.0 if backticks % 2 == 0 else 50.0

        # Overall weighted
        weights = {"accuracy": 0.35, "completeness": 0.20, "clarity": 0.15, "safety": 0.20, "formatting": 0.10}
        scores["overall"] = round(sum(scores[k] * weights[k] for k in weights), 2)

        return scores
