"""Cheap deterministic detectors.

These run before the LLM for two reasons: they catch high-signal patterns for
free, and their hits are injected into the prompt as "suspicious regions" so
the model spends its attention where evidence already exists. Every rule hit is
still confirmed by the LLM before it becomes a finding, so a regex false
positive never reaches the user on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    severity: str
    title: str
    pattern: re.Pattern
    languages: tuple[str, ...]
    cwe: str = ""
    owasp: str = ""


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


PY = ("python",)
JS = ("javascript", "typescript", "tsx")
ANY = ()

RULES: list[Rule] = [
    Rule("SQL_FSTRING", "security", "critical", "SQL built with string interpolation",
         _r(r"(execute|executemany|raw|cursor\.execute)\s*\(\s*[f\"']"), PY, "CWE-89", "A03:2021-Injection"),
    Rule("SQL_CONCAT_JS", "security", "critical", "SQL built by concatenation",
         _r(r"(query|execute)\s*\(\s*[\"'`][^\"'`]*\+\s*"), JS, "CWE-89", "A03:2021-Injection"),
    Rule("EVAL_EXEC", "security", "high", "Dynamic code execution",
         _r(r"\b(eval|exec)\s*\("), ANY, "CWE-95", "A03:2021-Injection"),
    Rule("PICKLE_LOAD", "security", "high", "Unsafe deserialization",
         _r(r"\b(pickle|cPickle|dill|yaml)\.(load|loads)\s*\("), PY, "CWE-502", "A08:2021-Software and Data Integrity Failures"),
    Rule("SHELL_TRUE", "security", "high", "Shell command with shell=True",
         _r(r"subprocess\.\w+\([^)]*shell\s*=\s*True"), PY, "CWE-78", "A03:2021-Injection"),
    Rule("CHILD_EXEC", "security", "high", "Shell command from interpolated string",
         _r(r"child_process\.(exec|execSync)\s*\(\s*[`\"'][^`\"']*\$\{"), JS, "CWE-78", "A03:2021-Injection"),
    Rule("HARDCODED_SECRET", "security", "high", "Possible hardcoded credential",
         _r(r"(api[_-]?key|secret|password|passwd|token|private[_-]?key)\s*[:=]\s*[\"'][A-Za-z0-9_\-/+]{12,}[\"']"),
         ANY, "CWE-798", "A07:2021-Identification and Authentication Failures"),
    Rule("VERIFY_FALSE", "security", "high", "TLS verification disabled",
         _r(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false"), ANY, "CWE-295", "A02:2021-Cryptographic Failures"),
    Rule("WEAK_HASH", "security", "medium", "Weak hash for sensitive data",
         _r(r"\b(md5|sha1)\s*\("), ANY, "CWE-327", "A02:2021-Cryptographic Failures"),
    Rule("JWT_NO_VERIFY", "security", "critical", "JWT decoded without verification",
         _r(r"(verify\s*=\s*False|verify_signature\"?\s*:\s*False|jwt\.decode\([^)]*options\s*=\s*\{[^}]*verify)"),
         ANY, "CWE-347", "A02:2021-Cryptographic Failures"),
    Rule("CORS_WILDCARD", "security", "medium", "Permissive CORS policy",
         _r(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']|Access-Control-Allow-Origin[\"']?\s*[:,]\s*[\"']\*"),
         ANY, "CWE-942", "A05:2021-Security Misconfiguration"),
    Rule("PATH_TRAVERSAL", "security", "high", "User input joined into a filesystem path",
         _r(r"(os\.path\.join|open|readFile|path\.join)\s*\([^)]*(request|req\.|params|query|argv)"),
         ANY, "CWE-22", "A01:2021-Broken Access Control"),
    Rule("DEBUG_TRUE", "security", "medium", "Debug mode enabled",
         _r(r"DEBUG\s*=\s*True|debug\s*:\s*true|app\.run\([^)]*debug\s*=\s*True"), ANY,
         "CWE-489", "A05:2021-Security Misconfiguration"),

    Rule("MUTABLE_DEFAULT", "logical_bug", "medium", "Mutable default argument",
         _r(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|set\(\))"), PY, "CWE-1188", ""),
    Rule("BARE_EXCEPT", "logical_bug", "medium", "Exception swallowed silently",
         _r(r"except\s*(Exception)?\s*:\s*(#.*)?\n\s*(pass|continue)\b"), PY, "CWE-390", ""),
    Rule("EMPTY_CATCH", "logical_bug", "medium", "Empty catch block",
         _r(r"catch\s*\([^)]*\)\s*\{\s*\}"), JS, "CWE-390", ""),
    Rule("EQ_NAN", "logical_bug", "low", "Loose equality comparison",
         _r(r"[^=!]==[^=]"), JS, "", ""),
    Rule("MISSING_AWAIT", "logical_bug", "high", "Promise/coroutine likely not awaited",
         _r(r"^\s*(?!await|return|yield)\w[\w.]*\.(then|catch)\s*\(|^\s*\w+\s*=\s*async\s"), JS, "CWE-703", ""),

    Rule("QUERY_IN_LOOP", "performance", "high", "Database query inside a loop (N+1)",
         _r(r"(for|while)\b[^\n]{0,120}\n(?:[^\n]{0,200}\n){0,6}?[^\n]{0,120}(\.query\(|\.filter\(|\.get\(|SELECT\s|\.find\(|\.findOne\(|execute\()"),
         ANY, "CWE-1049", ""),
    Rule("AWAIT_IN_LOOP", "performance", "medium", "Sequential awaits inside a loop",
         _r(r"for\s*\([^)]*\)\s*\{[^}]{0,300}await\s"), JS, "", ""),
    Rule("SYNC_IO_ASYNC", "performance", "high", "Blocking call inside async function",
         _r(r"async\s+def[^\n]*\n(?:[^\n]*\n){0,25}?\s*(time\.sleep|requests\.(get|post)|open\()"), PY, "", ""),
    Rule("SELECT_STAR", "performance", "low", "Unbounded SELECT *",
         _r(r"SELECT\s+\*\s+FROM"), ANY, "", ""),
    Rule("STRING_CONCAT_LOOP", "performance", "low", "String concatenation in a loop",
         _r(r"for\b[^\n]{0,120}\n(?:[^\n]{0,160}\n){0,5}?[^\n]{0,120}\w+\s*\+=\s*[\"'f]"), ANY, "", ""),
]


@dataclass
class RuleHit:
    rule: Rule
    line: int
    snippet: str

    def as_note(self) -> str:
        return f"  L{self.line}: [{self.rule.id}] {self.rule.title} -> {self.snippet.strip()[:120]}"


def scan(source: str, language: str) -> list[RuleHit]:
    hits: list[RuleHit] = []
    lines = source.splitlines()
    for rule in RULES:
        if rule.languages and language not in rule.languages:
            continue
        for match in rule.pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            snippet = lines[line_no - 1] if line_no <= len(lines) else ""
            if snippet.lstrip().startswith(("#", "//", "*")):
                continue  # commented-out code is not a live vulnerability
            hits.append(RuleHit(rule, line_no, snippet))
            if len(hits) > 60:
                return hits
    return hits


def rule_index(source: str, language: str) -> dict[str, list[RuleHit]]:
    out: dict[str, list[RuleHit]] = {}
    for hit in scan(source, language):
        out.setdefault(hit.rule.category, []).append(hit)
    return out
