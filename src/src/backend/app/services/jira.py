"""Jira ticketing for confirmed findings.

Only findings that survive triage AND meet the severity floor become tickets —
otherwise you hand the team a backlog nobody trusts. Tickets are keyed by
finding fingerprint so re-analysing the same repo never duplicates them.
"""
from __future__ import annotations

import base64

import httpx

from app.config import settings
from app.db.models import Severity
from app.logging_config import get_logger

log = get_logger(__name__)

SEVERITY_TO_PRIORITY = {
    "critical": "Highest", "high": "High", "medium": "Medium", "low": "Low", "info": "Lowest",
}


def _adf(text: str) -> dict:
    """Jira Cloud v3 wants Atlassian Document Format, not markdown."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p[:3000]}]}
            for p in paragraphs
        ] or [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}],
    }


class JiraClient:
    def __init__(self) -> None:
        self.enabled = bool(
            settings.JIRA_ENABLED and settings.JIRA_BASE_URL
            and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN
        )
        if self.enabled:
            token = base64.b64encode(
                f"{settings.JIRA_EMAIL}:{settings.JIRA_API_TOKEN}".encode()
            ).decode()
            self._client = httpx.AsyncClient(
                base_url=settings.JIRA_BASE_URL.rstrip("/"),
                timeout=30,
                headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
            )

    async def aclose(self) -> None:
        if self.enabled:
            await self._client.aclose()

    def meets_threshold(self, severity: str) -> bool:
        floor = Severity.ORDER.get(settings.JIRA_MIN_SEVERITY, 3)
        return Severity.ORDER.get(severity, 0) >= floor

    async def find_by_fingerprint(self, fingerprint: str) -> dict | None:
        if not self.enabled:
            return None
        jql = f'project = "{settings.JIRA_PROJECT_KEY}" AND description ~ "{fingerprint}"'
        r = await self._client.post(
            "/rest/api/3/search", json={"jql": jql, "maxResults": 1, "fields": ["key", "status"]}
        )
        if r.status_code >= 400:
            return None
        issues = r.json().get("issues", [])
        return issues[0] if issues else None

    async def create_issue(self, finding: dict, repo_full_name: str, links: dict) -> dict | None:
        if not self.enabled:
            return None
        if not self.meets_threshold(finding["severity"]):
            return None

        existing = await self.find_by_fingerprint(finding["fingerprint"])
        if existing:
            log.info("jira_ticket_exists", key=existing["key"])
            return {
                "key": existing["key"],
                "url": f"{settings.JIRA_BASE_URL.rstrip('/')}/browse/{existing['key']}",
                "existing": True,
            }

        description = "\n\n".join(
            filter(None, [
                finding.get("description", ""),
                f"Root cause: {finding.get('root_cause', 'n/a')}",
                f"Impact: {finding.get('impact', 'n/a')}",
                f"Location: {finding['path']}:{finding['start_line']}-{finding['end_line']}",
                f"Classification: {finding.get('cwe') or 'n/a'} / {finding.get('owasp') or 'n/a'}",
                f"Repository: {repo_full_name}",
                f"RepoVue report: {links.get('analysis_url', '')}",
                f"Fix PR: {links.get('pr_url', 'not generated')}",
                f"RepoVue fingerprint: {finding['fingerprint']}",
            ])
        )

        payload = {
            "fields": {
                "project": {"key": settings.JIRA_PROJECT_KEY},
                "issuetype": {"name": settings.JIRA_ISSUE_TYPE},
                "summary": f"[RepoVue] {finding['title']}"[:250],
                "description": _adf(description),
                "labels": ["repovue", finding["category"], finding["severity"]],
            }
        }
        r = await self._client.post("/rest/api/3/issue", json=payload)
        if r.status_code >= 400:
            log.error("jira_create_failed", status=r.status_code, body=r.text[:300])
            return None
        data = r.json()
        return {
            "key": data["key"],
            "url": f"{settings.JIRA_BASE_URL.rstrip('/')}/browse/{data['key']}",
            "existing": False,
        }

    async def add_remote_link(self, issue_key: str, url: str, title: str) -> None:
        if not self.enabled:
            return
        await self._client.post(
            f"/rest/api/3/issue/{issue_key}/remotelink",
            json={"object": {"url": url, "title": title}},
        )
