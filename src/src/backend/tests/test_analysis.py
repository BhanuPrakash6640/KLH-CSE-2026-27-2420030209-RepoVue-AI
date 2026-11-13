"""Tests that run without a database, an API key or Docker."""
from __future__ import annotations

import subprocess

import pytest

from app.services.analyzers import RawFinding, _similar, dedupe
from app.services.ast_parser import parse_source
from app.services.chunker import chunk_file
from app.services.embeddings import HashEmbeddings
from app.services.graphs import build_graphs, neighbours
from app.services.languages import detect_language, is_test_file, should_skip
from app.services.patcher import build_diff, diff_stats, verify_applies
from app.services.rules import scan

PY_SRC = '''
import os
import sqlite3

API_KEY = "abcd1234efgh5678ijkl"

def get_user(conn, user_id):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return cur.fetchone()

class OrderService:
    def __init__(self, db):
        self.db = db

    def totals(self, user_ids=[]):
        total = 0
        for uid in user_ids:
            row = get_user(self.db, uid)
            if row:
                total += row[3]
        return total
'''

JS_SRC = """
const db = require('./db');

async function loadOrders(ids) {
  const out = [];
  for (const id of ids) {
    const row = await db.query("SELECT * FROM orders WHERE id = " + id);
    out.push(row);
  }
  return out;
}
module.exports = { loadOrders };
"""


class TestParser:
    def test_extracts_python_symbols(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        names = {s.qualified_name for s in pf.symbols}
        assert "orders.get_user" in names
        assert "orders.OrderService.totals" in names
        assert pf.error is None

    def test_line_numbers_are_one_based_and_bounded(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        total = len(PY_SRC.splitlines())
        for s in pf.symbols:
            assert 1 <= s.start_line <= s.end_line <= total

    def test_methods_are_nested_under_class(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        method = next(s for s in pf.symbols if s.name == "totals")
        assert method.kind == "method"
        assert method.parent == "OrderService"

    def test_imports_marked_external(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        assert {i.target for i in pf.imports} >= {"os", "sqlite3"}
        assert all(i.is_external for i in pf.imports)

    def test_javascript(self):
        pf = parse_source("src/orders.js", "javascript", JS_SRC)
        assert any(s.name == "loadOrders" for s in pf.symbols)

    def test_unknown_grammar_degrades_gracefully(self):
        pf = parse_source("a.xyz", "not_a_real_language", "const x = 1;")
        assert pf.error is not None
        assert pf.symbols == []

    def test_complexity_counts_branches(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        totals = next(s for s in pf.symbols if s.name == "totals")
        assert totals.complexity > 1


class TestGraphs:
    def test_call_edge_resolution(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        bundle = build_graphs([pf])
        assert bundle.call_graph.has_edge("orders.OrderService.totals", "orders.get_user")

    def test_hotspots_ranked(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        bundle = build_graphs([pf])
        assert bundle.metrics["hotspots"]
        assert bundle.metrics["hotspots"][0]["score"] >= bundle.metrics["hotspots"][-1]["score"]

    def test_neighbours(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        bundle = build_graphs([pf])
        assert "orders.get_user" in neighbours(bundle.call_graph, "orders.OrderService.totals")


class TestRules:
    def test_detects_sql_injection_and_secret(self):
        ids = {h.rule.id for h in scan(PY_SRC, "python")}
        assert "SQL_FSTRING" in ids
        assert "HARDCODED_SECRET" in ids
        assert "MUTABLE_DEFAULT" in ids

    def test_ignores_commented_code(self):
        src = '# cur.execute(f"SELECT * FROM t WHERE id = {x}")\n'
        assert not [h for h in scan(src, "python") if h.rule.id == "SQL_FSTRING"]

    def test_language_scoping(self):
        assert not [h for h in scan(PY_SRC, "javascript") if h.rule.id == "MUTABLE_DEFAULT"]


class TestChunker:
    def test_chunks_align_to_symbols(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        chunks = chunk_file(pf, PY_SRC)
        assert chunks
        assert any(c.symbol_name and "totals" in c.symbol_name for c in chunks)

    def test_chunk_line_ranges_valid(self):
        pf = parse_source("app/orders.py", "python", PY_SRC)
        for c in chunk_file(pf, PY_SRC):
            assert c.start_line <= c.end_line


class TestPatcher:
    def test_diff_applies_to_real_git_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        original = 'def f(x):\n    return x / 0\n'
        (repo / "m.py").write_text(original)
        for cmd in (
            ["git", "init", "-q", "."],
            ["git", "config", "user.email", "t@t.t"],
            ["git", "config", "user.name", "t"],
            ["git", "add", "-A"],
            ["git", "commit", "-qm", "init"],
        ):
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)

        patched = 'def f(x):\n    if x == 0:\n        raise ValueError("x must be non-zero")\n    return 1 / x\n'
        diff = build_diff("m.py", original, patched)
        ok, err = verify_applies(str(repo), diff)
        assert ok, err
        assert diff_stats(diff)["files"] == 1

    def test_empty_diff_for_identical_content(self):
        assert build_diff("m.py", "a\n", "a\n") == ""


class TestDedupe:
    def _f(self, title, sev="high", line=10):
        return RawFinding(
            title=title, category="security", severity=sev, confidence=0.8,
            path="a.py", start_line=line, end_line=line + 2,
            description="d", snippet="cur.execute(sql)",
        )

    def test_identical_findings_collapse(self):
        assert len(dedupe([self._f("SQL injection in query"), self._f("SQL injection in query")])) == 1

    def test_keeps_distinct_findings(self):
        out = dedupe([self._f("SQL injection in query"), self._f("Hardcoded secret", line=40)])
        assert len(out) == 2

    def test_similarity(self):
        assert _similar("SQL injection in get_user", "SQL injection in the get_user query")
        assert not _similar("SQL injection", "Missing pagination on list endpoint")

    def test_fingerprint_is_line_independent(self):
        a, b = self._f("SQL injection", line=10), self._f("SQL injection", line=90)
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_separates_distinct_issues_in_same_snippet(self):
        # Note: the title signature tolerates minor rewording, but a heavy
        # rephrasing ("X in Y" -> "Y allows X") can still produce a second
        # fingerprint. Known limitation, tracked for the eval phase.
        a = self._f("SQL injection in query")
        b = self._f("Hardcoded database credential")
        assert a.fingerprint != b.fingerprint


class TestLanguages:
    def test_detection_and_skipping(self):
        assert detect_language("a/b/c.py") == "python"
        assert detect_language("a/b/c.tsx") == "tsx"
        assert detect_language("a/b/c.bin") is None
        assert should_skip("node_modules/react/index.js")
        assert should_skip("app/bundle.min.js")
        assert is_test_file("tests/test_orders.py")


@pytest.mark.asyncio
async def test_hash_embeddings_are_normalised_and_stable():
    emb = HashEmbeddings()
    a, b = await emb.embed(["def get_user(): pass", "def get_user(): pass"])
    assert a == b
    assert len(a) == emb.dim
    assert abs(sum(x * x for x in a) ** 0.5 - 1.0) < 1e-6
