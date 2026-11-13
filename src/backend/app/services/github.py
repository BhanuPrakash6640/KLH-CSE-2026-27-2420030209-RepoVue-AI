"""GitHub integration: clone, push a fix branch, open a PR, leave inline
review comments and publish a check run (the quality gate)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)
API = "https://api.github.com"

SEVERITY_EMOJI = {
    "critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟦", "info": "⬜",
}


def parse_repo_url(url: str) -> tuple[str, str]:
    path = urlparse(url if "://" in url else f"https://{url}").path
    parts = [p for p in path.strip("/").removesuffix(".git").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"cannot parse owner/repo from {url!r}")
    return parts[0], parts[1]


def authed_clone_url(clone_url: str, token: str | None = None) -> str:
    token = token or settings.GITHUB_TOKEN
    if not token:
        return clone_url
    owner, repo = parse_repo_url(clone_url)
    return f"https://x-access-token:{quote(token)}@github.com/{owner}/{repo}.git"


def _run(args: list[str], cwd: str | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        timeout=timeout or settings.CLONE_TIMEOUT_SEC,
        env=env,
    )


async def clone_repository(
    clone_url: str, dest: str, ref: str | None = None, depth: int = 1
) -> tuple[str, str]:
    """Clone (shallow by default) and return (path, resolved commit sha).

    A specific sha needs a fetch after clone: you cannot `git clone --branch <sha>`.
    """
    dest_path = Path(dest)
    if dest_path.exists():
        shutil.rmtree(dest_path, ignore_errors=True)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    url = authed_clone_url(clone_url)
    args = ["git", "clone", "--depth", str(depth), "--no-tags", "--single-branch"]
    if ref and not _looks_like_sha(ref):
        args += ["--branch", ref]
    args += [url, str(dest_path)]

    proc = await asyncio.to_thread(_run, args)
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {proc.stderr[-500:]}")

    if ref and _looks_like_sha(ref):
        await asyncio.to_thread(_run, ["git", "fetch", "--depth", "1", "origin", ref], str(dest_path))
        checkout = await asyncio.to_thread(_run, ["git", "checkout", "-f", ref], str(dest_path))
        if checkout.returncode != 0:
            log.warning("checkout_sha_failed", ref=ref, error=checkout.stderr[-200:])

    head = await asyncio.to_thread(_run, ["git", "rev-parse", "HEAD"], str(dest_path))
    size_mb = sum(f.stat().st_size for f in dest_path.rglob("*") if f.is_file()) / 1e6
    if size_mb > settings.MAX_REPO_MB:
        shutil.rmtree(dest_path, ignore_errors=True)
        raise RuntimeError(f"repository is {size_mb:.0f} MB, limit is {settings.MAX_REPO_MB} MB")

    return str(dest_path), head.stdout.strip()


def _looks_like_sha(ref: str) -> bool:
    return len(ref) >= 7 and all(c in "0123456789abcdef" for c in ref.lower())


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or settings.GITHUB_TOKEN
        self._client = httpx.AsyncClient(
            base_url=API,
            timeout=30,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        r = await self._client.request(method, url, **kwargs)
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()
        return r

    async def get_repo(self, owner: str, repo: str) -> dict:
        r = await self._request("GET", f"/repos/{owner}/{repo}")
        r.raise_for_status()
        return r.json()

    async def pr_files(self, owner: str, repo: str, number: int) -> list[str]:
        files: list[str] = []
        page = 1
        while page <= 10:
            r = await self._request(
                "GET", f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if r.status_code != 200:
                break
            batch = r.json()
            files.extend(f["filename"] for f in batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    async def create_pull_request(
        self, owner: str, repo: str, *, head: str, base: str, title: str, body: str
    ) -> dict:
        r = await self._request(
            "POST", f"/repos/{owner}/{repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body, "maintainer_can_modify": True},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"create PR failed ({r.status_code}): {r.text[:400]}")
        return r.json()

    async def comment_on_pr(self, owner: str, repo: str, number: int, body: str) -> dict:
        r = await self._request(
            "POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body}
        )
        return r.json() if r.status_code < 400 else {"error": r.text[:300]}

    async def create_review(
        self, owner: str, repo: str, number: int, commit_sha: str, comments: list[dict], body: str
    ) -> dict:
        """Inline review comments. GitHub rejects the whole review if any single
        comment points at a line outside the diff, so we retry without the
        inline part rather than losing the review entirely."""
        payload = {
            "commit_id": commit_sha,
            "body": body,
            "event": "COMMENT",
            "comments": comments[:40],
        }
        r = await self._request("POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)
        if r.status_code >= 400:
            log.warning("inline_review_failed", status=r.status_code, detail=r.text[:200])
            return await self.comment_on_pr(owner, repo, number, body)
        return r.json()

    async def create_check_run(
        self, owner: str, repo: str, *, sha: str, name: str, conclusion: str,
        title: str, summary: str, text: str = "",
    ) -> dict:
        r = await self._request(
            "POST", f"/repos/{owner}/{repo}/check-runs",
            json={
                "name": name, "head_sha": sha, "status": "completed",
                "conclusion": conclusion,
                "output": {"title": title, "summary": summary[:65000], "text": text[:65000]},
            },
        )
        return r.json() if r.status_code < 400 else {"error": r.text[:300]}


async def push_branch(repo_root: str, branch: str, message: str, clone_url: str) -> bool:
    """Commit everything currently in the working tree onto a new branch."""
    steps = [
        ["git", "config", "user.name", settings.GITHUB_BOT_NAME],
        ["git", "config", "user.email", settings.GITHUB_BOT_EMAIL],
        ["git", "checkout", "-b", branch],
        ["git", "add", "-A"],
        ["git", "commit", "-m", message],
        ["git", "remote", "set-url", "origin", authed_clone_url(clone_url)],
        ["git", "push", "-u", "origin", branch],
    ]
    for step in steps:
        proc = await asyncio.to_thread(_run, step, repo_root)
        if proc.returncode != 0:
            log.error("git_step_failed", step=" ".join(step[:3]), error=proc.stderr[-300:])
            return False
    return True


def verify_webhook(body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256, constant time. Fails closed when a secret is configured."""
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        log.warning("webhook_secret_missing", note="accepting unsigned payload - dev only")
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ------------------------------------------------------------- PR rendering
def render_findings_comment(findings: list[dict], analysis_url: str, stats: dict) -> str:
    if not findings:
        return (
            "## RepoVue\n\nNo issues found in the analysed changes. "
            f"\n\n<sub>{stats.get('files_analysed', 0)} files reviewed · "
            f"[full report]({analysis_url})</sub>"
        )

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    header = " · ".join(
        f"{SEVERITY_EMOJI.get(s, '')} {counts[s]} {s}"
        for s in ("critical", "high", "medium", "low") if s in counts
    )

    rows = ["| | Severity | Issue | Location |", "|---|---|---|---|"]
    for f in findings[:25]:
        loc = f"`{f['path']}:{f['start_line']}`"
        cwe = f" ({f['cwe']})" if f.get("cwe") else ""
        rows.append(
            f"| {SEVERITY_EMOJI.get(f['severity'], '')} | {f['severity']} | {f['title']}{cwe} | {loc} |"
        )

    extra = f"\n\n<sub>{len(findings) - 25} more in the full report.</sub>" if len(findings) > 25 else ""
    return (
        f"## RepoVue analysis\n\n{header}\n\n"
        + "\n".join(rows)
        + extra
        + f"\n\n<sub>{stats.get('files_analysed', 0)} files · "
        f"{stats.get('symbols', 0)} symbols · [full report]({analysis_url})</sub>"
    )


def render_inline_comments(findings: list[dict]) -> list[dict]:
    out = []
    for f in findings:
        body = (
            f"**{SEVERITY_EMOJI.get(f['severity'], '')} {f['severity'].upper()}: {f['title']}**\n\n"
            f"{f['description']}\n\n"
            f"**Root cause:** {f.get('root_cause') or 'n/a'}\n\n"
            f"**Impact:** {f.get('impact') or 'n/a'}\n"
        )
        if f.get("cwe"):
            body += f"\n`{f['cwe']}`" + (f" · `{f['owasp']}`" if f.get("owasp") else "")
        out.append({"path": f["path"], "line": max(1, f["start_line"]), "side": "RIGHT", "body": body})
    return out


def render_pr_body(items: list[dict], analysis_url: str) -> str:
    lines = [
        "## Automated fixes from RepoVue",
        "",
        "Every patch below was applied in a container, with the project's own test suite run before and after.",
        "",
        "| Issue | Severity | File | Tests | Runtime |",
        "|---|---|---|---|---|",
    ]
    for it in items:
        delta = it.get("perf_delta_pct")
        perf = "—" if delta is None else (f"{delta:+.1f}%")
        tests = "✅ pass" if it.get("tests_passed") else "⚠️ n/a"
        lines.append(
            f"| {it['title']} | {it['severity']} | `{it['path']}` | {tests} | {perf} |"
        )
    lines += ["", "### What changed", ""]
    for it in items:
        lines.append(f"**`{it['path']}`** — {it.get('explanation', '')}")
        if it.get("risk_notes"):
            lines.append(f"> Review carefully: {it['risk_notes']}")
        lines.append("")
    lines.append(f"<sub>Generated by RepoVue · [full report]({analysis_url})</sub>")
    return "\n".join(lines)
