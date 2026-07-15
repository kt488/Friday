"""Evaluator plugins for EVA."""
from eva.evaluators.base import BaseEvaluator
from eva.evaluators.exact_match import ExactMatchEvaluator
from eva.evaluators.semantic_similarity import SemanticSimilarityEvaluator
from eva.evaluators.keyword_match import KeywordMatchEvaluator
from eva.evaluators.regex_validator import RegexValidatorEvaluator
from eva.evaluators.json_schema_validator import JSONSchemaEvaluator
from eva.evaluators.ai_judge import AIJudgeEvaluator
from eva.evaluators.weighted_scoring import WeightedScoringEvaluator
from eva.evaluators.embedding_similarity import EmbeddingSimilarityEvaluator
from eva.evaluators.python_unit_test import PythonUnitTestEvaluator
from eva.evaluators.sql_validator import SQLValidatorEvaluator

__all__ = [
    "BaseEvaluator",
    "ExactMatchEvaluator",
    "SemanticSimilarityEvaluator",
    "KeywordMatchEvaluator",
    "RegexValidatorEvaluator",
    "JSONSchemaEvaluator",
    "AIJudgeEvaluator",
    "WeightedScoringEvaluator",
    "EmbeddingSimilarityEvaluator",
    "PythonUnitTestEvaluator",
    "SQLValidatorEvaluator",
]
