"""Embedding service for PaperFlow AI Stage 13.

Generates 384-dimensional dense vector embeddings using
`sentence-transformers/all-MiniLM-L6-v2`.

Features:
- Caches generated embeddings to avoid redundant computation.
- Lazy model loading with thread safety.
- Handles model download and execution failures gracefully.
- Generates unit-normalized 384-d vectors suitable for cosine similarity.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("paperflow.embedding_service")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# In-memory LRU / hash cache to prevent unnecessary re-embedding
# Key: sha256(text), Value: list[float] (length 384)
_embedding_cache: dict[str, list[float]] = {}
_cache_lock = threading.Lock()

# Model singleton
_model: Any = None
_model_lock = threading.Lock()

# Test mock hook
_test_embedding_generator: Callable[[str], list[float]] | None = None


def set_test_embedding_generator(generator: Callable[[str], list[float]] | None) -> None:
    """Set or clear a custom embedding generator (used for offline or isolated test suites)."""
    global _test_embedding_generator
    _test_embedding_generator = generator


def get_embedding_dimension() -> int:
    """Return the fixed embedding vector dimension (384)."""
    return EMBEDDING_DIMENSION


def _hash_text(text: str) -> str:
    """Compute deterministic SHA256 digest of normalized input text."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _get_model() -> Any:
    """Lazy load the SentenceTransformer model singleton."""
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
            _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            return _model
        except Exception as exc:
            logger.warning("Failed to initialize SentenceTransformer '%s': %s", EMBEDDING_MODEL_NAME, exc)
            raise RuntimeError(f"Embedding model initialization failed: {exc}") from exc


def _deterministic_fallback_embedding(text: str) -> list[float]:
    """Fallback pseudo-embedding generator ensuring 384-dimensional unit vector in offline testing."""
    import math
    import random

    # Seed random with text hash for deterministic output
    seed_int = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed_int)

    vec = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIMENSION)]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 6) for x in vec]


def generate_embedding(text: str) -> list[float]:
    """Generate a 384-dimensional vector embedding for a single text chunk.

    Uses the configured SentenceTransformer model and raises on failure rather than
    silently manufacturing fake vectors.
    """
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Cannot generate embedding for empty text.")

    if _test_embedding_generator is not None:
        vec = _test_embedding_generator(clean_text)
        if len(vec) != EMBEDDING_DIMENSION:
            raise ValueError(f"Custom embedding generator returned dimension {len(vec)}, expected {EMBEDDING_DIMENSION}")
        return vec

    cache_key = _hash_text(clean_text)
    with _cache_lock:
        if cache_key in _embedding_cache:
            return _embedding_cache[cache_key]

    try:
        model = _get_model()
        raw_embedding = model.encode(clean_text, normalize_embeddings=True)
        vector = [float(x) for x in raw_embedding]
    except Exception as exc:
        raise RuntimeError(f"Embedding generation failed for text: {exc}") from exc

    if len(vector) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Generated embedding dimension {len(vector)} does not match expected {EMBEDDING_DIMENSION}."
        )

    with _cache_lock:
        _embedding_cache[cache_key] = vector

    return vector


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Batch-generate 384-d vector embeddings, reusing cached vectors whenever possible.

    Empty strings are rejected instead of converted into fake vectors.
    """
    if not texts:
        return []

    normalized = []
    for text in texts:
        clean = (text or "").strip()
        if not clean:
            raise ValueError("Cannot generate embedding for empty text.")
        normalized.append(clean)

    results: list[list[float] | None] = [None] * len(normalized)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    for idx, text in enumerate(normalized):
        if _test_embedding_generator is not None:
            results[idx] = _test_embedding_generator(text)
            continue

        key = _hash_text(text)
        with _cache_lock:
            cached = _embedding_cache.get(key)
        if cached is not None:
            results[idx] = cached
        else:
            uncached_indices.append(idx)
            uncached_texts.append(text)

    if uncached_texts:
        try:
            model = _get_model()
            batch_vectors = model.encode(uncached_texts, normalize_embeddings=True)
            for i, raw_vec in enumerate(batch_vectors):
                vec = [float(x) for x in raw_vec]
                if len(vec) != EMBEDDING_DIMENSION:
                    raise ValueError(
                        f"Generated embedding dimension {len(vec)} does not match expected {EMBEDDING_DIMENSION}."
                    )
                orig_idx = uncached_indices[i]
                results[orig_idx] = vec
                key = _hash_text(uncached_texts[i])
                with _cache_lock:
                    _embedding_cache[key] = vec
        except Exception as exc:
            raise RuntimeError(f"Batch embedding generation failed: {exc}") from exc

    final: list[list[float]] = []
    for item in results:
        if item is None:
            raise RuntimeError("Embedding generation produced an incomplete result set.")
        final.append(item)
    return final


async def get_document_embeddings(texts: list[str]) -> list[list[float]]:
    """Consistent public embedding API for document chunks and queries."""
    return generate_embeddings_batch(texts)
