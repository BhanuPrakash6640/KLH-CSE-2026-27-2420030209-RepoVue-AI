"""Tests for RepoVue XGBoost Silent ML Fallback System.

Verifies that when external cloud LLM APIs are unavailable or fail,
the trained XGBoost models seamlessly produce valid findings, triage verdicts,
and patches without raising errors or interrupting user workflows.
"""
from __future__ import annotations

import pytest
from app.services.llm import LLMClient
from app.services.ml_backup.features import CodeFeatureExtractor, extract_structural_features
from app.services.ml_backup.inference import get_backup_engine
from app.services.ml_backup.model import FallbackMLBundle
from app.services import prompts as P


def test_structural_feature_extraction():
    code = """def fetch_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return db.execute(query)
"""
    feats = extract_structural_features(code)
    assert len(feats) == 24
    # Check that SQL indicator or security hits are flagged
    assert feats[8] > 0 or feats[22] > 0  # sec_hits or 'SELECT'


def test_feature_extractor_tfidf():
    extractor = CodeFeatureExtractor(max_tfidf_features=16)
    samples = [
        "def query(x): return db.execute(f'SELECT {x}')",
        "def clean_func(a, b): return a + b",
    ]
    mat = extractor.fit_transform(samples)
    assert mat.shape[0] == 2
    assert mat.shape[1] == 24 + 16


def test_trained_xgboost_bundle_inference():
    engine = get_backup_engine()
    bundle = engine.bundle
    assert bundle.is_ready is True

    # Test security sample
    sec_code = "def run(cmd): subprocess.call(cmd, shell=True)"
    preds = bundle.predict([sec_code])
    assert len(preds) == 1
    pred = preds[0]
    assert pred["category"] in ("security", "logical_bug")
    assert pred["severity"] in ("high", "critical", "medium")
    assert 0.50 <= pred["confidence"] <= 0.99


@pytest.mark.asyncio
async def test_llm_client_silent_fallback_findings():
    client = LLMClient()
    # Force cloud clients to None to test pure offline fallback
    client._gemini_client = None
    client._anthropic_client = None

    prompt = """FILE: auth/login.py
LANGUAGE: python

SOURCE (line numbers on the left, do not include them in any output):
```
    1 | def execute_login(username, password):
    2 |     query = f"SELECT * FROM accounts WHERE user = '{username}'"
    3 |     return db.execute(query)
```
Review the FILE above and report findings."""

    result = await client.structured(
        system=P.SECURITY_SYSTEM,
        prompt=prompt,
        schema=P.FINDINGS_SCHEMA,
    )

    assert "findings" in result
    assert isinstance(result["findings"], list)
    assert len(result["findings"]) > 0

    first_finding = result["findings"][0]
    assert first_finding["path"] == "auth/login.py"
    assert first_finding["category"] == "security"
    assert first_finding["severity"] in ("high", "critical")
    assert "SELECT" in first_finding["title"] or "SQL" in first_finding["title"] or "parameterized" in first_finding["title"].lower()
    assert first_finding["start_line"] >= 1


@pytest.mark.asyncio
async def test_llm_client_silent_fallback_patches():
    client = LLMClient()
    client._gemini_client = None
    client._anthropic_client = None

    prompt = """FINDING TO FIX
category: security
severity: high
title: Enable TLS certificate verification
file: api/client.py
lines: 12-12
description: TLS certificate verification explicitly disabled
root cause: verify=False

FILE REGION (line numbers on the left; your start_line/end_line must come from this column):
```
   10 | def call_remote_api():
   11 |     url = "https://internal-service.local/api"
   12 |     return requests.get(url, verify=False)
```
Produce the minimal patch."""

    result = await client.structured(
        system=P.PATCH_SYSTEM,
        prompt=prompt,
        schema=P.PATCH_SCHEMA,
    )

    assert result["can_fix"] is True
    assert result["path"] == "api/client.py"
    assert result["start_line"] == 12
    assert "verify=True" in result["replacement_code"]
    assert "TLS" in result["explanation"]


@pytest.mark.asyncio
async def test_llm_client_silent_fallback_triage():
    client = LLMClient()
    client._gemini_client = None
    client._anthropic_client = None

    prompt = """[0] category=security severity=critical confidence=0.9
file=main.py:1-2
title=SQL Injection
why=String formatting in SQL

code:
```
cursor.execute(f"SELECT * FROM t WHERE id={id}")
```"""

    result = await client.structured(
        system=P.TRIAGE_SYSTEM,
        prompt=prompt,
        schema=P.TRIAGE_SCHEMA,
    )

    assert "verdicts" in result
    assert len(result["verdicts"]) == 1
    assert result["verdicts"][0]["keep"] is True


@pytest.mark.asyncio
async def test_llm_client_silent_fallback_chat():
    client = LLMClient()
    client._gemini_client = None
    client._anthropic_client = None

    prompt = """REPOSITORY: test/repo
FINDING ID: 12345678-1234-5678-1234-567812345678
TITLE: Parameterize SQL queries
SEVERITY: critical
CATEGORY: security
FILE: db.py
LINE: 15
ROOT CAUSE: Dynamic f-string string interpolation
IMPACT: Potential unauthorized data access
SUGGESTED FIX: Pass query parameters as placeholders

USER QUERY: How do I fix the SQL security vulnerabilities in this repo?
"""

    result = await client.structured(
        system=P.CHAT_SYSTEM,
        prompt=prompt,
        schema=P.CHAT_SCHEMA,
    )

    assert "response" in result
    assert len(result["response"]) > 20
    assert "suggested_questions" in result
    assert len(result["suggested_questions"]) >= 2
    assert "referenced_finding_ids" in result
    assert "12345678-1234-5678-1234-567812345678" in result["referenced_finding_ids"]
