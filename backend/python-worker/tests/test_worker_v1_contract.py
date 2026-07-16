from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.contracts.worker_v1 import (
    ArtifactManifest,
    OcrCreateRequest,
    WorkerError,
    WorkerRequestEnvelope,
)
from app.main import app


def test_request_envelope_preserves_unknown_extension_fields() -> None:
    envelope = WorkerRequestEnvelope.model_validate(
        {
            "requestId": "request-1",
            "traceId": "trace-1",
            "pipelineVersion": "ocrflow.v1",
            "payload": {"fileName": "paper.pdf"},
            "futureFlag": True,
            "futureObject": {"version": 2},
        }
    )

    encoded = envelope.model_dump(mode="json", by_alias=True)

    assert envelope.schemaVersion == "worker-request.v1"
    assert encoded["futureFlag"] is True
    assert encoded["futureObject"] == {"version": 2}


def test_contract_models_have_stable_json_field_names() -> None:
    request = OcrCreateRequest(
        fileName="paper.pdf",
        contentType="application/pdf",
        inputSha256="a" * 64,
        pipelineVersion="ocrflow.v1",
    )
    error = WorkerError(
        code="OCR_PROVIDER_TIMEOUT",
        message="provider timed out",
        stage="provider",
        retryable=True,
        requestId="request-1",
        jobId="job-1",
        attemptId="attempt-1",
        provider="mineru",
    )
    artifact = ArtifactManifest(artifactId="artifact-1", sha256="b" * 64, kind="question-package")

    assert request.model_dump(by_alias=True)["fileName"] == "paper.pdf"
    assert error.model_dump(by_alias=True)["retryable"] is True
    assert artifact.model_dump(by_alias=True)["artifactId"] == "artifact-1"


def test_v1_capabilities_is_additive_and_lists_supported_operations() -> None:
    client = TestClient(app)

    response = client.get("/worker/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "worker-capabilities.v1"
    assert "ocr.create" in body["operations"]
    assert "canonicalization.preview" in body["operations"]
    assert "question-assembly" not in body["operations"]


def test_v1_standardize_delegates_to_existing_ai_path(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_standardize(payload):
        called["payload"] = payload
        return {"markdown": "normalized", "standardizer": {"source": "local"}}

    monkeypatch.setattr("app.routes.worker_v1.worker_standardize_markdown_ai", fake_standardize)
    client = TestClient(app)
    response = client.post(
        "/worker/v1/standardize",
        json={"markdown": "raw", "pipelineVersion": "standardization.v1"},
    )

    assert response.status_code == 200
    assert response.json()["markdown"] == "normalized"
    assert called["payload"].markdown == "raw"


def test_v1_standardize_delegates_force_ai_execution_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_standardize(payload):
        called["payload"] = payload
        return {"markdown": "normalized", "standardizer": {"source": "ai"}}

    monkeypatch.setattr("app.routes.worker_v1.worker_standardize_markdown_ai", fake_standardize)
    client = TestClient(app)
    response = client.post(
        "/worker/v1/standardize",
        json={"markdown": "raw", "forceAi": True, "executionMode": "force-ai"},
    )

    assert response.status_code == 200
    assert called["payload"].markdown == "raw"
    assert called["payload"].forceAi is True
    assert called["payload"].executionMode == "force-ai"


def test_v1_standardize_real_route_accepts_input_sha256_as_legacy_input_hash() -> None:
    client = TestClient(app)
    response = client.post(
        "/worker/v1/standardize",
        json={
            "markdown": "选择正确答案（ ）A. 甲 B. 乙 C. 丙 D. 丁",
            "structuredHints": {"questionId": "v1-q1", "type": "choice", "options": []},
            "executionMode": "local",
            "inputSha256": "abc123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["executionPath"] == "local"
    assert body["modelInvoked"] is False
    assert body["inputHash"] == "abc123"


def test_v1_standardize_real_route_accepts_legacy_input_hash() -> None:
    client = TestClient(app)
    response = client.post(
        "/worker/v1/standardize",
        json={
            "markdown": "选择正确答案（ ）A. 甲 B. 乙 C. 丙 D. 丁",
            "structuredHints": {"questionId": "v1-q2", "type": "choice", "options": []},
            "executionMode": "local",
            "inputHash": "legacy123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["executionPath"] == "local"
    assert body["inputHash"] == "legacy123"


def test_openapi_standardization_batch_execution_path_includes_two_stage_values() -> None:
    openapi = Path(__file__).resolve().parents[3] / "question-engine/openapi/question-engine.v1.yaml"
    content = openapi.read_text(encoding="utf-8")

    assert "executionPath: { type: string, enum: [rules, ocr-fallback, cache, llm, local, force-ai] }" in content


def test_generic_standardize_route_ignores_public_force_ai_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_standardize(markdown: str, **kwargs):
        called["markdown"] = markdown
        called["kwargs"] = kwargs
        return {"markdown": "normalized", "standardizer": {"source": "ai"}}

    monkeypatch.setattr("app.worker_routes.standardize_markdown_ai_response", fake_standardize)
    client = TestClient(app)
    response = client.post(
        "/api/markdown/standardize/ai",
        json={"markdown": "raw", "forceAi": True, "executionMode": "force-ai"},
    )

    assert response.status_code == 200
    assert called["markdown"] == "raw"
    assert "force_ai" not in called["kwargs"]
    assert "execution_mode" not in called["kwargs"]


def test_worker_standardize_route_honors_internal_force_ai_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_standardize(markdown: str, **kwargs):
        called["markdown"] = markdown
        called["kwargs"] = kwargs
        return {"markdown": "normalized", "standardizer": {"source": "ai"}}

    monkeypatch.setattr("app.worker_routes.standardize_markdown_ai_response", fake_standardize)
    client = TestClient(app)
    response = client.post(
        "/worker/ai/standardize",
        json={"markdown": "raw", "forceAi": True, "executionMode": "force-ai"},
    )

    assert response.status_code == 200
    assert called["markdown"] == "raw"
    assert called["kwargs"]["force_ai"] is True
    assert called["kwargs"]["execution_mode"] == "force-ai"
