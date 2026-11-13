"""Embedding providers behind one interface.

`hash` is a deterministic offline fallback so the pipeline (and the test suite,
and your demo on a train with no wifi) still runs without an embedding key.
It is a real bag-of-tokens projection, not random noise, so retrieval degrades
rather than breaks.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)
BATCH = 64
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,40}")


class EmbeddingProvider(ABC):
    dim: int = settings.EMBEDDING_DIM

    @abstractmethod
    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]: ...

    async def embed_one(self, text: str, input_type: str = "query") -> list[float]:
        return (await self.embed([text], input_type))[0]


class HashEmbeddings(EmbeddingProvider):
    """Hashing trick + sublinear TF + L2 norm. No network, no key."""

    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in TOKEN_RE.findall(text.lower()):
            for variant in (token, *_split_identifier(token)):
                idx = int(hashlib.md5(variant.encode()).hexdigest()[:8], 16) % self.dim
                vec[idx] += 1.0
        vec = [math.log1p(v) for v in vec]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _split_identifier(token: str) -> list[str]:
    parts = re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", token)
    return [p.lower() for p in parts if len(p) > 2]


class VoyageEmbeddings(EmbeddingProvider):
    URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self) -> None:
        if not settings.VOYAGE_API_KEY:
            raise RuntimeError("VOYAGE_API_KEY not set")
        self._client = httpx.AsyncClient(
            timeout=60,
            headers={"Authorization": f"Bearer {settings.VOYAGE_API_KEY}"},
        )

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(min=1, max=20),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _call(self, batch: list[str], input_type: str) -> list[list[float]]:
        r = await self._client.post(
            self.URL,
            json={
                "input": batch,
                "model": settings.EMBEDDING_MODEL,
                "input_type": input_type,
                "output_dimension": self.dim,
            },
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]

    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(await self._call(texts[i : i + BATCH], input_type))
            await asyncio.sleep(0)
        return out


class OpenAIEmbeddings(EmbeddingProvider):
    URL = "https://api.openai.com/v1/embeddings"

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        self._client = httpx.AsyncClient(
            timeout=60, headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
        )

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20), reraise=True)
    async def _call(self, batch: list[str]) -> list[list[float]]:
        r = await self._client.post(
            self.URL,
            json={"input": batch, "model": settings.EMBEDDING_MODEL, "dimensions": self.dim},
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]

    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(await self._call(texts[i : i + BATCH]))
        return out


_provider: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider
    try:
        if settings.EMBEDDING_PROVIDER == "voyage":
            _provider = VoyageEmbeddings()
        elif settings.EMBEDDING_PROVIDER == "openai":
            _provider = OpenAIEmbeddings()
        else:
            _provider = HashEmbeddings()
    except Exception as exc:
        log.warning("embedding_provider_fallback", error=str(exc))
        _provider = HashEmbeddings()
    return _provider
