import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel

from app.context import ProjectContext
from app.settings import Settings

TestCommandId = Literal[
    "auto",
    "python-compile",
    "python-pytest",
    "npm-lint",
    "npm-test",
    "npm-build",
]


class TestExecutionResult(BaseModel):
    command_id: str
    command: str
    status: Literal["passed", "failed", "timeout", "skipped"]
    exit_code: int | None
    duration_ms: int
    output: str
    truncated: bool = False


@dataclass(frozen=True)
class _ResolvedCommand:
    id: str
    argv: tuple[str, ...]


class SafeTestRunner:
    """Execute only server-defined commands without a shell or inherited secrets."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(
        self,
        context: ProjectContext | None,
        command_id: TestCommandId,
    ) -> TestExecutionResult:
        if not self.settings.test_execution_enabled:
            return self._skipped(command_id, "后端已关闭本地测试执行功能。")
        if context is None:
            return self._skipped(command_id, "未上传项目文件，跳过测试执行。")

        resolved = self._resolve(context.root, command_id)
        if resolved is None:
            return self._skipped(command_id, "未检测到适合当前项目的安全测试命令。")

        started = time.perf_counter()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = await asyncio.create_subprocess_exec(
                *resolved.argv,
                cwd=context.root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._safe_environment(context.root),
                creationflags=creationflags,
            )
        except OSError as exc:
            return TestExecutionResult(
                command_id=resolved.id,
                command=self._display_command(resolved.argv),
                status="failed",
                exit_code=None,
                duration_ms=self._elapsed_ms(started),
                output=f"无法启动测试命令：{exc}",
            )

        try:
            output_bytes, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self.settings.test_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return TestExecutionResult(
                command_id=resolved.id,
                command=self._display_command(resolved.argv),
                status="timeout",
                exit_code=None,
                duration_ms=self._elapsed_ms(started),
                output=f"测试执行超过 {self.settings.test_timeout_seconds} 秒，已终止。",
            )

        output = output_bytes.decode("utf-8", errors="replace")
        output, truncated = self._truncate(output)
        return TestExecutionResult(
            command_id=resolved.id,
            command=self._display_command(resolved.argv),
            status="passed" if process.returncode == 0 else "failed",
            exit_code=process.returncode,
            duration_ms=self._elapsed_ms(started),
            output=output.strip() or "命令执行完成，未产生输出。",
            truncated=truncated,
        )

    def _resolve(self, root: Path, command_id: TestCommandId) -> _ResolvedCommand | None:
        if command_id == "auto":
            command_id = self._detect(root)
            if command_id is None:
                return None

        if command_id == "python-compile":
            return _ResolvedCommand(
                id=command_id,
                argv=(sys.executable, "-m", "compileall", "-q", "."),
            )
        if command_id == "python-pytest":
            return _ResolvedCommand(
                id=command_id,
                argv=(sys.executable, "-m", "pytest", "-q"),
            )

        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if npm is None:
            return None
        script = command_id.removeprefix("npm-")
        if not self._has_npm_script(root, script):
            return None
        return _ResolvedCommand(id=command_id, argv=(npm, "run", script))

    def _detect(self, root: Path) -> TestCommandId | None:
        paths = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
        if any(path.startswith("tests/") and path.endswith(".py") for path in paths):
            return "python-pytest"
        if any(path.endswith(".py") for path in paths):
            return "python-compile"
        for script in ("test", "lint", "build"):
            if self._has_npm_script(root, script):
                return cast(TestCommandId, f"npm-{script}")
        return None

    @staticmethod
    def _has_npm_script(root: Path, script: str) -> bool:
        package_json = root / "package.json"
        if not package_json.exists():
            return False
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        scripts = package.get("scripts")
        return isinstance(scripts, dict) and isinstance(scripts.get(script), str)

    @staticmethod
    def _safe_environment(root: Path) -> dict[str, str]:
        keys = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
        environment = {key: os.environ[key] for key in keys if key in os.environ}
        temp_dir = root / ".codebugger-tmp"
        temp_dir.mkdir(exist_ok=True)
        environment.update(
            {
                "CI": "true",
                "NO_COLOR": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TEMP": str(temp_dir),
                "TMP": str(temp_dir),
            }
        )
        return environment

    def _truncate(self, output: str) -> tuple[str, bool]:
        limit = self.settings.test_max_output_chars
        if len(output) <= limit:
            return output, False
        head = output[: limit // 2]
        tail = output[-(limit // 2) :]
        return f"{head}\n\n[输出过长，中间内容已截断]\n\n{tail}", True

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    @staticmethod
    def _display_command(argv: tuple[str, ...]) -> str:
        return " ".join(Path(item).name if index == 0 else item for index, item in enumerate(argv))

    @staticmethod
    def _skipped(command_id: str, message: str) -> TestExecutionResult:
        return TestExecutionResult(
            command_id=command_id,
            command="",
            status="skipped",
            exit_code=None,
            duration_ms=0,
            output=message,
        )
