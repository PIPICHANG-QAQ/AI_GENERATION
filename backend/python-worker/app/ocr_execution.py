"""OCR 任务执行 worker。

该模块封装 Markdown 直读、.doc 预转换和 OCR provider 调用。任务状态最终由 Java 主后端同步和派生。
"""

from app.worker_base import *
from app.ocr_processing import *

def run_ocr_job(job_id: str, upload_path: str) -> None:
    """按上传文件类型调度 OCR job 执行流程。"""
    job = read_job(job_id)
    job.update({"status": "running", "startedAt": job.get("startedAt") or now_iso()})
    mark_ocr_flow_step(job, "preprocess", "running", "识别上传文件类型")
    write_job(job)
    suffix = Path(upload_path).suffix.lower()
    job = read_job(job_id)
    if suffix in MARKDOWN_EXTENSIONS:
        parser = "markdown"
        message = "Markdown 文件将直接进入结构化解析"
    elif suffix in DOC_CONVERT_EXTENSIONS:
        parser = "doc-convert"
        message = "DOC 文件需要先转换为 DOCX"
    else:
        parser = "ocr-provider"
        message = "文件将交给 OCR provider 处理"
    job["parser"] = parser
    mark_ocr_flow_step(job, "preprocess", "success", message)
    write_job(job)
    if suffix in MARKDOWN_EXTENSIONS:
        run_markdown_job(job_id, upload_path)
        return
    if suffix in DOC_CONVERT_EXTENSIONS:
        run_doc_conversion_job(job_id, upload_path)
        return
    run_ocr_provider_job(job_id, upload_path)


def run_markdown_job(job_id: str, upload_path: str) -> None:
    """直接把 Markdown 文件作为 OCR 输出写入 job。"""
    job = read_job(job_id)
    output_dir = OUTPUT_ROOT / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / Path(upload_path).name
    job.update({"status": "running", "startedAt": job.get("startedAt") or now_iso(), "parser": "markdown"})
    mark_ocr_flow_step(job, "ocr-provider", "running", "直接读取 Markdown 内容")
    write_job(job)
    try:
        markdown = Path(upload_path).read_text(encoding="utf-8", errors="replace")
        job["ocrFlowProvider"] = "markdown-direct"
        job["ocrProvider"] = "markdown-direct"
        output_path.write_text(markdown, encoding="utf-8")
        mark_ocr_flow_step(job, "ocr-provider", "success", "Markdown 内容读取完成")
        write_job(job)
        outputs = collect_outputs(job_id)
        job = read_job(job_id)
        job.update({"status": "success", "finishedAt": now_iso(), "outputs": outputs})
    except Exception as exc:  # pragma: no cover - background worker safety
        mark_ocr_flow_step(job, "ocr-provider", "failed", str(exc))
        job.update({"status": "failed", "finishedAt": now_iso(), "error": str(exc)})
    write_job(job)


def convert_doc_to_docx(upload_path: Path) -> tuple[Path | None, str, str]:
    """使用系统转换工具把 .doc 文件转换为 .docx。"""
    output_path = upload_path.with_suffix(".converted.docx")
    attempts: list[str] = []
    textutil_command = shutil.which("textutil")
    if textutil_command:
        result = subprocess.run(
            [textutil_command, "-convert", "docx", "-output", str(output_path), str(upload_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path, result.stdout[-4000:], result.stderr[-4000:]
        attempts.append(f"textutil exited with code {result.returncode}: {(result.stderr or result.stdout)[-1000:]}")

    office_command = shutil.which("soffice") or shutil.which("libreoffice")
    if office_command:
        result = subprocess.run(
            [office_command, "--headless", "--convert-to", "docx", "--outdir", str(upload_path.parent), str(upload_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        libreoffice_output = upload_path.with_suffix(".docx")
        if result.returncode == 0 and libreoffice_output.exists():
            return libreoffice_output, result.stdout[-4000:], result.stderr[-4000:]
        attempts.append(f"LibreOffice exited with code {result.returncode}: {(result.stderr or result.stdout)[-1000:]}")

    pandoc_command = shutil.which("pandoc")
    if pandoc_command:
        result = subprocess.run(
            [pandoc_command, str(upload_path), "-o", str(output_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path, result.stdout[-4000:], result.stderr[-4000:]
        attempts.append(f"Pandoc exited with code {result.returncode}: {(result.stderr or result.stdout)[-1000:]}")

    reason = "；".join(item for item in attempts if item) or "No .doc converter found. Install LibreOffice/soffice or use .docx."
    return None, "", reason


def run_doc_conversion_job(job_id: str, upload_path: str) -> None:
    """执行 DOC 转换并继续按 OCR provider 处理转换产物。"""
    job = read_job(job_id)
    job.update({"status": "running", "startedAt": job.get("startedAt") or now_iso(), "parser": "doc-convert"})
    mark_ocr_flow_step(job, "preprocess", "running", "正在转换 DOC 输入")
    write_job(job)
    try:
        converted_path, stdout, stderr = convert_doc_to_docx(Path(upload_path))
        job["conversionStdout"] = stdout
        job["conversionStderr"] = stderr
        if not converted_path:
            mark_ocr_flow_step(job, "preprocess", "failed", ".doc 转换为 .docx 失败")
            job.update(
                {
                    "status": "failed",
                    "finishedAt": now_iso(),
                    "error": f".doc cannot be parsed directly by the configured OCR provider. Conversion to .docx failed: {stderr}",
                }
            )
            write_job(job)
            return
        job["convertedInputPath"] = str(converted_path)
        mark_ocr_flow_step(job, "preprocess", "success", "DOC 已转换为 DOCX")
        write_job(job)
        run_ocr_provider_job(job_id, str(converted_path))
    except subprocess.TimeoutExpired:
        mark_ocr_flow_step(job, "preprocess", "failed", ".doc conversion timed out after 120 seconds.")
        job.update({"status": "failed", "finishedAt": now_iso(), "error": ".doc conversion timed out after 120 seconds."})
        write_job(job)
    except Exception as exc:  # pragma: no cover - background worker safety
        mark_ocr_flow_step(job, "preprocess", "failed", str(exc))
        job.update({"status": "failed", "finishedAt": now_iso(), "error": str(exc)})
        write_job(job)


def run_ocr_provider_job(job_id: str, upload_path: str) -> None:
    """调用当前 OCR provider 处理上传文件并收集输出。"""
    job = read_job(job_id)
    selected = selected_provider_name()
    provider = selected_ocr_provider()
    if provider is None:
        mark_ocr_flow_step(job, "ocr-provider", "failed", f"Unsupported OCR provider: {selected}.")
        job.update(
            {
                "status": "failed",
                "finishedAt": now_iso(),
                "ocrFlowProvider": selected,
                "ocrProvider": selected,
                "error": f"Unsupported OCR provider: {selected}. Available providers: {', '.join(sorted(ocr_flow_providers().keys()))}",
            }
        )
        write_job(job)
        return
    provider.run(job_id, upload_path, ocr_flow_runtime())


def run_mineru_job(job_id: str, upload_path: str) -> None:
    """兼容旧入口，按 MinerU provider 执行 OCR。"""
    providers(APP_ROOT, MINERU_VERSION_TIMEOUT_SECONDS)["mineru"].run(job_id, upload_path, ocr_flow_runtime())
