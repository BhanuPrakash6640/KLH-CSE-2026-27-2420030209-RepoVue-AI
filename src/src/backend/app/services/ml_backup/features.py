"""Feature extraction pipeline for code defect analysis using XGBoost.

Extracts AST metrics, complexity indicators, security markers, and token TF-IDF
features from source code.
"""
from __future__ import annotations

import math
import re
from typing import Any
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

SECURITY_PATTERNS = [
    re.compile(r"\b(eval|exec)\s*\(", re.IGNORECASE),
    re.compile(r"(execute|raw|cursor\.execute)\s*\(\s*[f\"']", re.IGNORECASE),
    re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True", re.IGNORECASE),
    re.compile(r"\b(pickle|cPickle|dill|yaml)\.(load|loads)\s*\(", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"']+[\"']", re.IGNORECASE),
    re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false", re.IGNORECASE),
    re.compile(r"\b(md5|sha1)\s*\(", re.IGNORECASE),
    re.compile(r"jwt\.decode\([^)]*verify\s*=\s*False", re.IGNORECASE),
    re.compile(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']", re.IGNORECASE),
]

BUG_PATTERNS = [
    re.compile(r"except\s*:\s*(pass|\.\.\.)", re.IGNORECASE),
    re.compile(r"except\s+Exception\s*:\s*(pass|\.\.\.)", re.IGNORECASE),
    re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}", re.IGNORECASE),
    re.compile(r"\b(NoneType|NullPointerException|undefined|NaN)\b", re.IGNORECASE),
    re.compile(r"while\s+True\s*:\s*(?!.*\bbreak\b)", re.DOTALL),
    re.compile(r"def\s+__init__\s*\([^)]*\)\s*:\s*(?!\s*self\.)", re.IGNORECASE),
    re.compile(r"(==\s*None|is\s+None\s*==\s*False)", re.IGNORECASE),
    re.compile(r"\bassert\s+", re.IGNORECASE),
]

PERF_PATTERNS = [
    re.compile(r"for\s+\w+\s+in\s+.*:\s*.*for\s+\w+\s+in\s+", re.DOTALL),
    re.compile(r"time\.sleep\s*\(", re.IGNORECASE),
    re.compile(r"\.all\(\)\s*\[", re.IGNORECASE),
    re.compile(r"SELECT\s+\*\s+FROM", re.IGNORECASE),
    re.compile(r"range\s*\(\s*len\s*\(", re.IGNORECASE),
    re.compile(r"(\.append\(|\+\=)\s*.*in\s+loop", re.IGNORECASE),
    re.compile(r"async\s+def.*time\.sleep", re.IGNORECASE),
]

ARCH_PATTERNS = [
    re.compile(r"\bglobal\s+\w+", re.IGNORECASE),
    re.compile(r"from\s+\w+\s+import\s+\*", re.IGNORECASE),
    re.compile(r"\bTODO\b|\bFIXME\b|\bHACK\b|\bXXX\b", re.IGNORECASE),
    re.compile(r"class\s+\w+.*:\s*(?:.*\n){300,}", re.IGNORECASE),
    re.compile(r"import\s+os\s*;\s*import\s+sys", re.IGNORECASE),
]

CONTROL_FLOW_PATTERN = re.compile(
    r"\b(if|elif|else|for|while|try|except|catch|finally|switch|case|break|continue|return|throw|yield|async|await)\b",
    re.IGNORECASE,
)


def calculate_entropy(text: str) -> float:
    """Shannon entropy of characters in text."""
    if not text:
        return 0.0
    freqs: dict[str, int] = {}
    for c in text:
        freqs[c] = freqs.get(c, 0) + 1
    total = len(text)
    return -sum((count / total) * math.log2(count / total) for count in freqs.values())


def extract_structural_features(code: str) -> np.ndarray:
    """Extract 24 dense AST & metric features from code."""
    lines = code.splitlines()
    loc = len(lines)
    non_empty = [l for l in lines if l.strip()]
    non_empty_count = len(non_empty) or 1
    total_chars = len(code)
    avg_line_len = total_chars / non_empty_count

    max_indent = 0
    comment_lines = 0
    for l in lines:
        stripped = l.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            comment_lines += 1
        indent = len(l) - len(l.lstrip())
        if indent > max_indent:
            max_indent = indent

    blank_ratio = (loc - non_empty_count) / max(loc, 1)
    comment_ratio = comment_lines / max(loc, 1)

    control_flow_count = len(CONTROL_FLOW_PATTERN.findall(code))
    cyclomatic_est = 1 + control_flow_count

    sec_hits = sum(len(p.findall(code)) for p in SECURITY_PATTERNS)
    bug_hits = sum(len(p.findall(code)) for p in BUG_PATTERNS)
    perf_hits = sum(len(p.findall(code)) for p in PERF_PATTERNS)
    arch_hits = sum(len(p.findall(code)) for p in ARCH_PATTERNS)

    entropy = calculate_entropy(code)
    symbol_count = len(re.findall(r"[{}\[\](),;:=<>!+\-*/&|%^~]", code))
    symbol_density = symbol_count / max(total_chars, 1)

    features = [
        float(loc),
        float(non_empty_count),
        float(total_chars),
        float(avg_line_len),
        float(max_indent),
        float(blank_ratio),
        float(comment_ratio),
        float(cyclomatic_est),
        float(sec_hits),
        float(bug_hits),
        float(perf_hits),
        float(arch_hits),
        float(entropy),
        float(symbol_density),
        float(control_flow_count),
        float(sec_hits > 0),
        float(bug_hits > 0),
        float(perf_hits > 0),
        float(arch_hits > 0),
        float(loc > 150),
        float(cyclomatic_est > 10),
        float("eval" in code or "exec" in code),
        float("SELECT" in code or "cursor" in code),
        float("password" in code.lower() or "secret" in code.lower() or "key" in code.lower()),
    ]
    return np.array(features, dtype=np.float32)


class CodeFeatureExtractor:
    """Combines TF-IDF n-grams with structural/AST metrics into a unified feature matrix."""

    def __init__(self, max_tfidf_features: int = 64) -> None:
        self.vectorizer = TfidfVectorizer(
            token_pattern=r"(?u)\b\w+\b|[=+\-*/<>!&|%^~]",
            ngram_range=(1, 2),
            max_features=max_tfidf_features,
            lowercase=True,
        )
        self.is_fitted = False

    def fit(self, texts: list[str]) -> CodeFeatureExtractor:
        self.vectorizer.fit(texts)
        self.is_fitted = True
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("CodeFeatureExtractor must be fitted before transform")
        tfidf_mat = self.vectorizer.transform(texts).toarray()
        structural = np.array([extract_structural_features(t) for t in texts], dtype=np.float32)
        return np.hstack([structural, tfidf_mat])

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        return self.fit(texts).transform(texts)
