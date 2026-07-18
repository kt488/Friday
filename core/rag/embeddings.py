"""Embedding generation — uses NVIDIA NIM API for vector embeddings.

Supports batched embedding, caching, and multiple embedding models.
"""

import hashlib
import json
import math
import os
import time
import requests
from typing import List, Optional

from core.config import Config

# numpy is optional — only needed for the NVIDIA API path's response parsing;
# the fallback embedding generator uses pure Python math.
try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:
    _HAVE_NUMPY = False


class EmbeddingGenerator:
    """Generates vector embeddings via NVIDIA NIM embedding API.

    Falls back to deterministic hash-based pseudo-embeddings when the
    NVIDIA API key is not configured, enabling offline development/testing.
    """

    def __init__(self, model: str = "nvidia/nv-embed-qa-4",
                 dimension: int = 4096,
                 cache_size: int = 1000):
        self.api_key = Config.NVIDIA_API_KEY
        self.url = f"{Config.NVIDIA_BASE_URL}/embeddings"
        self.model = model
        self.dimension = dimension
        self.session = requests.Session()
        self._cache: dict = {}
        self._cache_max = cache_size
        self._fallback = not bool(self.api_key)
        if self._fallback:
            print("[RAG Embedding] No NVIDIA_API_KEY set — using deterministic "
                  "hash-based fallback embeddings (offline mode)")

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _check_cache(self, text: str) -> Optional[List[float]]:
        key = self._cache_key(text)
        return self._cache.get(key)

    def _set_cache(self, text: str, vector: List[float]):
        key = self._cache_key(text)
        if len(self._cache) >= self._cache_max:
            # evict oldest
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = vector

    def _generate_fallback(self, text: str) -> List[float]:
        """Deterministic pseudo-embedding via SHA-256 → cyclic fill → L2 normalize.

        Produces a unit vector of ``self.dimension`` from the text hash, so the
        same text always yields the same embedding.  Good enough for keyword
        overlap and basic similarity; not semantically meaningful.

        Pure Python implementation — no numpy dependency required.
        """
        digest = hashlib.sha256(text.encode()).digest()  # 32 bytes
        # Convert each byte to float [0..255]
        vec = [float(b) for b in digest]  # 32 floats
        # Cycle to fill full dimension
        repeats = (self.dimension // len(vec)) + 1
        vec = (vec * repeats)[:self.dimension]
        # L2 normalize to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def generate(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text string."""
        cached = self._check_cache(text)
        if cached:
            return cached

        if self._fallback:
            vector = self._generate_fallback(text)
            self._set_cache(text, vector)
            return vector

        try:
            data = {
                "model": self.model,
                "input": text,
                "encoding_format": "float",
            }
            resp = self.session.post(
                self.url, headers=self._get_headers(),
                data=json.dumps(data), timeout=30
            )
            resp.raise_for_status()
            result = resp.json()
            vector = result["data"][0]["embedding"]
            self._set_cache(text, vector)
            return vector
        except Exception as e:
            print(f"[RAG Embedding] Error: {e}")
            return None

    def generate_batch(self, texts: List[str],
                       batch_size: int = 16) -> List[Optional[List[float]]]:
        """Generate embeddings for a batch of texts."""
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_results = []
            uncached_indices = []
            uncached_texts = []

            for j, text in enumerate(batch):
                cached = self._check_cache(text)
                if cached:
                    batch_results.append(cached)
                else:
                    batch_results.append(None)
                    uncached_indices.append(j)
                    uncached_texts.append(text)

            if uncached_texts:
                if self._fallback:
                    for idx in uncached_indices:
                        vec = self._generate_fallback(batch[idx])
                        batch_results[idx] = vec
                        self._set_cache(batch[idx], vec)
                else:
                    try:
                        data = {
                            "model": self.model,
                            "input": uncached_texts,
                            "encoding_format": "float",
                        }
                        resp = self.session.post(
                            self.url, headers=self._get_headers(),
                            data=json.dumps(data), timeout=60
                        )
                        resp.raise_for_status()
                        result = resp.json()
                        for idx, vec in zip(uncached_indices, result["data"]):
                            embedding = vec["embedding"]
                            batch_results[idx] = embedding
                            self._set_cache(batch[idx], embedding)
                    except Exception as e:
                        print(f"[RAG Embedding] Batch error: {e}")

            results.extend(batch_results)
        return results

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def clear_cache(self):
        self._cache.clear()
