"""Structural chunking — code-aware, document-aware, website-aware strategies.

Splits content into semantically meaningful chunks with rich metadata.
"""

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.rag.models import Chunk, ChunkMetadata, ChunkType


class BaseChunker:
    """Base chunker with shared utilities."""

    def compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (~4 chars per token)."""
        return len(text) // 4

    def merge_small_chunks(self, chunks: List[Chunk],
                           min_chars: int = 100) -> List[Chunk]:
        """Merge chunks that are too small with next chunk."""
        if not chunks:
            return chunks
        merged = []
        carry = None
        for c in chunks:
            if carry is None:
                carry = c
            else:
                if len(carry.content) < min_chars:
                    carry.content += "\n\n" + c.content
                    carry.tokens = self.estimate_tokens(carry.content)
                    carry.metadata.child_ids.append(c.id)
                else:
                    merged.append(carry)
                    carry = c
        if carry:
            merged.append(carry)
        return merged


class CodeChunker(BaseChunker):
    """Code-aware chunker using AST-like patterns.

    Splits by top-level definitions: classes, functions, interfaces, methods.
    """

    # Pattern to split code at top-level definitions
    SPLIT_PATTERNS = {
        ".py": r'(?:^|\n)(class\s+\w+|def\s+\w+|async\s+def\s+\w+|@\w+)',
        ".js": r'(?:^|\n)(function\s+\w+|class\s+\w+|const\s+\w+\s*=|async\s+function)',
        ".ts": r'(?:^|\n)(function\s+\w+|class\s+\w+|const\s+\w+\s*=|async\s+function|interface\s+\w+|type\s+\w+)',
        ".tsx": r'(?:^|\n)(function\s+\w+|class\s+\w+|const\s+\w+\s*=|async\s+function|interface\s+\w+|type\s+\w+)',
        ".jsx": r'(?:^|\n)(function\s+\w+|class\s+\w+|const\s+\w+\s*=|async\s+function)',
        ".go": r'(?:^|\n)(func\s+\w+|type\s+\w+\s+struct|type\s+\w+\s+interface)',
        ".rs": r'(?:^|\n)(fn\s+\w+|struct\s+\w+|impl\s+\w+|enum\s+\w+|trait\s+\w+)',
        ".java": r'(?:^|\n)(public\s+\w+\s+\w+|private\s+\w+\s+\w+|class\s+\w+|interface\s+\w+)',
        ".c": r'(?:^|\n)(\w+\s+\w+\s*\(|struct\s+\w+)',
        ".cpp": r'(?:^|\n)(\w+\s+\w+\s*\(|class\s+\w+|struct\s+\w+)',
    }

    DEFAULT_SPLIT = r'(?:^|\n)(class\s+\w+|def\s+\w+|function\s+\w+)'

    def __init__(self, chunk_size: int = 256, overlap: int = 32):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _get_split_pattern(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        return self.SPLIT_PATTERNS.get(ext, self.DEFAULT_SPLIT)

    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None,
              filename: Optional[str] = None) -> List[Chunk]:
        """Split code into semantically meaningful chunks."""
        meta = metadata or {}
        meta = {k: v for k, v in meta.items() if k != 'source_type'} if isinstance(meta, dict) else {}
        pattern = self._get_split_pattern(filename or meta.get("filename", ""))
        language = meta.get("language") or (
            os.path.splitext(filename or "")[1].lstrip(".") if filename else None
        )

        # Try splitting by definitions
        splits = list(re.finditer(pattern, content, re.MULTILINE))

        if not splits or len(splits) <= 1:
            # No clear splits found, use sliding window
            return self._sliding_window(content, meta, language)

        chunks = []
        for i, match in enumerate(splits):
            start = match.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(content)
            # Include preceding decorators/comments
            chunk_start = start
            if start > 0:
                preceding = content[max(0, start - 200):start]
                decorator_match = re.search(r'(@\w+|#.*?\n|\"\"\".*?\"\"\")\s*$', preceding, re.DOTALL)
                if decorator_match:
                    chunk_start = start - len(preceding) + decorator_match.start()
                    chunk_start = max(0, chunk_start)

            chunk_text = content[chunk_start:end].strip()
            if not chunk_text:
                continue

            # Extract heading (the definition line)
            heading = match.group(0).strip()
            heading = re.sub(r'^[\s\n]+', '', heading)

            # Build chunk-specific metadata
            chunk_meta = ChunkMetadata(
                **(meta if isinstance(meta, dict) else {}),
                source_type=ChunkType.CODE,
                language=language or "unknown",
                filename=filename,
                heading=heading,
                position=i,
                chunk_type="code_definition",
            )

            chunk = Chunk(
                id=hashlib.md5(f"{meta.get('source_id', '')}:{start}:{end}".encode()).hexdigest()[:16],
                content=chunk_text,
                metadata=chunk_meta,
                tokens=self.estimate_tokens(chunk_text),
            )
            chunks.append(chunk)

        return self.merge_small_chunks(chunks) if chunks else self._sliding_window(content, meta, language)

    def _sliding_window(self, content: str, metadata: dict,
                         language: Optional[str] = None) -> List[Chunk]:
        """Fallback: split by token-count-based sliding window."""
        metadata = {k: v for k, v in metadata.items() if k != 'source_type'} if isinstance(metadata, dict) else {}
        words = content.split()
        if not words:
            return []

        chunks = []
        for i in range(0, len(words), self.chunk_size - self.overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            if not chunk_text.strip():
                continue

            start_pos = content.index(chunk_text[:50]) if len(chunk_text) > 50 else 0
            chunk_meta = ChunkMetadata(
                **(metadata if isinstance(metadata, dict) else {}),
                source_type=ChunkType.CODE,
                language=language or "unknown",
                filename=metadata.get("filename"),
                position=i // (self.chunk_size - self.overlap),
                chunk_type="code_sliding",
            )
            chunk = Chunk(
                id=hashlib.md5(f"{metadata.get('source_id', '')}:{i}".encode()).hexdigest()[:16],
                content=chunk_text.strip(),
                metadata=chunk_meta,
                tokens=self.estimate_tokens(chunk_text.strip()),
            )
            chunks.append(chunk)

        return chunks


class DocumentChunker(BaseChunker):
    """Document-aware chunker using heading/section/table structure."""

    # Section heading patterns
    HEADING_PATTERN = re.compile(r'^#{1,6}\s+.*$', re.MULTILINE)
    MARKDOWN_HEADING = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)
    HTML_HEADING = re.compile(r'<h[1-6][^>]*>(.+?)</h[1-6]>', re.IGNORECASE | re.DOTALL)

    def __init__(self, chunk_size: int = 1024, overlap: int = 128):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None,
              filename: Optional[str] = None) -> List[Chunk]:
        """Split document by headings, then by size."""
        meta = metadata or {}
        mime_type = meta.get("mime_type", "")

        # Detect format
        if mime_type == "text/html" or (filename and filename.endswith((".html", ".htm"))):
            return self._chunk_html(content, meta, filename)
        else:
            return self._chunk_markdown(content, meta, filename)

    def _chunk_markdown(self, content: str, metadata: dict,
                         filename: Optional[str] = None) -> List[Chunk]:
        """Split markdown by headings."""
        metadata = {k: v for k, v in metadata.items() if k != 'source_type'} if isinstance(metadata, dict) else {}
        lines = content.split("\n")
        sections: List[Tuple[str, int, int]] = []  # (heading, start, end)

        current_heading = "Introduction"
        section_start = 0

        for i, line in enumerate(lines):
            m = self.MARKDOWN_HEADING.match(line)
            if m:
                if i > section_start:
                    sections.append((current_heading, section_start, i))
                current_heading = m.group(1).strip()
                section_start = i

        sections.append((current_heading, section_start, len(lines)))

        chunks = []
        for heading, start, end in sections:
            section_text = "\n".join(lines[start:end]).strip()
            if not section_text:
                continue

            # Check if section is too long, sub-chunk by paragraphs
            if len(section_text) > self.chunk_size * 4:
                sub_chunks = self._sub_chunk_by_paragraphs(section_text, heading, metadata)
                chunks.extend(sub_chunks)
            else:
                chunk_meta = ChunkMetadata(
                    **(metadata if isinstance(metadata, dict) else {}),
                    source_type=ChunkType.DOCUMENT,
                    mime_type="text/markdown",
                    filename=filename,
                    heading=heading,
                    section=heading,
                    chunk_type="markdown_section",
                )
                chunk = Chunk(
                    id=hashlib.md5(f"{metadata.get('source_id', '')}:{heading}".encode()).hexdigest()[:16],
                    content=section_text,
                    metadata=chunk_meta,
                    tokens=self.estimate_tokens(section_text),
                )
                chunks.append(chunk)

        return self.merge_small_chunks(chunks)

    def _chunk_html(self, content: str, metadata: dict,
                     filename: Optional[str] = None) -> List[Chunk]:
        """Split HTML by headings."""
        metadata = {k: v for k, v in metadata.items() if k != 'source_type'} if isinstance(metadata, dict) else {}
        headings = list(self.HTML_HEADING.finditer(content))
        if not headings:
            # Plain text fallback
            return self._chunk_markdown(content, metadata, filename)

        chunks = []
        for i, match in enumerate(headings):
            start = match.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            section_text = content[start:end].strip()
            if not section_text:
                continue

            heading_text = match.group(1).strip()
            chunk_meta = ChunkMetadata(
                **(metadata if isinstance(metadata, dict) else {}),
                source_type=ChunkType.DOCUMENT,
                mime_type="text/html",
                filename=filename,
                heading=heading_text,
                chunk_type="html_section",
            )
            chunk = Chunk(
                id=hashlib.md5(f"{metadata.get('source_id', '')}:html:{i}".encode()).hexdigest()[:16],
                content=section_text,
                metadata=chunk_meta,
                tokens=self.estimate_tokens(section_text),
            )
            chunks.append(chunk)

        return self.merge_small_chunks(chunks)

    def _sub_chunk_by_paragraphs(self, text: str, heading: str,
                                  metadata: dict) -> List[Chunk]:
        """Sub-chunk a large section into paragraph groups."""
        metadata = {k: v for k, v in metadata.items() if k != 'source_type'} if isinstance(metadata, dict) else {}
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_text = ""
        pos = 0

        for para in paragraphs:
            if len(current_text) + len(para) > self.chunk_size and current_text:
                chunk_meta = ChunkMetadata(
                    **(metadata if isinstance(metadata, dict) else {}),
                    source_type=ChunkType.DOCUMENT,
                    mime_type="text/markdown",
                    heading=heading,
                    section=heading,
                    position=pos,
                    chunk_type="markdown_paragraph",
                )
                chunk = Chunk(
                    id=hashlib.md5(f"{metadata.get('source_id', '')}:{heading}:{pos}".encode()).hexdigest()[:16],
                    content=current_text.strip(),
                    metadata=chunk_meta,
                    tokens=self.estimate_tokens(current_text.strip()),
                )
                chunks.append(chunk)
                current_text = para
                pos += 1
            else:
                current_text += "\n\n" + para if current_text else para

        if current_text.strip():
            chunk_meta = ChunkMetadata(
                **(metadata if isinstance(metadata, dict) else {}),
                source_type=ChunkType.DOCUMENT,
                mime_type="text/markdown",
                heading=heading,
                section=heading,
                position=pos,
                chunk_type="markdown_paragraph",
            )
            chunk = Chunk(
                id=hashlib.md5(f"{metadata.get('source_id', '')}:{heading}:{pos}".encode()).hexdigest()[:16],
                content=current_text.strip(),
                metadata=chunk_meta,
                tokens=self.estimate_tokens(current_text.strip()),
            )
            chunks.append(chunk)

        return chunks


class WebsiteChunker(BaseChunker):
    """Website-aware chunker for HTML content.

    Splits by structural elements: navbar, content, sidebar, footer.
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None,
              filename: Optional[str] = None) -> List[Chunk]:
        """Split website HTML into structural chunks."""
        meta = metadata or {}
        meta = {k: v for k, v in meta.items() if k != 'source_type'} if isinstance(meta, dict) else {}
        from bs4 import BeautifulSoup

        chunks = []
        try:
            soup = BeautifulSoup(content, "html.parser")
        except Exception:
            # Fallback to document chunking
            doc_chunker = DocumentChunker(self.chunk_size, self.overlap)
            return doc_chunker.chunk(content, metadata, filename)

        # Extract text by structural regions
        regions = []

        # Navigation
        nav = soup.find(["nav", "header", ".nav", "#nav"])
        if nav:
            regions.append(("navigation", nav.get_text(separator=" ", strip=True)))

        # Main content
        main = soup.find(["main", "article", ".content", "#content", ".main", "#main"])
        if main:
            regions.append(("main_content", main.get_text(separator=" ", strip=True)))
        else:
            # Fallback to body text
            body = soup.find("body")
            if body:
                regions.append(("body", body.get_text(separator=" ", strip=True)))

        # Sidebar
        sidebar = soup.find(["aside", ".sidebar", "#sidebar"])
        if sidebar:
            regions.append(("sidebar", sidebar.get_text(separator=" ", strip=True)))

        # Footer
        footer = soup.find("footer")
        if footer:
            regions.append(("footer", footer.get_text(separator=" ", strip=True)))

        for i, (region_name, text) in enumerate(regions):
            if not text.strip():
                continue

            # Split long regions
            if len(text) > self.chunk_size * 2:
                words = text.split()
                for j in range(0, len(words), self.chunk_size - self.overlap):
                    seg = " ".join(words[j:j + self.chunk_size])
                    if not seg.strip():
                        continue
                    chunk_meta = ChunkMetadata(
                        **(meta if isinstance(meta, dict) else {}),
                        source_type=ChunkType.WEBSITE,
                        mime_type="text/html",
                        heading=region_name,
                        section=region_name,
                        position=j,
                        chunk_type=f"website_{region_name}",
                    )
                    chunk = Chunk(
                        id=hashlib.md5(f"{meta.get('source_id', '')}:web:{i}:{j}".encode()).hexdigest()[:16],
                        content=seg.strip(),
                        metadata=chunk_meta,
                        tokens=self.estimate_tokens(seg.strip()),
                    )
                    chunks.append(chunk)
            else:
                chunk_meta = ChunkMetadata(
                    **(meta if isinstance(meta, dict) else {}),
                    source_type=ChunkType.WEBSITE,
                    mime_type="text/html",
                    heading=region_name,
                    section=region_name,
                    position=i,
                    chunk_type=f"website_{region_name}",
                )
                chunk = Chunk(
                    id=hashlib.md5(f"{meta.get('source_id', '')}:web:{i}".encode()).hexdigest()[:16],
                    content=text.strip(),
                    metadata=chunk_meta,
                    tokens=self.estimate_tokens(text.strip()),
                )
                chunks.append(chunk)

        return chunks or self._fallback_text(content, meta)

    def _fallback_text(self, content: str, metadata: dict) -> List[Chunk]:
        """Fallback: extract plain text from HTML."""
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
        except Exception:
            text = content

        doc_chunker = DocumentChunker(self.chunk_size, self.overlap)
        return doc_chunker.chunk(text, metadata)


class ChunkerFactory:
    """Factory to create the appropriate chunker for content type."""

    @staticmethod
    def get_chunker(chunk_type: ChunkType = ChunkType.DOCUMENT,
                    chunk_size: int = 512, overlap: int = 64):
        if chunk_type == ChunkType.CODE:
            return CodeChunker(chunk_size, overlap)
        elif chunk_type == ChunkType.WEBSITE:
            return WebsiteChunker(chunk_size, overlap)
        else:
            return DocumentChunker(chunk_size, overlap)


