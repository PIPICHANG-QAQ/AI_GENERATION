"""Python worker HTTP 路由。

本文件只注册 Java 仍需调用的内部 worker 接口和短期兼容接口；新增业务 API 应优先落到 Java backend。
"""

from app.worker_base import *
from app.question_markdown import *
from app.ocr_processing import *
from app.import_services import *
from app.export_service import *
from app.ocr_execution import *
from app.question_layout import attach_paper_layout, load_image_placement_evidence, render_source_page

@app.get("/api/health")
def health() -> dict[str, str]:
    """返回 worker 健康状态。"""
    return {"status": "ok"}


@app.get("/api/system/mineru")
def get_mineru_status() -> dict[str, Any]:
    """返回 MinerU 运行时状态。"""
    return mineru_status()


@app.get("/api/system/ocr-flow")
def get_ocr_flow_status() -> dict[str, Any]:
    """返回 OCR-Flow 运行时状态。"""
    return ocr_flow_status()


@app.get("/api/system/export-flow")
def get_export_flow_status() -> dict[str, Any]:
    """返回 Export-Flow 运行时状态。"""
    return export_flow_status()


@app.get("/api/system/llm")
def get_llm_status() -> dict[str, Any]:
    """返回 LLM 配置状态。"""
    return llm_status()


@app.post("/worker/import-tasks/recover")
def recover_import_task(payload: dict[str, Any]) -> dict[str, Any]:
    """根据持久化任务快照和 OCR job 文件恢复导入任务。

    Java backend 是导入任务元数据的可信快照；当 worker 的兼容 store 丢失任务但
    OCR job 文件仍存在时，用该接口重新执行 sync_import_task，恢复题目列表并回写
    worker store，避免前端详情页永久停在处理中。
    """
    task = dict(payload.get("task") or payload)
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Import task id is required")

    store = read_store()
    existing = find_by_id(store["importTasks"], task_id)
    if existing:
        existing.update(task)
        task = existing
    else:
        store["importTasks"].append(task)

    sync_import_task(task, store)
    attach_paper_layout(task, safe_read_job(task.get("paperOcrJobId")))
    write_store(store)
    return task


@app.post("/worker/import-tasks/canonicalization/preview")
def preview_import_task_canonicalization(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical question/layout preview without mutating worker state."""
    task = copy.deepcopy(payload.get("task") or payload)
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Import task id is required")
    paper_job = safe_read_job(task.get("paperOcrJobId"))
    if not paper_job:
        raise HTTPException(status_code=404, detail="Paper OCR job not found")
    outputs = paper_job.get("outputs") if isinstance(paper_job.get("outputs"), dict) else {}
    paper_job_id = str(paper_job.get("jobId") or task.get("paperOcrJobId") or "").strip()
    layout_items = load_image_placement_evidence(OUTPUT_ROOT / paper_job_id, str(outputs.get("markdown") or ""))
    answer_job = safe_read_job(task.get("answerOcrJobId")) if task.get("answerOcrJobId") else None
    answer_context = str(((answer_job or {}).get("outputs") or {}).get("markdown") or "")
    preview = canonicalize_import_outputs(task, outputs, answer_context, layout_items=layout_items)
    preview_task = copy.deepcopy(task)
    preview_task["questions"] = preview["questions"]
    preview_task["canonicalization"] = preview["canonicalization"]
    preview["paperLayout"] = attach_paper_layout(preview_task, paper_job)
    return preview


@app.get("/api/import-tasks")
def list_import_tasks() -> dict[str, Any]:
    """返回本地导入任务列表。"""
    store = read_store()
    for task in store["importTasks"]:
        sync_import_task(task, store)
    write_store(store)
    return {"items": sorted(store["importTasks"], key=lambda item: item.get("createdAt", ""), reverse=True)}


@app.post("/api/import-tasks")
async def create_import_task(
    background_tasks: BackgroundTasks,
    stage: str = Form(""),
    subject: str = Form(""),
    grade: str = Form(""),
    region: str = Form(""),
    year: str = Form(""),
    title: str = Form(""),
    paperFile: UploadFile = File(...),
    answerFile: UploadFile | None = File(None),
) -> dict[str, Any]:
    """创建导入任务并提交 OCR job。"""
    store = read_store()
    stage = require_form_text(stage, "学段")
    subject = require_form_text(subject, "学科")
    grade = require_form_text(grade, "年级")
    year = require_form_text(year, "年份")
    title = require_form_text(title, "标题")
    ensure_unique_import_task_title(store, title)
    paper_job = create_ocr_job_record(background_tasks, paperFile, IMPORT_UPLOAD_ROOT)
    answer_job = create_ocr_job_record(background_tasks, answerFile, IMPORT_UPLOAD_ROOT) if answerFile else None
    task = {
        "id": make_id("import_task"),
        "stage": stage,
        "subject": subject,
        "grade": grade,
        "region": region,
        "year": year,
        "title": title,
        "status": "处理中",
        "paperFile": {"filename": paper_job["filename"], "contentType": paper_job.get("contentType")},
        "answerFile": {"filename": answer_job["filename"], "contentType": answer_job.get("contentType")} if answer_job else None,
        "paperOcrJobId": paper_job["jobId"],
        "answerOcrJobId": answer_job["jobId"] if answer_job else None,
        "questions": [],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    store["importTasks"].append(task)
    write_store(store)
    return task


@app.get("/api/import-tasks/{task_id}")
def get_import_task(task_id: str) -> dict[str, Any]:
    """查询单个导入任务。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    sync_import_task(task, store)
    attach_paper_layout(task, safe_read_job(task.get("paperOcrJobId")))
    write_store(store)
    return task


@app.put("/api/import-tasks/{task_id}")
def update_import_task(task_id: str, payload: ImportTaskUpdatePayload) -> dict[str, Any]:
    """更新导入任务元数据。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    title = require_form_text(payload.title, "标题")
    ensure_unique_import_task_title(store, title, exclude_id=task_id)
    task["title"] = title
    task["updatedAt"] = now_iso()
    write_store(store)
    return task


@app.delete("/api/import-tasks/{task_id}")
def delete_import_task(task_id: str) -> dict[str, Any]:
    """删除导入任务。"""
    store = read_store()
    before = len(store["importTasks"])
    store["importTasks"] = [task for task in store["importTasks"] if task.get("id") != task_id]
    if len(store["importTasks"]) == before:
        raise HTTPException(status_code=404, detail="Import task not found")
    write_store(store)
    return {"deleted": True}


@app.post("/api/import-tasks/batch-delete")
def batch_delete_import_tasks(payload: ImportTaskBatchDeletePayload) -> dict[str, Any]:
    """批量删除导入任务。"""
    task_ids = [str(task_id).strip() for task_id in payload.taskIds if str(task_id).strip()]
    unique_task_ids = list(dict.fromkeys(task_ids))
    if not unique_task_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的导入任务")

    store = read_store()
    selected_ids = set(unique_task_ids)
    existing_ids = {str(task.get("id")) for task in store["importTasks"]}
    deleted_ids = [task_id for task_id in unique_task_ids if task_id in existing_ids]
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="Import tasks not found")

    store["importTasks"] = [task for task in store["importTasks"] if str(task.get("id")) not in selected_ids]
    write_store(store)
    return {"deleted": True, "deletedCount": len(deleted_ids), "deletedIds": deleted_ids}


@app.get("/api/import-tasks/{task_id}/source/{kind}")
def get_import_task_source_file(task_id: str, kind: str) -> FileResponse:
    """返回导入任务原文件。"""
    if kind not in {"paper", "answer"}:
        raise HTTPException(status_code=400, detail="Invalid source kind")
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    job_id = task.get("paperOcrJobId") if kind == "paper" else task.get("answerOcrJobId")
    job = safe_read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Source OCR job not found")
    target = Path(str(job.get("uploadPath") or "")).resolve()
    upload_root = IMPORT_UPLOAD_ROOT.resolve()
    try:
        target.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Source file not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")
    return FileResponse(
        target,
        media_type=job.get("contentType") or None,
        filename=job.get("filename") or target.name,
        content_disposition_type="inline",
    )


@app.get("/api/import-tasks/{task_id}/source/paper/pages/{page_index}")
def get_import_task_source_paper_page(task_id: str, page_index: int) -> FileResponse:
    """返回试卷原文件指定页预览图，用于布局解析框叠加。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    job = safe_read_job(task.get("paperOcrJobId"))
    if not job:
        raise HTTPException(status_code=404, detail="Source OCR job not found")
    return render_source_page(task, job, page_index)


@app.get("/api/import-tasks/{task_id}/image-library")
def get_import_task_image_library(task_id: str) -> dict[str, Any]:
    """返回导入任务题图库。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    return {"items": import_task_image_library(task)}


@app.get("/api/import-tasks/{task_id}/questions/{question_id}/images/{filename}")
def get_import_question_uploaded_image(task_id: str, question_id: str, filename: str) -> FileResponse:
    """返回导入题上传题图。"""
    target = import_question_image_file(task_id, question_id, safe_filename(filename)).resolve()
    upload_root = IMPORT_UPLOAD_ROOT.resolve()
    if not str(target).startswith(str(upload_root)) or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(target, media_type=None, filename=target.name, content_disposition_type="inline")


@app.post("/api/import-tasks/{task_id}/questions/{question_id}/images")
def upload_import_question_images(task_id: str, question_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """上传导入题题图。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    question = find_import_question(task, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Import question not found")
    if not files:
        raise HTTPException(status_code=400, detail="No image files uploaded")

    upload_dir = IMPORT_UPLOAD_ROOT / task_id / "question_images" / question_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, Any]] = []
    for file in files:
        original_name = safe_filename(file.filename or "question-image")
        suffix = Path(original_name).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {suffix or 'unknown'}")
        filename = f"{uuid.uuid4().hex[:8]}_{original_name}"
        target = upload_dir / filename
        with target.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        image = {
            "name": original_name,
            "path": f"question_uploads/{task_id}/{question_id}/{filename}",
            "url": f"/api/import-tasks/{task_id}/questions/{question_id}/images/{filename}",
            "source": "本地上传",
            "size": target.stat().st_size,
            "type": suffix.lstrip("."),
        }
        uploaded.append(image)

    question["images"] = normalize_question_images([*(question.get("images") or []), *uploaded])
    task["imageLibrary"] = normalize_question_images([*(task.get("imageLibrary") or []), *uploaded])
    question["updatedAt"] = now_iso()
    task["updatedAt"] = now_iso()
    write_store(store)
    return {"images": question["images"], "uploaded": uploaded, "task": task}


@app.put("/api/import-tasks/{task_id}/questions/{question_id}")
def update_import_question(task_id: str, question_id: str, payload: ImportQuestionPayload) -> dict[str, Any]:
    """更新导入题内容。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    question = find_import_question(task, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Import question not found")
    update_import_question_from_payload(question, payload)
    update_import_task_status(task)
    task["updatedAt"] = now_iso()
    write_store(store)
    return {"question": question, "task": task}


@app.post("/api/import-tasks/{task_id}/questions/{question_id}/analysis")
def generate_import_question_analysis(task_id: str, question_id: str, payload: QuestionAnalysisPayload) -> dict[str, Any]:
    """为导入题生成 AI 解析。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    question = find_import_question(task, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Import question not found")
    images = normalize_question_images(payload.images if payload.images is not None else question.get("images"))
    stem_markdown = strip_question_images_from_markdown(
        payload.manualMarkdown or question.get("manualMarkdown") or question.get("stemMarkdown") or "",
        images,
    )
    analysis, metadata = generate_question_analysis_with_llm(
        stem_markdown=stem_markdown,
        answer=payload.answer or question.get("answer") or "",
        question_type=normalize_question_type(payload.type or question.get("type")),
        knowledge_points=payload.knowledgePoints or question.get("knowledgePoints") or [],
        images=images,
        sub_questions=payload.subQuestions if payload.subQuestions is not None else question.get("subQuestions") or question.get("children") or [],
    )
    if analysis is None:
        raise HTTPException(status_code=409, detail=metadata.get("error") or "AI 解析失败")
    suggested_answer = metadata.get("answer") or ""
    return {
        "analysis": analysis,
        "answer": suggested_answer,
        "suggestedAnswer": suggested_answer,
        "subQuestions": metadata.get("subQuestions", []),
        "metadata": metadata,
    }


@app.post("/api/import-tasks/{task_id}/questions/{question_id}/standardize/ai")
def standardize_import_question_ai(task_id: str, question_id: str, payload: MarkdownPayload) -> dict[str, Any]:
    """为导入题执行 AI Markdown 标准化。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    question = find_import_question(task, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Import question not found")
    return standardize_markdown_ai_response(
        payload.markdown,
        raw_ocr_context=raw_ocr_context_for_import_question(task, question),
        structured_hints=standardize_question_hints(question),
    )


@app.post("/api/import-tasks/{task_id}/questions/{question_id}/bank")
def bank_single_import_question(task_id: str, question_id: str) -> dict[str, Any]:
    """将单道导入题入库。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    question = find_import_question(task, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Import question not found")
    if question.get("status") not in {"已校验", "已入库"}:
        raise HTTPException(status_code=409, detail="题目必须先标记为已校验")
    existing_index = find_bank_question_index_for_import(store, task, question)
    existing = store["bankQuestions"][existing_index] if existing_index >= 0 else None
    bank_question = bank_question_from_import(task, question, existing)
    duplicate_reason = bank_question_duplicate_reason(store, bank_question, bank_question.get("id"))
    if duplicate_reason:
        raise HTTPException(status_code=409, detail=duplicate_reason)
    if existing_index >= 0:
        store["bankQuestions"][existing_index] = bank_question
    else:
        store["bankQuestions"].append(bank_question)
    question["status"] = "已入库"
    question["bankQuestionId"] = bank_question["id"]
    question["updatedAt"] = now_iso()
    update_import_task_status(task)
    write_store(store)
    return {"question": question, "bankQuestion": bank_question, "task": task, "overwritten": existing_index >= 0}


@app.post("/api/import-tasks/{task_id}/bank")
def bank_import_questions(task_id: str, questionIds: list[str] | None = None) -> dict[str, Any]:
    """批量将导入题入库。"""
    store = read_store()
    task = get_import_task_or_404(store, task_id)
    selected_ids = set(questionIds or [question["id"] for question in task.get("questions", []) if question.get("status") == "已校验"])
    created: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for question in task.get("questions", []):
        if question.get("id") not in selected_ids or question.get("status") != "已校验":
            continue
        existing_index = find_bank_question_index_for_import(store, task, question)
        existing = store["bankQuestions"][existing_index] if existing_index >= 0 else None
        bank_question = bank_question_from_import(task, question, existing)
        duplicate_reason = bank_question_duplicate_reason(store, bank_question, bank_question.get("id"))
        if duplicate_reason:
            duplicates.append({"questionId": question.get("id"), "number": question.get("number"), "reason": duplicate_reason})
            continue
        if existing_index >= 0:
            store["bankQuestions"][existing_index] = bank_question
        else:
            store["bankQuestions"].append(bank_question)
        question["status"] = "已入库"
        question["bankQuestionId"] = bank_question["id"]
        question["updatedAt"] = now_iso()
        created.append(bank_question)
    update_import_task_status(task)
    write_store(store)
    return {"createdCount": len(created), "duplicateCount": len(duplicates), "duplicates": duplicates, "items": created, "task": task}


@app.get("/api/knowledge-points")
def list_knowledge_points() -> dict[str, Any]:
    """返回知识点列表。"""
    store = read_store()
    return {"items": store["knowledgePoints"]}


@app.post("/api/knowledge-points")
def create_knowledge_point(payload: KnowledgePointPayload) -> dict[str, Any]:
    """创建知识点。"""
    store = read_store()
    item = {
        "id": make_id("kp"),
        "name": payload.name,
        "parentId": payload.parentId,
        "subject": payload.subject,
        "grade": payload.grade,
        "description": payload.description,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    store["knowledgePoints"].append(item)
    write_store(store)
    return item


@app.put("/api/knowledge-points/{point_id}")
def update_knowledge_point(point_id: str, payload: KnowledgePointPayload) -> dict[str, Any]:
    """更新知识点。"""
    store = read_store()
    item = find_by_id(store["knowledgePoints"], point_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    item.update(payload.model_dump())
    item["updatedAt"] = now_iso()
    write_store(store)
    return item


@app.delete("/api/knowledge-points/{point_id}")
def delete_knowledge_point(point_id: str) -> dict[str, Any]:
    """删除知识点。"""
    store = read_store()
    before = len(store["knowledgePoints"])
    store["knowledgePoints"] = [item for item in store["knowledgePoints"] if item.get("id") != point_id]
    if len(store["knowledgePoints"]) == before:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    write_store(store)
    return {"deleted": True}


@app.get("/api/question-bank/questions")
def list_bank_questions(
    keyword: str = "",
    type: str = "",
    difficulty: str = "",
    subject: str = "",
    grade: str = "",
    region: str = "",
    year: str = "",
    source: str = "",
    score: str = "",
    knowledgePointId: str = "",
) -> dict[str, Any]:
    """查询题库题列表。"""
    store = read_store()
    changed = False
    for question in store["bankQuestions"]:
        if isinstance(question, dict):
            changed = ensure_question_images_in_markdown(question) or changed
    if changed:
        write_store(store)
    filters = {
        "keyword": keyword,
        "type": type,
        "difficulty": difficulty,
        "subject": subject,
        "grade": grade,
        "region": region,
        "year": year,
        "source": source,
        "score": score,
        "knowledgePointId": knowledgePointId,
    }
    items = [question for question in store["bankQuestions"] if question_matches_filters(question, filters)]
    return {"items": sorted(items, key=lambda item: item.get("createdAt", ""), reverse=True)}


@app.post("/api/question-bank/questions")
def create_bank_question(payload: BankQuestionPayload) -> dict[str, Any]:
    """创建题库题。"""
    store = read_store()
    question = bank_question_from_payload(payload)
    store["bankQuestions"].append(question)
    write_store(store)
    return question


@app.get("/api/question-bank/questions/{question_id}")
def get_bank_question(question_id: str) -> dict[str, Any]:
    """查询题库题。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if ensure_question_images_in_markdown(question):
        write_store(store)
    return question


@app.post("/api/question-bank/questions/{question_id}/analysis")
def generate_bank_question_analysis(question_id: str, payload: QuestionAnalysisPayload) -> dict[str, Any]:
    """为题库题生成 AI 解析。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    images = normalize_question_images(payload.images if payload.images is not None else question.get("images"))
    stem_markdown = strip_question_images_from_markdown(
        payload.manualMarkdown or question.get("manualMarkdown") or question.get("stemMarkdown") or "",
        images,
    )
    analysis, metadata = generate_question_analysis_with_llm(
        stem_markdown=stem_markdown,
        answer=payload.answer or question.get("answer") or "",
        question_type=normalize_question_type(payload.type or question.get("type")),
        knowledge_points=payload.knowledgePoints or question.get("knowledgePoints") or [],
        images=images,
        sub_questions=payload.subQuestions if payload.subQuestions is not None else question.get("subQuestions") or question.get("children") or [],
    )
    if analysis is None:
        raise HTTPException(status_code=409, detail=metadata.get("error") or "AI 解析失败")
    suggested_answer = metadata.get("answer") or ""
    return {
        "analysis": analysis,
        "answer": suggested_answer,
        "suggestedAnswer": suggested_answer,
        "subQuestions": metadata.get("subQuestions", []),
        "metadata": metadata,
    }


@app.post("/api/question-bank/questions/{question_id}/standardize/ai")
def standardize_bank_question_ai(question_id: str, payload: MarkdownPayload) -> dict[str, Any]:
    """为题库题执行 AI Markdown 标准化。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return standardize_markdown_ai_response(
        payload.markdown,
        raw_ocr_context=raw_ocr_context_for_bank_question(store, question),
        structured_hints=standardize_question_hints(question),
    )


@app.get("/api/question-bank/questions/{question_id}/image-library")
def get_bank_question_image_library(question_id: str) -> dict[str, Any]:
    """返回题库题可复用题图库。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    source_task_id = question.get("sourceImportTaskId")
    if not source_task_id:
        return {"items": []}
    task = find_by_id(store["importTasks"], str(source_task_id))
    if not task:
        return {"items": []}
    return {"items": import_task_image_library(task)}


@app.get("/api/question-bank/questions/{question_id}/images/{filename}")
def get_bank_question_uploaded_image(question_id: str, filename: str) -> FileResponse:
    """返回题库题上传题图。"""
    target = bank_question_image_file(question_id, safe_filename(filename)).resolve()
    upload_root = BANK_IMAGE_ROOT.resolve()
    if not str(target).startswith(str(upload_root)) or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(target, media_type=None, filename=target.name, content_disposition_type="inline")


@app.post("/api/question-bank/questions/{question_id}/images")
def upload_bank_question_images(question_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """上传题库题题图。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if not files:
        raise HTTPException(status_code=400, detail="No image files uploaded")

    upload_dir = BANK_IMAGE_ROOT / question_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, Any]] = []
    for file in files:
        original_name = safe_filename(file.filename or "question-image")
        suffix = Path(original_name).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {suffix or 'unknown'}")
        filename = f"{uuid.uuid4().hex[:8]}_{original_name}"
        target = upload_dir / filename
        with target.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        image = {
            "name": original_name,
            "path": f"bank_question_uploads/{question_id}/{filename}",
            "url": f"/api/question-bank/questions/{question_id}/images/{filename}",
            "source": "本地上传",
            "size": target.stat().st_size,
            "type": suffix.lstrip("."),
        }
        uploaded.append(image)

    question["images"] = normalize_question_images([*(question.get("images") or []), *uploaded])
    question["updatedAt"] = now_iso()
    write_store(store)
    return {"images": question["images"], "uploaded": uploaded, "question": question}


@app.put("/api/question-bank/questions/{question_id}")
def update_bank_question(question_id: str, payload: BankQuestionPayload) -> dict[str, Any]:
    """更新题库题。"""
    store = read_store()
    question = find_by_id(store["bankQuestions"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    updated = bank_question_from_payload(payload)
    updated["id"] = question["id"]
    updated["createdAt"] = question.get("createdAt", now_iso())
    updated["updatedAt"] = now_iso()
    question.clear()
    question.update(updated)
    write_store(store)
    return question


@app.delete("/api/question-bank/questions/{question_id}")
def delete_bank_question(question_id: str) -> dict[str, Any]:
    """删除题库题。"""
    store = read_store()
    before = len(store["bankQuestions"])
    store["bankQuestions"] = [item for item in store["bankQuestions"] if item.get("id") != question_id]
    if len(store["bankQuestions"]) == before:
        raise HTTPException(status_code=404, detail="Question not found")
    write_store(store)
    return {"deleted": True}


@app.get("/api/papers")
def list_papers(
    page: int = Query(1, ge=1),
    pageSize: int = Query(6, ge=1, le=100),
    subject: str = "",
    grade: str = "",
    keyword: str = "",
) -> dict[str, Any]:
    """查询试卷列表。"""
    store = read_store()
    normalized_subject = subject.strip().casefold()
    normalized_grade = grade.strip().casefold()
    normalized_keyword = keyword.strip().casefold()
    filtered_items = [
        item for item in store["papers"]
        if (not normalized_subject or normalized_subject in str(item.get("subject") or "").casefold())
        and (not normalized_grade or normalized_grade in str(item.get("grade") or "").casefold())
        and (
            not normalized_keyword
            or any(
                normalized_keyword in str(item.get(field) or "").casefold()
                for field in ("title", "subject", "grade", "status")
            )
        )
    ]
    sorted_items = sorted(filtered_items, key=lambda item: item.get("createdAt", ""), reverse=True)
    start = (page - 1) * pageSize
    paged = sorted_items[start:start + pageSize]
    return {
        "items": [serialize_paper(store, item) for item in paged],
        "total": len(sorted_items),
        "page": page,
        "pageSize": pageSize,
    }


@app.post("/api/papers")
def create_paper(payload: PaperPayload) -> dict[str, Any]:
    """创建试卷。"""
    store = read_store()
    question_ids = payload.questionIds or select_questions_by_rules(store, payload.rules)
    scores = build_paper_scores(store, question_ids, payload.scores)
    paper = {
        "id": make_id("paper"),
        "title": payload.title,
        "subject": payload.subject.strip(),
        "grade": payload.grade.strip(),
        "questionIds": question_ids,
        "rules": payload.rules,
        "answerDisplay": payload.answerDisplay,
        "scores": scores,
        "subSelections": payload.subSelections,
        "header": payload.header,
        "status": payload.status,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    store["papers"].append(paper)
    write_store(store)
    return serialize_paper(store, paper)


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    """查询试卷。"""
    store = read_store()
    paper = find_by_id(store["papers"], paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return serialize_paper(store, paper)


@app.put("/api/papers/{paper_id}")
def update_paper(paper_id: str, payload: PaperPayload) -> dict[str, Any]:
    """更新试卷。"""
    store = read_store()
    paper = find_by_id(store["papers"], paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    question_ids = payload.questionIds or select_questions_by_rules(store, payload.rules)
    paper.update(
        {
            "title": payload.title,
            "subject": payload.subject.strip(),
            "grade": payload.grade.strip(),
            "questionIds": question_ids,
            "rules": payload.rules,
            "answerDisplay": payload.answerDisplay,
            "scores": build_paper_scores(store, question_ids, payload.scores),
            "subSelections": payload.subSelections,
            "header": payload.header,
            "status": payload.status,
            "updatedAt": now_iso(),
        }
    )
    write_store(store)
    return serialize_paper(store, paper)


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str) -> dict[str, Any]:
    """删除试卷。"""
    store = read_store()
    before = len(store["papers"])
    store["papers"] = [item for item in store["papers"] if item.get("id") != paper_id]
    if len(store["papers"]) == before:
        raise HTTPException(status_code=404, detail="Paper not found")
    write_store(store)
    return {"deleted": True}


@app.get("/api/papers/{paper_id}/export")
def export_paper(paper_id: str, format: str = Query("docx"), variant: str = Query("teacher")) -> FileResponse:
    """导出试卷文件。"""
    store = read_store()
    paper = find_by_id(store["papers"], paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    serialized_paper = serialize_paper(store, paper)
    questions = serialized_paper.get("questions", [])
    include_answer = variant in {"teacher", "answer"}
    if format == "pdf":
        path = export_paper_pdf(serialized_paper, questions, include_answer)
        media_type = "application/pdf"
    else:
        path = export_paper_docx(serialized_paper, questions, include_answer)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/markdown/standardize/local")
def standardize_markdown_local(payload: MarkdownPayload) -> dict[str, Any]:
    """使用本地规则标准化 Markdown。"""
    result = normalize_math_markdown(payload.markdown)
    return {
        "markdown": result["markdown"],
        "standardizer": {
            "source": "local",
            "status": result["status"],
            "changed": result["changed"],
            "fixes": result["fixes"],
            "issues": result["issues"],
        },
    }


@app.post("/api/markdown/standardize/ai")
def standardize_markdown_ai(payload: MarkdownPayload) -> dict[str, Any]:
    """使用 AI 标准化 Markdown。"""
    return standardize_markdown_ai_response(
        payload.markdown,
        raw_ocr_context=payload.rawOcrContext,
        structured_hints=payload.structuredHints,
        pipeline_version=payload.pipelineVersion,
        input_hash=payload.inputHash,
        request_source=payload.requestSource,
    )


@app.post("/api/ai/analysis")
def generate_question_analysis(payload: QuestionAnalysisPayload) -> dict[str, Any]:
    """生成临时题目解析。"""
    analysis, metadata = generate_question_analysis_with_llm(
        stem_markdown=payload.manualMarkdown,
        answer=payload.answer,
        question_type=normalize_question_type(payload.type),
        knowledge_points=payload.knowledgePoints,
        images=normalize_question_images(payload.images),
        sub_questions=payload.subQuestions or [],
    )
    if analysis is None:
        raise HTTPException(status_code=409, detail=metadata.get("error") or "AI 解析失败")
    suggested_answer = metadata.get("answer") or ""
    return {
        "analysis": analysis,
        "answer": suggested_answer,
        "suggestedAnswer": suggested_answer,
        "subQuestions": metadata.get("subQuestions", []),
        "metadata": metadata,
    }


@app.post("/api/ocr/jobs")
async def create_ocr_job(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    """创建 OCR job。"""
    return create_ocr_job_record(background_tasks, file)


@app.get("/api/ocr/jobs/{job_id}")
def get_ocr_job(job_id: str) -> dict[str, Any]:
    """查询 OCR job。"""
    job = read_job(job_id)
    if job.get("status") == "success" and job.get("outputs") and outputs_need_refresh(job["outputs"]):
        job["outputs"] = collect_outputs(job_id)
        write_job(job)
    return summarize_ocr_job_response(job)


@app.get("/api/ocr/jobs/{job_id}/result")
def get_ocr_result(job_id: str) -> dict[str, Any]:
    """查询 OCR job 完整结果。"""
    job = read_job(job_id)
    if job["status"] != "success":
        raise HTTPException(status_code=409, detail=f"OCR job is {job['status']}")
    if job.get("outputs") and outputs_need_refresh(job["outputs"]):
        job["outputs"] = collect_outputs(job_id)
        write_job(job)
    return job["outputs"]


def summarize_ocr_job_response(job: dict[str, Any]) -> dict[str, Any]:
    """返回适合列表/详情轮询的 OCR job 摘要。

    完整 outputs 可能包含整份试卷 Markdown、大 JSON 和大量题图信息，只能通过
    /result 按需读取，避免 Java 桥接和前端轮询被大响应拖慢。
    """

    summary = summarize_ocr_job(job) or {}
    summary["contentType"] = job.get("contentType")
    summary["ocrFlowProvider"] = job.get("ocrFlowProvider")
    summary["ocrProvider"] = job.get("ocrProvider")
    summary["ocrFlowProviderCommand"] = job.get("ocrFlowProviderCommand")
    summary["ocrFlowProviderCommandSource"] = job.get("ocrFlowProviderCommandSource")
    summary["retryCount"] = job.get("retryCount", 0)
    outputs = job.get("outputs") or {}
    summary["hasOutputs"] = bool(outputs)
    if outputs:
        markdown = str(outputs.get("markdown") or "")
        summary["outputSummary"] = {
            "markdownLength": len(markdown),
            "questionCount": len(outputs.get("questions") or []),
            "assetCount": len(outputs.get("assets") or []),
            "sectionCount": len(outputs.get("sections") or []),
        }
    return summary


@app.put("/api/ocr/jobs/{job_id}/questions/{question_id}/manual-markdown")
def update_question_manual_markdown(job_id: str, question_id: str, payload: QuestionManualMarkdownPayload) -> dict[str, Any]:
    """更新 OCR 题目的人工 Markdown。"""
    job = read_job(job_id)
    if job["status"] != "success" or not job.get("outputs"):
        raise HTTPException(status_code=409, detail=f"OCR job is {job['status']}")
    question = find_question(job["outputs"], question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    submitted_markdown = append_question_images_to_markdown(payload.markdown, question.get("images"))
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
    job["outputs"]["mathValidation"] = normalize_structured_math(job["outputs"])
    write_job(job)
    return {"question": question, "mathValidation": job["outputs"]["mathValidation"]}


@app.get("/api/ocr/jobs/{job_id}/files/{relative_path:path}")
def get_ocr_file(job_id: str, relative_path: str) -> FileResponse:
    """返回 OCR 产物文件。"""
    output_dir = (OUTPUT_ROOT / job_id).resolve()
    target = (output_dir / relative_path).resolve()
    if not str(target).startswith(str(output_dir)) or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(target)


@app.post("/worker/ocr")
async def worker_create_ocr_job(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    """worker 命名空间创建 OCR job。"""
    return create_ocr_job_record(background_tasks, file)


@app.get("/worker/ocr-flow")
def worker_get_ocr_flow_status() -> dict[str, Any]:
    """worker 命名空间返回 OCR-Flow 状态。"""
    return ocr_flow_status()


@app.get("/worker/export-flow")
def worker_get_export_flow_status() -> dict[str, Any]:
    """worker 命名空间返回 Export-Flow 状态。"""
    return export_flow_status()


@app.get("/worker/ocr/{job_id}")
def worker_get_ocr_job(job_id: str) -> dict[str, Any]:
    """worker 命名空间查询 OCR job。"""
    return get_ocr_job(job_id)


@app.get("/worker/ocr/{job_id}/result")
def worker_get_ocr_result(job_id: str) -> dict[str, Any]:
    """worker 命名空间查询 OCR 结果。"""
    return get_ocr_result(job_id)


@app.post("/worker/ocr/{job_id}/retry")
def worker_retry_ocr_job(background_tasks: BackgroundTasks, job_id: str) -> dict[str, Any]:
    """worker 命名空间重试 OCR job。"""
    job = read_job(job_id)
    upload_path = str(job.get("uploadPath") or "")
    if not upload_path or not Path(upload_path).exists():
        raise HTTPException(status_code=404, detail="OCR upload file not found")
    retry_started_at = now_iso()
    job.update({
        "status": "pending",
        "startedAt": None,
        "finishedAt": None,
        "error": None,
        "retryCount": int(job.get("retryCount") or 0) + 1,
        "ocrFlow": build_ocr_flow(retry_started_at),
    })
    write_job(job)
    background_tasks.add_task(run_ocr_job, job_id, upload_path)
    return job


@app.post("/worker/ai/standardize")
def worker_standardize_markdown_ai(payload: MarkdownPayload) -> dict[str, Any]:
    """worker 命名空间执行 AI 标准化。"""
    return standardize_markdown_ai(payload)


@app.post("/worker/ai/analysis")
def worker_generate_question_analysis(payload: QuestionAnalysisPayload) -> dict[str, Any]:
    """worker 命名空间执行 AI 解析。"""
    return generate_question_analysis(payload)


@app.get("/worker/export/papers/{paper_id}")
def worker_export_paper(paper_id: str, format: str = Query("docx"), variant: str = Query("teacher")) -> FileResponse:
    """worker 命名空间导出试卷。"""
    return export_paper(paper_id, format=format, variant=variant)


@app.post("/worker/export")
def worker_export(payload: dict[str, Any]) -> FileResponse:
    """worker 命名空间兼容导出接口。"""
    paper_id = str(payload.get("paperId") or payload.get("paper_id") or "").strip()
    if not paper_id:
        raise HTTPException(status_code=400, detail="paperId is required")
    export_format = str(payload.get("format") or "docx")
    variant = str(payload.get("variant") or "teacher")
    return export_paper(paper_id, format=export_format, variant=variant)


@app.post("/worker/export/render")
def worker_export_render(payload: dict[str, Any]) -> FileResponse:
    """worker 命名空间按 payload 渲染导出文件。"""
    paper = dict(payload.get("paper") or {})
    if not paper:
        raise HTTPException(status_code=400, detail="paper is required")
    questions = list(payload.get("questions") or paper.get("questions") or [])
    export_format = str(payload.get("format") or "docx").lower()
    variant = str(payload.get("variant") or "teacher")
    export_job_id = str(payload.get("exportJobId") or "").strip()
    if export_job_id:
        paper["id"] = export_job_id
    paper.setdefault("id", f"paper_export_{uuid.uuid4().hex[:8]}")
    include_answer = variant in {"teacher", "answer"}
    if export_format == "pdf":
        path = export_paper_pdf(paper, questions, include_answer)
        media_type = "application/pdf"
    else:
        path = export_paper_docx(paper, questions, include_answer)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media_type, filename=path.name)
