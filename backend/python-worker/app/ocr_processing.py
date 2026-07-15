"""OCR 产物收集、结构化拆题和公式质量处理。

Java 负责任务状态和数据归属；本模块只把 OCR provider 输出整理成题目结构、图片资源和公式校验结果。
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.worker_base import *
from app.question_markdown import *
from app.llm_splitter import (
    boundary_refinement_skipped_metadata,
    llm_runtime_options,
    refine_question_boundaries_in_chunks,
)
from app.question_boundary import (
    build_structure_from_boundaries,
    detect_local_boundaries,
    evaluate_boundary_confidence,
    merge_legacy_images,
    plan_boundary_chunks,
    validate_structure,
)
from app.image_placement import reconcile_structure_image_placements
from app.question_layout import load_image_placement_evidence
from app.visual_repair import apply_visual_repairs, prepare_visual_repair_context
from app.ocr.contracts import CanonicalOcrBundle, validate_bundle_artifact_paths


def build_postprocess_input(bundle: CanonicalOcrBundle) -> dict[str, Any]:
    """Convert provider-neutral evidence into the unchanged algorithm input shape."""
    output_dir = validate_bundle_artifact_paths(bundle)
    markdown_path = output_dir / bundle.markdown_artifact_path if bundle.markdown_artifact_path else None
    json_path = output_dir / bundle.json_artifact_path if bundle.json_artifact_path else None
    return {
        "outputDir": output_dir,
        "markdown": bundle.canonical_markdown,
        "markdownFiles": [markdown_path] if markdown_path and markdown_path.is_file() else [],
        "jsonFiles": [json_path] if json_path and json_path.is_file() else [],
        "jsonContent": bundle.json_content,
        "assets": [
            {
                "name": asset.name,
                "path": asset.path,
                "url": asset.url,
                "size": asset.size_bytes,
                "type": Path(asset.path).suffix.lower().lstrip(".") or asset.media_type.split("/", 1)[-1],
            }
            for asset in bundle.assets
        ],
        "layoutItems": [block.to_dict() for block in bundle.layout_blocks],
        "uploadPath": bundle.source_document_ref.path if bundle.source_document_ref else "",
    }
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline


def structure_candidate_quality(structured: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return deterministic evidence coverage used only to compare invalid candidates."""
    questions = [question for question in structured.get("questions") or [] if isinstance(question, dict)]
    evidence_count = sum(
        1
        for question in questions
        if isinstance(question.get("sourceEvidence"), dict)
        and isinstance(question["sourceEvidence"].get("start"), int)
        and isinstance(question["sourceEvidence"].get("end"), int)
    )
    complete_choice_count = sum(
        1
        for question in questions
        if str(question.get("type") or "") != "choice" or len(question.get("options") or []) >= 2
    )
    option_count = sum(len(question.get("options") or []) for question in questions)
    image_count = sum(len(question.get("images") or []) for question in questions)
    return (evidence_count, complete_choice_count, option_count, image_count)


def select_structure_candidate(
    primary: dict[str, Any],
    primary_validation: dict[str, Any],
    fallback: dict[str, Any],
    fallback_validation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select a structure without allowing an invalid lower-quality fallback to replace primary evidence."""
    primary_valid = bool(primary_validation.get("valid"))
    fallback_valid = bool(fallback_validation.get("valid"))
    use_fallback = False
    if not primary_valid and fallback_valid:
        use_fallback = True
    elif not primary_valid and not fallback_valid:
        use_fallback = structure_candidate_quality(fallback) > structure_candidate_quality(primary)

    if use_fallback:
        validation = {
            **fallback_validation,
            "fallback": True,
            "requiresReview": not fallback_valid,
            "primaryValidation": primary_validation,
            "fallbackValidation": fallback_validation,
        }
        return fallback, validation

    validation = {
        **primary_validation,
        "fallback": False,
        "requiresReview": not primary_valid,
        "fallbackValidation": fallback_validation,
    }
    return primary, validation

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


def collect_outputs_impl(job_id: str, bundle: CanonicalOcrBundle | None = None) -> dict[str, Any]:
    """收集统一 OCR 证据并执行既有的题目后处理算法。"""
    current_step = "collect-outputs"
    job = read_job(job_id)
    mark_ocr_flow_step(job, current_step, "running", "正在读取 OCR 输出文件")
    write_job(job)
    visual_context_executor: ThreadPoolExecutor | None = None
    visual_context_future = None
    try:
        if bundle is not None:
            explicit_input = build_postprocess_input(bundle)
            output_dir = explicit_input["outputDir"]
            markdown_files = explicit_input["markdownFiles"]
            json_files = explicit_input["jsonFiles"]
            markdown = explicit_input["markdown"]
            json_content = explicit_input["jsonContent"]
            assets = explicit_input["assets"]
            placement_layout_items = explicit_input["layoutItems"]
            upload_path = explicit_input["uploadPath"]
        else:
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
            placement_layout_items = None
            upload_path = job.get("uploadPath")

        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "success", f"已收集 {len(markdown_files)} 个 Markdown、{len(json_files)} 个 JSON、{len(assets)} 个图片资源")
        current_step = "local-boundary-detect"
        mark_ocr_flow_step(job, current_step, "running", "正在识别题号、小问、选项和题图候选边界")
        write_job(job)

        legacy_structured = parse_structured_questions_legacy(markdown, output_dir, assets)
        local_boundaries = detect_local_boundaries(markdown, assets)
        boundary_confidence = evaluate_boundary_confidence(markdown, local_boundaries, assets)
        visual_context_executor = ThreadPoolExecutor(max_workers=1)
        visual_context_future = visual_context_executor.submit(
            prepare_visual_repair_context,
            output_dir,
            upload_path,
        )
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

        if boundary_confidence.get("highConfidence"):
            llm_boundaries = None
            boundary_splitter = boundary_refinement_skipped_metadata(boundary_confidence)
        else:
            runtime_options = llm_runtime_options()
            chunks = plan_boundary_chunks(
                markdown,
                local_boundaries,
                runtime_options["boundaryChunkSize"],
                runtime_options["boundaryChunkMaxChars"],
            )
            llm_boundaries, boundary_splitter = refine_question_boundaries_in_chunks(
                chunks,
                assets,
                local_boundaries,
                risk_context=boundary_confidence,
            )
            candidate_structured = build_structure_from_boundaries(markdown, llm_boundaries, assets) if llm_boundaries else {}
            candidate_validation = validate_structure(
                candidate_structured,
                markdown,
                assets,
                local_boundaries.get("structureContract"),
            ) if candidate_structured.get("questions") else {"valid": False}
            if llm_boundaries and not candidate_validation.get("valid"):
                previous_llm_calls = boundary_splitter.get("llmCalls") if isinstance(boundary_splitter, dict) else []
                external_boundaries, external_splitter = refine_question_boundaries_in_chunks(
                    chunks,
                    assets,
                    local_boundaries,
                    risk_context={**boundary_confidence, "forceExternal": True, "forceReason": "structure-validation-failed"},
                    force_external=True,
                )
                external_structured = build_structure_from_boundaries(markdown, external_boundaries, assets) if external_boundaries else {}
                external_validation = validate_structure(
                    external_structured,
                    markdown,
                    assets,
                    local_boundaries.get("structureContract"),
                ) if external_structured.get("questions") else {"valid": False}
                if external_boundaries and external_validation.get("valid"):
                    llm_boundaries = external_boundaries
                    boundary_splitter = external_splitter
                    boundary_splitter["llmCalls"] = [
                        *previous_llm_calls,
                        *(external_splitter.get("llmCalls") if isinstance(external_splitter, dict) else []),
                    ]
                    boundary_splitter.setdefault("warnings", []).append("本地模型边界结果结构校验失败，已升级外部模型兜底")
                else:
                    external_calls = external_splitter.get("llmCalls") if isinstance(external_splitter, dict) else []
                    boundary_splitter = rule_splitter_metadata("分片 AI 边界确认结构校验失败，外部兜底也未通过，已回退本地边界候选")
                    boundary_splitter["llmCalls"] = [*previous_llm_calls, *external_calls]
                    llm_boundaries = None
        boundary_source = llm_boundaries or local_boundaries
        splitter = boundary_splitter
        boundary_step_status = "skipped" if boundary_confidence.get("highConfidence") else ("success" if llm_boundaries else "skipped")
        boundary_step_message = (
            "本地边界高置信，跳过 AI 边界确认"
            if boundary_confidence.get("highConfidence")
            else ("AI 边界确认完成" if llm_boundaries else str(boundary_splitter.get("error") or "使用本地边界候选"))
        )
        boundary_metrics = build_llm_metrics(boundary_splitter)
        if boundary_metrics["callCount"] > 0:
            boundary_step_message = f"{boundary_step_message}，LLM {boundary_metrics['callCount']} 次/{boundary_metrics['totalDurationMs']}ms"
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, boundary_step_status, boundary_step_message)
        current_step = "question-structure-build"
        mark_ocr_flow_step(job, current_step, "running", "正在按证据边界切片生成题目结构")
        write_job(job)

        structured = build_structure_from_boundaries(markdown, boundary_source, assets)
        merge_legacy_images(structured, legacy_structured)
        try:
            if placement_layout_items is None:
                placement_layout_items = load_image_placement_evidence(output_dir, markdown)
            layout_image_realign = reconcile_structure_image_placements(structured, placement_layout_items)
            layout_image_realign["reason"] = "layout-read-only-reconciliation"
        except Exception as exc:
            layout_image_realign = {
                "applied": False,
                "reason": "layout-read-only-reconciliation-failed",
                "placementCount": 0,
                "assignedCounts": {},
                "methodCounts": {},
                "conflictCount": 0,
                "unassignedCount": 0,
                "warnings": [str(exc)],
            }
        if not structured.get("questions"):
            structured = legacy_structured
            previous_llm_calls = splitter.get("llmCalls") if isinstance(splitter, dict) else []
            splitter = rule_splitter_metadata("证据边界未生成题目，已回滚旧版规则拆题")
            splitter["llmCalls"] = previous_llm_calls
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

        visual_repair_context: dict[str, Any] | None = None
        if visual_context_future is not None:
            try:
                visual_repair_context = visual_context_future.result()
            except Exception as exc:
                visual_repair_context = {"warnings": [f"视觉修复预处理失败：{exc}"]}
            finally:
                if visual_context_executor is not None:
                    visual_context_executor.shutdown(wait=False)
                    visual_context_executor = None

        visual_repair = apply_visual_repairs(structured, output_dir, upload_path, job_id, visual_repair_context)
        visual_status = "success" if visual_repair.get("enabled", True) else "skipped"
        preprocessed = visual_repair.get("preprocessed") or {}
        visual_message = (
            f"视觉修复完成，crop {visual_repair.get('cropCount', 0)} 个，检测横线 {visual_repair.get('underlineCount', 0)} 条，"
            f"并发 {visual_repair.get('maxConcurrency', 1)}，预加载页 {preprocessed.get('preloadedPageCount', 0)}"
            if visual_repair.get("enabled", True)
            else str(visual_repair.get("skippedReason") or "视觉修复未启用")
        )
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, visual_status, visual_message)
        current_step = "structure-validate"
        mark_ocr_flow_step(job, current_step, "running", "正在校验结构证据和题图引用")
        write_job(job)

        primary_structured = structured
        primary_validation = validate_structure(primary_structured, markdown, assets, local_boundaries.get("structureContract"))
        if not primary_validation.get("valid"):
            fallback_validation = validate_structure(legacy_structured, markdown, assets, local_boundaries.get("structureContract"))
            structured, structure_validation = select_structure_candidate(
                primary_structured,
                primary_validation,
                legacy_structured,
                fallback_validation,
            )
            previous_llm_calls = splitter.get("llmCalls") if isinstance(splitter, dict) else []
            if structure_validation.get("fallback"):
                splitter = rule_splitter_metadata("主结构校验失败，已选择质量更高的旧版规则候选")
                splitter["llmCalls"] = previous_llm_calls
            else:
                splitter.setdefault("warnings", []).append("主结构与旧版候选均未通过校验，已保留证据质量更高的主结构并标记复核")
        else:
            structure_validation = {
                **primary_validation,
                "fallback": False,
                "requiresReview": False,
            }
        structured["structureValidation"] = structure_validation
        structured["layoutImageRealign"] = layout_image_realign
        question_count = len(structured.get("questions") or [])
        job = read_job(job_id)
        validation_message = (
            f"结构校验完成，父题 {question_count} 道，小问 {structure_validation.get('subQuestionCount', 0)} 个"
            if structure_validation.get("valid")
            else "结构校验未通过，已保留较高质量候选并标记复核"
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
        ai_metrics = build_llm_metrics(auto_semantic_repair)
        if ai_metrics["callCount"] > 0:
            ai_message = f"{ai_message}，LLM {ai_metrics['callCount']} 次/{ai_metrics['totalDurationMs']}ms"
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, ai_status, ai_message)
        write_job(job)
    except Exception as exc:
        if visual_context_executor is not None:
            visual_context_executor.shutdown(wait=False, cancel_futures=True)
        job = read_job(job_id)
        mark_ocr_flow_step(job, current_step, "failed", str(exc))
        write_job(job)
        raise

    llm_metrics = build_llm_metrics(splitter, auto_semantic_repair)
    return {
        "markdown": markdown,
        "json": json_content,
        "markdownFile": relative_file_url(job_id, markdown_files[0]) if markdown_files else None,
        "jsonFile": relative_file_url(job_id, json_files[0]) if json_files else None,
        "assets": assets,
        "sections": structured["sections"],
        "questions": structured["questions"],
        "splitter": splitter,
        "boundaryCandidates": local_boundaries,
        "boundaryConfidence": boundary_confidence,
        "structureValidation": structured.get("structureValidation"),
        "visualRepair": visual_repair,
        "mathValidation": math_validation,
        "autoSemanticRepair": auto_semantic_repair,
        "llmMetrics": llm_metrics,
    }


DEFAULT_OCR_POSTPROCESSING_PIPELINE = OcrPostProcessingPipeline()


def collect_outputs(job_id: str) -> dict[str, Any]:
    """Compatibility façade for the single OCR post-processing pipeline."""
    return DEFAULT_OCR_POSTPROCESSING_PIPELINE.run(job_id)


def append_llm_calls(target: list[dict[str, Any]], source: Any) -> None:
    """Append sanitized LLM call metrics from a metadata object."""
    if not isinstance(source, dict):
        return
    llm_call = source.get("llmCall")
    if isinstance(llm_call, dict):
        target.append(llm_call)
    for item in source.get("llmCalls") or []:
        if isinstance(item, dict):
            target.append(item)


def build_llm_metrics(*sources: Any) -> dict[str, Any]:
    """Aggregate OCR-level LLM call metrics."""
    enabled = llm_runtime_options()["metricsEnabled"]
    calls: list[dict[str, Any]] = []
    if enabled:
        for source in sources:
            append_llm_calls(calls, source)

    def duration_ms(item: dict[str, Any]) -> int:
        try:
            return max(0, int(item.get("durationMs") or 0))
        except (TypeError, ValueError):
            return 0

    local_calls = [item for item in calls if item.get("route") == "local"]
    external_calls = [item for item in calls if item.get("route") == "external"]

    return {
        "enabled": enabled,
        "callCount": len(calls),
        "totalDurationMs": sum(duration_ms(item) for item in calls),
        "localCallCount": len(local_calls),
        "localDurationMs": sum(duration_ms(item) for item in local_calls),
        "externalCallCount": len(external_calls),
        "externalDurationMs": sum(duration_ms(item) for item in external_calls),
        "cacheHitCount": sum(1 for item in calls if item.get("cacheHit") is True),
        "calls": calls,
    }


def apply_auto_semantic_repairs(structured: dict[str, Any]) -> dict[str, Any]:
    """对结构化题目应用自动语义修复。"""
    status = llm_status()
    options = llm_runtime_options()
    repair_mode = options["autoSemanticRepairMode"]
    summary: dict[str, Any] = {
        "enabled": True,
        "configured": status["configured"],
        "provider": status["provider"],
        "model": status["model"],
        "mode": "skipped" if repair_mode == "skip" else repair_mode,
        "candidateCount": 0,
        "appliedCount": 0,
        "skippedCount": 0,
        "failedCount": 0,
        "repairs": [],
        "llmCalls": [],
        "error": None,
    }
    if not status["enabled"]:
        summary["enabled"] = False
        summary["error"] = "LLM 已通过 ENABLE_LLM_SPLIT 关闭"
        return summary
    if not status["configured"]:
        summary["error"] = "未配置 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ALIYUN_LLM_API_KEY，跳过自动 AI 语义修复"
        return summary

    candidates: list[tuple[dict[str, Any], str]] = []
    seen_question_ids: set[str] = set()
    for question in iter_structured_questions(structured):
        question_id = str(question.get("id") or id(question))
        if question_id in seen_question_ids:
            continue
        seen_question_ids.add(question_id)
        if not needs_auto_semantic_repair(question):
            continue
        candidates.append((question, question_to_edit_markdown(question)))

    summary["candidateCount"] = len(candidates)
    if repair_mode == "skip":
        summary["skippedCount"] = len(candidates)
        summary["error"] = "OCR 主链路跳过自动 AI 语义修复，保留人工校验和 AI 标准化入口"
        return summary

    def repair_candidate(candidate: tuple[dict[str, Any], str]) -> tuple[dict[str, Any], str, str | None, dict[str, Any]]:
        question, before_markdown = candidate
        repaired_markdown, metadata = standardize_markdown_with_llm(before_markdown)
        return question, before_markdown, repaired_markdown, metadata

    repair_results: list[tuple[dict[str, Any], str, str | None, dict[str, Any]]] = []
    max_workers = min(options["maxConcurrency"], max(1, len(candidates)))
    if repair_mode == "inline-concurrent" and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(repair_candidate, candidate) for candidate in candidates]
            for future in as_completed(futures):
                repair_results.append(future.result())
    else:
        repair_results = [repair_candidate(candidate) for candidate in candidates]

    for question, before_markdown, repaired_markdown, metadata in repair_results:
        append_llm_calls(summary["llmCalls"], metadata)
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
