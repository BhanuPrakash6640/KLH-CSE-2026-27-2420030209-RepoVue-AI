"""Docker-based patch validation.

A patch that "looks right" is worthless. This module reproduces the project in
a container, records a baseline (tests + wall-clock), applies the patch,
re-runs, and only then decides. Everything runs with the network off, a memory
cap, a CPU cap and a hard timeout, because we are executing a stranger's test
suite.

The docker SDK is synchronous, so every blocking call is pushed onto a thread
via `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio
import shutil
import statistics
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger
from app.services.languages import ProjectProfile

log = get_logger(__name__)

DOCKERFILE_TEMPLATES = {
    "python": """FROM python:3.11-slim
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
COPY . /app
RUN {install}
CMD ["sleep", "infinity"]
""",
    "javascript": """FROM node:20-slim
WORKDIR /app
COPY . /app
RUN {install}
CMD ["sleep", "infinity"]
""",
    "go": """FROM golang:1.22
WORKDIR /app
COPY . /app
RUN {install}
CMD ["sleep", "infinity"]
""",
    "java": """FROM maven:3.9-eclipse-temurin-21
WORKDIR /app
COPY . /app
CMD ["sleep", "infinity"]
""",
}
DOCKERFILE_TEMPLATES["typescript"] = DOCKERFILE_TEMPLATES["javascript"]
DOCKERFILE_TEMPLATES["tsx"] = DOCKERFILE_TEMPLATES["javascript"]


@dataclass
class RunResult:
    exit_code: int
    duration_sec: float
    stdout: str = ""
    passed: bool = False
    durations: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "duration_sec": round(self.duration_sec, 3),
            "passed": self.passed,
            "runs": [round(d, 3) for d in self.durations],
            "output_tail": self.stdout[-4000:],
        }


@dataclass
class ValidationResult:
    verdict: str
    reason: str
    tests_passed: bool = False
    perf_delta_pct: float | None = None
    baseline: dict = field(default_factory=dict)
    patched: dict = field(default_factory=dict)
    image_tag: str | None = None
    test_command: str | None = None
    logs: str = ""


def docker_available() -> bool:
    try:
        import docker

        docker.from_env(timeout=10).ping()
        return True
    except Exception:
        return False


class Sandbox:
    """One sandbox per validation. Always use as an async context manager so the
    container and image are removed even when the test suite hangs."""

    def __init__(self, repo_root: str, profile: ProjectProfile) -> None:
        self.repo_root = Path(repo_root)
        self.profile = profile
        self.tag = f"repovue/{uuid.uuid4().hex[:12]}:latest"
        self.container = None
        self._client = None
        self.build_log = ""

    async def __aenter__(self) -> "Sandbox":
        import docker

        self._client = await asyncio.to_thread(docker.from_env, timeout=120)
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.cleanup()

    # ---------------------------------------------------------------- build
    def _dockerfile(self) -> str:
        if self.profile.has_dockerfile and self.profile.dockerfile_path:
            return (self.repo_root / self.profile.dockerfile_path).read_text(errors="ignore")
        template = DOCKERFILE_TEMPLATES.get(
            self.profile.primary_language, DOCKERFILE_TEMPLATES["python"]
        )
        return template.format(install=self.profile.install_command or "true")

    def _build_sync(self, build_dir: str) -> None:
        image, logs = self._client.images.build(
            path=build_dir, tag=self.tag, rm=True, forcerm=True, pull=True, nocache=False
        )
        self.build_log = "\n".join(
            str(chunk.get("stream", "")).rstrip() for chunk in logs if isinstance(chunk, dict)
        )[-8000:]
        return image

    async def build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "ctx"
            shutil.copytree(
                self.repo_root, build_dir,
                ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*.pyc", ".venv"),
            )
            if not (self.profile.has_dockerfile and self.profile.dockerfile_path):
                (build_dir / "Dockerfile").write_text(self._dockerfile())
            log.info("sandbox_building", tag=self.tag, language=self.profile.primary_language)
            await asyncio.to_thread(self._build_sync, str(build_dir))

    async def start(self) -> None:
        def _run():
            return self._client.containers.run(
                self.tag,
                command="sleep infinity",
                detach=True,
                network_mode=settings.SANDBOX_NETWORK,
                mem_limit=settings.SANDBOX_MEMORY_LIMIT,
                nano_cpus=int(settings.SANDBOX_CPU_LIMIT * 1e9),
                pids_limit=512,
                security_opt=["no-new-privileges:true"],
                working_dir="/app",
                auto_remove=False,
            )

        self.container = await asyncio.to_thread(_run)
        log.info("sandbox_started", container=self.container.short_id)

    # ------------------------------------------------------------------ run
    async def exec(self, command: str, timeout: int | None = None) -> RunResult:
        timeout = timeout or settings.SANDBOX_TIMEOUT_SEC

        def _exec():
            started = time.perf_counter()
            code, output = self.container.exec_run(
                cmd=["/bin/sh", "-lc", command], workdir="/app", demux=False
            )
            return code, output, time.perf_counter() - started

        try:
            code, output, elapsed = await asyncio.wait_for(
                asyncio.to_thread(_exec), timeout=timeout
            )
        except asyncio.TimeoutError:
            return RunResult(exit_code=124, duration_sec=float(timeout), stdout="timed out", passed=False)

        text = output.decode("utf-8", errors="ignore") if isinstance(output, bytes) else str(output)
        return RunResult(exit_code=code, duration_sec=elapsed, stdout=text, passed=code == 0)

    async def measure(self, command: str, runs: int) -> RunResult:
        """Run the command N times, keep the median so one cold cache doesn't
        masquerade as a regression."""
        results = [await self.exec(command) for _ in range(max(1, runs))]
        durations = [r.duration_sec for r in results]
        last = results[-1]
        last.durations = durations
        last.duration_sec = statistics.median(durations)
        last.passed = all(r.passed for r in results)
        return last

    async def copy_in(self, local_path: str, dest_dir: str = "/app") -> None:
        def _copy():
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as fh:
                tar_path = fh.name
            with tarfile.open(tar_path, "w") as tar:
                tar.add(local_path, arcname=Path(local_path).name)
            with open(tar_path, "rb") as fh:
                self.container.put_archive(dest_dir, fh.read())
            Path(tar_path).unlink(missing_ok=True)

        await asyncio.to_thread(_copy)

    async def cleanup(self) -> None:
        if self.container is not None:
            try:
                await asyncio.to_thread(self.container.remove, force=True)
            except Exception as exc:  # pragma: no cover
                log.warning("container_cleanup_failed", error=str(exc)[:200])
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.images.remove, self.tag, force=True)
            except Exception:
                pass


async def validate_patch(
    *, repo_root: str, profile: ProjectProfile, diff: str, patch_file_path: str
) -> ValidationResult:
    """Baseline -> apply -> re-run -> verdict."""
    if not settings.VALIDATION_ENABLED:
        return ValidationResult("skipped", "validation disabled by configuration")
    if not profile.test_command:
        return ValidationResult("skipped", "no test command detected for this project")
    if not await asyncio.to_thread(docker_available):
        return ValidationResult("skipped", "docker daemon not reachable")

    test_cmd = profile.test_command
    try:
        async with Sandbox(repo_root, profile) as box:
            await box.build()
            await box.start()

            baseline = await box.measure(test_cmd, settings.BENCHMARK_RUNS)
            logs = f"$ {test_cmd}\n{baseline.stdout[-3000:]}"

            if not baseline.passed:
                return ValidationResult(
                    "skipped",
                    "baseline test run already failed - cannot attribute changes to the patch",
                    baseline=baseline.to_dict(), image_tag=box.tag, test_command=test_cmd, logs=logs,
                )

            await box.copy_in(patch_file_path, "/tmp")
            applied = await box.exec(
                f"git apply --whitespace=nowarn /tmp/{Path(patch_file_path).name} "
                f"|| patch -p1 < /tmp/{Path(patch_file_path).name}"
            )
            if not applied.passed:
                return ValidationResult(
                    "fail", "patch did not apply inside the sandbox",
                    baseline=baseline.to_dict(), image_tag=box.tag,
                    test_command=test_cmd, logs=logs + "\n" + applied.stdout[-2000:],
                )

            patched = await box.measure(test_cmd, settings.BENCHMARK_RUNS)
            logs += f"\n--- after patch ---\n{patched.stdout[-3000:]}"

            delta = None
            if baseline.duration_sec > 0:
                delta = round((patched.duration_sec - baseline.duration_sec) / baseline.duration_sec * 100, 2)

            if not patched.passed:
                return ValidationResult(
                    "fail", "tests fail after applying the patch", tests_passed=False,
                    perf_delta_pct=delta, baseline=baseline.to_dict(), patched=patched.to_dict(),
                    image_tag=box.tag, test_command=test_cmd, logs=logs,
                )

            tolerance = settings.PERF_REGRESSION_TOLERANCE * 100
            if delta is not None and delta > tolerance:
                return ValidationResult(
                    "fail", f"tests pass but runtime regressed {delta}% (tolerance {tolerance}%)",
                    tests_passed=True, perf_delta_pct=delta, baseline=baseline.to_dict(),
                    patched=patched.to_dict(), image_tag=box.tag, test_command=test_cmd, logs=logs,
                )

            reason = "tests pass and no performance regression"
            if delta is not None and delta < -5:
                reason = f"tests pass and runtime improved {abs(delta)}%"
            return ValidationResult(
                "pass", reason, tests_passed=True, perf_delta_pct=delta,
                baseline=baseline.to_dict(), patched=patched.to_dict(),
                image_tag=box.tag, test_command=test_cmd, logs=logs,
            )
    except Exception as exc:
        log.exception("validation_error")
        return ValidationResult("error", f"sandbox error: {exc}"[:500])
