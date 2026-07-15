"""SQL query validator evaluator."""
import logging
import re
from typing import Any, Dict, List, Optional

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)


@plugin("evaluator", "sql_validator")
class SQLValidatorEvaluator(BaseEvaluator):
    """Validates SQL query output for syntax, correctness, and security.

    Checks:
    - SQL syntax validity (basic parsing)
    - Presence of required tables/columns
    - Security patterns (SQL injection, unsafe operations)
    - Query structure (SELECT, JOIN, WHERE, etc.)
    """

    name = "sql_validator"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._allowed_operations = self.config.get("allowed_operations",
                                                     ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"])
        self._forbidden_keywords = self.config.get("forbidden_keywords", [
            "INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE", "xp_cmdshell",
            "EXEC xp_", "sp_configure", "RECONFIGURE",
        ])

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        sql = self._extract_sql(output)
        if not sql:
            logger.debug("No SQL found in output for %s", test.get("id"))
            return {"sql_validity": 0.0, "sql_security": 0.0, "overall": 0.0}

        expected_sql = test.get("expected", "")
        required_tables: List[str] = test.get("required_tables", [])
        required_columns: List[str] = test.get("required_columns", [])
        expected_operation = test.get("expected_operation", "")

        validity = self._check_validity(sql)
        security = self._check_security(sql)
        structure = self._check_structure(sql, expected_operation, required_tables, required_columns)
        semantics = 100.0
        if expected_sql:
            semantics = self._check_semantics(sql, expected_sql)

        result: Dict[str, float] = {
            "sql_validity": validity,
            "sql_security": security,
            "sql_structure": structure,
        }
        if expected_sql:
            result["sql_semantics"] = semantics

        # Combined overall: validity * (security + structure) / 2 * weight
        overall = round(validity * (0.4 + security * 0.3 + structure * 0.3) / 100, 2)
        result["overall"] = round(overall * 100, 2)

        return result

    def _extract_sql(self, output: str) -> str:
        """Extract SQL from fenced blocks or raw text."""
        lines = output.split("\n")
        in_block = False
        blocks: List[str] = []
        current: List[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                lang = stripped.strip("`").strip().lower()
                if in_block:
                    blocks.append("\n".join(current))
                    current = []
                    in_block = False
                elif not lang or lang in ("sql", "mysql", "postgresql", "psql"):
                    in_block = True
                continue
            if in_block:
                current.append(line)

        if current:
            blocks.append("\n".join(current))

        if blocks:
            return "\n".join(blocks)

        # No blocks: check if output looks like SQL
        upper = output.strip().upper()
        if any(upper.startswith(op) for op in self._allowed_operations):
            return output.strip()

        return ""

    def _check_validity(self, sql: str) -> float:
        """Basic SQL syntax validity check."""
        required_keywords = {"SELECT", "FROM"}
        upper = sql.upper()

        # Must have at least SELECT...FROM or relevant operation
        has_select = "SELECT" in upper
        has_from = "FROM" in upper
        has_insert = "INSERT" in upper
        has_create = "CREATE" in upper

        # Check basic structure
        if has_select and has_from:
            # Check SELECT clause has something
            select_match = re.search(r"SELECT\s+(.+?)\s+FROM", upper, re.DOTALL)
            if select_match:
                select_content = select_match.group(1).strip()
                if select_content and select_content != "*":
                    return 100.0
                return 80.0  # SELECT * is valid but simple
            return 50.0
        elif has_insert:
            return 80.0 if "VALUES" in upper else 60.0
        elif has_create:
            return 80.0
        elif "UPDATE" in upper and "SET" in upper:
            return 80.0
        elif "DELETE" in upper and "FROM" in upper:
            return 80.0

        return 30.0  # Looks SQL-ish but weak structure

    def _check_security(self, sql: str) -> float:
        """Check for security issues in SQL."""
        upper = sql.upper()
        score = 100.0

        # Check for forbidden/dangerous operations
        for kw in self._forbidden_keywords:
            if kw in upper:
                score -= 40

        # Dynamic SQL via string concatenation
        if re.search(r"['\"]\s*\+\s*['\"]", sql):
            score -= 25

        # Missing WHERE on DELETE/UPDATE
        if ("DELETE" in upper or "UPDATE" in upper) and "WHERE" not in upper:
            score -= 30

        # DROP TABLE without IF EXISTS
        if "DROP TABLE" in upper and "IF EXISTS" not in upper:
            score -= 20

        # Potential injection via unquoted user input markers
        injection_patterns = [r"\$\{", r"\{\{", r"format\(.*user", r"f['\"].*\{"]  # noqa: PIE808
        for pat in injection_patterns:
            if re.search(pat, sql, re.IGNORECASE):
                score -= 35

        return max(0, score)

    def _check_structure(
        self, sql: str,
        expected_operation: str,
        required_tables: List[str],
        required_columns: List[str],
    ) -> float:
        """Check query structure against requirements."""
        upper = sql.upper()
        score = 100.0
        deductions = 0

        if expected_operation:
            if expected_operation.upper() not in upper:
                score -= 30
                deductions += 1

        for table in required_tables:
            if table.upper() not in upper:
                score -= 20
                deductions += 1

        for col in required_columns:
            if col.upper() not in upper:
                score -= 15
                deductions += 1

        return max(0, score)

    def _check_semantics(self, sql: str, expected_sql: str) -> float:
        """Compare SQL semantics using normalized form."""
        def normalize(q: str) -> str:
            q = re.sub(r"\s+", " ", q.strip().upper())
            q = re.sub(r"\b(\w+)\s*=\s*\1\b", "", q)
            return q

        norm_sql = normalize(sql)
        norm_expected = normalize(expected_sql)

        if norm_sql == norm_expected:
            return 100.0

        # Token-level Jaccard similarity
        sql_tokens = set(norm_sql.split())
        exp_tokens = set(norm_expected.split())
        if not exp_tokens:
            return 50.0

        intersection = sql_tokens & exp_tokens
        union = sql_tokens | exp_tokens
        similarity = len(intersection) / len(union) if union else 0

        return round(similarity * 100, 2)
