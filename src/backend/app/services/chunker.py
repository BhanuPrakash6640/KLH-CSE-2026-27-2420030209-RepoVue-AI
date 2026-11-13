"""Chunking for retrieval.

Naive fixed-window chunking splits functions in half and wrecks retrieval
quality. We chunk on AST symbol boundaries, fall back to sliding windows for
the leftover top-level code, and merge tiny symbols so one-line helpers don't
each become a vector.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.ast_parser import ParsedFile

MAX_CHARS = 6000
MIN_CHARS = 120
WINDOW = 2400
OVERLAP = 300


@dataclass
class Chunk:
    path: str
    language: str
    symbol_name: str | None
    start_line: int
    end_line: int
    content: str

    @property
    def token_estimate(self) -> int:
        return len(self.content) // 4


def _split_long(chunk: Chunk) -> list[Chunk]:
    if len(chunk.content) <= MAX_CHARS:
        return [chunk]
    lines = chunk.content.splitlines()
    out: list[Chunk] = []
    buf: list[str] = []
    start = chunk.start_line
    for i, line in enumerate(lines):
        buf.append(line)
        if sum(len(x) + 1 for x in buf) >= MAX_CHARS:
            out.append(
                Chunk(chunk.path, chunk.language, chunk.symbol_name, start,
                      chunk.start_line + i, "\n".join(buf))
            )
            buf = []
            start = chunk.start_line + i + 1
    if buf:
        out.append(Chunk(chunk.path, chunk.language, chunk.symbol_name, start, chunk.end_line, "\n".join(buf)))
    return out


def chunk_file(parsed: ParsedFile, source: str) -> list[Chunk]:
    lines = source.splitlines()
    if not lines:
        return []

    covered: set[int] = set()
    chunks: list[Chunk] = []

    # 1) one chunk per function/method (classes only if they hold no methods)
    symbols = sorted(parsed.symbols, key=lambda s: (s.start_line, -s.end_line))
    method_spans = [(s.start_line, s.end_line) for s in symbols if s.kind in ("function", "method")]

    for sym in symbols:
        if sym.kind == "class":
            has_methods = any(
                sym.start_line <= a and b <= sym.end_line and (a, b) != (sym.start_line, sym.end_line)
                for a, b in method_spans
            )
            if has_methods:
                continue
        body = "\n".join(lines[sym.start_line - 1 : sym.end_line])
        if len(body) < MIN_CHARS and sym.kind != "class":
            continue
        header = f"# {parsed.path}:{sym.start_line}-{sym.end_line} ({sym.kind} {sym.qualified_name})\n"
        chunks.append(
            Chunk(parsed.path, parsed.language, sym.qualified_name, sym.start_line, sym.end_line, header + body)
        )
        covered.update(range(sym.start_line, sym.end_line + 1))

    # 2) sliding window over whatever is left (imports, config, top-level code)
    leftover = [i for i in range(1, len(lines) + 1) if i not in covered]
    if leftover:
        run: list[int] = []
        for lineno in leftover + [None]:  # sentinel flushes the tail
            if lineno is not None and (not run or lineno == run[-1] + 1):
                run.append(lineno)
                continue
            if run:
                text = "\n".join(lines[run[0] - 1 : run[-1]])
                if len(text.strip()) >= MIN_CHARS:
                    for piece in _window(text, run[0]):
                        chunks.append(
                            Chunk(parsed.path, parsed.language, None, piece[0], piece[1],
                                  f"# {parsed.path}:{piece[0]}\n{piece[2]}")
                        )
            run = [lineno] if lineno is not None else []

    out: list[Chunk] = []
    for c in chunks:
        out.extend(_split_long(c))
    return out


def _window(text: str, base_line: int) -> list[tuple[int, int, str]]:
    if len(text) <= WINDOW:
        return [(base_line, base_line + text.count("\n"), text)]
    pieces: list[tuple[int, int, str]] = []
    lines = text.splitlines()
    buf: list[str] = []
    start_idx = 0
    for i, line in enumerate(lines):
        buf.append(line)
        if sum(len(x) + 1 for x in buf) >= WINDOW:
            pieces.append((base_line + start_idx, base_line + i, "\n".join(buf)))
            back = max(0, len(buf) - OVERLAP // 40)
            start_idx = i - back + 1
            buf = lines[start_idx : i + 1]
    if buf:
        pieces.append((base_line + start_idx, base_line + len(lines) - 1, "\n".join(buf)))
    return pieces
