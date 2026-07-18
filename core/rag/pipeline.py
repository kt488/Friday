"""RAG pipeline — end-to-end retrieval-augmented generation pipeline.

Coordinates: query understanding → hybrid search → reranking → context building
→ security → memory consolidation → LLM integration.
"""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.rag.chunking import ChunkerFactory, CodeChunker, DocumentChunker, WebsiteChunker
from core.rag.context_builder import ContextBuilder
from core.rag.database import RAGDatabase
from core.rag.embeddings import EmbeddingGenerator
from core.rag.hybrid_search import HybridSearch
from core.rag.memory_consolidation import MemoryConsolidation
from core.rag.models import (
    Chunk, ChunkMetadata, ChunkType, Document, QueryAnalysis,
    RAGConfig, RAGContext, SearchResult,
)
from core.rag.query_understanding import QueryUnderstanding
from core.rag.reranker import Reranker
from core.rag.security import SecurityFilter
from core.rag.vector_store import VectorStore


class RAGPipeline:
    """End-to-end RAG pipeline.

    Usage:
        pipeline = RAGPipeline()
        pipeline.initialize()
        context = pipeline.query("What is Friday?", user_id="u1", workspace_id="default")
        # context.context_text contains assembled context for LLM prompt
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()

        # Components (lazy initialized)
        self.db: Optional[RAGDatabase] = None
        self.embedder: Optional[EmbeddingGenerator] = None
        self.vector_store: Optional[VectorStore] = None
        self.hybrid_search: Optional[HybridSearch] = None
        self.reranker: Optional[Reranker] = None
        self.query_understanding: Optional[QueryUnderstanding] = None
        self.context_builder: Optional[ContextBuilder] = None
        self.security: Optional[SecurityFilter] = None
        self.memory: Optional[MemoryConsolidation] = None

        self._initialized = False
        self._stats = {
            "total_queries": 0,
            "total_chunks_indexed": 0,
            "total_time_ms": 0,
        }

    def initialize(self):
        """Lazy initialize all RAG components."""
        if self._initialized:
            return

        self.db = RAGDatabase()
        self.embedder = EmbeddingGenerator(
            model=self.config.embedding_model,
            dimension=self.config.embedding_dimension,
        )
        self.vector_store = VectorStore(self.db, self.embedder)
        self.hybrid_search = HybridSearch(
            self.db, self.vector_store,
            vector_weight=self.config.vector_weight,
            keyword_weight=self.config.keyword_weight,
            recency_weight=self.config.recency_weight,
            importance_weight=self.config.importance_weight,
        )
        self.reranker = Reranker()
        self.query_understanding = QueryUnderstanding()
        self.context_builder = ContextBuilder(
            max_tokens=self.config.max_context_tokens
        )
        self.security = SecurityFilter(
            sanitize_secrets=self.config.sanitize_secrets,
            enable_access_control=self.config.enable_access_control,
        )
        self.memory = MemoryConsolidation(
            self.db,
            importance_threshold=self.config.memory_importance_threshold,
            decay_rate=self.config.memory_decay_rate,
            rehearsal_interval=self.config.memory_rehearsal_interval,
            promotion_threshold=self.config.memory_promotion_threshold,
        )

        self._initialized = True

    # ── Indexing ─────────────────────────────────────────────────────────

    def index_text(self, content: str, metadata: Optional[Dict[str, Any]] = None,
                   source_type: str = "document",
                   workspace_id: str = "default",
                   user_id: Optional[str] = None) -> Optional[str]:
        """Index a text document into the RAG system.

        Returns the source_id if successful.
        """
        self.initialize()

        meta = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "source_type": (ChunkType(source_type).value
                           if source_type in [t.value for t in ChunkType]
                           else ChunkType.DOCUMENT.value),
            **(metadata or {}),
        }

        source_id = uuid.uuid4().hex
        meta["source_id"] = source_id

        # Choose chunker
        chunk_type = ChunkType(source_type) if source_type in [t.value for t in ChunkType] else ChunkType.DOCUMENT
        chunker = ChunkerFactory.get_chunker(
            chunk_type,
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap,
        )

        chunks = chunker.chunk(
            content=content,
            metadata=meta,
            filename=meta.get("filename"),
        )

        # Security sanitize
        for chunk in chunks:
            self.security.sanitize_chunk(chunk)

        # Store chunks
        for chunk in chunks:
            self.db.insert_chunk(
                chunk_id=chunk.id,
                content=chunk.content,
                metadata={
                    **meta,
                    "heading": chunk.metadata.heading,
                    "section": chunk.metadata.section,
                    "position": chunk.metadata.position,
                    "language": chunk.metadata.language,
                    "hash": chunk.metadata.hash,
                    "is_sanitized": chunk.metadata.is_sanitized,
                    "contains_pii": chunk.metadata.contains_pii,
                    "tags": chunk.metadata.tags,
                },
                tokens=chunk.tokens,
            )

        # Generate embeddings
        chunk_texts = [c.content for c in chunks]
        chunk_ids = [(c.id, c.content, meta) for c in chunks]
        indexed = self.vector_store.index_batch(chunk_ids)

        self._stats["total_chunks_indexed"] += indexed

        return source_id

    def index_document(self, document: Document) -> bool:
        """Index a Document object."""
        meta = document.metadata.__dict__ if hasattr(document.metadata, '__dict__') else {}
        source_id = self.index_text(
            content=document.content,
            metadata=meta,
            source_type=document.metadata.source_type.value if hasattr(document.metadata.source_type, 'value') else "document",
            workspace_id=meta.get("workspace_id", "default"),
            user_id=meta.get("user_id"),
        )
        return source_id is not None

    def delete_source(self, source_id: str, workspace_id: str = "default"):
        """Delete all chunks for a source."""
        self.initialize()
        self.db.delete_chunks_by_source(source_id, workspace_id)
        self.vector_store.clear_cache()

    # ── Query ────────────────────────────────────────────────────────────

    def query(self, query_text: str,
              workspace_id: str = "default",
              user_id: Optional[str] = None,
              top_k: Optional[int] = None,
              filters: Optional[Dict[str, Any]] = None,
              conversation_context: Optional[List[dict]] = None) -> RAGContext:
        """Execute full RAG pipeline: understand → search → rerank → build context."""
        t0 = time.time()
        self.initialize()
        self._stats["total_queries"] += 1

        k = top_k or self.config.top_k

        # Stage 1: Query understanding
        query_analysis = self.query_understanding.analyze(
            query_text,
            conversation_context=conversation_context,
        )

        # Stage 2: Hybrid search
        results = self.hybrid_search.search(
            query=query_analysis.rewritten_query or query_text,
            workspace_id=workspace_id,
            user_id=user_id,
            top_k=k,
            filters=filters,
        )

        # Stage 3: Rerank
        reranked = self.reranker.rerank(
            query=query_text,
            results=results,
            top_k=self.config.top_k_final,
            min_score=self.config.min_score,
            diversity_factor=self.config.diversity_factor,
        )

        # Stage 4: Memory retrieval
        memory_records = []
        if user_id:
            memory_list = self.db.search_memory(
                query=query_text,
                workspace_id=workspace_id,
                user_id=user_id,
                limit=5,
            )
            memory_records = [
                self._mem_dict_to_record(m) for m in memory_list
            ]

        # Stage 5: Build context
        context = self.context_builder.build(
            results=reranked,
            query_analysis=query_analysis,
            memory_records=memory_records,
        )

        context.retrieval_time_ms = (time.time() - t0) * 1000
        self._stats["total_time_ms"] += context.retrieval_time_ms

        return context

    def query_stream(self, query_text: str,
                      workspace_id: str = "default",
                      user_id: Optional[str] = None,
                      top_k: Optional[int] = None) -> RAGContext:
        """Lightweight query for streaming use (minimal processing)."""
        return self.query(
            query_text=query_text,
            workspace_id=workspace_id,
            user_id=user_id,
            top_k=top_k or min(self.config.top_k_final, 5),
        )

    # ── Memory ───────────────────────────────────────────────────────────

    def store_memory(self, content: str, memory_type: str = "short_term",
                      importance: float = 0.5,
                      workspace_id: str = "default",
                      user_id: Optional[str] = None,
                      metadata: Optional[Dict] = None) -> bool:
        """Store a memory record."""
        self.initialize()
        mem_id = f"mem_{uuid.uuid4().hex[:16]}"
        return self.db.insert_memory(
            mem_id=mem_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            workspace_id=workspace_id,
            user_id=user_id,
            metadata=metadata,
        )

    def run_memory_maintenance(self, workspace_id: str = "default",
                                user_id: Optional[str] = None) -> dict:
        """Run memory consolidation maintenance."""
        self.initialize()
        return self.memory.run_maintenance(workspace_id, user_id)

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self, workspace_id: str = "default") -> dict:
        """Get RAG engine statistics."""
        self.initialize()
        db_stats = self.db.get_stats(workspace_id)
        avg_time = (
            self._stats["total_time_ms"] / self._stats["total_queries"]
            if self._stats["total_queries"] > 0 else 0
        )
        return {
            **db_stats,
            "total_queries": self._stats["total_queries"],
            "total_chunks_indexed": self._stats["total_chunks_indexed"],
            "avg_query_time_ms": round(avg_time, 2),
        }

    def health_check(self) -> dict:
        """Check RAG engine health."""
        try:
            self.initialize()
            vector_count = self.vector_store.get_vector_count()
            db_stats = self.db.get_stats()
            return {
                "status": "healthy",
                "vector_count": vector_count,
                "chunk_count": db_stats.get("total_chunks", 0),
                "embedder_configured": bool(self.embedder.api_key),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    def _mem_dict_to_record(self, d: dict) -> Any:
        """Convert DB dict to memory record object."""
        from core.rag.models import MemoryRecord, MemoryType
        try:
            mt = MemoryType(d.get("memory_type", "short_term"))
        except ValueError:
            mt = MemoryType.SHORT_TERM
        return MemoryRecord(
            id=d.get("id", ""),
            content=d.get("content", ""),
            memory_type=mt,
            importance=d.get("importance", 0.5),
            access_count=d.get("access_count", 0),
            last_accessed_at=d.get("last_accessed_at", ""),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )
