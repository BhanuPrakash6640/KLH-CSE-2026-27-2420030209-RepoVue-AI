"""The API surface the web client is written against.

These run against the generated OpenAPI document, so they need no database,
API key or Docker — but they still fail loudly if an endpoint or a field the
frontend reads is renamed or dropped.
"""
from __future__ import annotations

import pytest

from app.main import app


@pytest.fixture(scope="module")
def schema() -> dict:
    return app.openapi()


def _properties(schema: dict, name: str) -> dict:
    return schema["components"]["schemas"][name]["properties"]


class TestRoutes:
    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/v1/health", "get"),
            ("/api/v1/metrics", "get"),
            ("/api/v1/repositories", "get"),
            ("/api/v1/repositories", "post"),
            ("/api/v1/repositories/overview", "get"),
            ("/api/v1/repositories/{repository_id}", "get"),
            ("/api/v1/analyses", "get"),
            ("/api/v1/analyses", "post"),
            ("/api/v1/analyses/{analysis_id}", "get"),
            ("/api/v1/analyses/{analysis_id}", "delete"),
            ("/api/v1/analyses/{analysis_id}/summary", "get"),
            ("/api/v1/analyses/{analysis_id}/files", "get"),
            ("/api/v1/analyses/{analysis_id}/graph", "get"),
            ("/api/v1/analyses/{analysis_id}/gate", "get"),
            ("/api/v1/findings", "get"),
            ("/api/v1/findings/{finding_id}", "get"),
            ("/api/v1/findings/{finding_id}", "patch"),
            ("/api/v1/findings/{finding_id}/jira", "get"),
            ("/api/v1/patches", "get"),
            ("/api/v1/patches/{patch_id}", "get"),
            ("/api/v1/patches/{patch_id}/validations", "get"),
            ("/api/v1/patches/{patch_id}/decision", "post"),
            ("/api/v1/search", "post"),
            ("/api/v1/chat", "post"),
            ("/api/v1/webhooks/github", "post"),
        ],
    )
    def test_endpoint_is_published(self, schema, path, method):
        assert method in schema["paths"].get(path, {}), f"{method.upper()} {path} is missing"

    def test_gate_is_declared_once(self, schema):
        """It lived in two modules at one point; CI polls it, so keep it single."""
        gates = [p for p in schema["paths"] if p.endswith("/gate")]
        assert gates == ["/api/v1/analyses/{analysis_id}/gate"]

    def test_literal_overview_path_precedes_the_uuid_route(self):
        """FastAPI matches in declaration order: `/repositories/overview` must be
        registered before `/repositories/{repository_id}` or it is swallowed."""
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert paths.index("/api/v1/repositories/overview") < paths.index(
            "/api/v1/repositories/{repository_id}"
        )


class TestResponseShapes:
    def test_analysis_carries_its_repository_name(self, schema):
        props = _properties(schema, "AnalysisOut")
        assert "repository_full_name" in props
        for field in ("status", "stage", "progress", "error", "stats"):
            assert field in props

    def test_finding_carries_triage_evidence_and_model(self, schema):
        props = _properties(schema, "FindingOut")
        for field in ("evidence", "model", "confidence", "snippet", "cwe", "owasp"):
            assert field in props

    def test_patch_links_back_to_its_analysis(self, schema):
        props = _properties(schema, "PatchOut")
        for field in ("analysis_id", "finding_id", "diff", "explanation", "risk_notes"):
            assert field in props

    def test_validation_reports_how_it_was_run(self, schema):
        props = _properties(schema, "ValidationOut")
        for field in ("image_tag", "test_command", "verdict", "perf_delta_pct", "baseline", "patched"):
            assert field in props

    def test_gate_answers_both_questions_ci_asks(self, schema):
        props = _properties(schema, "QualityGate")
        # "should I keep waiting" and "should I fail the build"
        assert "complete" in props
        assert "passed" in props
        assert "blocking_findings" in props

    def test_overview_row_has_what_the_table_renders(self, schema):
        props = _properties(schema, "RepositoryOverview")
        for field in ("repository", "last_analysis", "findings", "patched", "validated"):
            assert field in props

    def test_chat_response_structure(self, schema):
        props = _properties(schema, "ChatResponse")
        for field in ("response", "suggested_questions", "referenced_findings", "provider"):
            assert field in props
