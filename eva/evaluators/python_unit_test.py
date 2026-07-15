"""Python unit test evaluator - runs code against test cases."""
import ast
import logging
import sys
import textwrap
import traceback
from typing import Any, Dict, List, Optional

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "python_unit_test")
class PythonUnitTestEvaluator(BaseEvaluator):
    """Extracts Python code from output and runs unit tests against it.

    Test definitions in test definition should contain 'unit_tests' with
    a list of test cases, each with 'name', 'input', and optionally
    'expected' or 'assert' expressions.
    """

    name = "python_unit_test"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._timeout = self.config.get("timeout", 10)

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        test_cases: List[Dict[str, Any]] = test.get("unit_tests", test.get("test_cases", []))
        if not test_cases:
            logger.debug("No unit tests defined for %s", test.get("id"))
            return {"code_quality": 100.0, "overall": 100.0}

        code = self._extract_code(output)
        if not code:
            logger.debug("No Python code found in output for %s", test.get("id"))
            return {"code_quality": 0.0, "overall": 0.0}

        passed = 0
        failed = 0
        errors: List[str] = []

        for i, tc in enumerate(test_cases):
            try:
                result = self._run_test(code, tc)
                if result["passed"]:
                    passed += 1
                else:
                    failed += 1
                    errors.append(f"Test '{tc.get('name', f'case_{i}')}' failed: {result.get('error', '')}")
            except Exception as e:
                failed += 1
                errors.append(f"Test '{tc.get('name', f'case_{i}')}' error: {e}")

        total = len(test_cases)
        pass_rate = round((passed / total) * 100, 2) if total else 100.0
        code_quality = self._assess_code_quality(code)

        result: Dict[str, float] = {
            "code_quality": round(code_quality, 2),
            "pass_rate": pass_rate,
            "total_tests": float(total),
            "passed": float(passed),
            "failed": float(failed),
        }

        # Lower pass threshold for code quality adjustment
        quality_penalty = max(0, 100 - code_quality) * 0.2
        result["overall"] = round(pass_rate * 1.0 - quality_penalty, 2)

        if errors:
            result["_errors"] = float(len(errors))

        return result

    def _extract_code(self, output: str) -> str:
        """Extract Python code from output, handling fenced blocks."""
        # Try fenced code blocks first
        lines = output.split("\n")
        in_block = False
        code_blocks: List[str] = []
        current: List[str] = []

        for line in lines:
            if line.strip().startswith("```"):
                lang = line.strip().strip("`").strip().lower()
                if in_block:
                    code_blocks.append("\n".join(current))
                    current = []
                    in_block = False
                elif not lang or lang == "python":
                    in_block = True
                continue
            if in_block:
                current.append(line)

        if current:
            code_blocks.append("\n".join(current))

        if code_blocks:
            return "\n".join(code_blocks)

        # No fenced blocks found; try parsing whole output as Python
        try:
            ast.parse(output)
            return output
        except SyntaxError:
            pass

        return ""

    def _run_test(self, code: str, tc: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single test case against the code."""
        namespace: Dict[str, Any] = {}
        test_input = tc.get("input", tc.get("args", ""))
        expected = tc.get("expected")
        assert_expr = tc.get("assert")
        func_name = tc.get("function", tc.get("func", "solution"))

        try:
            exec(compile(ast.parse(textwrap.dedent(code)), "<eval>", "exec"), namespace)
        except Exception as e:
            return {"passed": False, "error": f"Compile error: {e}"}

        if func_name not in namespace:
            return {"passed": False, "error": f"Function '{func_name}' not defined"}

        try:
            if isinstance(test_input, list) and not isinstance(test_input, str):
                result = namespace[func_name](*test_input)
            elif isinstance(test_input, dict) and not isinstance(test_input, str):
                result = namespace[func_name](**test_input)
            else:
                result = namespace[func_name](test_input)
        except Exception as e:
            tb = traceback.format_exc()
            return {"passed": False, "error": f"Runtime error: {e}\n{tb}"}

        if assert_expr:
            try:
                assert_ns = {"result": result, **namespace}
                exec(f"assert {assert_expr}", assert_ns)
                return {"passed": True, "result": str(result)}
            except AssertionError:
                return {"passed": False, "error": f"Assertion failed: {assert_expr}, got {result}"}
            except Exception as e:
                return {"passed": False, "error": f"Assert error: {e}"}

        if expected is not None:
            match = result == expected
            return {"passed": match, "result": str(result),
                    "error": "" if match else f"Expected {expected!r}, got {result!r}"}

        return {"passed": True, "result": str(result)}

    def _assess_code_quality(self, code: str) -> float:
        """Assess code quality heuristically."""
        score = 100.0

        # Check for docstrings
        if '"""' not in code and "'''" not in code:
            score -= 10

        # Check for type hints (rough heuristic)
        if ":" in code and "def " in code:
            has_hints = any(":" in line and "def" in line for line in code.split("\n"))
            if not has_hints:
                score -= 10

        # Check line length
        for line in code.split("\n"):
            if len(line) > 100:
                score -= 2

        # Check for print statements (debugging artifacts)
        if "print(" in code:
            score -= 5

        # Check for bare except
        if "except:" in code:
            score -= 10

        return max(0, score)
