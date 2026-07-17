"""Friday AI Runtime Harness — Security Filters & Sandbox."""

from __future__ import annotations

import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

from .models import Severity


class SecurityManager:
    """Security filters, sandbox enforcement, and dangerous operation guards."""

    def __init__(
        self,
        allowed_paths: Optional[List[str]] = None,
        blocked_commands: Optional[List[str]] = None,
        dangerous_confirm: bool = True,
    ):
        self._allowed_paths = allowed_paths or [
            os.getcwd(),
            os.path.expanduser("~"),
        ]
        self._blocked_commands = blocked_commands or [
            "rm -rf /", "sudo", "chmod 777", "dd if=", "mkfs",
            "> /dev/", ":(){ :|:& };:", "wget ", "curl ",
        ]
        self._dangerous_confirm = dangerous_confirm
        self._audit_log: List[Dict[str, Any]] = []

    def validate_command(self, command: str) -> Tuple[bool, Optional[str]]:
        """Check if a shell command is safe to execute."""
        cmd_lower = command.lower().strip()

        for blocked in self._blocked_commands:
            if blocked.lower() in cmd_lower:
                self._audit("blocked_command", command, f"Matches blocked pattern: {blocked}")
                return False, f"Command blocked: matches dangerous pattern '{blocked}'"

        # Parse and check individual tokens
        try:
            tokens = shlex.split(command)
        except ValueError:
            self._audit("parse_error", command, "Failed to parse command")
            return False, "Invalid shell syntax"

        base_cmd = os.path.basename(tokens[0]) if tokens else ""

        # Block relative path traversal escapes
        for token in tokens:
            if ".." in token and "../" in token:
                self._audit("path_traversal", command, "Path traversal detected")
                return False, "Path traversal detected"

        self._audit("allowed", command, f"Command allowed: {base_cmd}")
        return True, None

    def validate_path(self, path: str, write: bool = False) -> Tuple[bool, Optional[str]]:
        """Check if a file path is within allowed boundaries."""
        abs_path = os.path.abspath(os.path.expanduser(path))

        allowed = False
        for allowed_path in self._allowed_paths:
            abs_allowed = os.path.abspath(os.path.expanduser(allowed_path))
            if abs_path.startswith(abs_allowed):
                allowed = True
                break

        if not allowed:
            return False, f"Path '{path}' is outside allowed directories"

        if write and os.path.exists(abs_path) and not os.access(abs_path, os.W_OK):
            return False, f"Path '{path}' is not writable"

        return True, None

    def confirm_dangerous(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Check if a dangerous tool requires confirmation."""
        if not self._dangerous_confirm:
            return True
        self._audit("dangerous_confirm", f"{tool_name}({args})",
                     "Dangerous tool requires user confirmation")
        return False  # Require external confirmation

    def add_allowed_path(self, path: str) -> None:
        """Add a path to the allowed list."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path not in self._allowed_paths:
            self._allowed_paths.append(abs_path)

    def remove_allowed_path(self, path: str) -> bool:
        """Remove a path from the allowed list."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path in self._allowed_paths:
            self._allowed_paths.remove(abs_path)
            return True
        return False

    def add_blocked_command(self, pattern: str) -> None:
        """Add a command pattern to the blocked list."""
        if pattern not in self._blocked_commands:
            self._blocked_commands.append(pattern)

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the security audit log."""
        return self._audit_log[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get security manager statistics."""
        total = len(self._audit_log)
        blocked = sum(1 for a in self._audit_log if a["action"] == "blocked_command")
        allowed = sum(1 for a in self._audit_log if a["action"] == "allowed")
        return {
            "total_checks": total,
            "blocked": blocked,
            "allowed": allowed,
            "danger_confirm_enabled": self._dangerous_confirm,
            "allowed_paths": len(self._allowed_paths),
            "blocked_patterns": len(self._blocked_commands),
        }

    def _audit(self, action: str, target: str, reason: str) -> None:
        self._audit_log.append({
            "action": action,
            "target": target[:200],
            "reason": reason,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })
