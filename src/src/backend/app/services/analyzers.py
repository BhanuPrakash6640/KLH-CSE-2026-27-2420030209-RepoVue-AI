"""The AI analysis stage.

Flow per file:
    rule scan -> build context (chunks + call-graph neighbours)
              -> N category analyzers in parallel
              -> merge + dedupe
              -> triage pass (separate model call, adversarial)
              -> persist
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.db.models import Category, Severity
from app.logging_config import get_logger
from app.services import prompts as P
from app.services.llm import get_llm
from app.services.rules import RuleHit

log = get_logger(__name__)

SYSTEM_BY_CATEGORY = {
    Category.BUG: P.BUG_SYSTEM,
    Category.SECURITY: P.SECURITY_SYSTEM,
    Category.PERFORMANCE: P.PERFORMANCE_SYSTEM,
    Category.ARCHITECTURE: P.ARCHITECTURE_SYSTEM,
}

MIN_CONFIDENCE = 0.45
WS = re.compile(r"\s+")


@dataclass
class RawFinding:
    title: str
    category: str
    severity: str
    confidence: float
    path: str
    start_line: int
    end_line: int
    description: str
    root_cause: str = ""
    impact: str = ""
    cwe: str | None = None
    owasp: str | None = None
    tags: list = field(default_factory=list)
    snippet: str = ""
    evidence: dict = field(default_factory=dict)
    model: str = settings.LLM_MODEL

    @property
    def fingerprint(self) -> str:
        """Stable across commits: category + file + issue identity + normalised
        code. Deliberately excludes line numbers, which shift the moment
        somebody adds an import, and includes a title signature so two
        different issues in the same function don't collapse into one."""
        return make_fingerprint(self.category, self.path, self.snippet or self.title, self.cwe, self.title)

    def severity_rank(self) -> int:
        return Severity.ORDER.get(self.severity, 0)


def _clamp_lines(f: RawFinding, total_lines: int) -> RawFinding:
    f.start_line = max(1, min(f.start_line or 1, total_lines))
    f.end_line = max(f.start_line, min(f.end_line or f.start_line, total_lines))
    return f


def _snippet(source_lines: list[str], start: int, end: int, pad: int = 2) -> str:
    a = max(0, start - 1 - pad)
    b = min(len(source_lines), end + pad)
    return "\n".join(source_lines[a:b])


def _graph_note(path: str, metrics: dict, related: list[str], hits: list[RuleHit]) -> str:
    lines: list[str] = []
    per_file = (metrics.get("per_file") or {}).get(path)
    if per_file:
        lines.append(
            f"  file: {per_file['symbols']} symbols, max cyclomatic complexity "
            f"{per_file['max_complexity']}, {per_file['imports']} imports"
        )
    hot = [h for h in metrics.get("hotspots", []) if h.get("path") == path][:5]
    for h in hot:
        lines.append(f"  hotspot: {h['symbol']} (complexity {h['complexity']}, called from {h['fan_in']} places)")
    cycles = [c for c in metrics.get("dependency_cycles", []) if path in c][:3]
    for c in cycles:
        lines.append("  dependency cycle: " + " -> ".join(str(x) for x in c))
    if related:
        lines.append("  calls into: " + ", ".join(related[:8]))
    if hits:
        lines.append("  pattern-scanner hits (verify each before reporting; some are false positives):")
        lines.extend(h.as_note() for h in hits)
    return "\n".join(lines)


async def analyse_file(
    *,
    path: str,
    language: str,
    source: str,
    categories: list[str],
    metrics: dict,
    related_symbols: list[str],
    context: str,
    rule_hits: list[RuleHit],
) -> list[RawFinding]:
    llm = get_llm()
    if not llm.enabled:
        return []

    source_lines = source.splitlines()
    numbered = P.number_lines(source)
    graph_note = _graph_note(path, metrics, related_symbols, rule_hits)
    prompt = P.build_file_prompt(path, language, numbered, context, graph_note)

    jobs = [
        {
            "system": SYSTEM_BY_CATEGORY[cat],
            "prompt": prompt,
            "schema": P.FINDINGS_SCHEMA,
            "tool_name": "report_findings",
            "tool_description": f"Report {cat} findings for this file.",
        }
        for cat in categories
        if cat in SYSTEM_BY_CATEGORY
    ]
    results = await llm.map_structured(jobs)

    out: list[RawFinding] = []
    for cat, result in zip([c for c in categories if c in SYSTEM_BY_CATEGORY], results):
        if not result:
            continue
        for item in result.get("findings", []) or []:
            try:
                f = RawFinding(
                    title=str(item["title"])[:290],
                    category=item.get("category") or cat,
                    severity=item.get("severity", "medium"),
                    confidence=float(item.get("confidence", 0.5)),
                    path=path,  # trust our path, not the model's
                    start_line=int(item.get("start_line") or 1),
                    end_line=int(item.get("end_line") or item.get("start_line") or 1),
                    description=item.get("description", ""),
                    root_cause=item.get("root_cause", ""),
                    impact=item.get("impact", ""),
                    cwe=(item.get("cwe") or "").strip() or None,
                    owasp=(item.get("owasp") or "").strip() or None,
                    tags=list(item.get("tags") or []),
                    evidence={
                        "reproduction": item.get("reproduction", ""),
                        "suggested_fix": item.get("suggested_fix", ""),
                        "detector": "llm",
                    },
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("malformed_finding", path=path, error=str(exc))
                continue
            if f.confidence < MIN_CONFIDENCE:
                continue
            _clamp_lines(f, len(source_lines))
            f.snippet = _snippet(source_lines, f.start_line, f.end_line)
            out.append(f)
    return dedupe(out)


def dedupe(findings: list[RawFinding]) -> list[RawFinding]:
    """Same fingerprint, or heavy line overlap in the same category -> keep the
    highest severity/confidence one."""
    best: dict[str, RawFinding] = {}
    for f in findings:
        key = f.fingerprint
        current = best.get(key)
        if current is None or (f.severity_rank(), f.confidence) > (current.severity_rank(), current.confidence):
            best[key] = f

    result: list[RawFinding] = []
    for f in sorted(best.values(), key=lambda x: (-x.severity_rank(), x.start_line)):
        overlapping = next(
            (
                r for r in result
                if r.category == f.category and r.path == f.path
                and not (f.end_line < r.start_line or f.start_line > r.end_line)
                and _similar(r.title, f.title)
            ),
            None,
        )
        if overlapping is None:
            result.append(f)
    return result


def _similar(a: str, b: str) -> bool:
    ta = set(WS.sub(" ", a.lower()).split())
    tb = set(WS.sub(" ", b.lower()).split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.55


async def triage(findings: list[RawFinding], batch_size: int = 12) -> list[RawFinding]:
    """Second opinion pass. Deliberately adversarial - its job is to delete."""
    llm = get_llm()
    if not llm.enabled or not findings:
        return findings

    kept: list[RawFinding] = []
    for i in range(0, len(findings), batch_size):
        batch = findings[i : i + batch_size]
        payload = "\n\n".join(
            f"[{n}] category={f.category} severity={f.severity} confidence={f.confidence}\n"
            f"file={f.path}:{f.start_line}-{f.end_line}\n"
            f"title={f.title}\nwhy={f.description}\nroot_cause={f.root_cause}\n"
            f"code:\n```\n{f.snippet[:1800]}\n```"
            for n, f in enumerate(batch)
        )
        result = await llm.map_structured(
            [
                {
                    "system": P.TRIAGE_SYSTEM,
                    "prompt": f"Candidate findings:\n\n{payload}\n\nReturn a verdict for every index.",
                    "schema": P.TRIAGE_SCHEMA,
                    "tool_name": "triage",
                    "model": settings.LLM_MODEL,
                }
            ]
        )
        verdicts = (result[0] or {}).get("verdicts") if result else None
        if not verdicts:
            kept.extend(batch)  # triage unavailable -> fail open, keep findings
            continue
        by_index = {int(v["index"]): v for v in verdicts if "index" in v}
        for n, f in enumerate(batch):
            v = by_index.get(n)
            if v is None:
                kept.append(f)
                continue
            if not v.get("keep", True):
                log.info("triage_dropped", title=f.title[:80], reason=str(v.get("reason"))[:160])
                continue
            if v.get("adjusted_severity") in Severity.ORDER:
                f.severity = v["adjusted_severity"]
            if isinstance(v.get("adjusted_confidence"), (int, float)):
                f.confidence = float(v["adjusted_confidence"])
            f.evidence["triage_reason"] = str(v.get("reason", ""))[:500]
            kept.append(f)
    return kept


def prioritise(findings: list[RawFinding], limit: int = 200) -> list[RawFinding]:
    return sorted(findings, key=lambda f: (-f.severity_rank(), -f.confidence))[:limit]


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "then",
    "which", "there", "here", "have", "has", "not", "can", "may", "will", "issue",
    "code", "using", "used", "use", "line", "lines", "function", "method",
}


def title_signature(title: str, keep: int = 6) -> str:
    """A wording-tolerant identity for an issue: sorted content words. Small
    rephrasings between runs produce the same signature, genuinely different
    issues do not."""
    tokens = {
        t for t in re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
        if len(t) > 3 and t not in STOPWORDS
    }
    return "-".join(sorted(tokens)[:keep])


def make_fingerprint(
    category: str, path: str, snippet: str, cwe: str | None = None, title: str = ""
) -> str:
    normalised = WS.sub(" ", snippet).strip().lower()[:400]
    basis = f"{category}|{path}|{cwe or ''}|{title_signature(title)}|{normalised}"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
