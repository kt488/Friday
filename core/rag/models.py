"""RAG data models — chunks, documents, embeddings, search results, config."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class ChunkType(enum.Enum):
    CODE = "code"
    DOCUMENT = "document"
    WEBSITE = "website"
    IMAGE = "image"
    DATABASE = "database"
    API = "api"
    CONVERSATION = "conversation"


class MemoryType(enum.Enum):
    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class AccessLevel(enum.IntEnum):
    PUBLIC = 0
    TEAM = 1
    ORGANIZATION = 2
    WORKSPACE = 3
    PRIVATE = 4


class IndexingStatus(enum.Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    STALE = "stale"


# ── Core Data Models ──────────────────────────────────────────────────────────

@dataclass
class ChunkMetadata:
    """Rich metadata attached to every chunk — 30+ fields for enterprise isolation."""
    # Tenant hierarchy
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    team_id: Optional[str] = None
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None

    # Source info
    source_type: ChunkType = ChunkType.DOCUMENT
    source_id: str = ""
    source_path: Optional[str] = None
    source_url: Optional[str] = None

    # Content metadata
    chunk_type: str = "text"
    language: Optional[str] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None

    # Structural positioning
    heading: Optional[str] = None
    section: Optional[str] = None
    parent_id: Optional[str] = None
    child_ids: List[str] = field(default_factory=list)
    position: int = 0

    # Importance & lifecycle
    importance: float = 0.5
    access_level: AccessLevel = AccessLevel.PRIVATE
    version: int = 1
    is_active: bool = True

    # Timestamps
    created_at: str = ""  # ISO
    updated_at: str = ""  # ISO
    expires_at: Optional[str] = None

    # Embedding info
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None
    embedding_dimension: int = 0

    # Security
    hash: str = ""  # SHA-256 of content
    is_sanitized: bool = False
    contains_pii: bool = False

    # Custom
    tags: List[str] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A single chunk of content with metadata and embedding."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    content: str = ""
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)
    embedding: Optional[List[float]] = None
    tokens: int = 0


@dataclass
class Document:
    """A source document to be chunked and indexed."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    content: str = ""
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)
    chunks: List[Chunk] = field(default_factory=list)
    status: IndexingStatus = IndexingStatus.PENDING
    error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class KnowledgeSource:
    """A registered knowledge source that feeds into the RAG system."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    source_type: ChunkType = ChunkType.DOCUMENT
    uri: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    last_indexed_at: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""


@dataclass
class EmbeddingRecord:
    """Stored embedding vector with metadata for persistence."""
    chunk_id: str = ""
    vector: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    model: str = ""
    dimension: int = 0
    created_at: str = ""


@dataclass
class SearchResult:
    """A single search result from hybrid retrieval."""
    chunk_id: str = ""
    content: str = ""
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)
    score: float = 0.0
    vector_score: float = 0.0
    keyword_score: float = 0.0
    recency_score: float = 0.0
    importance_score: float = 0.0
    rank: int = 0
    source: str = "hybrid"


@dataclass
class QueryAnalysis:
    """Result of query understanding and analysis."""
    original_query: str = ""
    rewritten_query: str = ""
    query_type: str = "factual"  # factual, conversational, instructional, exploratory
    intent: str = "retrieve"  # retrieve, generate, analyze, compare
    entities: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    sub_queries: List[str] = field(default_factory=list)
    expanded_queries: List[str] = field(default_factory=list)
    language: str = "en"
    needs_web_search: bool = False
    confidence: float = 1.0


@dataclass
class RAGContext:
    """Assembled context for LLM prompt injection."""
    chunks: List[SearchResult] = field(default_factory=list)
    memory_records: List[MemoryRecord] = field(default_factory=list)
    query_analysis: Optional[QueryAnalysis] = None
    context_text: str = ""
    total_tokens: int = 0
    retrieval_time_ms: float = 0.0
    source_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class MemoryRecord:
    """Unified memory record bridging RAG memory types with existing MemoryEntry."""
    id: str = ""
    content: str = ""
    memory_type: MemoryType = MemoryType.SHORT_TERM
    importance: float = 0.5
    access_count: int = 0
    last_accessed_at: str = ""
    created_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsolidationCandidate:
    """A memory chunk being considered for consolidation."""
    chunk_id: str = ""
    content: str = ""
    importance: float = 0.5
    access_frequency: int = 0
    age_days: float = 0.0
    consolidation_score: float = 0.0
    action: str = "keep"  # keep, promote, merge, archive, delete


@dataclass
class RAGConfig:
    """Central configuration for the RAG engine."""
    # Embedding
    embedding_model: str = "nvidia/nv-embed-qa-4"
    embedding_dimension: int = 4096
    embedding_batch_size: int = 16

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 64
    code_chunk_size: int = 256
    doc_chunk_size: int = 1024

    # Search
    top_k: int = 20
    top_k_rerank: int = 10
    top_k_final: int = 5
    min_score: float = 0.3
    vector_weight: float = 0.4
    keyword_weight: float = 0.3
    recency_weight: float = 0.15
    importance_weight: float = 0.15
    diversity_factor: float = 0.3  # MMR diversity

    # Memory
    memory_importance_threshold: float = 0.7
    memory_decay_rate: float = 0.1
    memory_rehearsal_interval: int = 86400  # 24h
    memory_promotion_threshold: float = 0.8
    memory_consolidation_interval: int = 3600  # 1h

    # Performance
    max_context_tokens: int = 4096
    cache_ttl: int = 300  # 5min
    enable_cache: bool = True

    # Security
    sanitize_secrets: bool = True
    enable_access_control: bool = True

    # Tenant
    default_workspace_id: str = "default"
    enable_tenant_isolation: bool = True
