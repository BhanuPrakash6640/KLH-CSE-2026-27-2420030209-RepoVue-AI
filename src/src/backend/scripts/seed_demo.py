"""Seed representative capstone project data into the database.

Matches the scenario in the Capstone Abstract:
- Repository: acme/paper-service
- Finding: N+1 query in PaperService.java at line 142 costing roughly 420ms
- Patch: Batch fetch replacement yielding validated 38% improvement
- Quality Gate: Passed
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from app.db.session import session_scope
from app.db.models import (
    Repository,
    Analysis,
    AnalysisStatus,
    Finding,
    FindingStatus,
    Patch,
    PatchStatus,
    ValidationRun,
    Verdict,
    Severity,
    SourceFile,
    Symbol,
)
from app.logging_config import configure_logging, get_logger

log = get_logger(__name__)

JAVA_ORIGINAL = '''    @Transactional(readOnly = true)
    public List<PaperDto> getRecentPapers(Long conferenceId) {
        List<Paper> papers = paperRepository.findByConferenceId(conferenceId);
        List<PaperDto> result = new ArrayList<>();
        for (Paper paper : papers) {
            // N+1 query: fetching author on each iteration
            Author author = authorRepository.findById(paper.getAuthorId())
                .orElse(Author.anonymous());
            result.add(new PaperDto(paper, author));
        }
        return result;
    }
'''

JAVA_PATCHED = '''    @Transactional(readOnly = true)
    public List<PaperDto> getRecentPapers(Long conferenceId) {
        List<Paper> papers = paperRepository.findByConferenceIdWithAuthors(conferenceId);
        return papers.stream()
            .map(p -> new PaperDto(p, p.getAuthor()))
            .collect(Collectors.toList());
    }
'''

DIFF_TEXT = """--- a/src/main/java/com/repovue/service/PaperService.java
+++ b/src/main/java/com/repovue/service/PaperService.java
@@ -142,9 +142,4 @@
-        List<Paper> papers = paperRepository.findByConferenceId(conferenceId);
-        List<PaperDto> result = new ArrayList<>();
-        for (Paper paper : papers) {
-            // N+1 query: fetching author on each iteration
-            Author author = authorRepository.findById(paper.getAuthorId())
-                .orElse(Author.anonymous());
-            result.add(new PaperDto(paper, author));
-        }
-        return result;
+        List<Paper> papers = paperRepository.findByConferenceIdWithAuthors(conferenceId);
+        return papers.stream()
+            .map(p -> new PaperDto(p, p.getAuthor()))
+            .collect(Collectors.toList());
"""


async def seed() -> None:
    configure_logging()
    async with session_scope() as session:
        # 1. Repository
        full_name = "acme/paper-service"
        existing_repo = (
            await session.execute(select(Repository).where(Repository.full_name == full_name))
        ).scalar_one_or_none()

        if existing_repo:
            log.info("repository_already_exists", repo=full_name)
            repo = existing_repo
        else:
            repo = Repository(
                full_name=full_name,
                provider="github",
                default_branch="main",
                clone_url="https://github.com/acme/paper-service.git",
                is_private=False,
            )
            session.add(repo)
            await session.flush()
            log.info("repository_created", id=str(repo.id))

        # 2. Analysis
        analysis = Analysis(
            repository_id=repo.id,
            commit_sha="a7b3c94d12ef88019ab234cde567890123456789",
            branch="main",
            status=AnalysisStatus.SUCCEEDED,
            stage="completed",
            progress=100,
            stats={
                "files_analyzed": 48,
                "total_loc": 6420,
                "symbols_indexed": 312,
                "findings_count": 3,
                "patches_generated": 1,
                "patches_validated": 1,
                "llm_model": "gemini-2.5-flash",
            },
        )
        session.add(analysis)
        await session.flush()

        # 3. Source File & Symbol
        source_file = SourceFile(
            analysis_id=analysis.id,
            path="src/main/java/com/repovue/service/PaperService.java",
            language="java",
            size_bytes=4820,
            loc=210,
        )
        session.add(source_file)
        await session.flush()

        symbol = Symbol(
            analysis_id=analysis.id,
            file_id=source_file.id,
            path=source_file.path,
            name="getRecentPapers",
            qualified_name="com.repovue.service.PaperService.getRecentPapers",
            kind="method",
            signature="public List<PaperDto> getRecentPapers(Long conferenceId)",
            start_line=138,
            end_line=155,
            complexity=4,
        )
        session.add(symbol)

        # 4. Finding 1 (The representative N+1 query from the abstract)
        f1 = Finding(
            analysis_id=analysis.id,
            fingerprint=uuid.uuid4().hex[:32],
            category="performance",
            severity=Severity.HIGH,
            confidence=0.96,
            title="N+1 database query in PaperService.java loading authors in loop",
            description=(
                "Executing individual findById queries for each paper inside a loop causes "
                "an N+1 query problem, increasing response time proportionally to the number of records."
            ),
            root_cause=(
                "The loop in getRecentPapers() calls authorRepository.findById(paper.getAuthorId()) "
                "for each Paper in the result list rather than performing a single batch JOIN or IN query."
            ),
            impact="Roughly 420 milliseconds per request under 50 records, degrading exponentially with dataset size.",
            path="src/main/java/com/repovue/service/PaperService.java",
            start_line=142,
            end_line=152,
            snippet=JAVA_ORIGINAL,
            cwe="CWE-1050",
            owasp="A04:2021-Insecure Design",
            status=FindingStatus.VALIDATED,
            model="gemini-2.5-flash",
            tags=["n+1", "database", "latency", "spring-data"],
            evidence={
                "measured_cost_ms": 420,
                "improvement_pct": 38.0,
                "query_count_before": 51,
                "query_count_after": 1,
            },
        )
        session.add(f1)

        # Finding 2 (Security - OWASP Top 10)
        f2 = Finding(
            analysis_id=analysis.id,
            fingerprint=uuid.uuid4().hex[:32],
            category="security",
            severity=Severity.CRITICAL,
            confidence=0.94,
            title="SQL Injection vulnerability in custom query string concatenation",
            description="Dynamic SQL query built via string concatenation allows malicious input execution.",
            root_cause="Parameter conferenceId is directly interpolated into raw SQL query without parameter binding.",
            impact="Full unauthorized read and write access to the relational database.",
            path="src/main/java/com/repovue/repository/CustomPaperRepository.java",
            start_line=64,
            end_line=72,
            snippet='String sql = "SELECT * FROM papers WHERE title LIKE \'%" + search + "%\'";',
            cwe="CWE-89",
            owasp="A03:2021-Injection",
            status=FindingStatus.OPEN,
            model="gemini-2.5-flash",
            tags=["sql-injection", "security", "owasp-top-10"],
        )
        session.add(f2)

        # Finding 3 (Architecture - tight coupling / circular dependency)
        f3 = Finding(
            analysis_id=analysis.id,
            fingerprint=uuid.uuid4().hex[:32],
            category="architecture",
            severity=Severity.MEDIUM,
            confidence=0.88,
            title="Bidirectional circular dependency between PaperService and ReviewService",
            description="PaperService injects ReviewService while ReviewService injects PaperService, causing tight coupling.",
            root_cause="Cross-service callbacks bypass domain boundary encapsulation.",
            impact="Prevents independent modular testing and risks startup failure.",
            path="src/main/java/com/repovue/service/PaperService.java",
            start_line=34,
            end_line=40,
            snippet="@Autowired\nprivate ReviewService reviewService;",
            cwe="CWE-1061",
            owasp="",
            status=FindingStatus.OPEN,
            model="gemini-2.5-flash",
            tags=["circular-dependency", "tight-coupling", "clean-architecture"],
        )
        session.add(f3)
        await session.flush()

        # 5. Patch for Finding 1
        patch = Patch(
            analysis_id=analysis.id,
            finding_id=f1.id,
            path=f1.path,
            diff=DIFF_TEXT,
            original_code=JAVA_ORIGINAL,
            patched_code=JAVA_PATCHED,
            explanation=(
                "Replaced iterative findById queries with a single batch fetch query "
                "(findByConferenceIdWithAuthors) utilizing a JOIN FETCH, reducing database roundtrips from 51 to 1."
            ),
            risk_notes="Low risk: query semantics preserved, verified against integration test suite.",
            status=PatchStatus.ACCEPTED,
            model="gemini-2.5-flash",
        )
        session.add(patch)
        await session.flush()

        # 6. Validation Run (Pass with 38% verified improvement)
        val = ValidationRun(
            patch_id=patch.id,
            image_tag="repovue-sandbox:openjdk-17",
            test_command="mvn test -Dtest=PaperServiceBenchmarkTest",
            baseline={"duration_ms": 420.5, "throughput_rps": 118, "queries": 51},
            patched={"duration_ms": 260.7, "throughput_rps": 189, "queries": 1},
            tests_passed=True,
            perf_delta_pct=-38.0,
            verdict=Verdict.PASS,
            reason="All 16 tests passed. Latency improved by 38.0% (420ms -> 260ms).",
            logs="[INFO] Tests run: 16, Failures: 0, Errors: 0, Skipped: 0\n[BENCHMARK] Baseline: 420.5ms | Patched: 260.7ms | Delta: -38.0%\n[INFO] BUILD SUCCESS",
        )
        session.add(val)
        await session.commit()
        log.info("seed_complete", analysis_id=str(analysis.id), finding_id=str(f1.id))
        print(f"\n--- DEMO DATA SEEDED SUCCESSFULLY ---")
        print(f"Repository: {full_name}")
        print(f"Analysis ID: {analysis.id}")
        print(f"Finding: {f1.title}")
        print(f"Improvement: 38% validated")


if __name__ == "__main__":
    asyncio.run(seed())
