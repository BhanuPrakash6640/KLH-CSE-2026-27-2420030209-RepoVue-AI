"""Language + build-system detection and repository walking."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

EXT_LANGUAGE = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "c_sharp",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sql": "sql",
    ".sh": "bash",
}

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", "out", "target", ".next", ".nuxt", "vendor", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode", "migrations",
    "site-packages", ".terraform", ".tox", "bin", "obj",
}

IGNORED_SUFFIXES = (
    ".min.js", ".bundle.js", ".lock", ".map", ".snap", ".pb.go", "_pb2.py",
    ".generated.ts", ".d.ts",
)

TEST_HINTS = ("test_", "_test.", "/tests/", "/test/", ".spec.", ".test.")


@dataclass
class ProjectProfile:
    """What kind of project is this and how do we build/test it in Docker?"""

    languages: dict[str, int] = field(default_factory=dict)
    primary_language: str = "unknown"
    package_managers: list[str] = field(default_factory=list)
    has_dockerfile: bool = False
    dockerfile_path: str | None = None
    has_compose: bool = False
    test_command: str | None = None
    install_command: str | None = None
    base_image: str | None = None
    frameworks: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "languages": self.languages,
            "primary_language": self.primary_language,
            "package_managers": self.package_managers,
            "has_dockerfile": self.has_dockerfile,
            "test_command": self.test_command,
            "install_command": self.install_command,
            "base_image": self.base_image,
            "frameworks": self.frameworks,
        }


def detect_language(path: str) -> str | None:
    return EXT_LANGUAGE.get(Path(path).suffix.lower())


def is_test_file(rel_path: str) -> bool:
    p = "/" + rel_path.replace("\\", "/")
    return any(h in p for h in TEST_HINTS)


def should_skip(rel_path: str) -> bool:
    parts = set(Path(rel_path).parts)
    if parts & IGNORED_DIRS:
        return True
    return rel_path.endswith(IGNORED_SUFFIXES)


def walk_repository(root: str | Path) -> list[dict]:
    """Return metadata for every source file worth analysing."""
    root = Path(root)
    out: list[dict] = []
    max_bytes = settings.MAX_FILE_KB * 1024

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for fname in filenames:
            abs_path = Path(dirpath) / fname
            rel = str(abs_path.relative_to(root))
            language = detect_language(rel)
            if not language or should_skip(rel):
                continue
            try:
                size = abs_path.stat().st_size
            except OSError:
                continue
            if size == 0 or size > max_bytes:
                continue
            try:
                text = abs_path.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            out.append(
                {
                    "path": rel.replace("\\", "/"),
                    "abs_path": str(abs_path),
                    "language": language,
                    "size_bytes": size,
                    "loc": text.count("\n") + 1,
                    "content_sha": hashlib.sha256(text.encode()).hexdigest()[:40],
                    "is_test": is_test_file(rel),
                }
            )
            if len(out) >= settings.MAX_FILES_PER_ANALYSIS:
                return out
    return out


def _exists(root: Path, *names: str) -> str | None:
    for n in names:
        if (root / n).exists():
            return n
    return None


def profile_project(root: str | Path, files: list[dict]) -> ProjectProfile:
    """Infer package manager, test command and base image for the sandbox."""
    root = Path(root)
    prof = ProjectProfile()

    for f in files:
        prof.languages[f["language"]] = prof.languages.get(f["language"], 0) + f["loc"]
    if prof.languages:
        prof.primary_language = max(prof.languages, key=prof.languages.get)

    df = _exists(root, "Dockerfile", "docker/Dockerfile", "build/Dockerfile")
    prof.has_dockerfile = df is not None
    prof.dockerfile_path = df
    prof.has_compose = _exists(root, "docker-compose.yml", "docker-compose.yaml") is not None

    # ---- Python ----
    if _exists(root, "pyproject.toml", "requirements.txt", "setup.py", "Pipfile"):
        prof.package_managers.append("pip")
        prof.base_image = prof.base_image or "python:3.11-slim"
        if (root / "poetry.lock").exists():
            prof.install_command = "pip install poetry && poetry install --no-interaction"
            prof.test_command = "poetry run pytest -q"
        elif (root / "requirements.txt").exists():
            prof.install_command = (
                "pip install --no-cache-dir -r requirements.txt || true; "
                "pip install --no-cache-dir pytest"
            )
            prof.test_command = "pytest -q"
        else:
            prof.install_command = "pip install --no-cache-dir -e . pytest || true"
            prof.test_command = "pytest -q"
        text = (root / "requirements.txt").read_text(errors="ignore") if (root / "requirements.txt").exists() else ""
        for fw in ("django", "fastapi", "flask", "sqlalchemy", "celery"):
            if fw in text.lower():
                prof.frameworks.append(fw)

    # ---- Node ----
    if (root / "package.json").exists():
        import json

        prof.package_managers.append("npm")
        prof.base_image = prof.base_image or "node:20-slim"
        try:
            pkg = json.loads((root / "package.json").read_text(errors="ignore"))
        except Exception:
            pkg = {}
        scripts = pkg.get("scripts", {}) or {}
        if (root / "pnpm-lock.yaml").exists():
            prof.install_command = "corepack enable && pnpm install --frozen-lockfile"
            runner = "pnpm"
        elif (root / "yarn.lock").exists():
            prof.install_command = "corepack enable && yarn install --frozen-lockfile"
            runner = "yarn"
        else:
            prof.install_command = "npm ci || npm install"
            runner = "npm run"
        if "test" in scripts:
            prof.test_command = f"{runner} test" if runner != "npm run" else "npm test"
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        for fw in ("react", "next", "express", "nestjs", "vue"):
            if any(fw in d for d in deps):
                prof.frameworks.append(fw)

    # ---- Go / Java ----
    if (root / "go.mod").exists():
        prof.package_managers.append("go")
        prof.base_image = prof.base_image or "golang:1.22"
        prof.install_command = "go mod download"
        prof.test_command = "go test ./..."
    if _exists(root, "pom.xml"):
        prof.package_managers.append("maven")
        prof.base_image = prof.base_image or "maven:3.9-eclipse-temurin-21"
        prof.test_command = "mvn -B -q test"
    elif _exists(root, "build.gradle", "build.gradle.kts"):
        prof.package_managers.append("gradle")
        prof.base_image = prof.base_image or "gradle:8-jdk21"
        prof.test_command = "gradle test --no-daemon"

    prof.entrypoints = [
        f["path"] for f in files
        if Path(f["path"]).name in {"main.py", "app.py", "index.js", "server.js", "main.go", "manage.py"}
    ][:10]
    return prof
