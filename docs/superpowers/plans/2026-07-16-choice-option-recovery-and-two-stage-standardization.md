# 粘连选择题选项恢复与两阶段标准化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让明确粘连在 `tasks` 内的 C/D 选项被无损拆分，并让导入题的首次标准化仅走本地候选、第二次同轮点击强制真实调用 AI。

**Architecture:** Python 和 TypeScript 各自实现同一份保守的 `tasks` 内联标签链恢复规则。导入题公开接口由 Java 编排层拥有：它将前端的 `forceAi` 转换为 Python Worker 内部 `local` 或 `force-ai` 执行模式；普通标准化继续是 `ai`。前端仅在导入题编辑卡片中维护本轮编辑的阶段状态，并将第二次请求显式标记为 `forceAi=true`。

**Tech Stack:** Python 3.11、FastAPI/Pydantic、pytest、TypeScript、React、TanStack Query、Vitest、Docker Compose。

---

## 文件职责

- `backend/python-worker/app/question_markdown.py`：解析与无损恢复 `tasks` 内的粘连选项。
- `backend/python-worker/app/import_services.py`：构造本地候选、阶段缓存、强制 AI 失败信封。
- `backend/python-worker/app/llm_splitter.py`：允许标准化调用显式跳过路由缓存。
- `backend/python-worker/app/worker_base.py`、`backend/python-worker/app/contracts/worker_v1.py`、`backend/python-worker/app/worker_routes.py`：传递兼容的 `forceAi` 字段和执行模式。
- `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`：在导入题 Java 入口将 `forceAi` 派生为受控 worker 执行模式。
- `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`：验证 Java 导入题入口把 `forceAi` 传至 worker。
- `question-engine/openapi/question-engine.v1.yaml`：声明公开请求的兼容 `forceAi` 字段。
- `local-platform/src/lib/question.ts`：与 Python 一致地解析粘连 `tasks` 选项。
- `local-platform/src/lib/interactive-standardization.ts`：纯函数管理“下一次是否强制 AI”的编辑会话状态。
- `local-platform/src/components/question-bank/QuestionCard.tsx`：仅导入题编辑界面发送 `forceAi` 并切换按钮文案。
- `local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx`：明确展示强制 AI 失败，避免被当成成功候选。
- `scripts/smoke_ai.py`：部署后验证本地阶段和强制 AI 阶段。

### Task 1: Python 粘连 `tasks` 选项恢复

**Files:**
- Modify: `backend/python-worker/app/question_markdown.py:202-260,941-971`
- Modify: `backend/python-worker/tests/test_question_markdown.py:1-58`

- [x] **Step 1: 写失败测试，固定截图同构题和反例**

```python
def test_recovers_glued_tasks_chain_outside_inline_math(self):
    markdown = r"""题干
\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ C $5.5 \times 10^{7}$ D．$5.5 \times 10^{8}$
\end{tasks}"""

    stem, options = split_choice_options(markdown, "choice")

    self.assertEqual("题干", stem)
    self.assertEqual(["A", "B", "C", "D"], [item["label"] for item in options])
    self.assertEqual("$55 \\times 10^{6}$", options[1]["content"])
    self.assertEqual("$5.5 \\times 10^{7}$", options[2]["content"])
    self.assertEqual("$5.5 \\times 10^{8}$", options[3]["content"])

def test_does_not_split_math_variable_or_incomplete_glued_tasks_chain(self):
    markdown = r"""题干
\begin{tasks}(2)
\task 甲
\task $C$ 是常数，点 D．
\end{tasks}"""

    _stem, options = split_choice_options(markdown, "choice")

    self.assertEqual(["A", "B"], [item["label"] for item in options])
    self.assertIn("$C$", options[1]["content"])
```

Add nine further regressions before implementation: a chain in a non-final `\\task` followed by a valid later task must still recover every label in order; labels inside `$$...$$`, `\\(...\\)` or `\\[...\\]` math must never be split; a non-contiguous `C ... E．...` sequence must remain whole; `点 D．...` must remain whole even with option punctuation; an unclosed unescaped `$`, `\\(`, or `\\[` must block recovery; and any empty `\\task` must block recovery for the whole block. Preserve the intended positive case for an explicit punctuated text chain `C. ... D．...`—the rule is not formula-only—an independent external C/D chain after an earlier formula contains a decoy `C.` label, and a bare expected label directly before a Markdown image. Labels inside a complete image alt/path must not split it, while an independent external chain after that image may recover.

- [x] **Step 2: 运行测试，确认当前实现无法恢复 C/D**

Run:

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests/test_question_markdown.py -q
```

Expected: 新增的同构题断言失败，当前结果只有 A/B。

- [x] **Step 3: 在 `question_markdown.py` 加入保守恢复器，并让 `split_tasks_options` 使用它**

```python
TASK_INLINE_OPTION_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<label>[A-HＡ-Ｈａ-ｈ])(?P<punct>[.．、:：])?"
    r"(?=\s*(?:\$|!\[|[（(\[]|[\u4e00-\u9fff0-9]))"
)

def is_outside_math(value: str, offset: int) -> bool:
    # Treat $...$, $$...$$, \(...\), and \[...\] as protected math ranges.
    ...

def recover_glued_task_parts(parts: list[str]) -> list[str]:
    recovered: list[str] = []
    for part in parts:
        recovered.append(part)
        expected = chr(ord("A") + len(recovered))
        markers: list[tuple[int, int, str]] = []
        for match in TASK_INLINE_OPTION_RE.finditer(part):
            label = normalize_choice_label(match.group("label"))
            previous = part[:match.start()].rstrip()[-1:]
            if label != expected or not is_outside_math(part, match.start()):
                continue
            if not match.group("punct") and previous not in {"$", ")", "]", "）", "】"}:
                continue
            markers.append((match.start(), match.end(), label))
            expected = chr(ord(expected) + 1)
        if len(markers) < 2:
            continue
        values = [part[:markers[0][0]].strip()]
        values.extend(
            part[end : markers[index + 1][0] if index + 1 < len(markers) else len(part)].strip()
            for index, (_start, end, _label) in enumerate(markers)
        )
        if all(values):
            recovered[-1:] = values
    return recovered
```

Then change `split_tasks_options` from:

```python
task_parts = re.split(r"\\task\b", body)[1:]
```

to:

```python
task_parts = recover_glued_task_parts(re.split(r"\\task\b", body)[1:])
```

- [x] **Step 4: 运行 Python 解析测试，确认 GREEN**

Run:

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests/test_question_markdown.py -q
```

Expected: 所有 `QuestionMarkdownTest` 用例通过，包含截图同构题和数学变量反例。

- [x] **Step 5: 提交解析恢复的独立提交**

```bash
git add backend/python-worker/app/question_markdown.py backend/python-worker/tests/test_question_markdown.py
git commit -m "fix: recover glued choice task options"
```

### Task 2: 前端解析与 Python 保持一致

**Files:**
- Modify: `local-platform/src/lib/question.ts:918-945`
- Modify: `local-platform/src/lib/question.test.ts`

- [x] **Step 1: 写 Vitest 失败测试**

```ts
it("recovers a consecutive C/D chain glued into a tasks item", () => {
  const result = getQuestionMarkdownParts([
    "题干",
    "\\begin{tasks}(2)",
    "\\task $5500 \\times 10^{4}$",
    "\\task $55 \\times 10^{6}$ C $5.5 \\times 10^{7}$ D．$5.5 \\times 10^{8}$",
    "\\end{tasks}",
  ].join("\n"), "choice");

  expect(result.options.map((option) => option.label)).toEqual(["A", "B", "C", "D"]);
  expect(result.options.map((option) => option.content)).toEqual([
    "$5500 \\times 10^{4}$", "$55 \\times 10^{6}$", "$5.5 \\times 10^{7}$", "$5.5 \\times 10^{8}$",
  ]);
});
```

Mirror the Python parser fixtures as well: a recovered chain in a non-final task must keep later labels aligned; `$...$`, `$$...$$`, `\\(...\\)` and `\\[...\\]` must not split; `$C$`, `点 D．...`, incomplete chains, and `C ... E．...` must remain a single existing task item.

- [x] **Step 2: 运行目标测试，确认 RED**

Run:

```bash
npm --prefix local-platform test -- --run src/lib/question.test.ts
```

Expected: 新增断言返回两个选项而失败。

- [x] **Step 3: 以与 Python 相同的保护条件扩展 `splitTasksOptions`**

```ts
const taskInlineOption = /(?<![A-Za-z0-9])([A-HＡ-Ｈａ-ｈ])([.．、:：])?(?=\s*(?:\$|!\[|[（(\[]|[\u4e00-\u9fff0-9]))/g;

function isMathPosition(value: string, offset: number) {
  // Mirror Python: $...$, $$...$$, \\(...\\), and \\[...\\] protect inline labels.
  ...
}

function recoverGluedTaskParts(parts: string[]) {
  const recovered: string[] = [];
  for (const part of parts) {
    recovered.push(part);
    let expected = String.fromCharCode("A".charCodeAt(0) + recovered.length);
    const markers: Array<{ start: number; end: number }> = [];
    for (const match of part.matchAll(taskInlineOption)) {
      const label = normalizeChoiceLabel(match[1] || "");
      const previous = part.slice(0, match.index).trimEnd().slice(-1);
      if (label !== expected || !outsideInlineMath(part, match.index ?? 0)) continue;
      if (!match[2] && !["$", ")", "]", "）", "】"].includes(previous)) continue;
      markers.push({ start: match.index ?? 0, end: (match.index ?? 0) + match[0].length });
      expected = String.fromCharCode(expected.charCodeAt(0) + 1);
    }
    if (markers.length < 2) continue;
    const values = [part.slice(0, markers[0].start).trim(), ...markers.map((marker, index) =>
      part.slice(marker.end, markers[index + 1]?.start).trim())];
    if (values.every(Boolean)) recovered.splice(-1, 1, ...values);
  }
  return recovered;
}
```

Use `recoverGluedTaskParts` before mapping `taskParts` to A/B/C/D options.

- [x] **Step 4: 运行目标前端测试，确认 GREEN**

Run:

```bash
npm --prefix local-platform test -- --run src/lib/question.test.ts
```

Expected: 现有 11 项与新增粘连选项测试均通过。

- [x] **Step 5: 提交前端解析一致性提交**

```bash
git add local-platform/src/lib/question.ts local-platform/src/lib/question.test.ts
git commit -m "fix: mirror glued choice recovery in editor"
```

### Task 3: 后端两阶段标准化与无缓存强制 AI

**Files:**
- Modify: `backend/python-worker/app/worker_base.py:118-130`
- Modify: `backend/python-worker/app/contracts/worker_v1.py:106-119`
- Modify: `backend/python-worker/app/worker_routes.py:350-364,820-827`
- Modify: `backend/python-worker/app/import_services.py:26-94,1001-1012,1310-1564`
- Modify: `backend/python-worker/app/llm_splitter.py:405-436,814-940`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java:122-140`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java:1215-1351`
- Modify: `question-engine/openapi/question-engine.v1.yaml:1173-1195`
- Modify: `backend/python-worker/tests/test_import_services.py`
- Modify: `backend/python-worker/tests/test_llm_splitter.py`
- Modify: `backend/python-worker/tests/test_worker_v1_contract.py`

- [x] **Step 1: 写阶段和失败信封的失败测试**

```python
GLUED_TASKS_MARKDOWN = r"""题干
\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ C $5.5 \times 10^{7}$ D．$5.5 \times 10^{8}$
\end{tasks}"""
TWO_OPTIONS = [
    {"label": "A", "content": "$5500 \\times 10^{4}$"},
    {"label": "B", "content": "$55 \\times 10^{6}$ C $5.5 \\times 10^{7}$ D．$5.5 \\times 10^{8}$"},
]
AI_SUCCESS_METADATA = {
    "source": "ai", "provider": "mock", "model": "mock-model", "error": None,
    "corrections": [], "warnings": [], "confidence": "high", "answer": "", "analysis": "",
}
AI_FAILURE_METADATA = {
    "source": "ai", "provider": "mock", "model": "mock-model", "error": "model timed out",
    "corrections": [], "warnings": [], "confidence": "low", "answer": "", "analysis": "",
}

def test_import_local_standardization_recovers_glued_options_without_llm(self):
    with patch("app.import_services.standardize_markdown_with_llm") as llm:
        result = standardize_markdown_ai_response(
            GLUED_TASKS_MARKDOWN,
            structured_hints={"type": "choice", "options": TWO_OPTIONS},
            execution_mode="local",
        )
    llm.assert_not_called()
    self.assertEqual("local", result["executionPath"])
    self.assertFalse(result["modelInvoked"])
    self.assertEqual(4, len(result["options"]))

def test_force_ai_bypasses_standardization_and_router_caches(self):
    with patch("app.import_services.standardize_markdown_with_llm") as llm:
        llm.return_value = ("题干", AI_SUCCESS_METADATA)
        result = standardize_markdown_ai_response("题干", execution_mode="force-ai")
    llm.assert_called_once()
    self.assertTrue(result["modelInvoked"])
    self.assertFalse(result["cacheHit"])
    self.assertEqual("force-ai", result["executionPath"])

def test_force_ai_failure_is_blocked_and_never_returns_local_fallback(self):
    with patch("app.import_services.standardize_markdown_with_llm", return_value=(None, AI_FAILURE_METADATA)):
        result = standardize_markdown_ai_response("题干", execution_mode="force-ai")
    self.assertTrue(result["modelInvoked"])
    self.assertTrue(result["standardizer"]["forceAiFailed"])
    self.assertFalse(result["standardizer"]["fallbackUsed"])
    self.assertTrue(result["standardizer"]["applyBlocked"])
    self.assertEqual("题干", result["markdown"])
```

Add a Python compatibility route test that posts `{ "markdown": "题干", "forceAi": true, "executionMode": "force-ai" }` to `/worker/v1/standardize` and asserts the delegate receives both fields. Add a Java `DomainControllerTest` that posts `{ "markdown": "题干", "forceAi": true }` to the public import-question endpoint and asserts the captured `/worker/ai/standardize` JSON contains `forceAi=true` and `executionMode=force-ai`; a false request must yield `executionMode=local`.

- [x] **Step 2: 运行目标测试，确认 RED**

Run:

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests/test_import_services.py backend/python-worker/tests/test_llm_splitter.py backend/python-worker/tests/test_worker_v1_contract.py -q
```

Expected: 新增 `execution_mode`、`forceAi` 与强制无缓存断言失败。

- [x] **Step 3: 扩展请求模型和接口模式选择**

```python
class MarkdownPayload(BaseModel):
    markdown: str = Field(default="", max_length=100000)
    rawOcrContext: str = Field(default="", max_length=100000)
    structuredHints: dict[str, Any] | None = None
    pipelineVersion: str = Field(default="standardization.v1", max_length=80)
    inputHash: str = Field(default="", max_length=128)
    requestSource: str = Field(default="single", max_length=40)
    forceAi: bool = False
    executionMode: str = Field(default="ai", max_length=20)
```

Apply both additive fields to `StandardizationRequest`. In Java `AiFlowOrchestrationService.standardizeImportQuestion`, derive a trusted worker request only for this import route:

```java
boolean forceAi = booleanValue(payload.get("forceAi"));
request.put("forceAi", forceAi);
request.put("executionMode", forceAi ? "force-ai" : "local");
```

Have the Python worker accept only `ai` / `local` / `force-ai`, map the imported worker request to its execution mode, and keep generic `/api/markdown/standardize/ai` and existing worker callers on `ai`. Add `forceAi: boolean` to the public `AiStandardizeRequest` OpenAPI schema; `executionMode` remains an internal Java-to-worker field.

Include a stable question scope in direct-Python structured hints so the local cache cannot cross questions:

```python
def standardize_question_hints(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "questionId": str(question.get("id") or ""),
        "number": question.get("number"),
        "type": question.get("type"),
        "answer": question.get("answer", ""),
        "options": question.get("options", []),
        "imageCount": len(question.get("images") or []),
        "subQuestions": normalize_sub_questions(question.get("subQuestions") or question.get("children")),
    }
```

- [x] **Step 4: 实现本地阶段、阶段化缓存和强制 AI 失败信封**

Change the cache key to include a stage and bump its version:

```python
AI_STANDARDIZE_CACHE_VERSION = "2026-07-16-two-stage-choice-recovery-v1"

def standardize_cache_key(markdown, raw_ocr_context, structured_hints, stage="ai"):
    payload = {
        "version": AI_STANDARDIZE_CACHE_VERSION,
        "stage": stage,
        "markdown": str(markdown or ""),
        "rawOcrContext": str(raw_ocr_context or ""),
        "structuredHints": structured_hints or {},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
```

In `standardize_markdown_ai_response`, accept `execution_mode: str = "ai"`. For `"local"`, rebuild a choice `tasks` block only when `split_choice_options` exposes more consecutive options than `structured_hints.options`, run existing deterministic normalization/render validation, set `executionPath="local"`, `modelInvoked=False`, and cache only under `stage="local"`.

For `"force-ai"`, never read or write `AI_STANDARDIZE_CACHE`; call the LLM with `bypass_cache=True`. If it returns no Markdown, return this non-fallback envelope through `finalize_standardize_response`:

```python
{
    "markdown": markdown,
    "standardizer": {
        **metadata,
        "source": "ai",
        "fallbackUsed": False,
        "forceAiFailed": True,
        "applyBlocked": True,
        "status": "failed",
        "changed": False,
        "warnings": [str(metadata.get("error") or "强制 AI 标准化失败")],
        "candidateSevereIssues": [],
        "renderValidation": {"valid": False, "issues": ["force_ai_failed"]},
    },
}
```

- [x] **Step 5: 让 LLM 路由缓存可显式绕过**

```python
def post_llm_json_for_endpoint(endpoint, payload, timeout_seconds, task_type, *, bypass_cache=False):
    routed_payload = {**payload, "model": endpoint.get("model") or payload.get("model")}
    cache_key = llm_cache_key(endpoint, task_type, routed_payload)
    if not bypass_cache:
        cached = cached_llm_response(cache_key)
        if cached is not None:
            return cached, True
    # existing HTTP request and response validation
    if not bypass_cache:
        store_llm_response(cache_key, data)
    return data, False
```

Add `bypass_cache: bool = False` to `standardize_markdown_with_llm` and pass it to every standardization `post_llm_json_for_endpoint` call. No other task family changes its cache behavior.

- [x] **Step 6: 运行目标 Python 测试，确认 GREEN**

Run:

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests/test_question_markdown.py backend/python-worker/tests/test_import_services.py backend/python-worker/tests/test_llm_splitter.py backend/python-worker/tests/test_worker_v1_contract.py -q
```

Expected: 解析、两阶段、缓存绕过、失败信封与 v1 兼容测试全部通过。

- [x] **Step 7: 提交后端两阶段实现**

```bash
git add backend/python-worker/app/question_markdown.py backend/python-worker/app/import_services.py backend/python-worker/app/llm_splitter.py backend/python-worker/app/worker_base.py backend/python-worker/app/contracts/worker_v1.py backend/python-worker/app/worker_routes.py backend/python-worker/tests/test_question_markdown.py backend/python-worker/tests/test_import_services.py backend/python-worker/tests/test_llm_splitter.py backend/python-worker/tests/test_worker_v1_contract.py backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java question-engine/openapi/question-engine.v1.yaml
git commit -m "fix: add two-stage choice standardization"
```

### Task 4: 导入题前端二次强制 AI 交互

**Files:**
- Modify: `local-platform/src/lib/api.ts:149-153`
- Create: `local-platform/src/lib/interactive-standardization.ts`
- Create: `local-platform/src/lib/interactive-standardization.test.ts`
- Modify: `local-platform/src/components/question-bank/QuestionCard.tsx:78-140,202-280,582-595`
- Modify: `local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx:13-110`
- Create: `local-platform/src/components/question-bank/StandardizeCandidatePanel.test.ts`

- [ ] **Step 1: 写纯状态和失败呈现的失败测试**

```ts
import { afterLocalStandardization, shouldForceAi } from "./interactive-standardization";

it("forces AI only after a local result for the current markdown", () => {
  const stage = afterLocalStandardization("本地候选");
  expect(shouldForceAi(stage, "本地候选")).toBe(true);
  expect(shouldForceAi(stage, "人工改写")).toBe(false);
});
```

```ts
it("does not expose a force-AI failure as an applicable candidate", () => {
  const result = standardizeCandidateFromPayload("原稿", {
    markdown: "原稿",
    standardizer: { forceAiFailed: true, applyBlocked: true, warnings: ["model timed out"] },
  });
  expect(result.candidate).toBeNull();
  expect(result.message).toContain("强制 AI 标准化失败");
});
```

- [ ] **Step 2: 运行前端目标测试，确认 RED**

Run:

```bash
npm --prefix local-platform test -- --run src/lib/interactive-standardization.test.ts src/components/question-bank/StandardizeCandidatePanel.test.ts
```

Expected: 新模块不存在，且 `forceAiFailed` 尚未被候选面板识别。

- [ ] **Step 3: 实现纯状态、API 参数和失败消息**

```ts
export type InteractiveStandardizationStage = { markdown: string } | null;

export function afterLocalStandardization(markdown: string): InteractiveStandardizationStage {
  return { markdown };
}

export function shouldForceAi(stage: InteractiveStandardizationStage, markdown: string) {
  return stage?.markdown === markdown;
}
```

Change the API method to:

```ts
standardizeImportQuestionAi: (taskId: string, qid: string, markdown: string, forceAi = false) =>
  fetcher(`/api/import-tasks/${taskId}/questions/${qid}/standardize/ai`, {
    method: "POST",
    body: JSON.stringify({ markdown, forceAi }),
  }),
```

Add `forceAiFailed?: boolean` and `error?: string` to `StandardizerResult`; make `standardizeNotice` return `强制 AI 标准化失败：...` before any success branch.

- [ ] **Step 4: 在 `QuestionCard` 接入两阶段状态**

```ts
const [interactiveStandardizationStage, setInteractiveStandardizationStage] =
  useState<InteractiveStandardizationStage>(null);
const forceAi = shouldForceAi(interactiveStandardizationStage, formData.markdown);

const localStdMutation = useMutation({
  mutationFn: ({ markdown, forceAi }: { markdown: string; forceAi: boolean }) =>
    api.standardizeImportQuestionAi(taskId, qid, markdown, forceAi),
  onSuccess: (res, { markdown, forceAi }) => {
    if (res?.standardizer?.forceAiFailed) {
      setInteractiveStandardizationStage(afterLocalStandardization(markdown));
      toast({ title: "强制 AI 标准化失败", description: res.standardizer.warnings?.[0], variant: "destructive" });
      return;
    }
    const result = standardizeCandidateFromPayload(markdown, res);
    if (result.candidate) {
      const { nextFormData, nextSubForms } = standardizedQuestionDraft(result.candidate);
      saveStandardizedDraft(nextFormData, nextSubForms, "AI 标准化已应用并保存");
      setInteractiveStandardizationStage(forceAi ? null : afterLocalStandardization(nextFormData.markdown));
      return;
    }
    setInteractiveStandardizationStage(forceAi ? null : afterLocalStandardization(markdown));
  },
});
```

Reset the state in the existing Markdown branch of `patch`. In the candidate-panel apply handler, calculate the origin and update the stage explicitly:

```ts
const localCandidate = candidate.payload?.executionPath === "local"
  || candidate.payload?.cachedExecutionPath === "local";
setInteractiveStandardizationStage(localCandidate
  ? afterLocalStandardization(nextFormData.markdown)
  : null);
```

Then render:

```tsx
<Code className="w-3.5 h-3.5" /> {forceAi ? "强制 AI 标准化" : "AI 标准化"}
```

with `localStdMutation.mutate({ markdown: formData.markdown, forceAi })`.

- [ ] **Step 5: 运行前端目标测试和构建，确认 GREEN**

Run:

```bash
npm --prefix local-platform test -- --run src/lib/question.test.ts src/lib/interactive-standardization.test.ts src/components/question-bank/StandardizeCandidatePanel.test.ts
npm --prefix local-platform run build
```

Expected: 所有目标测试通过，TypeScript 检查和 Vite 构建成功。

- [ ] **Step 6: 提交前端两阶段交互**

```bash
git add local-platform/src/lib/api.ts local-platform/src/lib/question.ts local-platform/src/lib/question.test.ts local-platform/src/lib/interactive-standardization.ts local-platform/src/lib/interactive-standardization.test.ts local-platform/src/components/question-bank/QuestionCard.tsx local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx local-platform/src/components/question-bank/StandardizeCandidatePanel.test.ts
git commit -m "feat: force AI on second choice standardization"
```

### Task 5: 部署 smoke 与完整验证

**Files:**
- Modify: `scripts/smoke_ai.py:118-187`
- Modify: `scripts/test_smoke_ai.py`

- [ ] **Step 1: 写 smoke 单元测试，约束两次请求载荷**

```python
def test_choice_standardization_smoke_sends_local_then_force_ai(self):
    local_response = {"markdown": "本地候选", "executionPath": "local", "modelInvoked": False}
    force_response = {
        "markdown": "AI 候选", "executionPath": "force-ai", "modelInvoked": True,
        "cacheHit": False, "standardizer": {"fallbackUsed": False},
    }
    with patch.object(smoke_ai, "request", side_effect=[local_response, force_response]) as request:
        smoke_ai.run_choice_standardization_smoke("task-1", "question-1", "题干")
    self.assertEqual(False, request.call_args_list[0].args[2]["forceAi"])
    self.assertEqual(True, request.call_args_list[1].args[2]["forceAi"])
```

- [ ] **Step 2: 运行 smoke 单元测试，确认 RED**

Run:

```bash
python3 -m unittest scripts/test_smoke_ai.py -v
```

Expected: `run_choice_standardization_smoke` 尚不存在。

- [ ] **Step 3: 在 `smoke_ai.py` 加入两阶段运行态检查**

```python
def run_choice_standardization_smoke(task_id: str, question_id: str, markdown: str) -> None:
    local = request("POST", f"/api/import-tasks/{task_id}/questions/{question_id}/standardize/ai", {"markdown": markdown, "forceAi": False})
    ok("choice local standardize", local.get("modelInvoked") is False, local)
    ok("choice local standardize path", local.get("executionPath") in {"local", "cache"}, local)

    forced = request("POST", f"/api/import-tasks/{task_id}/questions/{question_id}/standardize/ai", {"markdown": local.get("markdown", markdown), "forceAi": True}, timeout=90)
    ok("choice force ai invoked", forced.get("modelInvoked") is True, forced)
    ok("choice force ai cache bypass", forced.get("cacheHit") is False, forced)
    ok("choice force ai is not local fallback", not forced.get("standardizer", {}).get("fallbackUsed"), forced)
```

Call it after the imported task and first question have been created. Keep the existing analysis and global-standardization smoke unchanged.

- [ ] **Step 4: 运行完整本地验证**

Run:

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests -q
./scripts/test_python_worker.sh
JAVA_HOME="$(/usr/libexec/java_home -v 17)" PATH="$JAVA_HOME/bin:$PATH" mvn -f backend/pom.xml test
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/test_check_project_portability.py
python3 scripts/test_ocrflow_golden.py
python3 scripts/test_benchmark_ocrflow.py
python3 scripts/test_check_ocrflow_boundaries.py
python3 scripts/test_check_mineru.py
python3 scripts/test_rebuild_mineru_venv.py
python3 scripts/check_question_engine_contract.py
git diff --check
```

Expected: 所有命令退出码为 0；已有性能/受控基线边界仍按现有文档标记，不把工具测试误称为正式 benchmark compare。

- [ ] **Step 5: 提交 smoke、更新计划勾选状态并生成交付包**

```bash
git add scripts/smoke_ai.py scripts/test_smoke_ai.py docs/superpowers/plans/2026-07-16-choice-option-recovery-and-two-stage-standardization.md
git commit -m "test: smoke two-stage choice standardization"
python3 scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

- [ ] **Step 6: 服务器部署与验收**

1. 从通过验证的提交生成包含 `local-platform` 的交付包并记录 SHA-256；保留当前服务器镜像标签作为回滚点。
2. 上传到既有 release 目录，核验远端 SHA-256 后覆盖代码；不覆盖 `.env`、`server-data`、MinerU venv 或模型缓存。
3. 使用 `docker-compose.server.yml` 构建并 `up -d`，等待 Docker health 为 `healthy`。
4. 运行：

```bash
AI_GENERATION_BASE_URL=http://127.0.0.1:8018 python3 scripts/smoke_ai.py
curl -fsS http://127.0.0.1/api/java/health
curl -fsS http://127.0.0.1:8018/api/capabilities/ocr-flow/runtime
```

Expected: two-stage smoke 通过；首页 HTTP 200；Java health 成功；MinerU `installed=true`、`runtimeProbeOk=true`、`apiReady=true`。

- [ ] **Step 7: 提交交付记录**

```bash
git add docs/delivery docs/server docs/CHANGELOG.md
git commit -m "docs: record choice standardization deployment"
```

Only add files actually changed by deployment evidence; do not create a commit when no documentation content changes.
