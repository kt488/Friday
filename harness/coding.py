"""Friday AI Runtime Harness — Coding Assistant.

Provides code analysis, generation, review, debugging, and refactoring
capabilities with language-aware processing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .models import ValidationResult


class CodingAssistant:
    """Code analysis, generation, review, and debugging support."""

    def __init__(self):
        self._supported_languages = {
            "py": "python", "js": "javascript", "ts": "typescript",
            "tsx": "typescriptreact", "jsx": "javascriptreact",
            "go": "go", "rs": "rust", "java": "java", "rb": "ruby",
            "php": "php", "c": "c", "cpp": "cpp", "cs": "csharp",
            "swift": "swift", "kt": "kotlin", "scala": "scala",
            "html": "html", "css": "css", "scss": "scss", "sql": "sql",
            "sh": "bash", "yaml": "yaml", "json": "json", "xml": "xml",
            "md": "markdown", "toml": "toml", "dockerfile": "dockerfile",
        }
        self._reviews: List[Dict[str, Any]] = []

    def detect_language(self, filename: str, code: Optional[str] = None) -> str:
        """Detect programming language from filename or code content."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in self._supported_languages:
            return self._supported_languages[ext]
        if code:
            shebang = code.split("\n")[0] if code else ""
            if "python" in shebang.lower():
                return "python"
            if "node" in shebang.lower() or "bash" in shebang.lower():
                return "javascript" if "node" in shebang else "bash"
        return "unknown"

    def review_code(self, code: str, language: str = "python") -> ValidationResult:
        """Review code for issues, style problems, and potential bugs."""
        issues: List[str] = []
        suggestions: List[str] = []

        # Language-specific checks
        if language == "python":
            py_issues = self._review_python(code)
            issues.extend(py_issues["issues"])
            suggestions.extend(py_issues["suggestions"])
        elif language in ("javascript", "typescript"):
            js_issues = self._review_javascript(code, language)
            issues.extend(js_issues["issues"])
            suggestions.extend(js_issues["suggestions"])
        else:
            issues.append(f"No specific review checks for '{language}'")

        # Universal checks
        universal = self._review_universal(code)
        issues.extend(universal["issues"])
        suggestions.extend(universal["suggestions"])

        score = max(0.0, 1.0 - (len(issues) * 0.1))
        result = ValidationResult(
            passed=len(issues) == 0,
            score=round(score, 2),
            issues=issues[:15],
            suggestions=suggestions[:5],
        )

        self._reviews.append({
            "language": language,
            "lines": len(code.split("\n")),
            "issues": len(issues),
            "passed": result.passed,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })

        return result

    def get_review_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._reviews[-limit:]

    # ── Language-Specific Reviews ────────────────────────────────────────────

    def _review_python(self, code: str) -> Dict[str, Any]:
        """Python-specific code review checks."""
        issues = []
        suggestions = []

        # Bare except
        if re.search(r"except\s*:", code):
            issues.append("Bare 'except:' clause — catches all exceptions")
            suggestions.append("Use specific exception types instead of bare except")

        # Wildcard imports
        if re.search(r"from\s+\w+\s+import\s+\*", code):
            issues.append("Wildcard import detected")
            suggestions.append("Import only what you need")

        # Mutable default args
        mutable_defaults = re.findall(
            r"def\s+\w+\([^)]*=\s*(\[|\{)", code
        )
        if mutable_defaults:
            issues.append("Mutable default arguments detected")
            suggestions.append("Use None as default and create mutable inside function")

        # Print statements in non-script
        if "def " in code and re.search(r"^\s*print\(", code, re.M):
            suggestions.append("Consider using logging instead of print()")

        # Long lines
        for i, line in enumerate(code.split("\n"), 1):
            if len(line) > 100:
                suggestions.append(f"Line {i}: {len(line)} chars (limit 100)")
                break

        return {"issues": issues, "suggestions": suggestions}

    def _review_javascript(self, code: str, language: str) -> Dict[str, Any]:
        """JavaScript/TypeScript-specific code review checks."""
        issues = []
        suggestions = []

        # Console.log
        if re.search(r"console\.(log|warn|error)\(", code):
            suggestions.append("Remove console.* statements in production code")

        # Var usage
        if re.search(r"\bvar\s+\w+", code):
            issues.append("'var' keyword detected — use 'let' or 'const' instead")
            suggestions.append("Replace 'var' with 'let' or 'const'")

        # == vs ===
        eq_matches = re.findall(r"[^=!]==[^=]", code)
        if eq_matches:
            suggestions.append("Use === instead of == for strict equality")

        return {"issues": issues, "suggestions": suggestions}

    def _review_universal(self, code: str) -> Dict[str, Any]:
        """Universal code review checks across all languages."""
        issues = []
        suggestions = []

        # Hardcoded secrets
        secret_patterns = [
            (r"(?i)(password|secret|api_key|api\.key)\s*[:=]\s*['\"][^'\"]+['\"]", "Possible hardcoded secret"),
            (r"(?i)(token|apikey)\s*[:=]\s*['\"][^'\"]+['\"]", "Possible hardcoded token"),
        ]
        for pattern, msg in secret_patterns:
            if re.search(pattern, code, re.MULTILINE):
                issues.append(msg)
                break

        # TODO/FIXME
        todos = re.findall(r"(?i)(TODO|FIXME|HACK|XXX)", code)
        if todos:
            suggestions.append(f"Resolve {len(todos)} TODO/FIXME markers")

        # Extremely long functions
        lines = code.split("\n")
        if len(lines) > 200:
            suggestions.append(f"File is {len(lines)} lines — consider splitting")

        return {"issues": issues, "suggestions": suggestions}

    # ── Code Analysis ────────────────────────────────────────────────────────

    def analyze_code(self, code: str, language: str = "python") -> Dict[str, Any]:
        """Analyze code structure and extract metadata."""
        lines = code.split("\n")
        non_empty = [l for l in lines if l.strip()]

        # Count functions/classes
        functions = len(re.findall(r"^\s*(def |function |fn |public |private )", code, re.M))
        classes = len(re.findall(r"^\s*(class |interface |struct )", code, re.M))
        comments = len(re.findall(r"^\s*(#|//|--|/\*|\*)", code, re.M))

        return {
            "language": language,
            "total_lines": len(lines),
            "code_lines": len(non_empty),
            "blank_lines": len(lines) - len(non_empty),
            "functions": functions,
            "classes": classes,
            "comments": comments,
            "avg_line_length": round(sum(len(l) for l in non_empty) / len(non_empty), 1) if non_empty else 0,
        }

    def suggest_fix(self, error_message: str, code: str, language: str = "python") -> Optional[str]:
        """Suggest a fix based on an error message and context."""
        error_lower = error_message.lower()

        if "importerror" in error_lower or "modulenotfounderror" in error_lower:
            return "Ensure the module is installed and import path is correct"
        if "syntaxerror" in error_lower:
            line_match = re.search(r"line (\d+)", error_message)
            if line_match:
                return f"Check syntax around line {line_match.group(1)}"
            return "Check for syntax issues (missing colons, brackets, parentheses)"
        if "keyerror" in error_lower and language == "python":
            return "Use .get() method or check key existence before access"
        if "typeerror" in error_lower:
            return "Verify types — cast explicitly if needed"
        if "attributeerror" in error_lower:
            obj = re.search(r"'(\w+)' object has no attribute '(\w+)'", error_message)
            if obj:
                return f"'{obj.group(2)}' is not available on {obj.group(1)} objects"

        return None

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._reviews)
        passed = sum(1 for r in self._reviews if r["passed"])
        total_issues = sum(r["issues"] for r in self._reviews)
        return {
            "total_reviews": total,
            "passed": passed,
            "failed": total - passed,
            "total_issues_found": total_issues,
        }
