"""OCR 产物收集、结构化拆题和公式质量处理。

Java 负责任务状态和数据归属；本模块只把 OCR provider 输出整理成题目结构、图片资源和公式校验结果。
"""

from app.worker_base import *
from app.question_markdown import *
from app.question_boundary import (
    build_structure_from_boundaries,
    detect_local_boundaries,
    merge_legacy_images,
    validate_structure,
)
from app.visual_repair import apply_visual_repairs

def parse_structured_questions_from_v2(content_v2: Any, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """从 MinerU v2 JSON 内容解析结构化题目和资源引用。"""
    pages = content_v2 if isinstance(content_v2, list) else []
    sections: list[dict[str, Any]] = []
    flat_questions: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_question: dict[str, Any] | None = None
    pending_images: list[dict[str, Any]] = []

    def ensure_section() -> dict[str, Any]:
        """执行 ensure section 逻辑。"""
        nonlocal current_section
        if current_section is None:
            current_section = {
                "id": "section_0",
                "title": "未分组题目",
                "type": "unknown",
                "questions": [],
            }
            sections.append(current_section)
        return current_section

    def create_section(title: str) -> None:
        """执行 create section 逻辑。"""
        nonlocal current_section, current_question, pending_images
        current_section = {
            "id": f"section_{len(sections) + 1}",
            "title": title,
            "type": infer_question_type(title),
            "questions": [],
        }
        sections.append(current_section)
        current_question = None
        pending_images = []

    def create_question(number: str, markdown: str, page_index: int) -> dict[str, Any]:
        """执行 create question 逻辑。"""
        nonlocal current_question, pending_images
        section = ensure_section()
        stem, options = split_choice_options(markdown, section["type"])
        question = {
            "id": f"q_{number}",
            "number": int(number),
            "type": section["type"],
            "sectionId": section["id"],
            "sectionTitle": section["title"],
            "pageIndex": page_index,
            "stemMarkdown": stem,
            "images": pending_images,
            "options": options,
            "children": [],
        }
        pending_images = []
        section["questions"].append(question)
        flat_questions.append(question)
        current_question = question
        return question

    for page_index, page_blocks in enumerate(pages):
        if not isinstance(page_blocks, list):
            continue
        for block in page_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            markdown = block_to_markdown(block)

            if block_type == "page_number":
                continue

            if block_type == "image":
                image_path = block.get("content", {}).get("image_source", {}).get("path")
                if not image_path:
                    continue
                image = image_from_path(image_path, assets)
                if current_question and "如图" in current_question.get("stemMarkdown", ""):
                    current_question["images"].append(image)
                else:
                    pending_images.append(image)
                continue

            if not markdown:
                continue

            question_match = QUESTION_RE.match(markdown)
            is_numbered_title = block_type == "title" and question_match is not None
            is_section_title = block_type == "title" and not is_numbered_title and infer_question_type(markdown) != "unknown"
            if is_section_title:
                create_section(markdown)
                continue

            if question_match:
                number = question_match.group(1)
                question_markdown = question_match.group(2).strip()
                create_question(number, question_markdown, page_index)
                continue

            if current_question:
                merge_question_markdown(current_question, markdown)

    for image in pending_images:
        if current_question:
            current_question["images"].append(image)

    return {"sections": sections, "questions": flat_questions}


def parse_structured_questions(markdown: str, output_dir: Path, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """从 OCR Markdown 和资源目录解析结构化题目。"""
    return parse_structured_questions_legacy(markdown, output_dir, assets)


def parse_structured_questions_legacy(markdown: str, output_dir: Path, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """旧版规则拆题，作为证据驱动流水线的回滚结构。"""
    content_v2_files = sorted(output_dir.rglob("*_content_list_v2.json"), key=lambda path: path.as_posix())
    if content_v2_files:
        try:
            content_v2 = json.loads(content_v2_files[0].read_text(encoding="utf-8"))
            return parse_structured_questions_from_v2(content_v2, assets)
        except json.JSONDecodeError:
            pass

    sections: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_question: dict[str, Any] | None = None
    pending_images: list[dict[str, Any]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        image_match = re.match(r"!\[[^\]]*\]\(([^)]+)\)", stripped)
        if image_match:
            image = image_from_path(image_match.group(1), assets)
            if current_question and "如图" in current_question.get("stemMarkdown", ""):
                current_question["images"].append(image)
            else:
                pending_images.append(image)
            continue
        heading_text = stripped.lstrip("#").strip()
        if stripped.startswith("##") and infer_question_type(heading_text) != "unknown":
            current_section = {"id": f"section_{len(sections) + 1}", "title": heading_text, "type": infer_question_type(heading_text), "questions": []}
            sections.append(current_section)
            current_question = None
            pending_images = []
            continue
        question_match = QUESTION_RE.match(heading_text)
        if question_match:
            if current_section is None:
                current_section = {"id": "section_0", "title": "未分组题目", "type": "unknown", "questions": []}
                sections.append(current_section)
            stem, options = split_choice_options(question_match.group(2).strip(), current_section["type"])
            current_question = {
                "id": f"q_{question_match.group(1)}",
                "number": int(question_match.group(1)),
                "type": current_section["type"],
                "sectionId": current_section["id"],
                "sectionTitle": current_section["title"],
                "pageIndex": None,
                "stemMarkdown": stem,
                "images": pending_images,
                "options": options,
                "children": [],
            }
            pending_images = []
            current_section["questions"].append(current_question)
            questions.append(current_question)
        elif current_question:
            merge_question_markdown(current_question, stripped)
    return {"sections": sections, "questions": questions}


def collect_outputs(job_id: str) -> dict[str, Any]:
    """收集 OCR job 输出文件、结构化题目和数学校验结果。"""
    current_step = "collect-outputs"
    job = read_job(job_id)
    mark_ocr_flow_step(job, current_step, "running", "正在读取 OCR 输出文件")
    write_job(job)
    try:
        output_dir = OUTPUT_ROOT / job_id
        markdown_files = sorted(
            [path for path in output_dir.rglob("*") if path.suffix.lower() in MARKDOWN_EXTENSIONS],
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        json_files = sorted(output_dir.rglob("*.json"), key=lambda path: path.stat().st_size, reverse=True)
        image_files = sorted(
            [path for path in output_dir.rglob("*") if path.suffix.lower() in IMAGE_EXTENSIONS],
            key=lambda path: path.as_posix(),
        )

        markdown = markdown_files[0].read_text(encoding="utf-8", errors="replace") if markdown_files else ""
        json_content: Any = None
        json_path = json_files[0] if json_files else None
        if json_path:
            raw_json = json_path.read_text(encoding="utf-8", errors="replace")
            try:
                json_content = json.loads(raw_json)
            except json.JSONDecodeError:
                json_content = raw_json

        assets = [
            {
                "name": path.name,
                "path": path.relative_to(output_dir).as_posix(),
                "url": relative_file_url(job_id, path),
                "size": path.stat().st_size,
                "type": path.suffix.lower().lstrip("."),
            }
            for path in image_files
        ]

        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "success", f"已收集 {len(markdown_files)} 个 Markdown、{len(json_files)} 个 JSON、{len(assets)} 个图片资源")
        current_step = "local-boundary-detect"
        mark_ocr_flow_step(job, current_step, "running", "正在识别题号、小问、选项和题图候选边界")
        write_job(job)

        legacy_structured = parse_structured_questions_legacy(markdown, output_dir, assets)
        local_boundaries = detect_local_boundaries(markdown, assets)
        job = read_job(job_id)
        mark_ocr_flow_step(
            job,
            current_step,
            "success",
            f"已识别 {len(local_boundaries.get('questions') or [])} 个题目候选边界",
        )
        current_step = "llm-boundary-refine"
        mark_ocr_flow_step(job, current_step, "running", "正在让大模型确认边界，不改写题干")
        write_job(job)

        llm_boundaries, boundary_splitter = refine_question_boundaries_with_llm(markdown, assets, local_boundaries)
        boundary_source = llm_boundaries or local_boundaries
        splitter = boundary_splitter
        boundary_step_status = "success" if llm_boundaries else "skipped"
        boundary_step_message = "AI 边界确认完成" if llm_boundaries else str(boundary_splitter.get("error") or "使用本地边界候选")
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, boundary_step_status, boundary_step_message)
        current_step = "question-structure-build"
        mark_ocr_flow_step(job, current_step, "running", "正在按证据边界切片生成题目结构")
        write_job(job)

        structured = build_structure_from_boundaries(markdown, boundary_source, assets)
        merge_legacy_images(structured, legacy_structured)
        if not structured.get("questions"):
            structured = legacy_structured
            splitter = rule_splitter_metadata("证据边界未生成题目，已回滚旧版规则拆题")
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "success", f"已生成 {len(structured.get('questions') or [])} 道父题")
        current_step = "sub-question-split"
        mark_ocr_flow_step(job, current_step, "running", "正在确认大题中的小问结构")
        write_job(job)

        sub_question_count = sum(
            len(question.get("subQuestions") or question.get("children") or [])
            for section in structured.get("sections") or []
            if isinstance(section, dict)
            for question in section.get("questions") or []
            if isinstance(question, dict)
        )
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "success", f"已拆解 {sub_question_count} 个小问")
        current_step = "visual-repair"
        mark_ocr_flow_step(job, current_step, "running", "正在执行题目 crop、横线检测和可选二次 OCR")
        write_job(job)

        visual_repair = apply_visual_repairs(structured, output_dir, job.get("uploadPath"), job_id)
        visual_status = "success" if visual_repair.get("enabled", True) else "skipped"
        visual_message = (
            f"视觉修复完成，crop {visual_repair.get('cropCount', 0)} 个，检测横线 {visual_repair.get('underlineCount', 0)} 条"
            if visual_repair.get("enabled", True)
            else str(visual_repair.get("skippedReason") or "视觉修复未启用")
        )
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, visual_status, visual_message)
        current_step = "structure-validate"
        mark_ocr_flow_step(job, current_step, "running", "正在校验结构证据和题图引用")
        write_job(job)

        structure_validation = validate_structure(structured, markdown, assets)
        if not structure_validation.get("valid"):
            structured = legacy_structured
            fallback_validation = validate_structure(structured, markdown, assets)
            structure_validation = {
                **structure_validation,
                "fallback": True,
                "fallbackValidation": fallback_validation,
            }
            splitter = rule_splitter_metadata("结构校验失败，已回滚旧版规则拆题")
        else:
            structure_validation["fallback"] = False
        structured["structureValidation"] = structure_validation
        question_count = len(structured.get("questions") or [])
        job = read_job(job_id)
        validation_message = (
            f"结构校验完成，父题 {question_count} 道，小问 {structure_validation.get('subQuestionCount', 0)} 个"
            if structure_validation.get("valid")
            else "结构校验失败，已回滚旧版规则拆题"
        )
        mark_ocr_flow_step(job, current_step, "success" if structure_validation.get("valid") else "skipped", validation_message)
        current_step = "math-normalize"
        mark_ocr_flow_step(job, current_step, "running", "正在校验题目公式")
        write_job(job)

        math_validation = normalize_structured_math(structured)
        issue_count = int(math_validation.get("warningCount") or 0)
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "success", f"公式校验完成，发现 {issue_count} 个提示")
        current_step = "ai-enrich"
        mark_ocr_flow_step(job, current_step, "running", "正在检查是否需要 AI 增强")
        write_job(job)

        auto_semantic_repair = apply_auto_semantic_repairs(structured)
        if auto_semantic_repair["appliedCount"] > 0:
            math_validation = normalize_structured_math(structured)
        ai_status = "success"
        ai_message = f"AI 增强完成，应用 {auto_semantic_repair.get('appliedCount', 0)} 项修复"
        if not auto_semantic_repair.get("enabled", True) or not auto_semantic_repair.get("configured", False):
            ai_status = "skipped"
            ai_message = str(auto_semantic_repair.get("error") or "AI 增强未启用")
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, ai_status, ai_message)
        write_job(job)
    except Exception as exc:
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "failed", str(exc))
        write_job(job)
        raise

    return {
        "markdown": markdown,
        "json": json_content,
        "markdownFile": relative_file_url(job_id, markdown_files[0]) if markdown_files else None,
        "jsonFile": relative_file_url(job_id, json_path) if json_path else None,
        "assets": assets,
        "sections": structured["sections"],
        "questions": structured["questions"],
        "splitter": splitter,
        "boundaryCandidates": local_boundaries,
        "structureValidation": structured.get("structureValidation"),
        "visualRepair": visual_repair,
        "mathValidation": math_validation,
        "autoSemanticRepair": auto_semantic_repair,
    }


def apply_auto_semantic_repairs(structured: dict[str, Any]) -> dict[str, Any]:
    """对结构化题目应用自动语义修复。"""
    status = llm_status()
    summary: dict[str, Any] = {
        "enabled": True,
        "configured": status["configured"],
        "provider": status["provider"],
        "model": status["model"],
        "appliedCount": 0,
        "skippedCount": 0,
        "failedCount": 0,
        "repairs": [],
        "error": None,
    }
    if not status["enabled"]:
        summary["enabled"] = False
        summary["error"] = "LLM 已通过 ENABLE_LLM_SPLIT 关闭"
        return summary
    if not status["configured"]:
        summary["error"] = "未配置 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ALIYUN_LLM_API_KEY，跳过自动 AI 语义修复"
        return summary

    seen_question_ids: set[str] = set()
    for question in iter_structured_questions(structured):
        question_id = str(question.get("id") or id(question))
        if question_id in seen_question_ids:
            continue
        seen_question_ids.add(question_id)
        if not needs_auto_semantic_repair(question):
            continue

        before_markdown = question_to_edit_markdown(question)
        repaired_markdown, metadata = standardize_markdown_with_llm(before_markdown)
        repair_record = {
            "questionId": question.get("id"),
            "status": "failed",
            "source": metadata.get("source"),
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
            "confidence": metadata.get("confidence"),
            "corrections": metadata.get("corrections", []),
            "warnings": metadata.get("warnings", []),
            "error": metadata.get("error"),
            "repairedAt": now_iso(),
        }
        if repaired_markdown is None:
            summary["failedCount"] += 1
            question["autoSemanticRepair"] = repair_record
            summary["repairs"].append(repair_record)
            continue

        local_result = normalize_math_markdown(repaired_markdown)
        remaining_issues = local_result["issues"]
        confidence = str(metadata.get("confidence") or "").lower()
        can_apply = confidence != "low" and not has_semantic_ocr_issue(remaining_issues)
        if not can_apply:
            repair_record.update(
                {
                    "status": "skipped",
                    "error": "AI 修复置信度较低或仍存在同类语义 OCR 风险",
                    "warnings": list(dict.fromkeys([*repair_record["warnings"], *remaining_issues])),
                }
            )
            summary["skippedCount"] += 1
            question["autoSemanticRepair"] = repair_record
            summary["repairs"].append(repair_record)
            continue

        apply_edit_markdown_to_question(question, local_result["markdown"])
        repair_record.update(
            {
                "status": "applied",
                "changed": before_markdown != local_result["markdown"],
                "issues": remaining_issues,
                "fixes": local_result["fixes"],
            }
        )
        summary["appliedCount"] += 1
        question["autoSemanticRepair"] = repair_record
        summary["repairs"].append(repair_record)

    return summary


def iter_structured_questions(structured: dict[str, Any]):
    """遍历结构化结果中的所有题目。"""
    for section in structured.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in iter_questions(section.get("questions", [])):
            yield question
    for question in iter_questions(structured.get("questions", [])):
        yield question


def needs_auto_semantic_repair(question: dict[str, Any]) -> bool:
    """判断题目是否需要自动语义修复。"""
    validation = question.get("mathValidation") or {}
    if has_semantic_ocr_issue(validation.get("issues", [])):
        return True
    return bool(re.search(r"\b[\dA-Za-z]\s*[\"“”]\s*(?:=|，|,|、|\)|$)", question_to_edit_markdown(question)))


def has_semantic_ocr_issue(issues: Any) -> bool:
    """判断校验问题中是否包含语义 OCR 风险。"""
    if not isinstance(issues, list):
        return False
    return any("疑似指数被识别为引号" in str(issue) for issue in issues)


def iter_questions(questions: list[dict[str, Any]]):
    """递归遍历题目和子题。"""
    for question in questions:
        if not isinstance(question, dict):
            continue
        yield question
        for child in iter_questions(question.get("children", [])):
            yield child


def find_question(outputs: dict[str, Any], question_id: str) -> dict[str, Any] | None:
    """在 OCR 输出中按题目 ID 查找题目。"""
    for section in outputs.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in iter_questions(section.get("questions", [])):
            if question.get("id") == question_id:
                return question
    for question in iter_questions(outputs.get("questions", [])):
        if question.get("id") == question_id:
            return question
    return None


def outputs_need_refresh(outputs: dict[str, Any]) -> bool:
    """判断 OCR 输出是否需要重新生成结构化字段。"""
    if "questions" not in outputs or "splitter" not in outputs or "mathValidation" not in outputs:
        return True
    if "autoSemanticRepair" not in outputs:
        return True
    repair_summary = outputs.get("autoSemanticRepair") or {}
    if llm_status()["configured"] and not repair_summary.get("configured") and outputs_have_semantic_ocr_warning(outputs):
        return True
    for question in iter_questions(outputs.get("questions", [])):
        validation = question.get("mathValidation") or {}
        if any("连续 $$" in str(issue) for issue in validation.get("issues", [])):
            return True
    return False


def outputs_have_semantic_ocr_warning(outputs: dict[str, Any]) -> bool:
    """判断 OCR 输出是否包含语义 OCR 告警。"""
    for question in iter_questions(outputs.get("questions", [])):
        validation = question.get("mathValidation") or {}
        if has_semantic_ocr_issue(validation.get("issues", [])):
            return True
    return False
