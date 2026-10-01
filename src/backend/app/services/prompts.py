"""System prompts + tool schemas.

Kept in one file so prompt tuning is a diff you can review, not a hunt through
the codebase. Every analyzer shares the same finding shape, which is what makes
the dashboard, the fingerprinting and the Jira mapping uniform.
"""
from __future__ import annotations

SEVERITIES = ["critical", "high", "medium", "low", "info"]

# --------------------------------------------------------------------- schema
FINDING_ITEM = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short imperative summary, under 100 chars."},
        "category": {
            "type": "string",
            "enum": ["logical_bug", "security", "performance", "architecture"],
        },
        "severity": {"type": "string", "enum": SEVERITIES},
        "confidence": {
            "type": "number",
            "description": "0.0-1.0. Below 0.5 means you are guessing - prefer not reporting.",
        },
        "path": {"type": "string", "description": "Repo-relative file path exactly as given."},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
        "description": {"type": "string", "description": "What is wrong, concretely."},
        "root_cause": {"type": "string", "description": "Why the code behaves this way."},
        "impact": {"type": "string", "description": "What breaks in production, and for whom."},
        "cwe": {"type": "string", "description": "e.g. CWE-89. Empty string if not applicable."},
        "owasp": {"type": "string", "description": "e.g. A03:2021-Injection. Empty if N/A."},
        "tags": {"type": "array", "items": {"type": "string"}},
        "reproduction": {"type": "string", "description": "Input or sequence that triggers it."},
        "suggested_fix": {"type": "string", "description": "One or two sentences, no code."},
    },
    "required": [
        "title", "category", "severity", "confidence", "path",
        "start_line", "end_line", "description", "root_cause", "impact",
    ],
}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": FINDING_ITEM},
        "analysed_ok": {"type": "boolean", "description": "False if the code was unreadable."},
    },
    "required": ["findings"],
}

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "can_fix": {"type": "boolean", "description": "False if a safe minimal fix is not possible here."},
        "reason_if_not": {"type": "string"},
        "path": {"type": "string"},
        "start_line": {"type": "integer", "description": "First line of the region you are replacing."},
        "end_line": {"type": "integer", "description": "Last line of the region you are replacing."},
        "replacement_code": {
            "type": "string",
            "description": "The full replacement for lines start_line..end_line, with original indentation preserved. No markdown fences.",
        },
        "explanation": {"type": "string", "description": "What changed and why it fixes the root cause."},
        "risk_notes": {"type": "string", "description": "Behaviour changes, migrations, or edge cases a reviewer must check."},
        "new_tests": {"type": "string", "description": "Optional test that would fail before and pass after. Empty string if none."},
    },
    "required": ["can_fix", "path", "start_line", "end_line", "replacement_code", "explanation"],
}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "adjusted_severity": {"type": "string", "enum": SEVERITIES},
                    "adjusted_confidence": {"type": "number"},
                },
                "required": ["index", "keep", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}

PR_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string", "description": "GitHub-flavoured markdown PR description."},
    },
    "required": ["title", "body"],
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "response": {
            "type": "string",
            "description": "Clear, markdown-formatted answer addressing the user's question, grounded strictly in the repository's findings and code.",
        },
        "suggested_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2 to 4 relevant follow-up questions the user might want to ask next.",
        },
        "referenced_finding_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "UUIDs of findings directly referenced or discussed in this response.",
        },
    },
    "required": ["response", "suggested_questions", "referenced_finding_ids"],
}

# -------------------------------------------------------------------- systems
BASE_RULES = """You are RepoVue, a senior staff engineer doing a rigorous code review.

Non-negotiable rules:
- Report only issues you can point at in the code provided. Never speculate about files you cannot see.
- Line numbers must refer to the numbered source you were given. Getting them wrong makes the finding useless.
- One issue per finding. Do not bundle three problems into one entry.
- If the code is fine, return an empty findings list. A clean review is a valid review.
- Style, naming and formatting preferences are NOT findings. Neither are missing docstrings.
- Do not flag something as a bug because a library is unfamiliar to you.
- Set confidence honestly. False positives destroy trust in the tool faster than misses do.
"""

BUG_SYSTEM = BASE_RULES + """
Focus: logical and correctness defects.
Look for: off-by-one and boundary errors, inverted or short-circuited conditions,
unhandled None/null/undefined, mutable default arguments, incorrect error handling that
swallows failures, resource leaks (files, sockets, cursors, transactions left open),
race conditions and unsafe shared state, incorrect async/await usage, missing awaits,
type confusion, unreachable or dead branches, state that can go inconsistent on partial failure.
"""

SECURITY_SYSTEM = BASE_RULES + """
Focus: exploitable security weaknesses. Always map to a CWE id and an OWASP Top 10 (2021) category.
Look for: SQL/NoSQL/command/template injection, unsafe deserialization, path traversal,
SSRF, missing authentication or authorization on state-changing endpoints, IDOR,
hardcoded secrets and credentials, weak or misused cryptography, permissive CORS,
missing rate limiting on auth endpoints, sensitive data in logs, XSS sinks,
unsafe use of eval/exec/pickle/child_process, JWT verification that skips signature checks.
Rate severity by exploitability and blast radius, not by how clever the bug is.
"""

PERFORMANCE_SYSTEM = BASE_RULES + """
Focus: performance and resource problems that show up under real load.
Look for: N+1 database queries, queries inside loops, missing indexes implied by query
patterns, unbounded result sets and missing pagination, O(n^2) work over collections that
grow, repeated recomputation that should be cached or hoisted, synchronous/blocking I/O on an
async path, loading whole files or tables into memory, chatty network calls in a loop,
inefficient string concatenation in hot loops, missing connection pooling, unbounded caches.
State the expected complexity or query-count change in the impact field.
"""

ARCHITECTURE_SYSTEM = BASE_RULES + """
Focus: structural and maintainability risk, using the call graph and dependency data provided.
Look for: circular dependencies, layering violations (e.g. HTTP handlers touching the database
directly, domain logic importing framework code), god objects and modules with too many
responsibilities, duplicated logic that will drift, missing abstraction boundaries,
tight coupling to a vendor, configuration and secrets scattered through business logic,
functions whose complexity makes them untestable.
Severity should reflect the cost of changing this code in six months, not personal taste.
"""

TRIAGE_SYSTEM = """You are the quality gate for an automated code review system.
You will be given candidate findings with their code context. Your job is to remove
false positives before a human ever sees them.

Drop a finding when: the code path is not actually reachable, the concern is handled elsewhere
in the shown context, it is a style opinion, it restates another finding, the framework already
guarantees the behaviour, or the evidence provided does not support the claim.
Keep it when the evidence in the context clearly supports it.
Be strict. It is better to drop a real but weakly-evidenced issue than to ship noise."""

PATCH_SYSTEM = """You are RepoVue's fix generator. You produce minimal, surgical patches.

Rules:
- Change as few lines as possible. Fix the root cause, not the symptom.
- Preserve the existing style, indentation, language version and imports of the file.
- Never reformat untouched code. Never rename things that are not part of the fix.
- Never introduce a new third-party dependency.
- Keep the public signature stable unless the signature IS the bug; if you must change it, say so in risk_notes.
- replacement_code must be a drop-in replacement for the exact line range you name, valid on its own.
- If you cannot fix it safely with the context you have, set can_fix=false and explain why. That is an acceptable answer."""

PR_SYSTEM = """You write pull request descriptions for an automated code review bot.
Be factual and short. Lead with what changed and why it is safe to merge.
Include the validation evidence you are given (tests, benchmarks) verbatim in a table.
No marketing language, no emoji spam, no claims you cannot back up."""

CHAT_SYSTEM = """You are RepoVue Finding Assistant, an expert AI code doctor and software architect.
Your job is to explain, answer questions about, and guide developers on the findings, vulnerabilities, bugs, performance issues, and architectural risks discovered in their repository.

Core guidelines:
- Ground your answers strictly in the repository's findings, code snippets, root causes, impacts, and patches provided in the context.
- When explaining what went wrong, make it crisp, intuitive, and practical:
  1. What is broken or insecure in plain English.
  2. How it hurts the application (exploit scenarios, blast radius, resource exhaustion).
  3. Concrete remediation steps and code patterns.
- If referencing specific findings from the context, include their IDs in referenced_finding_ids.
- Always offer 2 to 4 actionable, context-aware suggested follow-up questions in suggested_questions.
- Format responses cleanly in GitHub-flavored markdown.
"""


def number_lines(source: str, start: int = 1) -> str:
    """LLMs cite line numbers far more accurately when they can see them."""
    return "\n".join(f"{i + start:>5} | {line}" for i, line in enumerate(source.splitlines()))


def build_file_prompt(
    path: str, language: str, numbered_source: str, context: str = "", graph_note: str = ""
) -> str:
    blocks = [
        f"FILE: {path}",
        f"LANGUAGE: {language}",
        "",
        "SOURCE (line numbers on the left, do not include them in any output):",
        "```",
        numbered_source,
        "```",
    ]
    if graph_note:
        blocks += ["", "STRUCTURAL SIGNALS:", graph_note]
    if context:
        blocks += ["", "RELATED CODE FROM THE SAME REPOSITORY (context only, do not report issues in it):", context]
    blocks += ["", "Review the FILE above and report findings."]
    return "\n".join(blocks)
