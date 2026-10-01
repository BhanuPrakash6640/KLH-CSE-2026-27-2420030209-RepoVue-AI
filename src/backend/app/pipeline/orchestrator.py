"""The RepoVue pipeline.

    clone -> index (AST + graphs) -> embed -> AI review -> triage
          -> fix generation -> docker validation -> PR + check run -> Jira

Each stage updates `Analysis.stage` / `progress` so the frontend can show a
live progress bar, and every stage is defensive: a failure in fix generation
must never throw away findings that were already produced.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Analysis,
    AnalysisStatus,
    CallEdge,
    DependencyEdge,
    Finding,
    FindingStatus,
    JiraTicket,
    Patch,
    PatchStatus,
    PullRequestRef,
    Repository,
    Severity,
    SourceFile,
    Symbol,
    ValidationRun,
    Verdict,
)
from app.db.session import session_scope
from app.logging_config import get_logger
from app.services import github as gh
from app.services import patcher
from app.services.analyzers import RawFinding, analyse_file, prioritise, triage
from app.services.ast_parser import ParsedFile, parse_source
from app.services.chunker import chunk_file
from app.services.embeddings import get_embedder
from app.services.graphs import build_graphs, neighbours
from app.services.jira import JiraClient
from app.services.languages import ProjectProfile, profile_project, walk_repository
from app.services.llm import get_llm
from app.services.retrieval import context_for_symbol, store_chunks
from app.services.rules import scan
from app.services.sandbox import validate_patch

log = get_logger(__name__)

MAX_LLM_FILES = 12          # top hotspot files ranked by complexity
MAX_PATCHES = 4             # top critical fixes generated per analysis
MAX_VALIDATIONS = 4         # docker runs are the slowest thing we do
PARSE_CONCURRENCY = 16

STAGES = [
    ("clone", 5), ("index", 20), ("embed", 35), ("review", 65),
    ("triage", 72), ("fix", 82), ("validate", 92), ("publish", 98), ("done", 100),
]


@dataclass
class PipelineContext:
    analysis_id: uuid.UUID
    repo_full_name: str
    clone_url: str
    default_branch: str
    ref: str | None
    pr_number: int | None
    diff_only: bool
    open_pr: bool
    categories: list[str]
    workdir: str = ""
    repo_dir: str = ""
    validated: list = field(default_factory=list)
    commit_sha: str = ""
    profile: ProjectProfile = field(default_factory=ProjectProfile)
    parsed: list[ParsedFile] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    call_graph = None
    findings: list[RawFinding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    changed: list[str] = field(default_factory=list)


async def _set_stage(session: AsyncSession, analysis_id: uuid.UUID, stage: str) -> None:
    progress = dict(STAGES).get(stage, 0)
    analysis = await session.get(Analysis, analysis_id)
    if analysis:
        analysis.stage = stage
        analysis.progress = progress
        await session.flush()
    log.info("stage", analysis=str(analysis_id), stage=stage, progress=progress)


async def run_analysis(analysis_id: uuid.UUID) -> None:
    """Entry point invoked by the worker."""
    started = time.perf_counter()
    async with session_scope() as session:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            log.error("analysis_missing", id=str(analysis_id))
            return
        repo = await session.get(Repository, analysis.repository_id)
        analysis.status = AnalysisStatus.RUNNING
        analysis.started_at = datetime.now(timezone.utc)
        await session.flush()

        options = analysis.stats.get("options", {}) if analysis.stats else {}
        ctx = PipelineContext(
            analysis_id=analysis_id,
            repo_full_name=repo.full_name,
            clone_url=repo.clone_url,
            default_branch=repo.default_branch,
            ref=analysis.commit_sha or analysis.branch or repo.default_branch,
            pr_number=analysis.pr_number,
            diff_only=analysis.diff_only,
            open_pr=bool(options.get("open_pr", True)),
            categories=options.get("categories") or [
                "logical_bug", "security", "performance", "architecture"
            ],
        )

    try:
        await _stage_clone(ctx)
        await _stage_index(ctx)
        await _stage_embed(ctx)
        await _stage_review(ctx)
        await _stage_triage(ctx)
        await _stage_fix_and_validate(ctx)
        await _stage_publish(ctx)

        async with session_scope() as session:
            analysis = await session.get(Analysis, analysis_id)
            analysis.status = AnalysisStatus.SUCCEEDED
            analysis.stage = "done"
            analysis.progress = 100
            analysis.finished_at = datetime.now(timezone.utc)
            ctx.stats["duration_sec"] = round(time.perf_counter() - started, 2)
            ctx.stats["llm_usage"] = get_llm().usage
            analysis.stats = {**(analysis.stats or {}), **ctx.stats}
        log.info("analysis_complete", id=str(analysis_id), seconds=ctx.stats["duration_sec"])

    except Exception as exc:
        log.exception("analysis_failed", id=str(analysis_id))
        async with session_scope() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis:
                analysis.status = AnalysisStatus.FAILED
                analysis.error = f"{type(exc).__name__}: {exc}"[:2000]
                analysis.finished_at = datetime.now(timezone.utc)
                analysis.stats = {**(analysis.stats or {}), **ctx.stats}
        raise
    finally:
        if ctx.workdir:
            shutil.rmtree(ctx.workdir, ignore_errors=True)


# ------------------------------------------------------------------ stages
async def _stage_clone(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "clone")

    base = Path(settings.WORKSPACE_DIR)
    base.mkdir(parents=True, exist_ok=True)
    ctx.workdir = tempfile.mkdtemp(prefix=f"an_{str(ctx.analysis_id)[:8]}_", dir=str(base))
    repo_dir = str(Path(ctx.workdir) / "repo")

    path, sha = await gh.clone_repository(ctx.clone_url, repo_dir, ctx.ref, depth=1 if not ctx.diff_only else 50)
    ctx.workdir = ctx.workdir  # keep root for cleanup
    ctx.repo_dir = path
    ctx.commit_sha = sha

    if ctx.diff_only and ctx.pr_number:
        owner, name = gh.parse_repo_url(ctx.clone_url)
        client = gh.GitHubClient()
        try:
            ctx.changed = await client.pr_files(owner, name, ctx.pr_number)
        finally:
            await client.aclose()
    elif ctx.diff_only:
        ctx.changed = patcher.changed_files(path, f"{ctx.commit_sha}~1", ctx.commit_sha)

    async with session_scope() as s:
        analysis = await s.get(Analysis, ctx.analysis_id)
        analysis.commit_sha = sha
    ctx.stats["commit_sha"] = sha
    ctx.stats["changed_files"] = len(ctx.changed)


async def _stage_index(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "index")

    repo_dir: str = ctx.repo_dir
    files = await asyncio.to_thread(walk_repository, repo_dir)
    ctx.profile = await asyncio.to_thread(profile_project, repo_dir, files)

    sem = asyncio.Semaphore(PARSE_CONCURRENCY)

    async def _parse(meta: dict) -> tuple[dict, ParsedFile, str]:
        async with sem:
            source = await asyncio.to_thread(
                lambda: Path(meta["abs_path"]).read_text("utf-8", errors="ignore")
            )
            parsed = await asyncio.to_thread(parse_source, meta["path"], meta["language"], source)
            return meta, parsed, source

    results = await asyncio.gather(*(_parse(m) for m in files))
    ctx.parsed = [r[1] for r in results]
    ctx.sources = {r[0]["path"]: r[2] for r in results}

    bundle = await asyncio.to_thread(build_graphs, ctx.parsed)
    ctx.metrics = bundle.metrics
    ctx.call_graph = bundle.call_graph

    async with session_scope() as s:
        file_rows: dict[str, SourceFile] = {}
        for meta, parsed, _ in results:
            row = SourceFile(
                analysis_id=ctx.analysis_id, path=meta["path"], language=meta["language"],
                size_bytes=meta["size_bytes"], loc=meta["loc"],
                content_sha=meta["content_sha"], parse_error=parsed.error,
            )
            s.add(row)
            file_rows[meta["path"]] = row
        await s.flush()

        for parsed in ctx.parsed:
            frow = file_rows[parsed.path]
            for sym in parsed.symbols:
                s.add(Symbol(
                    analysis_id=ctx.analysis_id, file_id=frow.id, path=parsed.path,
                    name=sym.name, qualified_name=sym.qualified_name, kind=sym.kind,
                    signature=sym.signature, start_line=sym.start_line, end_line=sym.end_line,
                    parent=sym.parent, complexity=sym.complexity,
                ))
            for call in parsed.calls[:500]:
                s.add(CallEdge(
                    analysis_id=ctx.analysis_id, caller=call.caller[:500], callee=call.callee[:500],
                    path=parsed.path, line=call.line,
                ))
            for imp in parsed.imports[:200]:
                s.add(DependencyEdge(
                    analysis_id=ctx.analysis_id, source_path=parsed.path,
                    target=imp.target[:500], is_external=imp.is_external, line=imp.line,
                ))

    ctx.stats.update({
        "files_analysed": len(files),
        "loc": sum(f["loc"] for f in files),
        "symbols": sum(len(p.symbols) for p in ctx.parsed),
        "languages": ctx.profile.languages,
        "project": ctx.profile.to_dict(),
        "graph": {
            k: v for k, v in ctx.metrics.items()
            if k in ("nodes", "edges", "unresolved_calls", "connected_components")
        },
        "dependency_cycles": len(ctx.metrics.get("dependency_cycles", [])),
    })


async def _stage_embed(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "embed")

    chunks = []
    for parsed in ctx.parsed:
        source = ctx.sources.get(parsed.path)
        if source:
            chunks.extend(chunk_file(parsed, source))
    if not chunks:
        ctx.stats["chunks"] = 0
        return

    embedder = get_embedder()
    vectors = await embedder.embed([c.content for c in chunks], "document")

    async with session_scope() as s:
        for i in range(0, len(chunks), 500):  # keep transactions small
            await store_chunks(s, ctx.analysis_id, chunks[i : i + 500], vectors[i : i + 500])
    ctx.stats["chunks"] = len(chunks)


def _select_files(ctx: PipelineContext) -> list[ParsedFile]:
    """Spending an LLM call on every file is wasteful on big repos. Rank by
    changed-in-this-PR > hotspot score > complexity, then cap."""
    if ctx.changed:
        changed = set(ctx.changed)
        selected = [p for p in ctx.parsed if p.path in changed]
        if selected:
            return selected[:MAX_LLM_FILES]

    hotspot_paths = {h["path"]: h["score"] for h in ctx.metrics.get("hotspots", []) if h.get("path")}
    per_file = ctx.metrics.get("per_file", {})

    def score(p: ParsedFile) -> float:
        m = per_file.get(p.path, {})
        base = hotspot_paths.get(p.path, 0)
        return base + m.get("max_complexity", 0) * 2 + m.get("symbols", 0)

    ranked = sorted(ctx.parsed, key=score, reverse=True)
    return [p for p in ranked if p.symbols or len(ctx.sources.get(p.path, "")) > 200][:MAX_LLM_FILES]


async def _stage_review(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "review")

    llm = get_llm()
    if not llm.enabled:
        ctx.stats["review_skipped"] = "ANTHROPIC_API_KEY not configured"
        return

    targets = _select_files(ctx)
    ctx.stats["files_reviewed"] = len(targets)
    sem = asyncio.Semaphore(max(2, settings.LLM_MAX_CONCURRENCY))

    async def _review(parsed: ParsedFile) -> list[RawFinding]:
        source = ctx.sources.get(parsed.path, "")
        if not source.strip():
            return []
        async with sem:
            related: list[str] = []
            for sym in parsed.symbols[:5]:
                related.extend(neighbours(ctx.call_graph, sym.qualified_name, depth=1))
            related = list(dict.fromkeys(related))[:10]

            async with session_scope() as s:
                context = await context_for_symbol(
                    s, ctx.analysis_id, parsed.path, None, related, budget_chars=12_000
                )
            hits = await asyncio.to_thread(scan, source, parsed.language)
            return await analyse_file(
                path=parsed.path, language=parsed.language, source=source,
                categories=ctx.categories, metrics=ctx.metrics,
                related_symbols=related, context=context, rule_hits=hits,
            )

    batches = await asyncio.gather(*(_review(p) for p in targets), return_exceptions=True)
    for batch in batches:
        if isinstance(batch, Exception):
            log.warning("file_review_failed", error=str(batch)[:200])
            continue
        ctx.findings.extend(batch)
    ctx.stats["raw_findings"] = len(ctx.findings)


async def _stage_triage(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "triage")

    before = len(ctx.findings)
    ctx.findings = prioritise(await triage(ctx.findings))
    ctx.stats["findings_dropped_by_triage"] = before - len(ctx.findings)
    ctx.stats["findings"] = len(ctx.findings)

    async with session_scope() as s:
        seen: set[str] = set()
        for f in ctx.findings:
            fp = f.fingerprint
            if fp in seen:
                continue
            seen.add(fp)
            s.add(Finding(
                analysis_id=ctx.analysis_id, fingerprint=fp, category=f.category,
                severity=f.severity, confidence=f.confidence, title=f.title,
                description=f.description, root_cause=f.root_cause, impact=f.impact,
                path=f.path, start_line=f.start_line, end_line=f.end_line,
                snippet=f.snippet[:8000], cwe=f.cwe, owasp=f.owasp, tags=f.tags,
                evidence=f.evidence, status=FindingStatus.OPEN, model=f.model,
            ))

    by_sev: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for f in ctx.findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    ctx.stats["by_severity"] = by_sev
    ctx.stats["by_category"] = by_cat


async def _stage_fix_and_validate(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "fix")

    repo_dir: str = ctx.repo_dir
    if not get_llm().enabled or not ctx.findings:
        return

    candidates = [
        f for f in ctx.findings
        if Severity.ORDER.get(f.severity, 0) >= Severity.ORDER["medium"] and f.confidence >= 0.6
    ][:MAX_PATCHES]

    generated: list[tuple[RawFinding, object]] = []
    for finding in candidates:  # sequential: each patch must see a clean tree
        try:
            patch = await patcher.generate_patch(finding=finding, repo_root=repo_dir)
        except Exception as exc:
            log.warning("patch_generation_failed", title=finding.title[:60], error=str(exc)[:200])
            continue
        if patch and patch.diff:
            generated.append((finding, patch))

    ctx.stats["patches_generated"] = len(generated)

    # persist patches
    patch_ids: dict[str, uuid.UUID] = {}
    async with session_scope() as s:
        rows = (await s.execute(
            select(Finding).where(Finding.analysis_id == ctx.analysis_id)
        )).scalars().all()
        by_fp = {r.fingerprint: r for r in rows}
        for finding, patch in generated:
            frow = by_fp.get(finding.fingerprint)
            if frow is None:
                continue
            prow = Patch(
                finding_id=frow.id, analysis_id=ctx.analysis_id, path=patch.path,
                diff=patch.diff, original_code=patch.original_code,
                patched_code=patch.patched_code, explanation=patch.explanation,
                risk_notes=patch.risk_notes,
                status=PatchStatus.GENERATED if patch.applies_cleanly else PatchStatus.REJECTED,
                model=settings.LLM_MODEL,
            )
            s.add(prow)
            frow.status = FindingStatus.PATCH_PROPOSED
            await s.flush()
            patch_ids[finding.fingerprint] = prow.id

    # ---- docker validation ----
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "validate")

    validated: list[dict] = []
    to_validate = [(f, p) for f, p in generated if p.applies_cleanly][:MAX_VALIDATIONS]

    for finding, patch in to_validate:
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, dir=ctx.workdir) as fh:
            fh.write(patch.diff if patch.diff.endswith("\n") else patch.diff + "\n")
            patch_file = fh.name

        result = await validate_patch(
            repo_root=repo_dir, profile=ctx.profile, diff=patch.diff, patch_file_path=patch_file
        )
        pid = patch_ids.get(finding.fingerprint)
        async with session_scope() as s:
            if pid:
                s.add(ValidationRun(
                    patch_id=pid, image_tag=result.image_tag, test_command=result.test_command,
                    baseline=result.baseline, patched=result.patched,
                    tests_passed=result.tests_passed, perf_delta_pct=result.perf_delta_pct,
                    verdict=result.verdict, reason=result.reason, logs=(result.logs or "")[:20000],
                ))
                prow = await s.get(Patch, pid)
                if prow:
                    prow.status = (
                        PatchStatus.ACCEPTED
                        if result.verdict in (Verdict.PASS, Verdict.SKIPPED)
                        else PatchStatus.REJECTED
                    )
                    frow = await s.get(Finding, prow.finding_id)
                    if frow and result.verdict == Verdict.PASS:
                        frow.status = FindingStatus.VALIDATED

        if result.verdict in (Verdict.PASS, Verdict.SKIPPED):
            validated.append({
                "title": finding.title, "severity": finding.severity, "path": patch.path,
                "explanation": patch.explanation, "risk_notes": patch.risk_notes,
                "diff": patch.diff, "tests_passed": result.tests_passed,
                "perf_delta_pct": result.perf_delta_pct, "verdict": result.verdict,
            })

    ctx.stats["patches_validated"] = len(validated)
    ctx.validated = validated


async def _stage_publish(ctx: PipelineContext) -> None:
    async with session_scope() as s:
        await _set_stage(s, ctx.analysis_id, "publish")

    owner, name = gh.parse_repo_url(ctx.clone_url)
    analysis_url = f"{_frontend_base()}/analyses/{ctx.analysis_id}"
    findings_payload = [
        {
            "title": f.title, "severity": f.severity, "category": f.category, "path": f.path,
            "start_line": f.start_line, "description": f.description, "root_cause": f.root_cause,
            "impact": f.impact, "cwe": f.cwe, "owasp": f.owasp, "fingerprint": f.fingerprint,
            "end_line": f.end_line,
        }
        for f in ctx.findings
    ]
    validated = ctx.validated

    if not settings.GITHUB_TOKEN:
        ctx.stats["publish_skipped"] = "GITHUB_TOKEN not configured"
        await _stage_jira(ctx, findings_payload, analysis_url, None)
        return

    client = gh.GitHubClient()
    pr_url = None
    try:
        # 1. quality gate check run
        blocking = [f for f in ctx.findings if f.severity in ("critical", "high")]
        conclusion = "failure" if blocking else "success"
        await client.create_check_run(
            owner, name, sha=ctx.commit_sha, name="RepoVue",
            conclusion=conclusion,
            title=f"{len(ctx.findings)} findings ({len(blocking)} blocking)",
            summary=gh.render_findings_comment(findings_payload, analysis_url, ctx.stats),
        )

        # 2. review on the triggering PR
        if ctx.pr_number:
            body = gh.render_findings_comment(findings_payload, analysis_url, ctx.stats)
            inline = gh.render_inline_comments(
                [f for f in findings_payload if not ctx.changed or f["path"] in set(ctx.changed)]
            )
            await client.create_review(owner, name, ctx.pr_number, ctx.commit_sha, inline, body)

        # 3. fix PR
        if ctx.open_pr and validated:
            repo_dir: str = ctx.repo_dir
            applied_any = False
            for item in validated:
                ok, err = await asyncio.to_thread(patcher.apply_diff, repo_dir, item["diff"])
                applied_any = applied_any or ok
                if not ok:
                    log.warning("apply_failed_on_branch", path=item["path"], error=err[:200])

            if applied_any:
                branch = f"repovue/fix-{str(ctx.analysis_id)[:8]}"
                pushed = await gh.push_branch(
                    repo_dir, branch,
                    f"fix: RepoVue automated fixes ({len(validated)} issues)",
                    ctx.clone_url,
                )
                if pushed:
                    pr = await client.create_pull_request(
                        owner, name, head=branch, base=ctx.default_branch,
                        title=f"RepoVue: {len(validated)} validated fixes",
                        body=gh.render_pr_body(validated, analysis_url),
                    )
                    pr_url = pr.get("html_url")
                    async with session_scope() as s:
                        s.add(PullRequestRef(
                            analysis_id=ctx.analysis_id, number=pr.get("number", 0),
                            url=pr_url or "", branch=branch,
                            patch_ids=[v["path"] for v in validated],
                        ))
                    ctx.stats["fix_pr_url"] = pr_url
    except Exception as exc:
        log.warning("publish_failed", error=str(exc)[:300])
        ctx.stats["publish_error"] = str(exc)[:300]
    finally:
        await client.aclose()

    await _stage_jira(ctx, findings_payload, analysis_url, pr_url)


async def _stage_jira(ctx: PipelineContext, findings: list[dict], analysis_url: str, pr_url: str | None) -> None:
    jira = JiraClient()
    if not jira.enabled:
        return
    created = 0
    try:
        async with session_scope() as s:
            rows = (await s.execute(
                select(Finding).where(Finding.analysis_id == ctx.analysis_id)
            )).scalars().all()
            by_fp = {r.fingerprint: r for r in rows}

            for f in findings:
                if not jira.meets_threshold(f["severity"]):
                    continue
                ticket = await jira.create_issue(
                    f, ctx.repo_full_name,
                    {"analysis_url": analysis_url, "pr_url": pr_url or ""},
                )
                if not ticket:
                    continue
                frow = by_fp.get(f["fingerprint"])
                if frow:
                    s.add(JiraTicket(finding_id=frow.id, issue_key=ticket["key"], url=ticket["url"]))
                if pr_url:
                    await jira.add_remote_link(ticket["key"], pr_url, "RepoVue fix PR")
                created += 1
    except Exception as exc:
        log.warning("jira_stage_failed", error=str(exc)[:300])
    finally:
        await jira.aclose()
    ctx.stats["jira_tickets"] = created


def _frontend_base() -> str:
    return "http://localhost:3000" if not settings.is_prod else "https://app.repovue.dev"
