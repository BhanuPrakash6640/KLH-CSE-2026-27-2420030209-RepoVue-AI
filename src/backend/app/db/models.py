"""Database schema.

Design notes
------------
* One `Repository` has many `Analysis` runs (one per commit / PR).
* Everything produced by a run (files, symbols, chunks, findings) hangs off the
  analysis so re-running is idempotent and old results stay queryable for
  trend charts on the dashboard.
* `Finding.fingerprint` is a stable hash (rule + file + normalised code) so the
  same issue is not re-reported on every commit, and so Jira tickets are not
  duplicated.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------
# Repository / analysis
# --------------------------------------------------------------------------
class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("provider", "full_name", name="uq_repo_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), default="github")
    full_name: Mapped[str] = mapped_column(String(255), index=True)  # owner/repo
    clone_url: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    installation_id: Mapped[str | None] = mapped_column(String(64))
    settings_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class AnalysisStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Analysis(TimestampMixin, Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_repo_created", "repository_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    branch: Mapped[str | None] = mapped_column(String(255))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual|push|pull_request
    status: Mapped[str] = mapped_column(String(24), default=AnalysisStatus.QUEUED, index=True)
    stage: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    diff_only: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[Repository] = relationship(back_populates="analyses")
    files: Mapped[list["SourceFile"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )

    @property
    def repository_full_name(self) -> str | None:
        """`owner/repo` when the relationship was eager-loaded, else None.

        Serialisers read this optimistically; a lazy load inside an async
        context raises, and an absent name is not worth failing a response for.
        """
        try:
            return self.repository.full_name if self.repository else None
        except Exception:
            return None


# --------------------------------------------------------------------------
# Static analysis artefacts
# --------------------------------------------------------------------------
class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (Index("ix_files_analysis_path", "analysis_id", "path"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str | None] = mapped_column(String(32), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    loc: Mapped[int] = mapped_column(Integer, default=0)
    content_sha: Mapped[str | None] = mapped_column(String(64))
    parse_error: Mapped[str | None] = mapped_column(Text)

    analysis: Mapped[Analysis] = relationship(back_populates="files")


class Symbol(Base):
    """A function / method / class extracted from the AST."""

    __tablename__ = "symbols"
    __table_args__ = (Index("ix_symbols_analysis_name", "analysis_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(255))
    qualified_name: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32))  # function|method|class|interface
    signature: Mapped[str | None] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    parent: Mapped[str | None] = mapped_column(String(255))
    complexity: Mapped[int] = mapped_column(Integer, default=1)


class CallEdge(Base):
    __tablename__ = "call_edges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    caller: Mapped[str] = mapped_column(String(512), index=True)
    callee: Mapped[str] = mapped_column(String(512), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    line: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class DependencyEdge(Base):
    __tablename__ = "dependency_edges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    source_path: Mapped[str] = mapped_column(String(1024), index=True)
    target: Mapped[str] = mapped_column(String(512))
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    line: Mapped[int] = mapped_column(Integer, default=0)


class CodeChunk(Base):
    """Embedded slice of code used for semantic context retrieval."""

    __tablename__ = "code_chunks"
    __table_args__ = (Index("ix_chunks_analysis", "analysis_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    symbol_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(32))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIM), nullable=True)


# --------------------------------------------------------------------------
# Findings / fixes / validation
# --------------------------------------------------------------------------
class Category:
    BUG = "logical_bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"


class Severity:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    ORDER = {CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1, INFO: 0}


class FindingStatus:
    OPEN = "open"
    PATCH_PROPOSED = "patch_proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    FALSE_POSITIVE = "false_positive"
    RESOLVED = "resolved"


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("analysis_id", "fingerprint", name="uq_finding_fingerprint"),
        Index("ix_findings_sev", "analysis_id", "severity"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer, default=0)
    end_line: Mapped[int] = mapped_column(Integer, default=0)
    snippet: Mapped[str | None] = mapped_column(Text)
    cwe: Mapped[str | None] = mapped_column(String(32))
    owasp: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=FindingStatus.OPEN, index=True)
    model: Mapped[str | None] = mapped_column(String(64))

    analysis: Mapped[Analysis] = relationship(back_populates="findings")
    patches: Mapped[list["Patch"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class PatchStatus:
    GENERATED = "generated"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PUBLISHED = "published"


class Patch(TimestampMixin, Base):
    __tablename__ = "patches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    diff: Mapped[str] = mapped_column(Text)
    original_code: Mapped[str | None] = mapped_column(Text)
    patched_code: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    risk_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default=PatchStatus.GENERATED, index=True)
    model: Mapped[str | None] = mapped_column(String(64))

    finding: Mapped[Finding] = relationship(back_populates="patches")
    validations: Mapped[list["ValidationRun"]] = relationship(
        back_populates="patch", cascade="all, delete-orphan"
    )


class Verdict:
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    ERROR = "error"


class ValidationRun(TimestampMixin, Base):
    __tablename__ = "validation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    patch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patches.id", ondelete="CASCADE"), index=True
    )
    image_tag: Mapped[str | None] = mapped_column(String(255))
    test_command: Mapped[str | None] = mapped_column(String(512))
    baseline: Mapped[dict] = mapped_column(JSONB, default=dict)
    patched: Mapped[dict] = mapped_column(JSONB, default=dict)
    tests_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    perf_delta_pct: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(16), default=Verdict.SKIPPED, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)

    patch: Mapped[Patch] = relationship(back_populates="validations")


class PullRequestRef(TimestampMixin, Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(512))
    branch: Mapped[str] = mapped_column(String(255))
    patch_ids: Mapped[list] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(24), default="open")


class JiraTicket(TimestampMixin, Base):
    __tablename__ = "jira_tickets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True, unique=True
    )
    issue_key: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(64), default="To Do")


# --------------------------------------------------------------------------
# Durable job queue (Postgres-backed, SKIP LOCKED)
# --------------------------------------------------------------------------
class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "Base", "Repository", "Analysis", "AnalysisStatus", "SourceFile", "Symbol",
    "CallEdge", "DependencyEdge", "CodeChunk", "Finding", "FindingStatus",
    "Category", "Severity", "Patch", "PatchStatus", "ValidationRun", "Verdict",
    "PullRequestRef", "JiraTicket", "Job", "JobStatus", "JSON",
]
