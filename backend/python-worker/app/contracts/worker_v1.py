"""Stable, additive transport contracts for the Python worker.

These models intentionally describe transport data only.  Existing OCR and AI
functions remain the source of truth for execution and are not reimplemented
here.  ``extra='allow'`` is part of the v1 compatibility promise: a newer
producer can add fields without making an older worker discard them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkerContractModel(BaseModel):
    """Base model with additive forward-compatible fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class WorkerRequestEnvelope(WorkerContractModel):
    schemaVersion: Literal["worker-request.v1"] = "worker-request.v1"
    requestId: str
    traceId: str = ""
    jobId: str = ""
    attemptId: str = ""
    attemptNo: int = 0
    idempotencyKey: str = ""
    inputSha256: str = ""
    pipelineVersion: str
    payload: dict[str, Any]


class WorkerResponseEnvelope(WorkerContractModel):
    schemaVersion: Literal["worker-response.v1"] = "worker-response.v1"
    requestId: str = ""
    traceId: str = ""
    jobId: str = ""
    attemptId: str = ""
    attemptNo: int = 0
    pipelineVersion: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    error: "WorkerError | None" = None


class OcrCreateRequest(WorkerContractModel):
    fileName: str = ""
    contentType: str = ""
    inputSha256: str = ""
    pipelineVersion: str = "ocrflow.v1"
    idempotencyKey: str = ""
    sourcePath: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OcrJobAccepted(WorkerContractModel):
    schemaVersion: Literal["worker-ocr-accepted.v1"] = "worker-ocr-accepted.v1"
    jobId: str
    status: str = "pending"
    requestId: str = ""
    traceId: str = ""
    attemptId: str = ""
    attemptNo: int = 0
    pipelineVersion: str = "ocrflow.v1"
    acceptedAt: str = ""
    pollUrl: str = ""


class OcrJobSnapshot(WorkerContractModel):
    schemaVersion: Literal["worker-ocr-job.v1"] = "worker-ocr-job.v1"
    jobId: str
    status: str
    requestId: str = ""
    traceId: str = ""
    attemptId: str = ""
    attemptNo: int = 0
    pipelineVersion: str = "ocrflow.v1"
    resultUrl: str = ""
    error: "WorkerError | None" = None


class OcrResult(WorkerContractModel):
    schemaVersion: Literal["worker-ocr-result.v1"] = "worker-ocr-result.v1"
    jobId: str
    status: str = "success"
    pipelineVersion: str = "ocrflow.v1"
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list["ArtifactManifest"] = Field(default_factory=list)


class RetryRequest(WorkerContractModel):
    reason: str = ""
    idempotencyKey: str = ""
    attemptNo: int = 0


class QuestionAssemblyRequest(WorkerContractModel):
    jobId: str = ""
    source: dict[str, Any] = Field(default_factory=dict)
    pipelineVersion: str = "question-assembly.v1"


class QuestionAssemblyResponse(WorkerContractModel):
    jobId: str = ""
    questions: list[dict[str, Any]] = Field(default_factory=list)
    pipelineVersion: str = "question-assembly.v1"


class StandardizationRequest(WorkerContractModel):
    markdown: str = ""
    rawOcrContext: str = ""
    structuredHints: dict[str, Any] | None = None
    forceAi: bool = False
    executionMode: str = "ai"
    pipelineVersion: str = "standardization.v1"
    inputSha256: str = ""
    inputHash: str = ""
    requestSource: str = "worker-v1"

    @field_validator("executionMode")
    @classmethod
    def normalize_execution_mode(cls, value: str) -> str:
        mode = str(value or "ai").strip().lower().replace("_", "-")
        if mode not in {"ai", "local", "force-ai"}:
            raise ValueError("executionMode must be one of ai, local, force-ai")
        return mode

    @model_validator(mode="after")
    def sync_input_hash_fields(self) -> "StandardizationRequest":
        if not self.inputHash and self.inputSha256:
            self.inputHash = self.inputSha256
        if not self.inputSha256 and self.inputHash:
            self.inputSha256 = self.inputHash
        return self


class StandardizationResponse(WorkerContractModel):
    markdown: str = ""
    standardizer: dict[str, Any] = Field(default_factory=dict)
    answer: str = ""
    analysis: str = ""


class AnalysisRequest(WorkerContractModel):
    manualMarkdown: str = ""
    type: str = "unknown"
    answer: str = ""
    knowledgePoints: list[str] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    subQuestions: list[dict[str, Any]] = Field(default_factory=list)


class AnalysisResponse(WorkerContractModel):
    analysis: str = ""
    answer: str = ""
    suggestedAnswer: str = ""
    subQuestions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalizationRequest(WorkerContractModel):
    task: dict[str, Any] = Field(default_factory=dict)
    pipelineVersion: str = "canonicalization.v1"


class CanonicalizationResponse(WorkerContractModel):
    questions: list[dict[str, Any]] = Field(default_factory=list)
    canonicalization: dict[str, Any] = Field(default_factory=dict)
    paperLayout: dict[str, Any] = Field(default_factory=dict)


class WorkerError(WorkerContractModel):
    code: str
    message: str
    stage: str = ""
    retryable: bool = False
    requestId: str = ""
    jobId: str = ""
    attemptId: str = ""
    provider: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ArtifactManifest(WorkerContractModel):
    artifactId: str = ""
    kind: str = ""
    sha256: str = ""
    uri: str = ""
    sizeBytes: int = 0
    contentType: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


WorkerResponseEnvelope.model_rebuild()
OcrJobSnapshot.model_rebuild()
OcrResult.model_rebuild()
