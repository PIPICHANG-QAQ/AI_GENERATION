#!/usr/bin/env python3
"""Check that question-engine contract, SDK, and docs stay in sync.

This script is intentionally dependency-free so it can run in local development,
CI, or a delivery packaging step before a full OpenAPI generator is introduced.
"""

import html
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MERMAID_SVG_PAIRS = (
    ("docs/architecture/engine-boundary.mmd", "docs/architecture/engine-boundary.svg"),
    ("docs/architecture/import-ocr-workbench-flow.mmd", "docs/architecture/import-ocr-workbench-flow.svg"),
    ("docs/architecture/ocr-flow.mmd", "docs/architecture/ocr-flow.svg"),
    ("docs/architecture/platform-openapi-sdk-overview.mmd", "docs/architecture/platform-openapi-sdk-overview.svg"),
    ("docs/architecture/server-ocr-flow.mmd", "docs/architecture/server-ocr-flow.svg"),
)

MERMAID_NODE_DECLARATION = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\[|\(|\{)", re.MULTILINE)
MERMAID_NODE_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\[|\(|\{)")
MERMAID_CLASS_STATEMENT = re.compile(
    r"^\s*class\s+([A-Za-z_][A-Za-z0-9_,-]*)\s+([A-Za-z_][A-Za-z0-9_-]*)\s*;?\s*$"
)
MERMAID_CLASS_DEFINITION = re.compile(r"^\s*classDef\s+([A-Za-z_][A-Za-z0-9_-]*)\b", re.MULTILINE)
MERMAID_RENDERED_NODE_ID = re.compile(
    r"(?:^|[-_])flowchart-(?P<node_id>[A-Za-z_][A-Za-z0-9_-]*)-(?P<render_index>[0-9]+)$"
)


def normalize_mermaid_label(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def declared_mermaid_semantics(mmd: str) -> tuple[dict[str, str], set[tuple[str, str]], dict[str, set[str]]]:
    labels: dict[str, str] = {}
    classes: dict[str, set[str]] = {}
    lines = mmd.splitlines()
    for line in lines:
        declaration = MERMAID_NODE_LINE.match(line)
        if declaration:
            node_id = declaration.group(1)
            quoted_label = re.search(r'["\'](.*?)["\']', line)
            if quoted_label:
                labels[node_id] = normalize_mermaid_label(quoted_label.group(1))
            inline_class = re.search(r":::\s*([A-Za-z_][A-Za-z0-9_-]*)", line)
            if inline_class:
                classes.setdefault(node_id, set()).add(inline_class.group(1))
        class_statement = MERMAID_CLASS_STATEMENT.match(line)
        if class_statement:
            for node_id in class_statement.group(1).split(","):
                classes.setdefault(node_id, set()).add(class_statement.group(2))

    declared_ids = set(labels)
    id_pattern = re.compile(
        r"(?<![A-Za-z0-9_-])(" + "|".join(sorted((re.escape(item) for item in declared_ids), key=len, reverse=True)) + r")(?![A-Za-z0-9_-])"
    ) if declared_ids else None
    edges: set[tuple[str, str]] = set()
    if id_pattern:
        for line in lines:
            if "->" not in line:
                continue
            without_labels = re.sub(r'".*?"|\|.*?\|', " ", line)
            connected_ids = id_pattern.findall(without_labels)
            edges.update(zip(connected_ids, connected_ids[1:]))
    return labels, edges, classes


def rendered_mermaid_edges(rendered_ids: set[str], declared_nodes: set[str]) -> set[tuple[str, str]]:
    """Map Mermaid edge ids to declared endpoint pairs; duplicate SVG instances collapse into one edge."""
    prefixes = sorted(
        (
            (f"L_{source}_{target}_", (source, target))
            for source in declared_nodes
            for target in declared_nodes
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    edges: set[tuple[str, str]] = set()
    for rendered_id in rendered_ids:
        for prefix, edge in prefixes:
            suffix = rendered_id.removeprefix(prefix)
            if suffix != rendered_id and suffix.isdigit():
                edges.add(edge)
                break
    return edges


def rendered_mermaid_nodes(svg_root: ElementTree.Element) -> dict[str, list[ElementTree.Element]]:
    """Index rendered flowchart node elements while preserving hyphens and underscores in Mermaid ids."""
    nodes: dict[str, list[ElementTree.Element]] = {}
    for element in svg_root.iter():
        rendered_id = element.get("id") or ""
        match = MERMAID_RENDERED_NODE_ID.search(rendered_id)
        if match:
            nodes.setdefault(match.group("node_id"), []).append(element)
    return nodes


def validate_mermaid_svg_pair(mmd_path: Path, svg_path: Path) -> list[str]:
    """Check XML plus rendered flowchart nodes, labels, edges, and classes."""
    mmd = mmd_path.read_text(encoding="utf-8")
    declared_labels, declared_edges, declared_classes = declared_mermaid_semantics(mmd)
    declared_nodes = sorted(set(MERMAID_NODE_DECLARATION.findall(mmd)))
    if not declared_nodes:
        return [f"{mmd_path.name}: no declared flowchart nodes found"]
    try:
        svg_root = ElementTree.parse(svg_path).getroot()
    except ElementTree.ParseError as exc:
        return [f"{svg_path.name}: invalid XML: {exc}"]
    rendered_nodes = rendered_mermaid_nodes(svg_root)
    rendered_edge_ids = {element.get("data-id", "") for element in svg_root.iter() if element.get("data-id")}
    semantic_nodes = set(declared_nodes) | set(rendered_nodes)
    rendered_edges = rendered_mermaid_edges(rendered_edge_ids, semantic_nodes)
    source_custom_classes = set(MERMAID_CLASS_DEFINITION.findall(mmd))
    source_custom_classes.update(
        class_name
        for assigned_classes in declared_classes.values()
        for class_name in assigned_classes
    )
    failures: list[str] = []
    missing_nodes: set[str] = set()
    for node_id in sorted(semantic_nodes):
        node_elements = rendered_nodes.get(node_id) or []
        if not node_elements:
            failures.append(f"{svg_path.name}: missing rendered node id for {node_id}")
            missing_nodes.add(node_id)
            continue
        if node_id not in declared_nodes:
            failures.append(f"{svg_path.name}: unexpected rendered node id for {node_id}")
        expected_label = declared_labels.get(node_id)
        if expected_label:
            rendered_label = normalize_mermaid_label(" ".join(node_elements[0].itertext()))
            if rendered_label != expected_label:
                failures.append(f"{svg_path.name}: stale rendered label for {node_id}: expected '{expected_label}'")
        expected_classes = declared_classes.get(node_id) or set()
        rendered_classes = set((node_elements[0].get("class") or "").split()) & source_custom_classes
        for class_name in sorted(expected_classes - rendered_classes):
            failures.append(f"{svg_path.name}: missing rendered class {class_name} for {node_id}")
        for class_name in sorted(rendered_classes - expected_classes):
            failures.append(f"{svg_path.name}: unexpected rendered class {class_name} for {node_id}")
    for source, target in sorted(declared_edges - rendered_edges):
        if source in missing_nodes or target in missing_nodes:
            continue
        failures.append(f"{svg_path.name}: missing rendered directed edge {source} -> {target}")
    for source, target in sorted(rendered_edges - declared_edges):
        failures.append(f"{svg_path.name}: unexpected rendered directed edge {source} -> {target}")
    return failures


CHECKS = {
    "question-engine/openapi/question-engine.v1.yaml": [
        "securitySchemes",
        "PlatformBearerAuth",
        "TenantHeader",
        "OperatorHeader",
        "/api/import-tasks/{jobId}/image-library",
        "/api/import-tasks/{jobId}/rescan",
        "/api/import-tasks/{jobId}/canonicalization/preview",
        "/api/import-tasks/{jobId}/canonicalization/apply",
        "/api/import-tasks/{jobId}/standardization-jobs",
        "CanonicalizationPreview",
        "CanonicalizationApplyRequest",
        "StandardizationBatchJob",
        "rulesCount",
        "ocrFallbackCount",
        "cacheHitCount",
        "llmQuestionCount",
        "reviewRequiredCount",
        "providerCallAttempts",
        "currentLlmConcurrency",
        "maximumLlmConcurrency",
        "/api/import-tasks/{jobId}/questions/{questionId}/images/select",
        "/api/import-tasks/{jobId}/questions/{questionId}/standardize/ai",
        "/api/import-tasks/{jobId}/questions/{questionId}/analysis",
        "/api/question-bank/questions/{questionId}/image-library",
        "/api/question-bank/questions/{questionId}/standardize/ai",
        "/api/question-bank/questions/{questionId}/analysis",
        "QuestionImageLibrary",
        "ImportTaskRescanResult",
        "SelectQuestionImagesRequest",
        "AiStandardizeRequest",
        "AiStandardizeResult",
        "writeSkippedReason",
        "writeResult",
        "AiAnalysisRequest",
        "AiAnalysisResult",
        "imagePlacements",
        "QuestionImagePlacement",
        "ImagePlacementTarget",
        "ImagePlacementEvidence",
        "ImagePlacementInference",
        "unassigned",
        "explicit-offset",
    ],
    "question-engine/sdk/generated/typescript/QuestionEngineClient.ts": [
        "rescanImportTask",
        "previewImportTaskCanonicalization",
        "createStandardizationBatchJob",
        "getStandardizationBatchJob",
        "getImportTaskImageLibrary",
        "selectImportQuestionImages",
        "standardizeImportQuestion",
        "analyzeImportQuestion",
        "getBankQuestionImageLibrary",
        "standardizeBankQuestion",
        "analyzeBankQuestion",
    ],
    "question-engine/sdk/generated/typescript/models.ts": [
        "QuestionImageLibrary",
        "ImportTaskRescanResult",
        "CanonicalizationPreview",
        "StandardizationBatchJob",
        "SelectQuestionImagesInput",
        "QuestionImageMutationResult",
        "AiStandardizeInput",
        "AiStandardizeResult",
        "writeSkippedReason",
        "AiAnalysisInput",
        "AiAnalysisResult",
        "QuestionImagePlacement",
        "imagePlacements",
    ],
    "question-engine/sdk/generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineClient.java": [
        "rescanImportTask",
        "previewImportTaskCanonicalization",
        "createStandardizationBatchJob",
        "getImportTaskImageLibrary",
        "selectImportQuestionImages",
        "standardizeImportQuestion",
        "getBankQuestionImageLibrary",
        "standardizeBankQuestion",
    ],
    "question-engine/sdk/generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineModels.java": [
        "QuestionImageLibrary",
        "ImportTaskRescanResult",
        "CanonicalizationPreview",
        "StandardizationBatchJob",
        "SelectQuestionImagesRequest",
        "QuestionImageMutationResult",
        "AiStandardizeRequest",
        "AiStandardizeResult",
        "AiAnalysisRequest",
        "AiAnalysisResult",
        "QuestionImagePlacement",
        "imagePlacements",
    ],
    "docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md": [
        "/api/import-tasks/{jobId}/image-library",
        "/api/import-tasks/{jobId}/questions/{questionId}/images/select",
        "standardizeImportQuestion",
        "standardizeBankQuestion",
        "writeResult=false",
        "latexDelimiterRepaired",
        "candidateSevereIssues",
        "question-engine/sdk/USAGE.md",
        "docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md",
        "rescanImportTask",
    ],
    "question-engine/sdk/README.md": [
        "USAGE.md",
        "RELEASE.md",
        "LOCAL_PLATFORM_AS_EXAMPLE.md",
        "../../examples/platform-integration",
    ],
    "question-engine/sdk/RELEASE.md": [
        "OpenAPI",
        "MAJOR.MINOR.PATCH",
        "question-package.v1",
        "breaking",
        "python question-engine/sdk/generate-sdk.py",
    ],
    "question-engine/sdk/USAGE.md": [
        "QuestionEngineClient",
        "createProcessingJob",
        "getQuestionPackage",
        "rescanImportTask",
        "writeResult 默认是 false",
        "writeSkippedReason",
        "latexDelimiterRepaired",
        "question-package.v1",
        "local-platform",
        "接入前提",
        "TypeScript 接入",
        "Java 接入",
        "processingStatus",
        "回调和异步",
        "排错清单",
        "接入验收清单",
        "不要直接调用 Python worker",
    ],
    "docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md": [
        "local-platform",
        "QuestionEngineClient",
        "题目导入",
        "题库中心",
        "组卷中心",
        "知识点库",
        "[封装能力]",
        "[平台自研]",
        "[需配置]",
        "docs/example/local-platform-question-engine-sequence.svg",
        "docs/example/local-platform-business-flow.svg",
        "](../example/local-platform-question-engine-sequence.svg)",
        "](../example/local-platform-business-flow.svg)",
        "/api/import-tasks",
        "/api/capabilities/question-processing/jobs/{jobId}/question-package",
        "question-package.v1",
    ],
    "docs/example/README.md": [
        "](local-platform-question-engine-sequence.svg)",
        "](local-platform-business-flow.svg)",
        "local-platform-question-engine-sequence.svg",
        "local-platform-question-engine-sequence.mmd",
        "local-platform-business-flow.svg",
        "local-platform-business-flow.mmd",
        "[封装能力]",
        "[平台自研]",
        "[需配置]",
    ],
    "docs/example/local-platform-question-engine-sequence.mmd": [
        "QuestionEngineClient",
        "[封装能力]",
        "[本地演示]",
        "[平台自研]",
        "[需配置]",
        "getQuestionPackage",
    ],
    "docs/example/local-platform-question-engine-sequence.svg": [
        "<svg",
        "QuestionEngineClient",
        "getQuestionPackage",
    ],
    "docs/example/local-platform-business-flow.mmd": [
        "模块一：题目导入",
        "模块二：题库中心",
        "模块三：组卷中心",
        "模块四：知识点库",
        "question-package.v1",
        "classDef packaged",
    ],
    "docs/example/local-platform-business-flow.svg": [
        "<svg",
        "模块一：题目导入",
        "question-package.v1",
    ],
    "docs/README.md": [
        "development/DEVELOPMENT_GUIDE.md",
        "development/CONTRIBUTING.md",
        "delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md",
        "delivery/DELIVERY_PACKAGE.md",
        "delivery/OPERATIONS_GUIDE.md",
        "delivery/ACCEPTANCE.md",
        "product/LOCAL_PLATFORM_AS_EXAMPLE.md",
        "architecture/ENGINE_DELIVERY_BOUNDARY.md",
        "architecture/decisions/README.md",
        "samples/",
    ],
    "docs/development/DEVELOPMENT_GUIDE.md": [
        "../delivery/DELIVERY_PACKAGE.md",
        "../delivery/SECURITY_AND_INTEGRATION_CONTRACT.md",
        "../delivery/OPERATIONS_GUIDE.md",
        "../delivery/ERROR_AND_STATUS_GUIDE.md",
        "../delivery/ACCEPTANCE.md",
        "../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md",
        "../product/OCR_PHASE_1_SPEC.md",
        "../architecture/ENGINE_DELIVERY_BOUNDARY.md",
        "CONTRIBUTING.md",
        "../../question-engine/sdk/USAGE.md",
    ],
    "docs/development/CONTRIBUTING.md": [
        "新增或改变 `question-engine` 能力",
        "新增能力变更模板",
        "OCR Provider 插件开发模板",
        "SDK 发布和升级模板",
        "测试分层要求",
        "question-engine/openapi/question-engine.v1.yaml",
        "question-engine/sdk/generated/typescript",
        "question-engine/sdk/generated/java",
        "examples/platform-integration/",
        "docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md",
        "docs/delivery/ACCEPTANCE.md",
    ],
    ".env.example": [
        "PLATFORM_SECURITY_CONTEXT_VALIDATION_ENABLED",
        "PLATFORM_SECURITY_AUTHORIZATION_REQUIRED",
        "PLATFORM_SECURITY_REQUIRED_HEADERS",
    ],
    "backend/src/main/java/com/aigeneration/questionbank/common/PlatformSecurityContextFilter.java": [
        "Missing required platform security headers",
        "Authorization",
    ],
    "backend/src/main/java/com/aigeneration/questionbank/config/PlatformSecurityProperties.java": [
        "X-Tenant-Id",
        "X-Operator-Id",
        "excludedPathPrefixes",
    ],
    "backend/src/test/java/com/aigeneration/questionbank/PlatformSecurityContextFilterTest.java": [
        "platform.security.context-validation-enabled=true",
        "rejectsCapabilityRequestWithoutPlatformHeaders",
        "allowsCapabilityRequestWithPlatformHeaders",
    ],
    "docs/delivery/DELIVERY_PACKAGE.md": [
        "Dockerfile",
        "docker-compose.server.yml",
        "deploy/nginx.conf",
        "--release-name",
        "backend/storage/",
        "backend/target/",
        "backend/python-worker/.venv/",
        "backend/python-worker/tests/",
        "protocal/",
        "scripts/deploy_local.sh",
        "scripts/smoke_deploy_basic.py",
        "scripts/smoke_ocr.py",
        "scripts/smoke_ai.py",
        "scripts/package_question_engine_delivery.py",
        "scripts/acceptance_question_engine_plugin.py",
    ],
    "protocal/README.md": [
        "历史 Replit UI 原型",
        "Do Not Ship",
        "正式交付包必须排除整个 `protocal/` 目录",
        "question-engine/openapi/question-engine.v1.yaml",
    ],
    "docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md": [
        "X-Tenant-Id",
        "X-Operator-Id",
        "X-Question-Engine-Signature",
        "PLATFORM_SECURITY_CONTEXT_VALIDATION_ENABLED=true",
        "PYTHON_WORKER_API_PROXY_ENABLED",
        "HMAC-SHA256",
    ],
    "docs/delivery/OPERATIONS_GUIDE.md": [
        "Java backend",
        "Python worker",
        "./scripts/deploy_local.sh",
        "--with-mineru",
        "--with-ai",
        ".run/deploy.env",
        ".run/logs/",
        "SPRING_PROFILES_ACTIVE",
        "PYTHON_WORKER_API_PROXY_ENABLED=false",
        "MINERU_COMMAND",
        "DASHSCOPE_API_KEY",
        "OCR provider",
        "DashScope",
        "Pandoc",
        "MinIO",
        "callback",
        "数据保留与清理策略",
        "large-file-mb",
        "OCR 并发",
        "SLA",
        "基准测试",
    ],
    "docs/delivery/ERROR_AND_STATUS_GUIDE.md": [
        "PROCESSING",
        "WAITING_REVIEW",
        "COMPLETED",
        "UNSUPPORTED_FILE_TYPE",
        "OCR_PROVIDER_UNAVAILABLE",
        "CALLBACK_DELIVERY_FAILED",
    ],
    "docs/delivery/ACCEPTANCE.md": [
        "./scripts/deploy_local.sh",
        "--with-mineru",
        "--with-ai",
        ".run/deploy.env",
        "--dev-reload",
        "scripts/acceptance_question_engine_plugin.py",
        "question-package.v1",
        "非法文件",
        "callback",
        "large-file-mb",
    ],
    "docs/architecture/decisions/README.md": [
        "0001-java-main-backend.md",
        "0002-python-worker-boundary.md",
        "0003-mineru-default-ocr-provider.md",
        "0004-local-h2-dev-mode.md",
    ],
    "docs/samples/platform-integration/README.md": [
        "paper.md",
        "answer.md",
        "expected-question-package.v1.json",
    ],
    "docs/samples/platform-integration/expected-question-package.v1.json": [
        "question-package.v1",
        "WAITING_REVIEW",
        "stemMarkdown",
        "sourceEvidence",
    ],
    "examples/platform-integration/README.md": [
        "TypeScript",
        "Java",
        "QUESTION_ENGINE_BASE_URL",
        "docs/samples/platform-integration/",
    ],
    "examples/platform-integration/typescript/src/index.ts": [
        "QuestionEngineClient",
        "X-Tenant-Id",
        "getQuestionPackage",
    ],
    "examples/platform-integration/java/src/main/java/com/aigeneration/examples/PlatformIntegrationExample.java": [
        "QuestionEngineClient",
        "X-Tenant-Id",
        "getQuestionPackage",
    ],
    "scripts/acceptance_question_engine_plugin.py": [
        "/api/capabilities/question-processing/jobs",
        "question-package.v1",
        "callback-flow/test",
        "callback signature hmac",
        "source_preview_check",
        "invalid file rejected",
    ],
    "scripts/deploy_local.sh": [
        "--with-mineru",
        "--with-ai",
        "--strict-ports",
        "--dev-reload",
        ".run",
        "smoke_deploy_basic.py",
        "smoke_ocr.py",
        "smoke_ai.py",
    ],
    "scripts/smoke_deploy_basic.py": [
        "basic deployment smoke",
        "/api/java/worker",
        "/api/capabilities",
    ],
    "scripts/smoke_ocr.py": [
        "ocr provider executable",
        "/api/capabilities/ocr-flow/runtime",
        "/api/import-tasks",
    ],
    "scripts/smoke_ai.py": [
        "ai standardize",
        "ai analysis",
        "/standardize/ai",
    ],
    "scripts/package_question_engine_delivery.py": [
        "REQUIRED_IN_PACKAGE",
        "--release-name",
        "contractVersion",
        "storage",
        "protocal",
        "question-engine/openapi/question-engine.v1.yaml",
    ],
}

SOURCE_ONLY_CHECKS = {
    "protocal/README.md",
}


def main() -> None:
    failures: list[str] = []
    for relative_path, expected_items in CHECKS.items():
        path = ROOT / relative_path
        if not path.exists():
            if relative_path in SOURCE_ONLY_CHECKS:
                continue
            failures.append(f"missing file: {relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        for item in expected_items:
            if item not in content:
                failures.append(f"{relative_path}: missing {item}")
    for mmd_relative, svg_relative in MERMAID_SVG_PAIRS:
        failures.extend(validate_mermaid_svg_pair(ROOT / mmd_relative, ROOT / svg_relative))
    if failures:
        for failure in failures:
            print(failure)
        raise SystemExit(1)
    print("question-engine contract, SDK, and docs are in sync.")


if __name__ == "__main__":
    main()
