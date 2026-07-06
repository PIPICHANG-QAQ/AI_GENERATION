"""导入任务兼容服务。

当前 Java 主后端已接管导入任务元数据，但仍通过这些函数兼容旧的 Python 任务 JSON、入库桥和本地开发数据。
"""

from app.worker_base import *
from app.question_markdown import *
from app.ocr_processing import *

INLINE_MATH_OPERATOR = (
    r"\\(?:div|times|cdot|leq|geq|neq|approx|sim|pm|mp|to|rightarrow|leftarrow|"
    r"Rightarrow|Leftarrow|in|notin|subseteq|subset|supseteq|supset|parallel|perp|cap|cup)\b"
)
INLINE_MATH_OPERATOR_FRAGMENT_RE = re.compile(
    rf"(?<!\$)\$(?!\$)(?P<left>[^$\n]+?)\$(?!\$)\s*"
    rf"(?P<op>{INLINE_MATH_OPERATOR})\s*"
    rf"(?<!\$)\$(?!\$)(?P<right>[^$\n]+?)\$(?!\$)"
)


def sync_import_task(task: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    """将导入任务写入本地 store 并维护唯一任务。"""
    paper_job = safe_read_job(task.get("paperOcrJobId"))
    answer_job = safe_read_job(task.get("answerOcrJobId"))
    task["paperOcrJob"] = summarize_ocr_job(paper_job)
    task["answerOcrJob"] = summarize_ocr_job(answer_job) if task.get("answerOcrJobId") else None

    if paper_job and paper_job.get("status") == "success" and not task.get("questions"):
        if paper_job.get("outputs") and outputs_need_refresh(paper_job["outputs"]):
            paper_job["outputs"] = collect_outputs(paper_job["jobId"])
            write_job(paper_job)
        answer_context = ""
        if answer_job and answer_job.get("status") == "success":
            if answer_job.get("outputs") and outputs_need_refresh(answer_job["outputs"]):
                answer_job["outputs"] = collect_outputs(answer_job["jobId"])
                write_job(answer_job)
            answer_context = str((answer_job.get("outputs") or {}).get("markdown") or "")
        task["questions"] = build_import_questions(task, paper_job.get("outputs") or {}, answer_context)
        task["updatedAt"] = now_iso()

    if task.get("questions"):
        changed = False
        for question in task.get("questions", []):
            if isinstance(question, dict):
                changed = ensure_question_images_in_markdown(question) or changed
        if changed:
            task["updatedAt"] = now_iso()

    update_import_task_status(task)
    return task


def safe_read_job(job_id: Any) -> dict[str, Any] | None:
    """安全读取 OCR job，读取失败时返回 None。"""
    if not job_id:
        return None
    path = job_file(str(job_id))
    job = read_json_with_backup(path)
    return job if isinstance(job, dict) else None


def detect_severe_latex_issues(markdown: str) -> list[str]:
    """检测 Markdown 中严重 LaTeX 风险。"""
    text = str(markdown or "")
    issues: list[str] = []
    if not text.strip():
        return issues

    if re.search(r"\${4,}", text):
        issues.append("存在连续 4 个及以上 $，公式分隔符可能严重损坏")
    if len(re.findall(r"(?<!\\)\$\$", text)) % 2 == 1:
        issues.append("展示公式 $$ 分隔符数量不成对")
    if re.search(r"\\frac\s*(?<!\\)\$", text):
        issues.append("存在 \\frac 后紧跟 $ 的损坏片段")

    for display_match in re.finditer(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$", text, re.S):
        if re.search(r"(?<!\\)\$(?!\$)", display_match.group(1)):
            issues.append("展示公式内部嵌套了单个 $ 分隔符")
            break
    if INLINE_MATH_OPERATOR_FRAGMENT_RE.search(text):
        issues.append("行内公式被数学运算符切断")

    for env_name in ("array", "cases", "aligned", "matrix", "pmatrix", "bmatrix"):
        begin_count = len(re.findall(rf"\\begin\{{{env_name}\}}", text))
        end_count = len(re.findall(rf"\\end\{{{env_name}\}}", text))
        if begin_count != end_count:
            issues.append(f"{env_name} 环境 begin/end 数量不匹配")

    left_count = len(re.findall(r"\\left(?:\b|[.({\[\|\\])", text))
    right_count = len(re.findall(r"\\right(?:\b|[.})\]\|\\])", text))
    if left_count != right_count:
        issues.append("\\left 与 \\right 数量不匹配")

    brace_depth = 0
    for index, char in enumerate(text):
        if char not in "{}":
            continue
        if index > 0 and text[index - 1] == "\\":
            continue
        if char == "{":
            brace_depth += 1
        elif brace_depth > 0:
            brace_depth -= 1
        else:
            issues.append("存在未配对的右花括号")
            break
    if brace_depth > 0:
        issues.append("存在未闭合的左花括号")

    deduped: list[str] = []
    for issue in issues:
        if issue not in deduped:
            deduped.append(issue)
    return deduped


def repair_latex_delimiter_fragments(markdown: str) -> tuple[str, list[dict[str, str]], list[str]]:
    """修复 OCR 常见的 LaTeX 公式分隔符碎裂问题。"""
    original = str(markdown or "")
    current = original
    corrections: list[dict[str, str]] = []
    warnings: list[str] = []

    current, display_count = strip_nested_dollars_in_display_math(current)
    if display_count:
        corrections.append(
            {
                "before": "展示公式内部嵌套的单个 $ 分隔符",
                "after": "展示公式内部直接保留 LaTeX 内容",
                "reason": f"修复 {display_count} 个展示公式内部嵌套的单个 $ 分隔符",
            }
        )

    current, merge_count = merge_inline_math_operator_fragments(current)
    if merge_count:
        corrections.append(
            {
                "before": "$...$\\operator$...$",
                "after": "$...\\operator...$",
                "reason": f"合并 {merge_count} 个被数学运算符切断的行内公式",
            }
        )

    return current, corrections, warnings


def strip_nested_dollars_in_display_math(markdown: str) -> tuple[str, int]:
    """移除 $$...$$ 展示公式内部误嵌套的单个 $。"""
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        body = match.group(1)
        fixed = re.sub(r"(?<!\\)\$(?!\$)", "", body)
        if fixed != body:
            count += 1
        return f"$${fixed}$$"

    fixed = re.sub(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$", replace, str(markdown or ""), flags=re.S)
    return fixed, count


def merge_inline_math_operator_fragments(markdown: str) -> tuple[str, int]:
    """合并被 \\div、\\leq 等数学运算符切断的相邻行内公式。"""
    current = str(markdown or "")
    total = 0

    def replace(match: re.Match[str]) -> str:
        left = match.group("left").strip()
        op = match.group("op").strip()
        right = match.group("right").strip()
        return f"${left}{op} {right}$"

    for _ in range(4):
        next_text, count = INLINE_MATH_OPERATOR_FRAGMENT_RE.subn(replace, current)
        total += count
        current = next_text
        if count == 0:
            break
    return current, total


def raw_ocr_markdown_for_task(task: dict[str, Any]) -> str:
    """读取导入任务关联 OCR job 的原始 Markdown。"""
    job = safe_read_job(task.get("paperOcrJobId"))
    outputs = (job or {}).get("outputs") or {}
    return str(outputs.get("markdown") or "")


def extract_raw_ocr_context(raw_markdown: str, question: dict[str, Any]) -> str:
    """从原始 OCR Markdown 中提取题目上下文片段。"""
    raw_text = str(raw_markdown or "")
    if not raw_text.strip():
        return ""

    try:
        number = int(question.get("number"))
    except (TypeError, ValueError):
        number = 0

    if number > 0:
        starts = list(re.finditer(r"(?m)(?:^|\n)\s*(\d{1,3})\s*[\.．、)]", raw_text))
        for index, match in enumerate(starts):
            if int(match.group(1)) != number:
                continue
            end = len(raw_text)
            for next_match in starts[index + 1 :]:
                if int(next_match.group(1)) > number:
                    end = next_match.start()
                    break
            return raw_text[match.start() : end].strip()[:6000]

    fallback = str(question.get("stemMarkdown") or question.get("manualMarkdown") or "")
    return fallback.strip()[:6000]


def raw_ocr_context_for_import_question(task: dict[str, Any], question: dict[str, Any]) -> str:
    """为导入题构造原始 OCR 上下文。"""
    return extract_raw_ocr_context(raw_ocr_markdown_for_task(task), question)


def raw_ocr_context_for_bank_question(store: dict[str, Any], question: dict[str, Any]) -> str:
    """为题库题构造原始 OCR 上下文。"""
    source_task_id = question.get("sourceImportTaskId")
    source_question_id = question.get("sourceImportQuestionId")
    if not source_task_id:
        return ""
    task = find_by_id(store["importTasks"], str(source_task_id))
    if not task:
        return ""
    source_question = find_import_question(task, str(source_question_id)) if source_question_id else None
    return extract_raw_ocr_context(raw_ocr_markdown_for_task(task), source_question or question)


def standardize_question_hints(question: dict[str, Any]) -> dict[str, Any]:
    """构造 AI 标准化所需的结构化提示信息。"""
    return {
        "number": question.get("number"),
        "type": question.get("type"),
        "answer": question.get("answer", ""),
        "options": question.get("options", []),
        "imageCount": len(question.get("images") or []),
        "subQuestions": normalize_sub_questions(question.get("subQuestions") or question.get("children")),
    }


def remove_extracted_solution_blocks(markdown: str, answer: str, analysis: str) -> tuple[str, list[dict[str, str]], list[str]]:
    """从题干 Markdown 中移除已抽取的答案和解析块。"""
    if not str(answer or "").strip() and not str(analysis or "").strip():
        return markdown, [], []

    original = str(markdown or "")
    if not original.strip():
        return original, [], []

    corrections: list[dict[str, str]] = []
    warnings: list[str] = []
    cleaned = original
    block_pattern = re.compile(
        r"(?im)(^|\n)\s*(?:[-*+]\s*)?(?:[【\[]\s*)?"
        r"(答案解析|参考答案|答案|解析|解答|详解|解)"
        r"\s*(?:[】\]]|[:：])"
    )
    marker = block_pattern.search(cleaned)
    if marker:
        cut_at = marker.start(0)
        prefix = cleaned[:cut_at].strip()
        removed = cleaned[cut_at:].strip()
        if prefix and removed:
            cleaned = prefix
            corrections.append(
                {
                    "before": removed[:160],
                    "after": "",
                    "reason": "AI 标准化已抽取答案或解析，删除题干中的答案/解析块",
                }
            )

    line_answer_pattern = re.compile(r"(?im)^\s*(?:[-*+]\s*)?(?:故)?答案(?:是|为)?\s*[:：]?.*$")
    next_cleaned = line_answer_pattern.sub("", cleaned)
    if next_cleaned != cleaned:
        corrections.append(
            {
                "before": "题干中的答案行",
                "after": "",
                "reason": "AI 标准化已抽取答案，删除题干中的答案行",
            }
        )
        cleaned = next_cleaned

    answer_text = str(answer or "").strip()
    answer_core = re.sub(r"^[\s$]+|[\s$]+$", "", answer_text)
    if answer_core:
        escaped_answer = re.escape(answer_core)
        inline_answer_pattern = re.compile(
            rf"(?P<prefix>(?:的\s*)?(?:长|长度|值|结果|答案)?\s*(?:是|为|等于)\s*[:：]?)"
            rf"\s*\$?\s*{escaped_answer}\s*\$?\s*([。．.,，；;\s]*)$"
        )
        next_cleaned = inline_answer_pattern.sub(r"\g<prefix>（ ）\2", cleaned)
        if next_cleaned != cleaned:
            corrections.append(
                {
                    "before": answer_text,
                    "after": "（ ）",
                    "reason": "AI 标准化已抽取答案，删除题干末尾直接拼入的答案",
                }
            )
            cleaned = next_cleaned

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        warnings.append("答案/解析块清理后题干为空，已保留模型返回的原始题干")
        return original, [], warnings
    return cleaned, corrections, warnings


def safe_normalize_standardize_candidate(markdown: str) -> tuple[dict[str, Any], list[str]]:
    """标准化 AI 候选；如果本地规则会重新引入严重风险，则保留候选原文。"""
    candidate = str(markdown or "")
    candidate_severe_issues = detect_severe_latex_issues(candidate)
    local_result = normalize_math_markdown(candidate)
    normalized_severe_issues = detect_severe_latex_issues(local_result["markdown"])
    if len(normalized_severe_issues) > len(candidate_severe_issues):
        return (
            {
                **local_result,
                "markdown": candidate,
                "status": "warning" if candidate_severe_issues else "fixed",
                "changed": False,
                "fixes": ["跳过会引入严重 LaTeX 风险的本地公式标准化，保留 AI 候选原文"],
                "issues": [],
            },
            ["本地公式标准化会引入严重公式风险，已保留 AI 候选原文"],
        )
    return local_result, []


def standardize_markdown_ai_response(
    markdown: str,
    raw_ocr_context: str = "",
    structured_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用 AI 标准化并合并规则修复结果。"""
    severe_issues = detect_severe_latex_issues(markdown)
    raw_context = str(raw_ocr_context or "").strip()
    llm_config = llm_status()
    repaired_markdown, delimiter_corrections, delimiter_warnings = repair_latex_delimiter_fragments(markdown)
    if delimiter_corrections:
        local_repair_result, local_repair_warnings = safe_normalize_standardize_candidate(normalize_tasks_environment(repaired_markdown))
        local_repair_severe_issues = detect_severe_latex_issues(local_repair_result["markdown"])
        if severe_issues and not local_repair_severe_issues:
            return {
                "markdown": local_repair_result["markdown"],
                "answer": "",
                "analysis": "",
                "standardizer": {
                    "source": "rules",
                    "provider": llm_config["provider"],
                    "model": llm_config["model"],
                    "error": None,
                    "corrections": delimiter_corrections,
                    "warnings": [*delimiter_warnings, *local_repair_warnings],
                    "confidence": "high",
                    "status": "fixed" if local_repair_result["status"] == "ok" else local_repair_result["status"],
                    "changed": local_repair_result["markdown"] != markdown,
                    "fixes": [
                        *local_repair_result["fixes"],
                        *[item["reason"] for item in delimiter_corrections],
                    ],
                    "issues": local_repair_result["issues"],
                    "severeIssues": severe_issues,
                    "candidateSevereIssues": local_repair_severe_issues,
                    "rawOcrContextUsed": bool(raw_context),
                    "rawOcrFallbackUsed": False,
                    "latexDelimiterRepaired": True,
                },
            }
    if severe_issues and raw_context and llm_config["enabled"] and llm_config["configured"]:
        raw_candidate_severe_issues = detect_severe_latex_issues(raw_context)
        if len(raw_candidate_severe_issues) < len(severe_issues):
            return {
                "markdown": raw_context,
                "standardizer": {
                    "source": "ai",
                    "provider": llm_config["provider"],
                    "model": llm_config["model"],
                    "error": None,
                    "corrections": [
                        {
                            "before": "当前编辑题干存在严重公式结构损坏",
                            "after": "同题原始 OCR 片段",
                            "reason": "原始 OCR 同题片段的 LaTeX 结构更完整，优先作为修复候选",
                        }
                    ],
                    "warnings": ["已使用原始 OCR 同题片段生成候选，请人工核对题号、分值和小问边界"],
                    "confidence": "medium",
                    "status": "fixed",
                    "changed": raw_context != markdown,
                    "fixes": ["使用同题原始 OCR 片段恢复严重损坏题干"],
                    "issues": [],
                    "severeIssues": severe_issues,
                    "candidateSevereIssues": raw_candidate_severe_issues,
                    "rawOcrContextUsed": True,
                    "rawOcrFallbackUsed": True,
                    "latexDelimiterRepaired": False,
                },
                "answer": "",
                "analysis": "",
            }
    standardized_markdown, metadata = standardize_markdown_with_llm(
        repaired_markdown,
        raw_ocr_context=raw_context,
        structured_hints=structured_hints,
    )
    if standardized_markdown is None:
        raise HTTPException(status_code=409, detail=metadata.get("error") or "AI 标准化失败")
    standardized_markdown = normalize_tasks_environment(standardized_markdown)
    standardized_markdown, post_delimiter_corrections, post_delimiter_warnings = repair_latex_delimiter_fragments(standardized_markdown)
    answer = str(metadata.get("answer") or "")
    analysis = str(metadata.get("analysis") or "")
    sub_question_solutions = normalize_sub_questions(metadata.get("subQuestions"))
    solution_answer = answer or "\n".join(str(sub.get("answer") or "") for sub in sub_question_solutions)
    solution_analysis = analysis or "\n".join(str(sub.get("analysis") or "") for sub in sub_question_solutions)
    cleaned_markdown, cleanup_corrections, cleanup_warnings = remove_extracted_solution_blocks(
        standardized_markdown,
        solution_answer,
        solution_analysis,
    )
    local_result, local_warnings = safe_normalize_standardize_candidate(cleaned_markdown)
    candidate_severe_issues = detect_severe_latex_issues(local_result["markdown"])
    return {
        "markdown": local_result["markdown"],
        "answer": "" if sub_question_solutions else answer,
        "analysis": "" if sub_question_solutions else analysis,
        "subQuestions": sub_question_solutions,
        "standardizer": {
            **metadata,
            "status": local_result["status"],
            "changed": local_result["markdown"] != markdown,
            "fixes": [
                *local_result["fixes"],
                *[item["reason"] for item in delimiter_corrections],
                *[item["reason"] for item in post_delimiter_corrections],
                *[item["reason"] for item in cleanup_corrections],
            ],
            "issues": local_result["issues"],
            "severeIssues": severe_issues,
            "candidateSevereIssues": candidate_severe_issues,
            "rawOcrContextUsed": bool(raw_context),
            "rawOcrFallbackUsed": False,
            "corrections": [
                *delimiter_corrections,
                *metadata.get("corrections", []),
                *post_delimiter_corrections,
                *cleanup_corrections,
            ],
            "warnings": [
                *delimiter_warnings,
                *metadata.get("warnings", []),
                *post_delimiter_warnings,
                *cleanup_warnings,
                *local_warnings,
            ],
            "solutionBlockRemoved": bool(cleanup_corrections),
            "latexDelimiterRepaired": bool(delimiter_corrections or post_delimiter_corrections),
        },
    }


def safe_normalize_manual_markdown(markdown: str) -> dict[str, Any]:
    """安全执行人工 Markdown 规范化，失败时保留原文。"""
    local_result = normalize_math_markdown(markdown)
    submitted_severe_issues = detect_severe_latex_issues(markdown)
    normalized_severe_issues = detect_severe_latex_issues(local_result["markdown"])
    if normalized_severe_issues and len(normalized_severe_issues) > len(submitted_severe_issues):
        return {
            **local_result,
            "markdown": markdown,
            "status": "warning",
            "changed": False,
            "fixes": [],
            "issues": [
                "本地公式标准化会引入严重公式风险，已保留原提交内容",
                *submitted_severe_issues,
            ],
        }
    return local_result


def summarize_ocr_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """将 OCR job 摘要化为前端任务状态字段。"""
    if not job:
        return None
    ensure_ocr_flow(job)
    return {
        "jobId": job.get("jobId"),
        "filename": job.get("filename"),
        "status": job.get("status"),
        "createdAt": job.get("createdAt"),
        "startedAt": job.get("startedAt"),
        "finishedAt": job.get("finishedAt"),
        "parser": job.get("parser"),
        "ocrFlowProvider": job.get("ocrFlowProvider"),
        "ocrProvider": job.get("ocrProvider"),
        "ocrFlowProviderCommandSource": job.get("ocrFlowProviderCommandSource"),
        "retryCount": job.get("retryCount", 0),
        "ocrFlow": job.get("ocrFlow"),
        "error": job.get("error"),
    }


def build_import_questions(task: dict[str, Any], outputs: dict[str, Any], answer_context: str) -> list[dict[str, Any]]:
    """根据 OCR 输出和答案上下文构造导入题列表。"""
    source_questions = top_level_ocr_questions(outputs)
    paper_ocr_context = str(outputs.get("markdown") or "")
    if import_sync_ai_enrich_enabled():
        enriched, enrichment_meta = enrich_questions_metadata_with_llm(source_questions, answer_context, paper_ocr_context)
    else:
        enriched = {}
        enrichment_meta = rule_splitter_metadata("导入任务同步阶段跳过 AI 元数据补全，避免页面查询被大模型长调用阻塞")
    import_questions: list[dict[str, Any]] = []
    for index, source_question in enumerate(source_questions, start=1):
        if not isinstance(source_question, dict):
            continue
        source_id = str(source_question.get("id") or f"q_{index}")
        metadata = enriched.get(source_id, {})
        difficulty = normalize_difficulty(metadata.get("difficulty"))
        images = normalize_question_images(source_question.get("images", []))
        stem_markdown = strip_question_images_from_markdown(source_question.get("stemMarkdown") or "", images)
        manual_markdown = (
            strip_question_images_from_markdown(source_question.get("manualMarkdown"), images)
            if source_question.get("manualMarkdown")
            else None
        )
        sub_questions = normalize_sub_questions(
            source_question.get("subQuestions") or source_question.get("children"),
            metadata.get("subQuestions"),
        )
        import_questions.append(
            {
                "id": make_id("import_question"),
                "sourceQuestionId": source_id,
                "number": source_question.get("number", index),
                "status": "待校验",
                "type": normalize_question_type(metadata.get("type") or source_question.get("type")),
                "stemMarkdown": stem_markdown,
                "manualMarkdown": manual_markdown,
                "answer": "" if sub_questions else metadata.get("answer", ""),
                "analysis": "" if sub_questions else metadata.get("analysis", ""),
                "knowledgePointIds": [],
                "knowledgePoints": normalize_string_values(metadata.get("knowledgePoints")),
                "difficulty": difficulty,
                "score": float(metadata.get("score", 0) or 0),
                "images": images,
                "options": source_question.get("options", []),
                "children": sub_questions,
                "subQuestions": sub_questions,
                "mathValidation": source_question.get("mathValidation"),
                "autoSemanticRepair": source_question.get("autoSemanticRepair"),
                "aiMetadata": {
                    **enrichment_meta,
                    "contextMatched": bool(metadata.get("contextMatched")),
                    "answerEvidence": str(metadata.get("answerEvidence") or ""),
                    "analysisEvidence": str(metadata.get("analysisEvidence") or ""),
                    "warnings": normalize_string_values(metadata.get("warnings")),
                    "subQuestions": metadata.get("subQuestions", []),
                },
                "commonTags": {
                    "stage": task.get("stage", ""),
                    "subject": task.get("subject", ""),
                    "grade": task.get("grade", ""),
                    "region": task.get("region", ""),
                    "year": task.get("year", ""),
                    "title": task.get("title", ""),
                },
                "createdAt": now_iso(),
                "updatedAt": now_iso(),
                "bankQuestionId": None,
            }
        )
    return import_questions


def top_level_ocr_questions(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """优先从 sections 读取父题，避免扁平 questions 中的小问变成独立导入题。"""
    top_level: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in outputs.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("id") or "")
            if question_id and question_id in seen:
                continue
            if question_id:
                seen.add(question_id)
            top_level.append(question)
    if top_level:
        return top_level
    return [question for question in outputs.get("questions", []) if isinstance(question, dict)]


def import_sync_ai_enrich_enabled() -> bool:
    """是否允许导入任务同步阶段调用 AI 补全。

    导入任务列表和详情是页面高频查询接口，不能被大模型调用阻塞。默认关闭后，
    OCR 成功会先生成可人工校验的题目；答案、解析、标准化由 Java 编排的 AI
    job 或单题按钮触发。
    """

    value = os.getenv("ENABLE_IMPORT_SYNC_AI_ENRICH", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def update_import_task_status(task: dict[str, Any]) -> None:
    """根据 OCR job 和题目入库状态更新导入任务状态。"""
    paper_job = task.get("paperOcrJob") or summarize_ocr_job(safe_read_job(task.get("paperOcrJobId")))
    answer_job = task.get("answerOcrJob") or summarize_ocr_job(safe_read_job(task.get("answerOcrJobId")))
    active_jobs = [job for job in (paper_job, answer_job) if job]
    if any(job.get("status") in {"pending", "running"} for job in active_jobs):
        task["status"] = "处理中"
        return
    questions = task.get("questions", [])
    if not questions:
        task["status"] = "待校验"
        return
    statuses = [question.get("status") for question in questions if isinstance(question, dict)]
    if statuses and all(status == "已入库" for status in statuses):
        task["status"] = "已完成"
    elif any(status in {"已校验", "已入库"} for status in statuses):
        task["status"] = "部分完成"
    else:
        task["status"] = "待校验"


def get_import_task_or_404(store: dict[str, Any], task_id: str) -> dict[str, Any]:
    """按 ID 查找导入任务，缺失时抛出 404。"""
    task = find_by_id(store["importTasks"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Import task not found")
    sync_import_task(task, store)
    write_store(store)
    return task


def find_import_question(task: dict[str, Any], question_id: str) -> dict[str, Any] | None:
    """在导入任务中查找指定题目。"""
    return next((question for question in task.get("questions", []) if question.get("id") == question_id), None)


def require_form_text(value: str, label: str) -> str:
    """校验表单文本非空并返回去空白值。"""
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"请填写{label}")
    return text


def ensure_unique_import_task_title(store: dict[str, Any], title: str, exclude_id: str | None = None) -> None:
    """校验导入任务标题在本地 store 中唯一。"""
    normalized_title = title.strip().casefold()
    if any(
        str(task.get("title") or "").strip().casefold() == normalized_title and task.get("id") != exclude_id
        for task in store.get("importTasks", [])
    ):
        raise HTTPException(status_code=409, detail="导入任务标题已存在，请更换标题")


def normalize_duplicate_text(value: Any) -> str:
    """归一化用于重复题检测的文本。"""
    text = strip_question_images_from_markdown(str(value or ""), [])
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def normalize_sub_questions(value: Any, enriched_value: Any = None) -> list[dict[str, Any]]:
    """归一化大题下的小问结构。"""
    if not isinstance(value, list):
        return []
    enriched_items = enriched_value if isinstance(enriched_value, list) else []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        enriched = match_sub_question_enrichment(item, enriched_items, index)
        images = normalize_question_images(item.get("images", []))
        stem_markdown = strip_question_images_from_markdown(
            enriched.get("stemMarkdown") or item.get("stemMarkdown") or item.get("stem") or item.get("manualMarkdown") or "",
            images,
        )
        manual_markdown = strip_question_images_from_markdown(
            enriched.get("manualMarkdown") or item.get("manualMarkdown") or stem_markdown,
            images,
        )
        try:
            score = float(enriched.get("score", item.get("score", 0)) or 0)
        except (TypeError, ValueError):
            score = 0.0
        knowledge_point_ids = enriched.get("knowledgePointIds", item.get("knowledgePointIds", []))
        result.append(
            {
                "id": str(item.get("id") or f"sub_{index}"),
                "label": str(item.get("label") or f"({index})"),
                "type": normalize_question_type(enriched.get("type") or item.get("type")),
                "difficulty": normalize_difficulty(enriched.get("difficulty") or item.get("difficulty")),
                "score": score,
                "stem": str(item.get("stem") or stem_markdown),
                "stemMarkdown": stem_markdown,
                "manualMarkdown": manual_markdown,
                "answer": str(enriched.get("answer") or item.get("answer") or ""),
                "analysis": str(enriched.get("analysis") or item.get("analysis") or ""),
                "knowledgePointIds": [str(point) for point in knowledge_point_ids if str(point).strip()]
                if isinstance(knowledge_point_ids, list)
                else [],
                "knowledgePoints": normalize_string_values(enriched.get("knowledgePoints") or item.get("knowledgePoints")),
                "images": images,
                "options": enriched.get("options", item.get("options", [])) if isinstance(enriched.get("options", item.get("options", [])), list) else [],
                "aiMetadata": {
                    "contextMatched": bool(enriched.get("contextMatched")),
                    "answerEvidence": str(enriched.get("answerEvidence") or ""),
                    "analysisEvidence": str(enriched.get("analysisEvidence") or ""),
                    "warnings": normalize_string_values(enriched.get("warnings")),
                },
            }
        )
    return result


def match_sub_question_enrichment(source: dict[str, Any], enriched_items: list[Any], index: int) -> dict[str, Any]:
    """按 id、label 或顺序匹配小问 AI 元数据。"""
    source_id = str(source.get("id") or "").strip()
    source_label = str(source.get("label") or f"({index})").strip()
    for item in enriched_items:
        if not isinstance(item, dict):
            continue
        if source_id and str(item.get("id") or "").strip() == source_id:
            return item
        if source_label and str(item.get("label") or "").strip() == source_label:
            return item
    fallback = enriched_items[index - 1] if index - 1 < len(enriched_items) else {}
    return fallback if isinstance(fallback, dict) else {}


def bank_question_duplicate_reason(store: dict[str, Any], question: dict[str, Any]) -> str | None:
    """判断入库题目是否与已有题库题重复。"""
    source_task_id = str(question.get("sourceImportTaskId") or "")
    source_question_id = str(question.get("sourceImportQuestionId") or question.get("id") or "")
    candidate_markdown = normalize_duplicate_text(question.get("manualMarkdown") or question.get("stemMarkdown"))
    candidate_answer = normalize_duplicate_text(question.get("answer"))
    for existing in store.get("bankQuestions", []):
        if not isinstance(existing, dict):
            continue
        if source_task_id and source_question_id:
            if existing.get("sourceImportTaskId") == source_task_id and existing.get("sourceImportQuestionId") == source_question_id:
                return "这道题已从当前导入任务入库"
        existing_markdown = normalize_duplicate_text(existing.get("manualMarkdown") or existing.get("stemMarkdown"))
        existing_answer = normalize_duplicate_text(existing.get("answer"))
        if candidate_markdown and candidate_markdown == existing_markdown and candidate_answer == existing_answer:
            return "题库中已存在相同题干和答案的题目"
    return None


def import_task_image_library(task: dict[str, Any]) -> list[dict[str, Any]]:
    """汇总导入任务下可复用的题图资源。"""
    images: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_asset(asset: dict[str, Any], source: str) -> None:
        """执行 append asset 逻辑。"""
        url = str(asset.get("url") or "").strip()
        path = str(asset.get("path") or asset.get("name") or url).strip()
        if not url and not path:
            return
        key = url or path
        if key in seen:
            return
        seen.add(key)
        images.append(
            {
                "name": str(asset.get("name") or Path(path).name or "题图"),
                "path": path,
                "url": url,
                "source": source,
                "size": asset.get("size", 0),
                "type": asset.get("type") or Path(path).suffix.lower().lstrip(".") or "image",
            }
        )

    for source, job_key in (("试卷 OCR", "paperOcrJobId"), ("答案 OCR", "answerOcrJobId")):
        job = safe_read_job(task.get(job_key))
        outputs = (job or {}).get("outputs") or {}
        for asset in outputs.get("assets") or []:
            if isinstance(asset, dict):
                append_asset(asset, source)

    for image in task.get("imageLibrary") or []:
        if isinstance(image, dict):
            append_asset(image, str(image.get("source") or "本地上传"))
    return images


def import_question_image_file(task_id: str, question_id: str, filename: str) -> Path:
    """计算导入题上传题图文件路径。"""
    return IMPORT_UPLOAD_ROOT / task_id / "question_images" / question_id / filename


def bank_question_image_file(question_id: str, filename: str) -> Path:
    """计算题库题上传题图文件路径。"""
    return BANK_IMAGE_ROOT / question_id / filename


def update_import_question_from_payload(question: dict[str, Any], payload: ImportQuestionPayload) -> None:
    """将更新载荷写回导入题并刷新 Markdown/图片字段。"""
    if payload.images is not None:
        question["images"] = normalize_question_images(payload.images)
    if payload.subQuestions is not None:
        sub_questions = normalize_sub_questions(payload.subQuestions)
        question["subQuestions"] = sub_questions
        question["children"] = sub_questions
    if payload.type is not None:
        question["type"] = normalize_question_type(payload.type)
    if payload.manualMarkdown is not None:
        submitted_markdown = strip_question_images_from_markdown(payload.manualMarkdown, question.get("images"))
        local_result = safe_normalize_manual_markdown(submitted_markdown)
        question["manualMarkdown"] = local_result["markdown"]
        question["manualEditedAt"] = now_iso()
        question["mathValidation"] = {
            "status": local_result["status"],
            "changed": local_result["changed"],
            "issues": local_result["issues"],
            "fields": [
                {
                    "field": "manualMarkdown",
                    "status": local_result["status"],
                    "changed": local_result["changed"],
                    "passCount": local_result["passCount"],
                    "fixes": local_result["fixes"],
                    "issues": local_result["issues"],
                }
            ],
        }
        apply_edit_markdown_to_question(question, local_result["markdown"])
    if payload.answer is not None:
        question["answer"] = payload.answer
    if payload.analysis is not None:
        question["analysis"] = payload.analysis
    if payload.knowledgePointIds is not None:
        question["knowledgePointIds"] = payload.knowledgePointIds
    if payload.knowledgePoints is not None:
        question["knowledgePoints"] = normalize_string_values(payload.knowledgePoints)
    if payload.difficulty is not None:
        question["difficulty"] = normalize_difficulty(payload.difficulty)
    if payload.score is not None:
        question["score"] = payload.score
    if payload.options is not None:
        question["options"] = payload.options
    if payload.status is not None:
        if payload.status not in QUESTION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid question status")
        question["status"] = payload.status
    if question.get("subQuestions") or question.get("children"):
        question["answer"] = ""
        question["analysis"] = ""
    question["updatedAt"] = now_iso()


def bank_question_from_import(task: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    """将导入题转换为题库题 payload。"""
    images = normalize_question_images(question.get("images", []))
    stem_markdown = strip_question_images_from_markdown(question.get("stemMarkdown") or "", images)
    markdown = strip_question_images_from_markdown(question.get("manualMarkdown") or stem_markdown, images)
    sub_questions = normalize_sub_questions(question.get("subQuestions") or question.get("children"))
    return {
        "id": make_id("bank_question"),
        "sourceImportTaskId": task.get("id"),
        "sourceImportQuestionId": question.get("id"),
        "source": task.get("title", ""),
        "stage": task.get("stage", ""),
        "subject": task.get("subject", ""),
        "grade": task.get("grade", ""),
        "region": task.get("region", ""),
        "year": task.get("year", ""),
        "title": task.get("title", ""),
        "number": question.get("number"),
        "type": normalize_question_type(question.get("type")),
        "stemMarkdown": stem_markdown,
        "manualMarkdown": markdown,
        "answer": "" if sub_questions else question.get("answer", ""),
        "analysis": "" if sub_questions else question.get("analysis", ""),
        "knowledgePointIds": question.get("knowledgePointIds", []),
        "knowledgePoints": question.get("knowledgePoints", []),
        "difficulty": normalize_difficulty(question.get("difficulty")),
        "score": float(question.get("score", 0) or 0),
        "images": images,
        "options": question.get("options", []),
        "children": sub_questions,
        "subQuestions": sub_questions,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }


def bank_question_from_payload(payload: BankQuestionPayload) -> dict[str, Any]:
    """将题库题请求载荷归一化为内部字典。"""
    images = normalize_question_images(payload.images)
    stem_markdown = strip_question_images_from_markdown(payload.stemMarkdown, images)
    manual_markdown = strip_question_images_from_markdown(payload.manualMarkdown or stem_markdown, images)
    local_result = safe_normalize_manual_markdown(manual_markdown)
    sub_questions = normalize_sub_questions(payload.subQuestions)
    return {
        "id": make_id("bank_question"),
        "sourceImportTaskId": None,
        "sourceImportQuestionId": None,
        "source": payload.source,
        "stage": "",
        "subject": payload.subject,
        "grade": payload.grade,
        "region": payload.region,
        "year": payload.year,
        "title": payload.source,
        "number": None,
        "type": normalize_question_type(payload.type),
        "stemMarkdown": stem_markdown,
        "manualMarkdown": local_result["markdown"],
        "answer": "" if sub_questions else payload.answer,
        "analysis": "" if sub_questions else payload.analysis,
        "knowledgePointIds": payload.knowledgePointIds,
        "knowledgePoints": payload.knowledgePoints,
        "difficulty": normalize_difficulty(payload.difficulty),
        "score": payload.score,
        "images": images,
        "options": payload.options,
        "children": sub_questions,
        "subQuestions": sub_questions,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }


def question_matches_filters(question: dict[str, Any], filters: dict[str, str]) -> bool:
    """判断题库题是否满足筛选条件。"""
    keyword = filters.get("keyword", "").strip().lower()
    if keyword:
        haystack = "\n".join(
            [
                str(question.get("manualMarkdown") or question.get("stemMarkdown") or ""),
                str(question.get("answer") or ""),
                str(question.get("analysis") or ""),
                " ".join(question.get("knowledgePoints", [])),
                json.dumps(question.get("subQuestions") or question.get("children") or [], ensure_ascii=False),
            ]
        ).lower()
        if keyword not in haystack:
            return False
    for field in ("type", "difficulty"):
        value = filters.get(field, "").strip()
        if value and str(question.get(field, "")) != value:
            return False
    for field in ("subject", "grade", "region", "year", "source"):
        value = filters.get(field, "").strip().lower()
        if value and value not in str(question.get(field, "")).lower():
            return False
    score = filters.get("score", "").strip()
    if score:
        try:
            if float(question.get("score", 0) or 0) != float(score):
                return False
        except ValueError:
            return False
    knowledge_point_id = filters.get("knowledgePointId", "").strip()
    if knowledge_point_id and knowledge_point_id not in question.get("knowledgePointIds", []):
        return False
    return True


def select_questions_by_rules(store: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    """根据组卷规则从题库中选择题目 ID。"""
    count = int(rules.get("count") or 10)
    filters = {
        "keyword": str(rules.get("keyword") or ""),
        "type": str(rules.get("type") or ""),
        "difficulty": str(rules.get("difficulty") or ""),
        "subject": str(rules.get("subject") or ""),
        "grade": str(rules.get("grade") or ""),
        "region": str(rules.get("region") or ""),
        "year": str(rules.get("year") or ""),
        "source": str(rules.get("source") or ""),
        "score": str(rules.get("score") or ""),
        "knowledgePointId": str(rules.get("knowledgePointId") or ""),
    }
    matched = [question for question in store["bankQuestions"] if question_matches_filters(question, filters)]
    return [question["id"] for question in matched[:count]]


def serialize_paper(store: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    """将试卷定义展开为包含题目和分值的响应结构。"""
    questions: list[dict[str, Any]] = []
    scores = paper.get("scores", {}) or {}
    for question_id in paper.get("questionIds", []):
        question = find_by_id(store["bankQuestions"], question_id)
        if not question:
            continue
        serialized_question = dict(question)
        serialized_question["score"] = float(scores.get(question_id, question.get("score", 0) or 0) or 0)
        questions.append(serialized_question)
    total_score = sum(float(item.get("score", 0) or 0) for item in questions)
    return {
        **paper,
        "subject": str(paper.get("subject") or ""),
        "grade": str(paper.get("grade") or ""),
        "questions": questions,
        "questionCount": len(questions),
        "totalScore": total_score,
    }


def build_paper_scores(store: dict[str, Any], question_ids: list[str], provided_scores: dict[str, float]) -> dict[str, float]:
    """为试卷题目构建分值映射。"""
    scores: dict[str, float] = {}
    for question_id in question_ids:
        question = find_by_id(store["bankQuestions"], question_id)
        default_score = question.get("score", 0) if question else 0
        scores[question_id] = float(provided_scores.get(question_id, default_score) or 0)
    return scores
