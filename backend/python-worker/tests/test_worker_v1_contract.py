from __future__ import annotations

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
