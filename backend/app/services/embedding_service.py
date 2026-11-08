import hashlib
import logging
import math
import re
from typing import List, Optional
import httpx
import numpy as np

from app.core.config import settings

logger = logging.getLogger("neuroforge.embedding_service")


class EmbeddingService:
    """
    Dedicated embedding generator for scientific text knowledge retrieval.
    Primary provider: Vultr Serverless Inference (/embeddings endpoint, qwen3-embedding-4b).
    Fallback provider: Deterministic token-projected normalized L2 embeddings for offline/test resilience.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dimension: int = 2560,
        timeout: float = 15.0,
        mock_mode: bool = False,
    ):
        self.api_key = api_key if api_key is not None else settings.VULTR_INFERENCE_API_KEY
        self.base_url = (base_url or settings.VULTR_INFERENCE_BASE_URL).rstrip("/")
        self.model = model or getattr(settings, "VULTR_EMBEDDING_MODEL", "qwen3-embedding-4b")
        self.dimension = dimension or getattr(settings, "EMBEDDING_DIMENSION", 2560)
        self.timeout = timeout
        self.mock_mode = mock_mode

    def is_vultr_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 0 and not self.mock_mode)

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate float vector embeddings for a batch of text strings."""
        if not texts:
            return []

        # Explicit mock mode requested (e.g. unit testing)
        if self.mock_mode:
            return [self._generate_deterministic_embedding(t) for t in texts]

        # Determine whether offline/test fallback is explicitly permitted
        allow_mock = bool(
            getattr(settings, "ALLOW_MOCK_EMBEDDINGS", False)
            or getattr(settings, "current_env", "") == "test"
        )
        is_production = getattr(settings, "current_env", "") == "production"

        # If Vultr is configured, call Vultr serverless inference
        if self.is_vultr_available():
            try:
                return self._call_vultr_embeddings(texts)
            except Exception as e:
                # In production or when fallback is not permitted, fail with explicit error
                if is_production or not allow_mock:
                    logger.error(f"Vultr embedding inference failed: {e}")
                    raise RuntimeError(
                        f"Vultr embedding service failed ({e}). Live semantic embeddings (qwen3-embedding-4b) are required."
                    ) from e
                logger.warning(
                    f"Vultr embedding service call failed ({e}); using development/test mock fallback because ALLOW_MOCK_EMBEDDINGS is enabled."
                )
                return [self._generate_deterministic_embedding(t) for t in texts]

        # Vultr is not configured or API key is missing
        if is_production or not allow_mock:
            raise RuntimeError(
                "Vultr embedding service is unconfigured or missing VULTR_INFERENCE_API_KEY. "
                "Live semantic embeddings (qwen3-embedding-4b) are required in production."
            )

        logger.warning("VULTR_INFERENCE_API_KEY not configured; using development/test mock fallback.")
        return [self._generate_deterministic_embedding(t) for t in texts]

    def generate_single_embedding(self, text: str) -> List[float]:
        """Convenience method for generating embedding for a single text."""
        res = self.generate_embeddings([text])
        return res[0] if res else [0.0] * self.dimension

    def _call_vultr_embeddings(self, texts: List[str]) -> List[List[float]]:
        endpoint = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NeuroForge-RAG/1.0",
        }

        # Process in batches of up to 16 to respect payload and rate limits
        batch_size = 16
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {
                "input": batch,
                "model": self.model,
            }
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code != 200:
                    raise RuntimeError(f"Vultr embeddings API returned HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                items = data.get("data", [])
                # Sort by index if returned out of order
                items.sort(key=lambda x: x.get("index", 0))
                for it in items:
                    emb = it.get("embedding", [])
                    all_embeddings.append(emb)

        if len(all_embeddings) != len(texts):
            raise RuntimeError(f"Expected {len(texts)} embeddings from Vultr, but received {len(all_embeddings)}.")

        return all_embeddings

    def _generate_deterministic_embedding(self, text: str) -> List[float]:
        """
        Generate a deterministic, semantic-preserving unit-normalized vector for testing/offline use.
        Uses token hashing across n-grams to preserve lexical and semantic similarity between related queries.
        """
        vec = np.zeros(self.dimension, dtype=np.float32)
        words = re.findall(r"\w+", text.lower())
        if not words:
            vec[0] = 1.0
            return vec.tolist()

        # Unigrams and bigrams
        tokens = list(words)
        for j in range(len(words) - 1):
            tokens.append(f"{words[j]}_{words[j+1]}")

        for tok in tokens:
            # MD5 digest as 128-bit integer mapped to dimension
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if ((h >> 16) & 1) else -1.0
            weight = math.log1p(len(tok))
            vec[idx] += sign * weight

        # L2 Normalize
        norm = np.linalg.norm(vec)
        if norm > 1e-12:
            vec /= norm
        else:
            vec[0] = 1.0

        return [round(float(x), 7) for x in vec.tolist()]
