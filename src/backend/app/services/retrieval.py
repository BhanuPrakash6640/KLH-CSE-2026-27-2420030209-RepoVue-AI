"""Context retrieval.

Vector search alone misses exact identifiers ("why didn't it find
`process_payment`?"), so we run a hybrid: cosine similarity from pgvector +
trigram/ILIKE lexical match, fused with reciprocal rank fusion, then widened
along the call graph.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeChunk
from app.services.embeddings import get_embedder

RRF_K = 60


async def store_chunks(
    session: AsyncSession, analysis_id: uuid.UUID, chunks: list, embeddings: list[list[float]]
) -> int:
    rows = [
        CodeChunk(
            analysis_id=analysis_id,
            path=c.path,
            symbol_name=c.symbol_name,
            language=c.language,
            start_line=c.start_line,
            end_line=c.end_line,
            content=c.content,
            token_estimate=c.token_estimate,
            embedding=emb,
        )
        for c, emb in zip(chunks, embeddings)
    ]
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def vector_search(
    session: AsyncSession, analysis_id: uuid.UUID, query: str, limit: int = 10
) -> list[tuple[CodeChunk, float]]:
    vec = await get_embedder().embed_one(query, "query")
    distance = CodeChunk.embedding.cosine_distance(vec).label("distance")
    stmt = (
        select(CodeChunk, distance)
        .where(CodeChunk.analysis_id == analysis_id)
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], 1.0 - float(row[1])) for row in rows]


async def lexical_search(
    session: AsyncSession, analysis_id: uuid.UUID, query: str, limit: int = 10
) -> list[CodeChunk]:
    terms = [t for t in query.replace(".", " ").split() if len(t) > 2][:6]
    if not terms:
        return []
    clauses = " OR ".join(f"content ILIKE :t{i}" for i in range(len(terms)))
    params = {f"t{i}": f"%{t}%" for i, t in enumerate(terms)}
    params["aid"] = str(analysis_id)
    params["lim"] = limit
    sql = text(
        f"SELECT id FROM code_chunks WHERE analysis_id = :aid AND ({clauses}) "
        f"ORDER BY length(content) ASC LIMIT :lim"
    )
    ids = [r[0] for r in (await session.execute(sql, params)).all()]
    if not ids:
        return []
    rows = (await session.execute(select(CodeChunk).where(CodeChunk.id.in_(ids)))).scalars().all()
    order = {i: n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda c: order.get(c.id, 999))


async def hybrid_search(
    session: AsyncSession, analysis_id: uuid.UUID, query: str, limit: int = 8
) -> list[tuple[CodeChunk, float]]:
    dense = await vector_search(session, analysis_id, query, limit * 2)
    sparse = await lexical_search(session, analysis_id, query, limit * 2)

    scores: dict[uuid.UUID, float] = {}
    keep: dict[uuid.UUID, CodeChunk] = {}
    for rank, (chunk, _) in enumerate(dense):
        scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (RRF_K + rank + 1)
        keep[chunk.id] = chunk
    for rank, chunk in enumerate(sparse):
        scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (RRF_K + rank + 1)
        keep[chunk.id] = chunk

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [(keep[cid], round(score, 5)) for cid, score in ranked]


async def context_for_symbol(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    path: str,
    symbol: str | None,
    related_symbols: list[str],
    budget_chars: int = 24_000,
) -> str:
    """Assemble the code context block handed to the LLM."""
    parts: list[str] = []
    used = 0

    stmt = select(CodeChunk).where(
        CodeChunk.analysis_id == analysis_id, CodeChunk.path == path
    ).order_by(CodeChunk.start_line)
    for chunk in (await session.execute(stmt)).scalars().all():
        block = f"\n----- {chunk.path}:{chunk.start_line}-{chunk.end_line} -----\n{chunk.content}"
        if used + len(block) > budget_chars * 0.6:
            break
        parts.append(block)
        used += len(block)

    for related in related_symbols[:6]:
        if used >= budget_chars:
            break
        hits = await hybrid_search(session, analysis_id, related, limit=1)
        for chunk, _ in hits:
            block = f"\n----- related: {chunk.path}:{chunk.start_line}-{chunk.end_line} -----\n{chunk.content}"
            if used + len(block) > budget_chars:
                break
            parts.append(block)
            used += len(block)

    return "".join(parts)
