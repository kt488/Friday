"""
Core evaluation engine for EVA.

Async evaluation runner with plugin-based evaluator registry, parallel
execution, timeout handling, result aggregation, and progress tracking.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from eva.config import EVAConfig

logger = logging.getLogger(__name__)


class TestStatus(Enum):
    """Status of a single test evaluation."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class TestResult:
    """Result of evaluating a single test."""
    id: str
    test_id: str
    category: str
    status: TestStatus
    scores: Dict[str, float] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    output: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost: float = 0.0
    timestamp: float = field(default_factory=time.time)
    model: str = ""
    evaluator: str = ""

    @property
    def overall_score(self) -> float:
        """Get overall score from scores dict, defaulting to 0."""
        return self.scores.get("overall", self.scores.get("accuracy", 0.0))

    @property
    def passed(self) -> bool:
        """Check if test passed."""
        return self.status == TestStatus.PASSED

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "test_id": self.test_id,
            "category": self.category,
            "status": self.status.value,
            "scores": self.scores,
            "metrics": self.metrics,
            "errors": self.errors,
            "output": self.output,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
            "timestamp": self.timestamp,
            "model": self.model,
            "evaluator": self.evaluator,
            "overall_score": self.overall_score,
            "passed": self.passed,
        }


@dataclass
class EvalRun:
    """Represents a complete evaluation run."""
    id: str
    name: str
    start_time: float
    end_time: Optional[float] = None
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    results: List[TestResult] = field(default_factory=list)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        """Get run duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed / self.total_tests) * 100.0

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency across results."""
        if not self.results:
            return 0.0
        return sum(r.latency_ms for r in self.results) / len(self.results)

    @property
    def total_cost(self) -> float:
        """Calculate total cost across results."""
        return sum(r.cost for r in self.results)

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens used."""
        return sum(r.tokens_used for r in self.results)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "pass_rate": self.pass_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "results": [r.to_dict() for r in self.results],
        }

    def get_category_scores(self) -> Dict[str, Dict[str, float]]:
        """Get average scores grouped by category."""
        categories: Dict[str, List[TestResult]] = {}
        for r in self.results:
            categories.setdefault(r.category, []).append(r)

        result: Dict[str, Dict[str, float]] = {}
        for cat, cat_results in categories.items():
            scores: Dict[str, List[float]] = {}
            for cr in cat_results:
                for score_name, score_val in cr.scores.items():
                    scores.setdefault(score_name, []).append(score_val)

            avg_scores: Dict[str, float] = {}
            for sname, svals in scores.items():
                avg_scores[sname] = sum(svals) / len(svals) if svals else 0.0

            result[cat] = avg_scores

        return result


class EvaluationEngine:
    """Core evaluation engine for running test suites.

    Handles test execution, timeout management, retry logic,
    result collection, and progress tracking.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or EVAConfig.get_section("engine")
        self._running = False
        self._cancel_flag = False
        self._progress: Dict[str, Any] = {
            "total": 0,
            "completed": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
        }
        self.logger = logger

    async def run_suite(
        self,
        suite_name: str,
        tests: List[Dict[str, Any]],
        evaluators: Optional[List[str]] = None,
        parallel: bool = True,
    ) -> EvalRun:
        """Run a complete test suite.

        Args:
            suite_name: Name for this evaluation run.
            tests: List of test definitions.
            evaluators: List of evaluator names to use.
            parallel: Whether to run tests in parallel.

        Returns:
            EvalRun with aggregated results.
        """
        from eva.core.registry import PluginRegistry

        eval_run = EvalRun(
            id=str(uuid.uuid4()),
            name=suite_name,
            start_time=time.time(),
            total_tests=len(tests),
            config_snapshot=EVAConfig.to_dict(),
        )

        self._running = True
        self._cancel_flag = False
        self._progress = {
            "total": len(tests),
            "completed": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
        }

        evaluator_names = evaluators or EVAConfig.get("evaluators.default", ["exact_match"])
        evaluator_instances = []
        for ename in evaluator_names:
            try:
                inst = PluginRegistry.create("evaluator", ename)
                evaluator_instances.append(inst)
            except KeyError:
                self.logger.warning("Evaluator '%s' not found, skipping", ename)

        if not evaluator_instances:
            self.logger.error("No evaluators available")
            eval_run.end_time = time.time()
            return eval_run

        if parallel and len(tests) > 1:
            results = await self._run_parallel(tests, evaluator_instances)
        else:
            results = []
            for test in tests:
                if self._cancel_flag:
                    break
                result = await self._execute_test(test, evaluator_instances)
                results.append(result)
                self._update_progress(result)

        eval_run.results = results
        self._aggregate_results(eval_run)
        eval_run.end_time = time.time()
        self._running = False

        self.logger.info(
            "Suite '%s' complete: %d/%d passed (%.1f%%) in %.2fs",
            suite_name,
            eval_run.passed,
            eval_run.total_tests,
            eval_run.pass_rate,
            eval_run.duration,
        )

        return eval_run

    async def run_single_test(
        self,
        test: Dict[str, Any],
        evaluators: Optional[List[str]] = None,
    ) -> TestResult:
        """Run a single test through specified evaluators.

        Args:
            test: Test definition dict.
            evaluators: List of evaluator names.

        Returns:
            TestResult for this test.
        """
        from eva.core.registry import PluginRegistry

        evaluator_names = evaluators or EVAConfig.get("evaluators.default", ["exact_match"])
        instances = []
        for ename in evaluator_names:
            try:
                instances.append(PluginRegistry.create("evaluator", ename))
            except KeyError:
                self.logger.warning("Evaluator '%s' not found", ename)

        return await self._execute_test(test, instances)

    async def _run_parallel(
        self,
        tests: List[Dict[str, Any]],
        evaluator_instances: List,
    ) -> List[TestResult]:
        """Run tests in parallel using asyncio.

        Args:
            tests: List of test definitions.
            evaluator_instances: List of instantiated evaluators.

        Returns:
            List of TestResults.
        """
        max_workers = self.config.get("max_workers", 4)
        semaphore = asyncio.Semaphore(max_workers)

        async def _run_with_semaphore(test: Dict[str, Any]) -> TestResult:
            async with semaphore:
                result = await self._execute_test(test, evaluator_instances)
                self._update_progress(result)
                return result

        tasks = [_run_with_semaphore(t) for t in tests]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_test(
        self,
        test: Dict[str, Any],
        evaluator_instances: List,
    ) -> TestResult:
        """Execute a single test through all evaluators.

        Args:
            test: Test definition dict.
            evaluator_instances: List of evaluator instances.

        Returns:
            TestResult with scores from all evaluators.
        """
        test_id = test.get("id", str(uuid.uuid4()))
        category = test.get("category", "general")
        timeout = test.get("max_latency", self.config.get("default_timeout", 60))
        max_retries = self.config.get("retry_count", 2)

        result = TestResult(
            id=str(uuid.uuid4()),
            test_id=test_id,
            category=category,
            status=TestStatus.RUNNING,
        )

        start_time = time.time()

        for attempt in range(max_retries + 1):
            try:
                combined_scores: Dict[str, float] = {}
                combined_errors: List[str] = []

                for evaluator in evaluator_instances:
                    try:
                        eval_scores = await asyncio.wait_for(
                            evaluator.evaluate(test, test.get("output", "")),
                            timeout=timeout,
                        )
                        combined_scores.update(eval_scores)
                    except asyncio.TimeoutError:
                        combined_errors.append(
                            f"Evaluator '{evaluator.name}' timed out after {timeout}s"
                        )
                    except Exception as e:
                        combined_errors.append(
                            f"Evaluator '{evaluator.name}' error: {str(e)}"
                        )

                result.scores = combined_scores
                result.errors = combined_errors

                # Determine pass/fail
                pass_threshold = EVAConfig.get("scoring.pass_threshold", 70.0)
                overall = combined_scores.get("overall",
                                              combined_scores.get("accuracy", 0.0))
                if overall >= pass_threshold and not combined_errors:
                    result.status = TestStatus.PASSED
                else:
                    result.status = TestStatus.FAILED

                break  # Success, exit retry loop

            except Exception as e:
                self.logger.error(
                    "Test %s attempt %d failed: %s", test_id, attempt + 1, str(e)
                )
                if attempt == max_retries:
                    result.status = TestStatus.ERROR
                    result.errors.append(str(e))
                else:
                    await asyncio.sleep(1 * (attempt + 1))

        result.latency_ms = (time.time() - start_time) * 1000
        result.tokens_used = test.get("expected_tokens", 0)
        self._calculate_metrics(result)

        return result

    @staticmethod
    def _calculate_metrics(result: TestResult) -> None:
        """Calculate derived metrics from raw results."""
        metrics = {}

        scores_list = list(result.scores.values())
        if scores_list:
            metrics["avg_score"] = sum(scores_list) / len(scores_list)
            metrics["min_score"] = min(scores_list)
            metrics["max_score"] = max(scores_list)

        metrics["latency_seconds"] = result.latency_ms / 1000.0
        metrics["cost_estimate"] = (result.tokens_used * 0.000003)  # rough estimate

        result.metrics = metrics
        result.cost = metrics["cost_estimate"]

    @staticmethod
    def _aggregate_results(run: EvalRun) -> None:
        """Aggregate all results into summary statistics.

        Args:
            run: EvalRun to update with aggregated counts.
        """
        passed = 0
        failed = 0
        errors = 0

        for result in run.results:
            if result.status == TestStatus.PASSED:
                passed += 1
            elif result.status in (TestStatus.FAILED, TestStatus.TIMEOUT):
                failed += 1
            elif result.status == TestStatus.ERROR:
                errors += 1

        run.passed = passed
        run.failed = failed
        run.errors = errors

    def _update_progress(self, result: TestResult) -> None:
        """Update progress tracking with a completed result."""
        self._progress["completed"] += 1
        if result.status == TestStatus.PASSED:
            self._progress["passed"] += 1
        elif result.status in (TestStatus.FAILED, TestStatus.TIMEOUT):
            self._progress["failed"] += 1
        elif result.status == TestStatus.ERROR:
            self._progress["errors"] += 1

    def get_progress(self) -> Dict[str, Any]:
        """Get current progress of running evaluation.

        Returns:
            Dict with total, completed, passed, failed, errors counts.
        """
        progress = dict(self._progress)
        if progress["total"] > 0:
            progress["percent"] = (progress["completed"] / progress["total"]) * 100
        else:
            progress["percent"] = 0
        return progress

    def cancel(self) -> None:
        """Cancel the running evaluation."""
        self._cancel_flag = True
        self._running = False
        self.logger.info("Evaluation cancelled by user")

    @property
    def is_running(self) -> bool:
        """Check if engine is currently running an evaluation."""
        return self._running
