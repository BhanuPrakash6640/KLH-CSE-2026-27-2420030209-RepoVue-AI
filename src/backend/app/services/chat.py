"""Finding Chatbot Service.

Leverages the unified RepoVue LLM strategy (Gemini -> Anthropic -> Silent ML Engine fallback)
to answer arbitrary questions about repository defects, vulnerabilities, architecture,
and remediation strategies grounded strictly in detected findings and evidence.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Analysis, Finding, Patch, Repository, Severity
from app.logging_config import get_logger
from app.schemas.api import ChatFindingRef, ChatRequest, ChatResponse
from app.services.llm import get_llm
from app.services.prompts import CHAT_SCHEMA, CHAT_SYSTEM

log = get_logger(__name__)


async def answer_finding_query(db: AsyncSession, request: ChatRequest) -> ChatResponse:
    target_analysis: Analysis | None = None
    target_finding: Finding | None = None

    # 1. Resolve finding if finding_id provided
    if request.finding_id:
        target_finding = (
            await db.execute(
                select(Finding)
                .where(Finding.id == request.finding_id)
                .options(selectinload(Finding.patches))
            )
        ).scalar_one_or_none()
        if target_finding:
            request.analysis_id = target_finding.analysis_id

    # 2. Resolve analysis
    if request.analysis_id:
        target_analysis = (
            await db.execute(
                select(Analysis)
                .where(Analysis.id == request.analysis_id)
                .options(selectinload(Analysis.repository))
            )
        ).scalar_one_or_none()
    else:
        # Fallback to most recent analysis in DB
        target_analysis = (
            await db.execute(
                select(Analysis)
                .order_by(Analysis.created_at.desc())
                .limit(1)
                .options(selectinload(Analysis.repository))
            )
        ).scalar_one_or_none()

    if target_analysis is None:
        return ChatResponse(
            response=(
                "No repository analyses were found in the database. "
                "Please run an analysis on a repository first, and I will be happy to explain "
                "its security, correctness, and performance findings in detail!"
            ),
            suggested_questions=[
                "How do I start a new repository analysis?",
                "What kind of defects does RepoVue detect?",
            ],
            referenced_findings=[],
            provider="RepoVue Assistant",
        )

    # 3. Load findings for this analysis
    findings_stmt = (
        select(Finding)
        .where(Finding.analysis_id == target_analysis.id)
        .options(selectinload(Finding.patches))
    )
    raw_findings = (await db.execute(findings_stmt)).scalars().all()

    # Sort by severity rank
    sev_rank = Severity.ORDER
    sorted_findings = sorted(
        raw_findings,
        key=lambda f: (-sev_rank.get(f.severity.lower(), 0), f.path, f.start_line),
    )
    findings_by_id = {str(f.id): f for f in sorted_findings}

    # Summary tallies
    sev_counts: dict[str, int] = {}
    cat_counts: dict[str, int] = {}
    for f in sorted_findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
        cat_counts[f.category] = cat_counts.get(f.category, 0) + 1

    repo_name = (
        target_analysis.repository.full_name
        if target_analysis.repository
        else "target-repository"
    )

    # 4. Build prompt blocks
    prompt_lines: list[str] = [
        f"REPOSITORY: {repo_name}",
        f"BRANCH: {target_analysis.branch or 'main'}",
        f"COMMIT: {target_analysis.commit_sha or 'HEAD'}",
        f"ANALYSIS STATUS: {target_analysis.status}",
        f"FINDINGS TOTAL: {len(sorted_findings)}",
        f"BY SEVERITY: {sev_counts}",
        f"BY CATEGORY: {cat_counts}",
        "",
    ]

    if target_finding:
        prompt_lines.append("PRIMARY FOCUS FINDING (User explicitly asked about this finding):")
        patch_info = (
            f"Proposed patch: {target_finding.patches[0].diff}"
            if target_finding.patches
            else "No patch generated yet."
        )
        prompt_lines.append(
            f"FINDING ID: {target_finding.id}\n"
            f"TITLE: {target_finding.title}\n"
            f"SEVERITY: {target_finding.severity}\n"
            f"CATEGORY: {target_finding.category}\n"
            f"FILE: {target_finding.path}\n"
            f"LINE: {target_finding.start_line}-{target_finding.end_line}\n"
            f"CWE: {target_finding.cwe or 'N/A'}\n"
            f"OWASP: {target_finding.owasp or 'N/A'}\n"
            f"DESCRIPTION: {target_finding.description}\n"
            f"ROOT CAUSE: {target_finding.root_cause or 'N/A'}\n"
            f"IMPACT: {target_finding.impact or 'N/A'}\n"
            f"CODE SNIPPET:\n{target_finding.snippet or 'N/A'}\n"
            f"{patch_info}\n"
        )
        prompt_lines.append("OTHER REPOSITORY FINDINGS (Top items for context):")

    # Include top 25 findings to stay well within token limits
    for f in sorted_findings[:25]:
        if target_finding and str(f.id) == str(target_finding.id):
            continue
        patch_snippet = (
            target_finding.patches[0].explanation if f.patches and f.patches[0].explanation else ""
        )
        prompt_lines.append(
            f"FINDING ID: {f.id}\n"
            f"TITLE: {f.title}\n"
            f"SEVERITY: {f.severity}\n"
            f"CATEGORY: {f.category}\n"
            f"FILE: {f.path}\n"
            f"LINE: {f.start_line}-{f.end_line}\n"
            f"CWE: {f.cwe or 'N/A'}\n"
            f"ROOT CAUSE: {f.root_cause or 'N/A'}\n"
            f"IMPACT: {f.impact or 'N/A'}\n"
            f"SUGGESTED FIX: {patch_snippet or f.description}\n"
        )

    # Add conversation history
    if request.history:
        prompt_lines.append("\nPREVIOUS CONVERSATION:")
        for msg in request.history[-6:]:
            role_label = "User" if msg.role == "user" else "Assistant"
            prompt_lines.append(f"{role_label}: {msg.content}")

    prompt_lines.append(f"\nUSER QUERY: {request.query}")
    full_prompt = "\n".join(prompt_lines)

    # 5. Call LLM with unified strategy
    llm = get_llm()
    provider_name = (
        "Gemini 2.5 Flash"
        if settings.GEMINI_API_KEY and llm._gemini_client
        else "Claude 3.5 Sonnet"
        if settings.ANTHROPIC_API_KEY and llm._anthropic_client
        else "RepoVue ML Defect Engine"
    )

    try:
        data = await llm.structured(
            system=CHAT_SYSTEM,
            prompt=full_prompt,
            schema=CHAT_SCHEMA,
            tool_name="finding_chat_response",
            tool_description="Explain findings and provide remediation guidance.",
        )
    except Exception as exc:
        log.warning("chat_llm_structured_failed_fallback", error=str(exc))
        data = llm._ml_backup.generate_chat(full_prompt)

    response_text = data.get("response", "").strip()
    if not response_text:
        fallback_data = llm._ml_backup.generate_chat(full_prompt)
        response_text = fallback_data.get("response", "I have reviewed your repository findings.")
        data["suggested_questions"] = fallback_data.get("suggested_questions", [])
        data["referenced_finding_ids"] = fallback_data.get("referenced_finding_ids", [])

    # 6. Resolve referenced findings
    raw_refs = data.get("referenced_finding_ids", [])
    if target_finding and str(target_finding.id) not in raw_refs:
        raw_refs.insert(0, str(target_finding.id))

    ref_objects: list[ChatFindingRef] = []
    for ref_id in raw_refs:
        f = findings_by_id.get(str(ref_id).strip())
        if f:
            ref_objects.append(
                ChatFindingRef(
                    id=f.id,
                    title=f.title,
                    category=f.category,
                    severity=f.severity,
                    path=f.path,
                    start_line=f.start_line,
                    end_line=f.end_line,
                    cwe=f.cwe,
                )
            )

    suggested_q = data.get("suggested_questions") or [
        "What are the highest severity vulnerabilities?",
        "How can I patch the critical findings?",
        "Are there any performance bottlenecks?",
    ]

    return ChatResponse(
        response=response_text,
        suggested_questions=suggested_q,
        referenced_findings=ref_objects,
        provider=provider_name,
    )
