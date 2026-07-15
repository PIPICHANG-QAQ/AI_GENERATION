#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "backend" / "python-worker"
WORKER_PYTHON = WORKER_DIR / ".venv" / "bin" / "python"


def provider_status(check_api: bool | None = None) -> dict[str, object]:
    worker_path = str(WORKER_DIR)
    if worker_path not in sys.path:
        sys.path.insert(0, worker_path)
    from app.ocr_flow import MineruOcrProvider

    return MineruOcrProvider(WORKER_DIR, 5).status(check_api=check_api)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check MinerU command, runtime, and optional API readiness.")
    api_mode = parser.add_mutually_exclusive_group()
    api_mode.add_argument("--skip-api", action="store_true", help="Check command and runtime imports only.")
    api_mode.add_argument("--check-api", action="store_true", help="Also require MinerU OpenAPI readiness.")
    parser.add_argument("--json", action="store_true", help="Emit one line of JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    check_api = False if args.skip_api else True if args.check_api else None
    try:
        payload = provider_status(check_api=check_api)
    except Exception as exc:
        payload = {
            "installed": False,
            "runtimeProbeOk": False,
            "apiReady": False,
            "error": str(exc),
        }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    ready = payload.get("installed") is True and payload.get("runtimeProbeOk") is True
    if args.check_api or (not args.skip_api and payload.get("apiEnabled") is True):
        ready = ready and payload.get("apiReady") is True
    return 0 if ready else 1


def entrypoint(argv: Sequence[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    if os.getenv("CHECK_MINERU_IN_WORKER_VENV") != "1" and WORKER_PYTHON.exists():
        env = os.environ.copy()
        env["CHECK_MINERU_IN_WORKER_VENV"] = "1"
        try:
            result = subprocess.run(
                [str(WORKER_PYTHON), str(Path(__file__).resolve()), *cli_args],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            print(f"MinerU readiness re-exec failed: {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if result.returncode == 0 and "Traceback (most recent call last):" in output:
            return 1
        return result.returncode
    return main(cli_args)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
