#!/usr/bin/env python3
"""Validate the lightweight SDK files against question-engine.v1.yaml.

This local generator is intentionally small and dependency-free. It keeps the
checked-in SDK surface reproducible until the project switches to a full
OpenAPI generator in the delivery pipeline.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "openapi" / "question-engine.v1.yaml"

REQUIRED_OPENAPI_ITEMS = [
    "openapi: 3.0.3",
    "version: 1.1.0",
    "securitySchemes:",
    "PlatformBearerAuth:",
    "TenantHeader:",
    "OperatorHeader:",
    "/api/capabilities/question-processing/jobs:",
    "/api/capabilities/question-processing/jobs/{jobId}:",
    "/api/capabilities/question-processing/jobs/{jobId}/question-package:",
    "/api/import-tasks/{jobId}/rescan:",
    "CreateProcessingJobRequest:",
    "ProcessingJob:",
    "ImportTaskRescanResult:",
    "QuestionPackage:",
    "QuestionImageLibrary:",
    "QuestionImagePlacement:",
    "ImagePlacementTarget:",
    "AiAnalysisRequest:",
    "AiAnalysisResult:",
    "CallbackEvent:",
]

EXPECTED_OPERATION_IDS = [
    "listCapabilities",
    "getEngineCatalog",
    "getEngineInterfaces",
    "getDeliveryBoundary",
    "getQuestionProcessingCapability",
    "listProcessingJobs",
    "createProcessingJob",
    "getProcessingJob",
    "getQuestionPackage",
    "rescanImportTask",
    "getOcrFlowCapability",
    "getOcrFlowRuntime",
    "getAiFlowRuntime",
    "getExportFlowRuntime",
    "getFileFlowRuntime",
    "getImportTaskImageLibrary",
    "uploadImportQuestionImages",
    "selectImportQuestionImages",
    "getImportQuestionImage",
    "standardizeImportQuestion",
    "analyzeImportQuestion",
    "getBankQuestionImageLibrary",
    "uploadBankQuestionImages",
    "getBankQuestionImage",
    "standardizeBankQuestion",
    "analyzeBankQuestion",
    "getCallbackFlowRuntime",
    "listCallbackEvents",
    "createCallbackTestEvent",
    "retryCallbackEvent",
    "retryDueCallbackEvents",
]

EXPECTED_SDK_METHODS = [
    "listCapabilities",
    "getEngineCatalog",
    "getEngineInterfaces",
    "getDeliveryBoundary",
    "getQuestionProcessingCapability",
    "getProcessingJob",
    "getQuestionPackage",
    "rescanImportTask",
    "getImportTaskImageLibrary",
    "selectImportQuestionImages",
    "standardizeImportQuestion",
    "analyzeImportQuestion",
    "getBankQuestionImageLibrary",
    "standardizeBankQuestion",
    "analyzeBankQuestion",
    "listCallbackEvents",
    "retryCallbackEvent",
]

REQUIRED_SCHEMA_FIELDS = {
    "ProcessingJob": ["jobId", "status", "processingStatus"],
    "QuestionPackage": ["packageVersion", "capability", "job", "questions", "warnings"],
    "ProcessedQuestion": ["questionId", "stemMarkdown", "images", "options", "children", "mathValidation", "sourceEvidence"],
    "CreateProcessingJobRequest": ["paperFile"],
    "ImportTaskRescanResult": ["taskId", "status", "rescanInProgress", "rescannedJobs"],
    "QuestionImageLibrary": ["items"],
    "QuestionImageMutationResult": ["images"],
    "AiStandardizeRequest": ["markdown"],
    "AiStandardizeResult": ["aiJobId", "writeResult", "markdown"],
    "CreateCallbackEventRequest": ["callbackUrl"],
}


def section_after(text: str, marker: str) -> str:
    """Return the indented section after a top-level OpenAPI marker."""
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for candidate in ("\npaths:", "\ncomponents:", "\n  parameters:", "\n  schemas:"):
        index = text.find(candidate, start)
        if index > start:
            end = min(end, index)
    return text[start:end]


def collect_component_names(text: str, marker: str) -> set[str]:
    section = section_after(text, marker)
    return set(re.findall(r"^    ([A-Za-z][A-Za-z0-9_]*):\s*$", section, flags=re.MULTILINE))


def schema_block(text: str, schema_name: str) -> str:
    schemas = section_after(text, "\n  schemas:")
    match = re.search(rf"^    {re.escape(schema_name)}:\s*$", schemas, flags=re.MULTILINE)
    if not match:
        return ""
    next_match = re.search(r"^    [A-Za-z][A-Za-z0-9_]*:\s*$", schemas[match.end():], flags=re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(schemas)
    return schemas[match.start():end]


def required_fields(block: str) -> set[str]:
    match = re.search(r"required:\s*\[([^\]]+)]", block)
    if not match:
        return set()
    return {item.strip() for item in match.group(1).split(",") if item.strip()}


def main() -> None:
    if not OPENAPI.exists():
        raise SystemExit(f"missing OpenAPI source: {OPENAPI}")
    openapi_text = OPENAPI.read_text(encoding="utf-8")
    failures: list[str] = []
    for item in REQUIRED_OPENAPI_ITEMS:
        if item not in openapi_text:
            failures.append(f"OpenAPI missing required item: {item}")

    operation_ids = re.findall(r"operationId:\s*([A-Za-z0-9_]+)", openapi_text)
    duplicates = sorted({item for item in operation_ids if operation_ids.count(item) > 1})
    if duplicates:
        failures.append("OpenAPI duplicate operationId: " + ", ".join(duplicates))
    for operation_id in EXPECTED_OPERATION_IDS:
        if operation_id not in operation_ids:
            failures.append(f"OpenAPI missing operationId: {operation_id}")

    schemas = collect_component_names(openapi_text, "\n  schemas:")
    parameters = collect_component_names(openapi_text, "\n  parameters:")
    security_schemes = collect_component_names(openapi_text, "\n  securitySchemes:")
    refs = re.findall(r'\$ref:\s*"#/components/(schemas|parameters|securitySchemes)/([^"]+)"', openapi_text)
    for ref_type, ref_name in refs:
        available = {
            "schemas": schemas,
            "parameters": parameters,
            "securitySchemes": security_schemes,
        }[ref_type]
        if ref_name not in available:
            failures.append(f"OpenAPI unresolved $ref: #/components/{ref_type}/{ref_name}")

    if "security:\n  - PlatformBearerAuth: []\n    TenantHeader: []\n    OperatorHeader: []" not in openapi_text:
        failures.append("OpenAPI top-level security must require PlatformBearerAuth, TenantHeader, and OperatorHeader")
    if "security: []" in openapi_text:
        failures.append("OpenAPI contains an operation-level security override that disables auth")

    for schema_name, fields in REQUIRED_SCHEMA_FIELDS.items():
        block = schema_block(openapi_text, schema_name)
        if not block:
            failures.append(f"OpenAPI missing required schema: {schema_name}")
            continue
        actual_required = required_fields(block)
        for field in fields:
            if field not in actual_required:
                failures.append(f"OpenAPI schema {schema_name} missing required field: {field}")

    generated = [
        ROOT / "sdk" / "generated" / "typescript" / "models.ts",
        ROOT / "sdk" / "generated" / "typescript" / "QuestionEngineClient.ts",
        ROOT / "sdk" / "generated" / "typescript" / "index.ts",
        ROOT / "sdk" / "generated" / "java" / "src" / "main" / "java" / "com" / "aigeneration" / "questionengine" / "sdk" / "QuestionEngineModels.java",
        ROOT / "sdk" / "generated" / "java" / "src" / "main" / "java" / "com" / "aigeneration" / "questionengine" / "sdk" / "QuestionEngineClient.java",
    ]
    for path in generated:
        if not path.exists():
            failures.append(f"generated SDK file is missing: {path}")

    ts_client = (ROOT / "sdk" / "generated" / "typescript" / "QuestionEngineClient.ts")
    java_client = (ROOT / "sdk" / "generated" / "java" / "src" / "main" / "java" / "com" / "aigeneration" / "questionengine" / "sdk" / "QuestionEngineClient.java")
    if ts_client.exists() and java_client.exists():
        ts_text = ts_client.read_text(encoding="utf-8")
        java_text = java_client.read_text(encoding="utf-8")
        for method in EXPECTED_SDK_METHODS:
            if method not in ts_text:
                failures.append(f"TypeScript SDK missing method: {method}")
            if method not in java_text:
                failures.append(f"Java SDK missing method: {method}")

    if failures:
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print(f"OpenAPI source: {OPENAPI}")
    print("OpenAPI contract and checked-in SDK files are consistent.")
    print("Generated SDK files:")
    for path in generated:
        print(f"- {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
