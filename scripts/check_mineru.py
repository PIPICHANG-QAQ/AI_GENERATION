from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from importlib import metadata


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "backend" / "python-worker"
WORKER_PYTHON = WORKER_DIR / ".venv" / "bin" / "python"


def find_mineru() -> str | None:
    configured = os.getenv("MINERU_COMMAND")
    if configured:
        return configured
    local_command = WORKER_DIR / ".venv" / "bin" / "mineru"
    if local_command.exists():
        return str(local_command)
    return shutil.which("mineru")


def provider_status() -> dict | None:
    sys.path.insert(0, str(WORKER_DIR))
    try:
        from app.ocr_flow import MineruOcrProvider

        return MineruOcrProvider(WORKER_DIR, 5).status()
    except Exception as exc:
        return {"installed": False, "command": None, "version": None, "error": str(exc)}


def main() -> int:
    if os.getenv("CHECK_MINERU_IN_WORKER_VENV") != "1" and WORKER_PYTHON.exists():
        env = os.environ.copy()
        env["CHECK_MINERU_IN_WORKER_VENV"] = "1"
        try:
            result = subprocess.run(
                [str(WORKER_PYTHON), str(Path(__file__).resolve())],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            print((result.stdout or result.stderr).strip())
            return result.returncode
        except Exception:
            pass

    status = provider_status()
    if status:
        payload = status
    else:
        command = find_mineru()
        payload = {"installed": command is not None, "command": command, "version": None, "error": None}
        if command:
            try:
                result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5)
                payload["version"] = (result.stdout or result.stderr).strip() or None
                payload["returncode"] = result.returncode
                payload["installed"] = result.returncode == 0
                if result.returncode != 0:
                    payload["error"] = payload["version"] or f"Exited with code {result.returncode}."
            except Exception as exc:
                payload["installed"] = False
                payload["error"] = str(exc)
            if not payload.get("version"):
                try:
                    payload["version"] = metadata.version("mineru")
                except metadata.PackageNotFoundError:
                    pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["installed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
