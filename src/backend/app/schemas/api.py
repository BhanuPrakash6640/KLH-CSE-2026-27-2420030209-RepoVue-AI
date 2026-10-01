"""Request / response contracts. The frontend can generate a typed client
straight from /openapi.json."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GITHUB_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- repositories ----------------
class RepositoryCreate(BaseModel):
    url: str = Field(..., examples=["https://github.com/pallets/flask"])
    default_branch: str | None = None

    @field_validator("url")
    @classmethod
    def _validate(cls, v: str) -> str:
        if not GITHUB_URL.match(v.strip()):
            raise ValueError("Must be a GitHub repository URL (github.com/owner/repo)")
        return v.strip()

    @property
    def full_name(self) -> str:
        m = GITHUB_URL.match(self.url)
        assert m
        return f"{m.group('owner')}/{m.group('repo')}"


class RepositoryOut(ORMModel):
    id: uuid.UUID
    provider: str
    full_name: str
    clone_url: str
    default_branch: str
    is_private: bool
    created_at: datetime


# ---------------- analyses ----------------
class AnalysisCreate(BaseModel):
    repository_id: uuid.UUID | None = None
    url: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    diff_only: bool = Field(
        False, description="Only analyse files touched by the PR/commit"
    )
    open_pr: bool = Field(True, description="Open a fix PR when patches validate")
    categories: list[Literal["logical_bug", "security", "performance", "architecture"]] = Field(
        default_factory=lambda: ["logical_bug", "security", "performance", "architecture"]
    )


class AnalysisOut(ORMModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    repository_full_name: str | None = None
    commit_sha: str | None
    branch: str | None
    pr_number: int | None
    trigger: str
    status: str
    stage: str | None
    progress: int
    error: str | None
    stats: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AnalysisSummary(BaseModel):
    analysis: AnalysisOut
    repository: RepositoryOut | None = None
    findings_by_severity: dict[str, int]
    findings_by_category: dict[str, int]
    patches: dict[str, int]
    top_files: list[dict[str, Any]]


class QualityGate(BaseModel):
    """What CI polls. `complete` tells the workflow to stop waiting;
    `passed` tells it whether to fail the build."""

    analysis_id: uuid.UUID
    status: str
    complete: bool
    passed: bool
    stage: str | None
    progress: int
    fail_on: str
    blocking_findings: int
    counts: dict[str, int]
    patches: dict[str, int]
    error: str | None = None


class RepositoryOverview(BaseModel):
    """One row of the repositories table: the repo plus what its most recent
    completed run left behind."""

    repository: RepositoryOut
    last_analysis: AnalysisOut | None = None
    findings: int = 0
    patched: int = 0
    validated: int = 0
    false_positives: int = 0
    by_severity: dict[str, int] = {}


# ---------------- findings ----------------
class PatchOut(ORMModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    analysis_id: uuid.UUID
    path: str
    diff: str
    explanation: str | None
    risk_notes: str | None
    status: str
    model: str | None = None
    created_at: datetime


class ValidationOut(ORMModel):
    id: uuid.UUID
    patch_id: uuid.UUID
    image_tag: str | None = None
    test_command: str | None = None
    tests_passed: bool
    perf_delta_pct: float | None
    verdict: str
    reason: str | None
    baseline: dict[str, Any]
    patched: dict[str, Any]
    logs: str | None = None
    created_at: datetime


class FindingOut(ORMModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    category: str
    severity: str
    confidence: float
    title: str
    description: str
    root_cause: str | None
    impact: str | None
    path: str
    start_line: int
    end_line: int
    snippet: str | None
    cwe: str | None
    owasp: str | None
    tags: list[Any]
    evidence: dict[str, Any] = {}
    status: str
    model: str | None = None
    created_at: datetime


class FindingDetail(FindingOut):
    patches: list[PatchOut] = []


class FindingStatusUpdate(BaseModel):
    status: Literal["open", "patch_proposed", "validated", "rejected", "false_positive", "resolved"]
    note: str | None = None


# ---------------- search ----------------
class SearchRequest(BaseModel):
    analysis_id: uuid.UUID
    query: str
    limit: int = Field(8, ge=1, le=50)


class SearchHit(BaseModel):
    path: str
    symbol_name: str | None
    start_line: int
    end_line: int
    score: float
    content: str


# ---------------- misc ----------------
class Page(BaseModel):
    total: int
    limit: int
    offset: int


class FindingPage(Page):
    items: list[FindingOut]


class Health(BaseModel):
    status: str
    env: str
    database: str
    llm_configured: bool
    docker: str
    version: str


# ---------------- chat assistant ----------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatFindingRef(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    severity: str
    path: str
    start_line: int
    end_line: int
    cwe: str | None = None


class ChatRequest(BaseModel):
    query: str
    analysis_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    suggested_questions: list[str] = Field(default_factory=list)
    referenced_findings: list[ChatFindingRef] = Field(default_factory=list)
    provider: str = "assistant"
