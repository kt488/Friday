"""Friday AI Runtime Harness — File Operations Module.

Safe file I/O with path validation, encoding detection, size limits,
and git-aware operations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Severity


class FileHandler:
    """Safe file operations with validation and limits."""

    def __init__(self, max_file_size: int = 10 * 1024 * 1024):
        self._max_file_size = max_file_size
        self._allowed_extensions: set = set()
        self._blocked_patterns: List[str] = [
            r"\.env$", r"\.env\.", r"credentials\.", r"config\.json$",
            r"secret", r"key\.",
        ]
        self._history: List[Dict[str, Any]] = []

    def read_file(self, path: str, offset: int = 0, limit: Optional[int] = None) -> Dict[str, Any]:
        """Read a file with safety checks."""
        path_obj = Path(path).resolve()
        result = self._validate_path(path_obj)
        if not result["valid"]:
            return {"success": False, "error": result["error"]}

        if path_obj.stat().st_size > self._max_file_size:
            return {"success": False, "error": f"File exceeds max size ({self._max_file_size} bytes)"}

        try:
            encoding = self._detect_encoding(path_obj)
            content = path_obj.read_text(encoding=encoding)
            lines = content.split("\n")

            if offset > 0:
                lines = lines[offset:]
            if limit:
                lines = lines[:limit]

            self._record("read", path, len(content))
            return {
                "success": True,
                "content": "\n".join(lines),
                "total_lines": len(content.split("\n")),
                "returned_lines": len(lines),
                "encoding": encoding,
                "size_bytes": path_obj.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "error": f"Read error: {e}"}

    def write_file(self, path: str, content: str, safe: bool = True) -> Dict[str, Any]:
        """Write a file with safety checks."""
        path_obj = Path(path).resolve()

        if safe:
            result = self._validate_path(path_obj, write=True)
            if not result["valid"]:
                return {"success": False, "error": result["error"]}

        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(content)
            self._record("write", path, len(content))
            return {
                "success": True,
                "path": str(path_obj),
                "size_bytes": path_obj.stat().st_size,
                "lines": len(content.split("\n")),
            }
        except Exception as e:
            return {"success": False, "error": f"Write error: {e}"}

    def list_directory(
        self, path: str, pattern: Optional[str] = None, recursive: bool = False
    ) -> Dict[str, Any]:
        """List directory contents with optional glob pattern."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}
        if not path_obj.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        try:
            if recursive:
                items = list(path_obj.rglob(pattern or "*"))
            else:
                items = list(path_obj.glob(pattern or "*"))

            entries = []
            for item in sorted(items):
                try:
                    stat = item.stat()
                    entries.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "dir" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else 0,
                        "modified": stat.st_mtime,
                    })
                except OSError:
                    continue

            return {"success": True, "entries": entries, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": f"List error: {e}"}

    def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get file metadata without reading content."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            return {"success": False, "error": "File not found"}
        try:
            stat = path_obj.stat()
            return {
                "success": True,
                "name": path_obj.name,
                "path": str(path_obj),
                "type": "dir" if path_obj.is_dir() else "file",
                "size_bytes": stat.st_size,
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "extension": path_obj.suffix,
            }
        except Exception as e:
            return {"success": False, "error": f"Info error: {e}"}

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._history)
        reads = sum(1 for h in self._history if h["operation"] == "read")
        writes = sum(1 for h in self._history if h["operation"] == "write")
        total_bytes = sum(h["size"] for h in self._history)
        return {
            "total_operations": total,
            "reads": reads,
            "writes": writes,
            "total_bytes_transferred": total_bytes,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _validate_path(self, path: Path, write: bool = False) -> Dict[str, Any]:
        """Validate file path for safety."""
        if not write and not path.exists():
            return {"valid": False, "error": "File not found"}
        if write and path.is_dir():
            return {"valid": False, "error": "Cannot write to a directory"}
        for pattern in self._blocked_patterns:
            if re.search(pattern, path.name, re.I):
                return {"valid": False, "error": f"File blocked by security pattern: {pattern}"}
        return {"valid": True}

    def _detect_encoding(self, path: Path) -> str:
        """Detect file encoding."""
        try:
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                return "utf-8-sig"
            # Try common encodings
            for enc in ["utf-8", "latin-1", "cp1252"]:
                try:
                    raw.decode(enc)
                    return enc
                except (UnicodeDecodeError, UnicodeEncodeError):
                    continue
            return "utf-8"
        except Exception:
            return "utf-8"

    def _record(self, operation: str, path: str, size: int) -> None:
        self._history.append({
            "operation": operation,
            "path": path,
            "size": size,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })
