"""Security layer — secret sanitization, PII detection, access control, audit logging.

Ensures sensitive information is never stored in the RAG knowledge base.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.rag.models import AccessLevel, Chunk, ChunkMetadata

logger = logging.getLogger(__name__)


class SecurityFilter:
    """Security layer for RAG — sanitizes content before indexing.

    Features:
    - Secret/key detection and redaction
    - PII detection and masking
    - Access level enforcement
    - Audit logging
    """

    # Secret patterns
    SECRET_PATTERNS = [
        (r'(?i)(api[_-]?key|apikey|secret|password|token|auth|credential)\s*[=:]\s*["\']?([\w\-_.]{8,})["\']?', 'SECRET'),
        (r'(?i)(sk-[a-zA-Z0-9]{20,})', 'OPENAI_KEY'),  # OpenAI keys
        (r'(?i)(nvapi-[a-zA-Z0-9\-_]{20,})', 'NVIDIA_KEY'),  # NVIDIA keys
        (r'(?:-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----)', 'PRIVATE_KEY'),
        (r'ghp_[a-zA-Z0-9]{36}', 'GITHUB_TOKEN'),
        (r'gho_[a-zA-Z0-9]{36}', 'GITHUB_TOKEN'),
        (r'xox[baprs]-[a-zA-Z0-9\-]{10,}', 'SLACK_TOKEN'),
        (r'(?i)(eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+)', 'JWT_TOKEN'),
    ]

    # PII patterns
    PII_PATTERNS = [
        (r'\b[\w\.-]+@[\w\.-]+\.\w+\b', 'EMAIL'),
        (r'\b(?:\d{3}[-.]?){2}\d{4}\b', 'PHONE'),  # US phone
        (r'\b\d{3}-\d{2}-\d{4}\b', 'SSN'),  # SSN
        (r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b', 'CREDIT_CARD'),
        (r'\b\d{5}(?:-\d{4})?\b', 'ZIPCODE'),
    ]

    def __init__(self, sanitize_secrets: bool = True,
                 enable_access_control: bool = True):
        self.sanitize_secrets = sanitize_secrets
        self.enable_access_control = enable_access_control
        self._audit_log: List[dict] = []

    def sanitize(self, content: str) -> str:
        """Sanitize content by redacting secrets and PII."""
        if not self.sanitize_secrets:
            return content

        original = content

        # Redact secrets
        for pattern, label in self.SECRET_PATTERNS:
            content = re.sub(pattern, f'[REDACTED_{label}]', content)

        # Mask PII
        for pattern, label in self.PII_PATTERNS:
            content = re.sub(pattern, f'[REDACTED_{label}]', content)

        if content != original:
            self._audit_log.append({
                "action": "sanitize",
                "timestamp": datetime.utcnow().isoformat(),
                "original_length": len(original),
                "sanitized_length": len(content),
            })

        return content

    def check_pii(self, content: str) -> bool:
        """Check if content contains PII."""
        for pattern, _ in self.PII_PATTERNS:
            if re.search(pattern, content):
                return True
        return False

    def check_secrets(self, content: str) -> bool:
        """Check if content contains secrets."""
        for pattern, _ in self.SECRET_PATTERNS:
            if re.search(pattern, content):
                return True
        return False

    def sanitize_chunk(self, chunk: Chunk) -> Chunk:
        """Sanitize a chunk's content in place."""
        original_content = chunk.content
        chunk.content = self.sanitize(chunk.content)
        chunk.metadata.is_sanitized = (chunk.content != original_content)
        chunk.metadata.contains_pii = self.check_pii(chunk.content)
        chunk.metadata.hash = hashlib.sha256(chunk.content.encode()).hexdigest()[:16]

        # Add sanitization tags
        if chunk.metadata.is_sanitized:
            if "sanitized" not in chunk.metadata.tags:
                chunk.metadata.tags.append("sanitized")
        if chunk.metadata.contains_pii:
            if "contains_pii" not in chunk.metadata.tags:
                chunk.metadata.tags.append("contains_pii")

        return chunk

    def check_access(self, chunk: Chunk,
                      user_access_level: AccessLevel = AccessLevel.PRIVATE,
                      workspace_id: Optional[str] = None,
                      user_id: Optional[str] = None) -> bool:
        """Check if user has access to a chunk."""
        if not self.enable_access_control:
            return True

        # Workspace isolation
        if workspace_id and chunk.metadata.workspace_id:
            if chunk.metadata.workspace_id != workspace_id:
                return False

        # User isolation
        if user_id and chunk.metadata.user_id:
            if chunk.metadata.user_id != user_id:
                return False

        # Access level check
        if user_access_level.value < chunk.metadata.access_level.value:
            return False

        return True

    def filter_by_access(self, chunks: List[Chunk],
                          user_access_level: AccessLevel = AccessLevel.PRIVATE,
                          workspace_id: Optional[str] = None,
                          user_id: Optional[str] = None) -> List[Chunk]:
        """Filter chunks by user's access level and tenant scope."""
        return [
            c for c in chunks
            if self.check_access(c, user_access_level, workspace_id, user_id)
        ]

    def get_audit_log(self, recent: int = 100) -> List[dict]:
        """Get recent audit log entries."""
        return self._audit_log[-recent:]

    def log_access(self, action: str, chunk_id: str, user_id: str,
                    workspace_id: str, details: Optional[dict] = None):
        """Log an access event."""
        entry = {
            "action": action,
            "chunk_id": chunk_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details or {},
        }
        self._audit_log.append(entry)
        logger.info(f"Access: {action} chunk={chunk_id} user={user_id}")
