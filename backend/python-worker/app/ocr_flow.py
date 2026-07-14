"""OCR-Flow provider 抽象。

Provider 只负责把输入文件转换为 OCR 工件。题库后处理由执行编排层在 Provider
成功后统一调用，因此新增 Provider 不需要依赖题库题目解析实现。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from app.ocr.contracts import CanonicalOcrBundle


DEFAULT_OCR_PROVIDER = "mineru"


@dataclass(frozen=True)
class OcrProviderRequest:
    """Provider 执行所需的输入；不携带平台任务状态或后处理回调。"""
    document_id: str
    input_path: str
    output_dir: Path
    timeout_seconds: int


@dataclass(frozen=True)
class OcrProviderResult:
    """Provider 的归一化执行结果，成功时必须交付可后处理的 Bundle。"""
    success: bool
    bundle: CanonicalOcrBundle | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if self.success and self.bundle is None:
            raise ValueError("successful OCR provider result requires canonical bundle")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ProviderCommand:
    """OCR provider 的可执行入口。

    display 用于状态接口和任务日志，args 用于 subprocess 执行。二者分开后，可以
    安全支持 Python entry point 这类不适合直接展示完整命令的调用方式。
    """

    args: list[str]
    display: str
    source: str


class OcrProvider:
    """OCR provider 抽象基类，定义 provider 能力和执行接口。"""
    name = ""

    def status(self) -> dict[str, Any]:
        """执行 status 逻辑。"""
        raise NotImplementedError

    def run(self, request: OcrProviderRequest) -> OcrProviderResult:
        """生成并验证标准 OCR Bundle，不读取或修改平台任务状态。"""
        raise NotImplementedError


class MineruOcrProvider(OcrProvider):
    """MinerU OCR provider 实现。"""
    name = "mineru"

    def __init__(self, app_root: Path, version_timeout_seconds: int) -> None:
        """执行   init   逻辑。"""
        self.app_root = app_root
        self.version_timeout_seconds = version_timeout_seconds

    def _script_command_candidates(self) -> list[ProviderCommand]:
        """执行  script command candidates 逻辑。"""
        candidates: list[ProviderCommand] = []
        configured = os.getenv("MINERU_COMMAND")
        if configured:
            candidates.append(
                ProviderCommand(
                    args=shlex.split(configured),
                    display=configured,
                    source="MINERU_COMMAND",
                )
            )
            return candidates

        local_command = self.app_root / ".venv" / "bin" / "mineru"
        if local_command.exists():
            candidates.append(
                ProviderCommand(
                    args=[str(local_command)],
                    display=str(local_command),
                    source="local-venv-script",
                )
            )

        path_command = shutil.which("mineru")
        if path_command and path_command != str(local_command):
            candidates.append(
                ProviderCommand(
                    args=[path_command],
                    display=path_command,
                    source="PATH",
                )
            )
        return candidates

    def _entrypoint_command_candidate(self) -> ProviderCommand | None:
        """执行  entrypoint command candidate 逻辑。"""
        try:
            distribution = metadata.distribution("mineru")
        except metadata.PackageNotFoundError:
            return None

        for entry_point in distribution.entry_points:
            if entry_point.group != "console_scripts" or entry_point.name != "mineru":
                continue
            module = entry_point.module
            attr = entry_point.attr
            if not module or not attr:
                continue
            code = (
                "import importlib, sys; "
                "sys.argv[0] = 'mineru'; "
                f"_module = importlib.import_module({module!r}); "
                "_target = _module; "
                f"\nfor _part in {attr.split('.')!r}:\n"
                "    _target = getattr(_target, _part)\n"
                "raise SystemExit(_target())"
            )
            return ProviderCommand(
                args=[sys.executable, "-c", code],
                display=f"{sys.executable} -c <mineru:{entry_point.value}>",
                source="python-entrypoint",
            )
        return None

    def _command_candidates(self) -> list[ProviderCommand]:
        """执行  command candidates 逻辑。"""
        candidates = self._script_command_candidates()
        entrypoint = self._entrypoint_command_candidate()
        if entrypoint:
            candidates.append(entrypoint)
        return candidates

    def _api_url(self) -> str | None:
        """Return the optional persistent MinerU API URL."""
        value = os.getenv("MINERU_API_URL", "").strip()
        return value or None

    def _command_availability_error(self, command: ProviderCommand) -> str | None:
        """检查命令入口本身是否可启动，版本探测不参与可用性判定。"""
        if not command.args:
            return "Command is empty."

        executable = command.args[0]
        executable_path: Path | None
        if os.path.isabs(executable) or os.sep in executable:
            executable_path = Path(executable)
        else:
            resolved = shutil.which(executable)
            executable_path = Path(resolved) if resolved else None

        if executable_path is None:
            return f"Executable not found: {executable}."
        if not executable_path.exists():
            return f"Executable does not exist: {executable_path}."
        if executable_path.is_file() and not os.access(executable_path, os.X_OK):
            return f"Executable is not runnable: {executable_path}."

        try:
            with executable_path.open("rb") as fp:
                first_line = fp.readline(256).decode("utf-8", errors="ignore").strip()
        except OSError:
            return None

        if first_line.startswith("#!"):
            interpreter = first_line[2:].split(" ", 1)[0]
            if interpreter != "/usr/bin/env" and not Path(interpreter).exists():
                return f"Script interpreter does not exist: {interpreter}."

        return None

    def _probe_command(self, command: ProviderCommand) -> dict[str, Any]:
        """执行  probe command 逻辑。"""
        availability_error = self._command_availability_error(command)
        if availability_error:
            return {
                "source": command.source,
                "command": command.display,
                "returncode": None,
                "version": None,
                "valid": False,
                "versionProbeOk": False,
                "error": availability_error,
            }

        try:
            result = subprocess.run(
                [*command.args, "--version"],
                capture_output=True,
                text=True,
                timeout=self.version_timeout_seconds,
            )
            output = (result.stdout or result.stderr).strip()
            return {
                "source": command.source,
                "command": command.display,
                "returncode": result.returncode,
                "version": output if result.returncode == 0 and output else None,
                "valid": True,
                "versionProbeOk": result.returncode == 0,
                "error": None if result.returncode == 0 else output or f"Exited with code {result.returncode}.",
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "source": command.source,
                "command": command.display,
                "returncode": None,
                "version": None,
                "valid": True,
                "versionProbeOk": False,
                "error": f"Version probe timed out after {exc.timeout} seconds.",
            }
        except Exception as exc:  # pragma: no cover - defensive status endpoint
            return {
                "source": command.source,
                "command": command.display,
                "returncode": None,
                "version": None,
                "valid": False,
                "versionProbeOk": False,
                "error": str(exc),
            }

    def resolve_command(self) -> tuple[ProviderCommand | None, dict[str, Any]]:
        """执行 resolve command 逻辑。"""
        probes = []
        for candidate in self._command_candidates():
            probe = self._probe_command(candidate)
            probes.append(probe)
            if probe["valid"]:
                return candidate, {
                    "selectedSource": candidate.source,
                    "selectedCommand": candidate.display,
                    "version": probe["version"],
                    "candidates": probes,
                }

        return None, {
            "selectedSource": None,
            "selectedCommand": None,
            "version": None,
            "candidates": probes,
            "error": "No valid MinerU command found. Install MinerU in the Python worker venv or configure MINERU_COMMAND.",
        }

    def command(self) -> str | None:
        """执行 command 逻辑。"""
        resolved, _ = self.resolve_command()
        return resolved.display if resolved else None

    def status(self) -> dict[str, Any]:
        """执行 status 逻辑。"""
        command, resolution = self.resolve_command()
        status: dict[str, Any] = {
            "provider": self.name,
            "installed": command is not None,
            "command": command.display if command else None,
            "commandSource": command.source if command else None,
            "version": resolution.get("version"),
            "error": resolution.get("error"),
            "candidates": resolution.get("candidates", []),
        }
        return status

    def run(self, request: OcrProviderRequest) -> OcrProviderResult:
        """调用 MinerU 并把工件归一为 Bundle，不执行题库后处理或状态写入。"""
        command, resolution = self.resolve_command()
        if not command:
            return OcrProviderResult(
                success=False,
                metadata={
                    "ocrFlowProvider": self.name,
                    "ocrProvider": self.name,
                    "ocrFlowProviderResolution": resolution,
                },
                error=resolution.get("error") or "MinerU CLI is not installed or not available.",
            )

        request.output_dir.mkdir(parents=True, exist_ok=True)
        api_url = self._api_url()
        provider_metadata = {
            "ocrFlowProvider": self.name,
            "ocrProvider": self.name,
            "ocrFlowProviderCommand": command.display,
            "ocrFlowProviderCommandSource": command.source,
            "ocrFlowProviderResolution": resolution,
            "mineruCommand": command.display,
            "mineruApiUrl": api_url,
        }

        cmd = [*command.args, "-p", request.input_path, "-o", str(request.output_dir), "-b", "pipeline"]
        if api_url:
            cmd.extend(["--api-url", api_url])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=request.timeout_seconds)
            provider_metadata.update({"mineruStdout": result.stdout[-8000:], "mineruStderr": result.stderr[-8000:]})
            if result.returncode != 0:
                return OcrProviderResult(
                    success=False,
                    metadata=provider_metadata,
                    error=f"MinerU exited with code {result.returncode}.",
                )
            # 延迟导入避免 provider 基础抽象与布局适配器的历史 worker 依赖形成循环。
            from app.ocr.mineru_adapter import MineruOcrBundleAdapter

            bundle = MineruOcrBundleAdapter().from_output(
                {
                    "jobId": request.document_id,
                    "uploadPath": request.input_path,
                    "ocrFlowProvider": self.name,
                    "ocrProvider": self.name,
                },
                request.output_dir,
            )
            return OcrProviderResult(success=True, bundle=bundle, metadata=provider_metadata)
        except subprocess.TimeoutExpired:
            return OcrProviderResult(
                success=False,
                metadata=provider_metadata,
                error=f"MinerU timed out after {request.timeout_seconds} seconds.",
            )
        except Exception as exc:  # pragma: no cover - background worker safety
            return OcrProviderResult(success=False, metadata=provider_metadata, error=str(exc))


def parse_extensions(value: str | None, fallback: set[str]) -> set[str]:
    """解析 OCR provider 支持的文件后缀集合。"""
    if not value:
        return set(fallback)
    extensions = set()
    for item in value.split(","):
        extension = item.strip().lower()
        if not extension:
            continue
        extensions.add(extension if extension.startswith(".") else f".{extension}")
    return extensions or set(fallback)


def selected_provider_name() -> str:
    """读取当前 OCR provider 名称。"""
    return (os.getenv("OCR_FLOW_PROVIDER") or os.getenv("OCR_PROVIDER") or DEFAULT_OCR_PROVIDER).strip().lower()


def providers(app_root: Path, version_timeout_seconds: int) -> dict[str, OcrProvider]:
    """构造 OCR provider 注册表。"""
    mineru = MineruOcrProvider(app_root, version_timeout_seconds)
    return {mineru.name: mineru}
