import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import UploadFile
from pydantic import BaseModel

from app.settings import Settings

ALLOWED_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}


class ContextUploadError(Exception):
    pass


class ContextFileInfo(BaseModel):
    path: str
    size: int
    language: str


class ProjectContextResponse(BaseModel):
    context_id: str
    files: list[ContextFileInfo]
    total_bytes: int
    expires_in_seconds: int


@dataclass(frozen=True)
class ProjectContext:
    id: str
    root: Path
    files: tuple[ContextFileInfo, ...]
    total_bytes: int
    created_at: float


def _safe_relative_path(raw_name: str) -> Path:
    normalized = raw_name.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ContextUploadError("文件路径不安全，已拒绝上传。")
    return Path(*path.parts)


def _language_for(path: Path) -> str:
    names = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".vue": "vue",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".sql": "sql",
        ".json": "json",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    return names.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "text")


class ProjectContextStore:
    def __init__(self, settings: Settings, root: Path | None = None) -> None:
        self.settings = settings
        self.root = root or Path(tempfile.gettempdir()) / "codebugger-contexts"
        self.root.mkdir(parents=True, exist_ok=True)
        self._contexts: dict[str, ProjectContext] = {}

    async def create(self, uploads: list[UploadFile]) -> ProjectContextResponse:
        self.cleanup_expired()
        if not uploads:
            raise ContextUploadError("请选择至少一个代码文件。")

        context_id = uuid.uuid4().hex
        context_root = self.root / context_id
        context_root.mkdir(parents=True, exist_ok=False)
        file_infos: list[ContextFileInfo] = []
        total_bytes = 0

        try:
            for upload in uploads:
                filename = upload.filename or ""
                if filename.lower().endswith(".zip"):
                    archive_bytes = await upload.read(self.settings.context_max_bytes + 1)
                    total_bytes = self._write_zip(
                        archive_bytes,
                        context_root,
                        file_infos,
                        total_bytes,
                    )
                    continue

                relative_path = _safe_relative_path(filename)
                if relative_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue
                content = await upload.read(self.settings.context_max_bytes + 1)
                total_bytes = self._write_file(
                    relative_path,
                    content,
                    context_root,
                    file_infos,
                    total_bytes,
                )

            if not file_infos:
                raise ContextUploadError("没有找到支持的代码或文本文件。")
        except Exception:
            shutil.rmtree(context_root, ignore_errors=True)
            raise

        context = ProjectContext(
            id=context_id,
            root=context_root,
            files=tuple(file_infos),
            total_bytes=total_bytes,
            created_at=time.time(),
        )
        self._contexts[context_id] = context
        return ProjectContextResponse(
            context_id=context.id,
            files=list(context.files),
            total_bytes=context.total_bytes,
            expires_in_seconds=self.settings.context_ttl_seconds,
        )

    def get(self, context_id: str | None) -> ProjectContext | None:
        if not context_id:
            return None
        self.cleanup_expired()
        return self._contexts.get(context_id)

    def prompt_text(self, context: ProjectContext | None) -> str:
        if context is None:
            return "未提供项目文件。"

        remaining = self.settings.context_prompt_max_chars
        sections: list[str] = []
        for info in context.files:
            path = context.root / info.path
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            header = f"\n--- FILE: {info.path} ---\n"
            chunk = f"{header}{content}"
            if len(chunk) > remaining:
                chunk = chunk[:remaining] + "\n[内容因上下文限制被截断]"
            sections.append(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                break
        return "".join(sections) or "项目文件无法读取。"

    def cleanup_expired(self) -> None:
        expires_before = time.time() - self.settings.context_ttl_seconds
        expired = [
            context_id
            for context_id, context in self._contexts.items()
            if context.created_at < expires_before
        ]
        for context_id in expired:
            context = self._contexts.pop(context_id)
            shutil.rmtree(context.root, ignore_errors=True)

    def _write_zip(
        self,
        archive_bytes: bytes,
        context_root: Path,
        file_infos: list[ContextFileInfo],
        total_bytes: int,
    ) -> int:
        if len(archive_bytes) > self.settings.context_max_bytes:
            raise ContextUploadError("压缩包超过允许的总大小。")
        archive_path = context_root / ".upload.zip"
        archive_path.write_bytes(archive_bytes)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    relative_path = _safe_relative_path(member.filename)
                    if relative_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                        continue
                    if member.file_size > self.settings.context_max_bytes:
                        raise ContextUploadError("压缩包内存在过大的文件。")
                    content = archive.read(member)
                    total_bytes = self._write_file(
                        relative_path,
                        content,
                        context_root,
                        file_infos,
                        total_bytes,
                    )
        except zipfile.BadZipFile as exc:
            raise ContextUploadError("上传的 ZIP 文件无法解析。") from exc
        finally:
            archive_path.unlink(missing_ok=True)
        return total_bytes

    def _write_file(
        self,
        relative_path: Path,
        content: bytes,
        context_root: Path,
        file_infos: list[ContextFileInfo],
        total_bytes: int,
    ) -> int:
        if b"\x00" in content:
            return total_bytes
        next_total = total_bytes + len(content)
        if next_total > self.settings.context_max_bytes:
            raise ContextUploadError("上传文件总大小超过限制。")
        target = context_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        file_infos.append(
            ContextFileInfo(
                path=relative_path.as_posix(),
                size=len(content),
                language=_language_for(relative_path),
            )
        )
        return next_total
