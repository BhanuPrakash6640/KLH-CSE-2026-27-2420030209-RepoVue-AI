"""Fix generation.

The model never writes the diff itself — LLM-authored unified diffs fail
`git apply` constantly (wrong hunk headers, wrong context). Instead the model
returns a replacement for an explicit line range; we splice it into the real
file, generate the diff with difflib, and verify it applies cleanly with
`git apply --check` before it ever reaches validation.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger
from app.services import prompts as P
from app.services.analyzers import RawFinding
from app.services.llm import get_llm

log = get_logger(__name__)


@dataclass
class GeneratedPatch:
    path: str
    diff: str
    original_code: str
    patched_code: str
    explanation: str
    risk_notes: str
    new_tests: str = ""
    applies_cleanly: bool = False


def _dedent_guard(original_block: str, replacement: str) -> str:
    """Models occasionally strip the leading indentation of the whole block.
    If the original was indented and the replacement is not, re-indent it."""
    orig_lines = [line for line in original_block.splitlines() if line.strip()]
    new_lines = [line for line in replacement.splitlines() if line.strip()]
    if not orig_lines or not new_lines:
        return replacement
    orig_indent = min(len(line) - len(line.lstrip()) for line in orig_lines)
    new_indent = min(len(line) - len(line.lstrip()) for line in new_lines)
    if orig_indent > new_indent:
        pad = " " * (orig_indent - new_indent)
        return "\n".join(pad + line if line.strip() else line for line in replacement.splitlines())
    return replacement


def _strip_fences(code: str) -> str:
    lines = code.splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def build_diff(path: str, original: str, patched: str, context: int = 3) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context,
    )
    body = "".join(diff)
    if not body:
        return ""
    header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    # difflib already emitted ---/+++ lines; keep only the git header
    body_lines = body.splitlines(keepends=True)
    body = "".join(body_lines[2:])
    return header + body


def verify_applies(repo_root: str, diff: str) -> tuple[bool, str]:
    """`git apply --check` in the real checkout: the only honest test."""
    if not diff.strip():
        return False, "empty diff"
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
        patch_file = fh.name
    try:
        proc = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn", patch_file],
            cwd=repo_root, capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0, (proc.stderr or proc.stdout).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return False, str(exc)
    finally:
        os.unlink(patch_file)


def apply_diff(repo_root: str, diff: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
        patch_file = fh.name
    try:
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
            cwd=repo_root, capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0, (proc.stderr or proc.stdout).strip()
    finally:
        os.unlink(patch_file)


async def generate_patch(
    *, finding: RawFinding, repo_root: str, context: str = ""
) -> GeneratedPatch | None:
    llm = get_llm()
    if not llm.enabled:
        return None

    file_path = Path(repo_root) / finding.path
    if not file_path.exists():
        log.warning("patch_target_missing", path=finding.path)
        return None
    original = file_path.read_text("utf-8", errors="ignore")
    lines = original.splitlines()

    window_start = max(1, finding.start_line - 25)
    window_end = min(len(lines), finding.end_line + 25)
    window = P.number_lines("\n".join(lines[window_start - 1 : window_end]), start=window_start)

    prompt = f"""FINDING TO FIX
category: {finding.category}
severity: {finding.severity}
title: {finding.title}
file: {finding.path}
lines: {finding.start_line}-{finding.end_line}
description: {finding.description}
root cause: {finding.root_cause}
impact: {finding.impact}
suggested direction: {finding.evidence.get('suggested_fix', '')}

FILE REGION (line numbers on the left; your start_line/end_line must come from this column):
```
{window}
```
{"RELATED CODE FOR REFERENCE:" + context if context else ""}

Produce the minimal patch. The region you replace must be inside {window_start}-{window_end}."""

    result = await llm.structured(
        system=P.PATCH_SYSTEM,
        prompt=prompt,
        schema=P.PATCH_SCHEMA,
        tool_name="propose_patch",
        tool_description="Propose a minimal fix for the finding.",
        temperature=0.0,
    )

    if not result.get("can_fix", False):
        log.info("patch_declined", title=finding.title[:80], reason=result.get("reason_if_not", "")[:160])
        return None

    start = max(1, min(int(result.get("start_line") or finding.start_line), len(lines)))
    end = max(start, min(int(result.get("end_line") or finding.end_line), len(lines)))
    if start < window_start or end > window_end:
        log.warning("patch_out_of_window", path=finding.path, start=start, end=end)
        return None

    original_block = "\n".join(lines[start - 1 : end])
    replacement = _dedent_guard(original_block, _strip_fences(result["replacement_code"]).rstrip("\n"))
    if replacement.strip() == original_block.strip():
        return None

    patched_lines = lines[: start - 1] + replacement.splitlines() + lines[end:]
    patched = "\n".join(patched_lines) + ("\n" if original.endswith("\n") else "")

    diff = build_diff(finding.path, original, patched)
    ok, err = await asyncio.get_running_loop().run_in_executor(
        None, verify_applies, repo_root, diff
    )
    if not ok:
        log.warning("patch_does_not_apply", path=finding.path, error=err[:200])

    return GeneratedPatch(
        path=finding.path,
        diff=diff,
        original_code=original_block,
        patched_code=replacement,
        explanation=result.get("explanation", ""),
        risk_notes=result.get("risk_notes", ""),
        new_tests=result.get("new_tests", ""),
        applies_cleanly=ok,
    )


def combine_diffs(diffs: list[str]) -> str:
    """Stack independent single-file diffs into one patch for the PR branch."""
    return "\n".join(d.rstrip("\n") for d in diffs if d.strip()) + "\n"


def diff_stats(diff: str) -> dict:
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    files = len({line.split(" b/")[-1] for line in diff.splitlines() if line.startswith("diff --git")})
    return {"files": files, "additions": added, "deletions": removed}


def changed_files(repo_root: str, base_ref: str, head_ref: str = "HEAD") -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
            cwd=repo_root, capture_output=True, text=True, timeout=settings.CLONE_TIMEOUT_SEC,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return []
