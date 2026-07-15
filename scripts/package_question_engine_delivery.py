#!/usr/bin/env python3
"""Package question-engine delivery artifacts and verify package boundaries."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "question-engine-delivery.tar.gz"
DEFAULT_MANIFEST = ROOT / "dist" / "question-engine-delivery-manifest.json"

INCLUDE_ROOTS = [
    "README.md",
    ".env.example",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.local.yml",
    "docker-compose.server.yml",
    "deploy",
    "backend/README.md",
    "backend/pom.xml",
    "backend/src",
    "backend/python-worker/README.md",
    "backend/python-worker/pyproject.toml",
    "backend/python-worker/app",
    "backend/python-worker/tests",
    "question-engine",
    "docs",
    "examples/platform-integration",
    "scripts",
]

LOCAL_PLATFORM_INCLUDE = [
    "local-platform/README.md",
    "local-platform/package.json",
    "local-platform/package-lock.json",
    "local-platform/src",
    "local-platform/index.html",
    "local-platform/vite.config.ts",
    "local-platform/tsconfig.json",
    "local-platform/tsconfig.app.json",
    "local-platform/tsconfig.node.json",
]

MINERU_WHEELHOUSE_INCLUDE = [
    "vendor/mineru-wheelhouse",
]

EXCLUDE_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".venv",
    "node_modules",
    "target",
    "storage",
    "dist",
    "tmp",
    "artifacts",
    "protocal",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".key",
    ".pem",
    ".p12",
}

EXCLUDE_NAMES = {
    ".DS_Store",
}

REQUIRED_IN_PACKAGE = [
    "README.md",
    "backend/src/main/java/com/aigeneration/questionbank/capability/controller/QuestionProcessingCapabilityController.java",
    "backend/python-worker/pyproject.toml",
    "backend/python-worker/app/ocr_flow.py",
    "backend/python-worker/tests/test_ocr_flow.py",
    "question-engine/openapi/question-engine.v1.yaml",
    "question-engine/sdk/generated/typescript/QuestionEngineClient.ts",
    "question-engine/sdk/generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineClient.java",
    "docs/development/DEVELOPMENT_GUIDE.md",
    "docs/delivery/DELIVERY_PACKAGE.md",
    "docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md",
    "docs/delivery/OPERATIONS_GUIDE.md",
    "docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md",
    "docs/delivery/ERROR_AND_STATUS_GUIDE.md",
    "docs/delivery/ACCEPTANCE.md",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.server.yml",
    "deploy/nginx.conf",
    "scripts/deploy_local.sh",
    "scripts/build_mineru_wheelhouse.sh",
    "scripts/check_mineru.py",
    "scripts/test_check_mineru.py",
    "scripts/rebuild_mineru_venv.py",
    "scripts/test_rebuild_mineru_venv.py",
    "scripts/rollback_mineru_venv.sh",
    "scripts/test_rollback_mineru_venv.py",
    "scripts/docker-entrypoint.sh",
    "scripts/start_server_docker.sh",
    "scripts/test_docker_entrypoint.py",
    "scripts/acceptance_question_engine_plugin.py",
    "scripts/check_project_portability.py",
    "scripts/smoke_deploy_basic.py",
    "scripts/smoke_ocr.py",
    "scripts/smoke_ai.py",
    "scripts/test_python_worker.sh",
    "examples/platform-integration/README.md",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--release-name", help="Optional archive basename, for example AI_GENERATION_TOGO_20260709_v14")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--include-local-platform", action="store_true")
    parser.add_argument("--include-mineru-wheelhouse", action="store_true")
    args = parser.parse_args()
    if args.release_name:
        args.output = args.output or ROOT / "dist" / f"{args.release_name}.tar.gz"
        args.manifest = args.manifest or ROOT / "dist" / f"{args.release_name}_MANIFEST.json"
    else:
        args.output = args.output or DEFAULT_OUTPUT
        args.manifest = args.manifest or DEFAULT_MANIFEST
    return args


def should_exclude(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    parts = set(relative.parts)
    if parts & EXCLUDE_PARTS:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    if path.name.startswith(".env") and path.name != ".env.example":
        return True
    return path.suffix in EXCLUDE_SUFFIXES


def iter_files(include_local_platform: bool, include_mineru_wheelhouse: bool = False) -> list[Path]:
    roots = list(INCLUDE_ROOTS)
    if include_local_platform:
        roots.extend(LOCAL_PLATFORM_INCLUDE)
    if include_mineru_wheelhouse:
        roots.extend(MINERU_WHEELHOUSE_INCLUDE)

    files: list[Path] = []
    for item in roots:
        path = ROOT / item
        if not path.exists():
            continue
        if path.is_file():
            if not should_exclude(path):
                files.append(path)
            continue
        for child in path.rglob("*"):
            if child.is_file() and not should_exclude(child):
                files.append(child)
    return sorted(set(files), key=lambda value: value.as_posix())


def validate(files: list[Path]) -> list[str]:
    failures: list[str] = []
    relatives = {path.relative_to(ROOT).as_posix() for path in files}
    for required in REQUIRED_IN_PACKAGE:
        if required not in relatives:
            failures.append(f"missing required delivery file: {required}")
    for relative in relatives:
        parts = set(Path(relative).parts)
        if parts & EXCLUDE_PARTS:
            failures.append(f"excluded path leaked into package: {relative}")
        if relative.endswith((".pyc", ".pyo", ".log", ".key", ".pem", ".p12")):
            failures.append(f"excluded file type leaked into package: {relative}")
    return failures


def read_contract_version() -> str:
    openapi = ROOT / "question-engine" / "openapi" / "question-engine.v1.yaml"
    if not openapi.exists():
        return "unknown"
    match = re.search(r"^  version:\s*(.+)$", openapi.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def write_manifest(files: list[Path], manifest: Path, release_name: str | None = None) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "releaseName": release_name,
        "contractVersion": read_contract_version(),
        "fileCount": len(files),
        "files": [path.relative_to(ROOT).as_posix() for path in files],
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_archive(files: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(ROOT).as_posix())


def main() -> None:
    args = parse_args()
    if args.include_mineru_wheelhouse:
        wheelhouse = ROOT / "vendor" / "mineru-wheelhouse"
        manifest = wheelhouse / "MANIFEST.json"
        has_packages = wheelhouse.exists() and any(
            child.is_file() and child.suffix in {".whl", ".zip", ".gz"}
            for child in wheelhouse.iterdir()
        )
        if not has_packages or not manifest.exists():
            print("missing MinerU wheelhouse. Run ./scripts/build_mineru_wheelhouse.sh first.")
            raise SystemExit(1)

    files = iter_files(args.include_local_platform, args.include_mineru_wheelhouse)
    failures = validate(files)
    if failures:
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    if args.check_only:
        print(f"delivery package boundary is valid. files={len(files)}")
        return

    write_archive(files, args.output)
    write_manifest(files, args.manifest, args.release_name)
    print(f"created {args.output}")
    print(f"created {args.manifest}")
    print(f"files={len(files)}")


if __name__ == "__main__":
    main()
