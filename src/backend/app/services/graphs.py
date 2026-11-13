"""Build call and dependency graphs, then derive the signals the LLM stage
uses to decide *where* to look: hotspots, cycles, god files, hub functions."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from app.services.ast_parser import ParsedFile


@dataclass
class GraphBundle:
    call_graph: nx.DiGraph
    dep_graph: nx.DiGraph
    metrics: dict


def build_graphs(parsed: list[ParsedFile]) -> GraphBundle:
    call_graph = nx.DiGraph()
    dep_graph = nx.DiGraph()

    # qualified-name lookup so `foo()` can resolve to `module.Class.foo`
    by_short: dict[str, list[str]] = {}
    for pf in parsed:
        for sym in pf.symbols:
            call_graph.add_node(
                sym.qualified_name,
                path=pf.path,
                kind=sym.kind,
                complexity=sym.complexity,
                start_line=sym.start_line,
                end_line=sym.end_line,
            )
            by_short.setdefault(sym.name, []).append(sym.qualified_name)

    for pf in parsed:
        dep_graph.add_node(pf.path, kind="file", language=pf.language)
        for call in pf.calls:
            candidates = by_short.get(call.callee, [])
            if len(candidates) == 1:
                target, resolved = candidates[0], True
            elif candidates:
                # prefer a target defined in the same file
                same_file = [c for c in candidates if call_graph.nodes.get(c, {}).get("path") == pf.path]
                target, resolved = (same_file[0] if same_file else candidates[0]), bool(same_file)
            else:
                target, resolved = f"external:{call.callee}", False
            if not call_graph.has_node(target):
                call_graph.add_node(target, path=None, kind="external")
            call_graph.add_edge(call.caller, target, line=call.line, path=pf.path, resolved=resolved)

        for imp in pf.imports:
            node = imp.target if imp.is_external else _normalise_local(pf.path, imp.target)
            dep_graph.add_node(node, kind="package" if imp.is_external else "module")
            dep_graph.add_edge(pf.path, node, external=imp.is_external, line=imp.line)

    return GraphBundle(call_graph, dep_graph, _metrics(call_graph, dep_graph, parsed))


def _normalise_local(source_path: str, target: str) -> str:
    t = target.strip().lstrip(".").replace(".", "/")
    return t or source_path


def _metrics(call_graph: nx.DiGraph, dep_graph: nx.DiGraph, parsed: list[ParsedFile]) -> dict:
    internal = [n for n, d in call_graph.nodes(data=True) if d.get("kind") != "external"]
    sub = call_graph.subgraph(internal)

    fan_in = {n: call_graph.in_degree(n) for n in internal}
    fan_out = {n: call_graph.out_degree(n) for n in internal}

    try:
        cycles = [c for c in nx.simple_cycles(dep_graph) if len(c) > 1][:20]
    except Exception:
        cycles = []

    complexity = {
        n: d.get("complexity", 1) for n, d in call_graph.nodes(data=True) if d.get("kind") != "external"
    }
    # hotspot = complex AND widely called -> best return on review effort
    hotspots = sorted(
        (
            {
                "symbol": n,
                "path": call_graph.nodes[n].get("path"),
                "complexity": complexity.get(n, 1),
                "fan_in": fan_in.get(n, 0),
                "start_line": call_graph.nodes[n].get("start_line"),
                "end_line": call_graph.nodes[n].get("end_line"),
                "score": complexity.get(n, 1) * (1 + fan_in.get(n, 0)),
            }
            for n in internal
        ),
        key=lambda x: x["score"],
        reverse=True,
    )[:40]

    per_file: dict[str, dict] = {}
    for pf in parsed:
        symbols = pf.symbols
        per_file[pf.path] = {
            "symbols": len(symbols),
            "max_complexity": max((s.complexity for s in symbols), default=0),
            "avg_complexity": round(sum(s.complexity for s in symbols) / len(symbols), 2) if symbols else 0,
            "imports": len(pf.imports),
            "language": pf.language,
        }

    god_files = sorted(
        ({"path": p, **m} for p, m in per_file.items()),
        key=lambda x: (x["symbols"], x["max_complexity"]),
        reverse=True,
    )[:15]

    return {
        "nodes": call_graph.number_of_nodes(),
        "edges": call_graph.number_of_edges(),
        "unresolved_calls": sum(1 for _, _, d in call_graph.edges(data=True) if not d.get("resolved")),
        "dependency_cycles": cycles,
        "hotspots": hotspots,
        "god_files": god_files,
        "orphans": [n for n in internal if fan_in.get(n, 0) == 0 and fan_out.get(n, 0) == 0][:50],
        "per_file": per_file,
        "connected_components": nx.number_weakly_connected_components(sub) if sub.number_of_nodes() else 0,
    }


def neighbours(call_graph: nx.DiGraph, symbol: str, depth: int = 1) -> list[str]:
    """Callers + callees, used to widen LLM context around a finding."""
    if symbol not in call_graph:
        return []
    seen = {symbol}
    frontier = {symbol}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            nxt |= set(call_graph.predecessors(node)) | set(call_graph.successors(node))
        nxt -= seen
        seen |= nxt
        frontier = nxt
    return [s for s in seen if s != symbol and not s.startswith("external:")]
