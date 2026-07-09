# Question Engine SDK

This folder contains the OpenAPI contract, generated SDK surface, and legacy
examples for platform teams.

Start here:

- `USAGE.md`：面向平台开发者的 SDK 使用说明、TypeScript/Java 示例、任务轮询、标准题目包消费和接入边界。
- `RELEASE.md`：SDK 版本、发布方式、兼容策略、升级流程和 breaking change 规则。

Source of truth:

- `../openapi/question-engine.v1.yaml`

Generated SDK entry points:

- `generated/typescript/QuestionEngineClient.ts`
- `generated/typescript/models.ts`
- `generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineClient.java`
- `generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineModels.java`

Legacy handwritten clients were moved to `examples/`. They are kept only as
usage references and should not be treated as the platform integration source.

Stable HTTP entry points:

- `GET /api/capabilities`
- `GET /api/engine`
- `GET /api/engine/interfaces`
- `POST /api/capabilities/question-processing/jobs`
- `GET /api/capabilities/question-processing/jobs/{jobId}`
- `GET /api/capabilities/question-processing/jobs/{jobId}/question-package`
- `GET /api/import-tasks/{jobId}`
- `POST /api/import-tasks/{jobId}/rescan`
- `GET /api/import-tasks/{jobId}/source/paper/pages/{pageIndex}`
- `GET /api/import-tasks/{jobId}/image-library`
- `POST /api/import-tasks/{jobId}/questions/{questionId}/images/select`
- `POST /api/import-tasks/{jobId}/questions/{questionId}/standardize/ai`
- `POST /api/import-tasks/{jobId}/questions/{questionId}/analysis`
- `GET /api/question-bank/questions/{questionId}/image-library`
- `POST /api/question-bank/questions/{questionId}/standardize/ai`
- `POST /api/question-bank/questions/{questionId}/analysis`

The SDKs intentionally cover the engine boundary only. Local admin pages, prototype routes, and demo assets are not part of the SDK surface.

`local-platform` is only a demo shell and workflow example. See `../../docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` before reusing any local page behavior.

Capability-specific APIs such as review-workbench OCR rescan, image libraries, file-flow image selection, AI standardize writeback, AI analysis, and callback events are part of the generated SDK surface. Export jobs and lower-level runtime diagnostics remain discoverable through `GET /api/capabilities` and can be expanded in SDK packages as platform usage stabilizes.

Review-workbench layout boxes are exposed as readonly `paperLayout` on `GET /api/import-tasks/{jobId}` plus page images from `GET /api/import-tasks/{jobId}/source/paper/pages/{pageIndex}`. Generated SDK packages may consume these APIs through direct HTTP until the platform decides whether to formalize them as first-class SDK methods.

Current TypeScript client includes multipart helpers for local image upload. Current Java client covers JSON APIs; multipart file upload should be generated from OpenAPI by the platform build pipeline when needed.

Regenerate/check SDK files:

```bash
python question-engine/sdk/generate-sdk.py
```

Platform integration examples:

- `../../examples/platform-integration`
