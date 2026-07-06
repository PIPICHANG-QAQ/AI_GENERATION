"""试卷 Markdown、DOCX 和 PDF 导出 worker。

Java 创建导出任务并管理文件存储；本模块只负责把 Java 传入的试卷快照渲染为具体文件。
"""

from app.worker_base import *
from app.question_markdown import *
from app.import_services import *

SUPERSCRIPT_DIGITS = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
SUBSCRIPT_DIGITS = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
LATEX_SYMBOLS = {
    r"\pi": "π",
    r"\infty": "∞",
    r"\angle": "∠",
    r"\circ": "°",
    r"\times": "×",
    r"\div": "÷",
    r"\cdot": "·",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\pm": "±",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\theta": "θ",
    r"\Delta": "Δ",
}

def strip_markdown_image_lines(markdown: str) -> str:
    """移除 Markdown 中的图片行。"""
    return "\n".join(line for line in str(markdown or "").splitlines() if not re.search(r"!\[[^\]]*\]\([^)]+\)", line))


def replace_latex_groups(text: str) -> str:
    """替换 LaTeX 分组语法以适配导出。"""
    current = text
    fraction_re = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    sqrt_re = re.compile(r"\\sqrt\s*\{([^{}]+)\}")
    nth_root_re = re.compile(r"\\sqrt\s*\[([^][]+)\]\s*\{([^{}]+)\}")
    power_group_re = re.compile(r"\^\{([^{}]+)\}")
    sub_group_re = re.compile(r"_\{([^{}]+)\}")

    def render_fraction(match: re.Match[str]) -> str:
        """执行 render fraction 逻辑。"""
        numerator = match.group(1).strip()
        denominator = match.group(2).strip()
        if re.fullmatch(r"[\w+\-π∞]+", numerator) and re.fullmatch(r"[\w+\-π∞]+", denominator):
            return f"{numerator}/{denominator}"
        return f"({numerator})/({denominator})"

    def render_nth_root(match: re.Match[str]) -> str:
        """执行 render nth root 逻辑。"""
        degree = match.group(1).strip()
        radicand = match.group(2).strip()
        return f"{degree}√{radicand}"

    for _ in range(12):
        next_text = fraction_re.sub(render_fraction, current)
        next_text = nth_root_re.sub(render_nth_root, next_text)
        next_text = sqrt_re.sub(lambda match: f"√{match.group(1)}", next_text)
        next_text = power_group_re.sub(lambda match: f"^{match.group(1).translate(SUPERSCRIPT_DIGITS)}", next_text)
        next_text = sub_group_re.sub(lambda match: f"_{match.group(1).translate(SUBSCRIPT_DIGITS)}", next_text)
        if next_text == current:
            return next_text
        current = next_text
    return current


def render_latex_inline(content: str) -> str:
    """渲染内联 LaTeX 内容为导出友好文本。"""
    text = replace_latex_groups(content)
    for source, target in LATEX_SYMBOLS.items():
        text = text.replace(source, target)
    text = re.sub(r"\\(?:left|right|displaystyle|textstyle|big|Big|bigg|Bigg)\s*", "", text)
    text = re.sub(r"\\text\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\mathrm\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\mathbf\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def render_markdown_for_export(markdown: str) -> str:
    """将 Markdown 转换为导出友好的纯文本。"""
    text = strip_markdown_image_lines(markdown)
    text = re.sub(r"\\begin\{tasks\}(?:\([^)]+\))?", "", text)
    text = re.sub(r"\\end\{tasks\}", "", text)
    text = re.sub(r"\\task\s*", "• ", text)
    text = re.sub(r"\$\$(.*?)\$\$", lambda match: render_latex_inline(match.group(1)), text, flags=re.S)
    text = re.sub(r"\$(.*?)\$", lambda match: render_latex_inline(match.group(1)), text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)([^_\n]+)(?<!_)_(?!_)", r"\1", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def paper_header_lines(paper: dict[str, Any], questions: list[dict[str, Any]]) -> list[str]:
    """生成试卷导出页眉信息。"""
    header = paper.get("header") or {}
    total_score = sum(float(question.get("score", 0) or 0) for question in questions)
    lines = [str(paper.get("title") or "组卷")]
    if header.get("subtitle"):
        lines.append(str(header["subtitle"]))
    meta_parts = []
    if header.get("school"):
        meta_parts.append(f"学校：{header['school']}")
    if header.get("duration"):
        meta_parts.append(f"考试时长：{header['duration']}")
    meta_parts.append(f"满分：{total_score:g} 分")
    meta_parts.append(f"题量：{len(questions)} 题")
    if meta_parts:
        lines.append("　".join(meta_parts))
    lines.append("姓名：__________　班级：__________　考号：__________")
    if header.get("instructions"):
        lines.append(f"考生须知：{render_markdown_for_export(str(header['instructions']))}")
    return lines


def render_question_lines(question: dict[str, Any], number: int, include_answer: bool) -> list[str]:
    """生成单题导出的多行文本。"""
    raw_markdown = question.get("manualMarkdown") or question.get("stemMarkdown") or ""
    stem_markdown, task_options = split_tasks_options(str(raw_markdown))
    lines = [f"{number}. {render_markdown_for_export(stem_markdown)}"]
    options = question.get("options") or task_options
    for option in options:
        lines.append(f"{option.get('label')}. {render_markdown_for_export(str(option.get('content') or ''))}")
    score = question.get("score")
    if score is not None:
        lines.append(f"（本题 {float(score or 0):g} 分）")
    if include_answer:
        if question.get("answer"):
            lines.append(f"答案：{render_markdown_for_export(str(question.get('answer')))}")
        if question.get("analysis"):
            lines.append(f"解析：{render_markdown_for_export(str(question.get('analysis')))}")
    return lines


def render_question_plain(question: dict[str, Any], number: int, include_answer: bool) -> str:
    """生成单题导出的纯文本。"""
    return "\n".join(render_question_lines(question, number, include_answer))


def safe_resolved_child(root: Path, *parts: str) -> Path | None:
    """在根目录内安全解析子路径。"""
    try:
        target = root.joinpath(*parts).resolve()
        resolved_root = root.resolve()
        if str(target).startswith(str(resolved_root)) and target.exists() and target.is_file():
            return target
    except Exception:
        return None
    return None


def resolve_export_image_path(image: dict[str, Any]) -> Path | None:
    """解析导出时可读取的题图路径。"""
    if not isinstance(image, dict):
        return None
    raw_values = [str(image.get(key) or "").strip() for key in ("url", "path", "name")]
    url = raw_values[0]
    path = raw_values[1]

    ocr_match = re.search(r"/api/ocr/jobs/([^/]+)/files/(.+)$", url)
    if ocr_match:
        target = safe_resolved_child(OUTPUT_ROOT / ocr_match.group(1), ocr_match.group(2))
        if target:
            return target

    upload_match = re.search(r"/api/import-tasks/([^/]+)/questions/([^/]+)/images/([^/?#]+)", url)
    if upload_match:
        target = import_question_image_file(upload_match.group(1), upload_match.group(2), safe_filename(upload_match.group(3))).resolve()
        upload_root = IMPORT_UPLOAD_ROOT.resolve()
        if str(target).startswith(str(upload_root)) and target.exists() and target.is_file():
            return target

    upload_path_match = re.search(r"question_uploads/([^/]+)/([^/]+)/([^/?#]+)", path)
    if upload_path_match:
        target = import_question_image_file(upload_path_match.group(1), upload_path_match.group(2), safe_filename(upload_path_match.group(3))).resolve()
        upload_root = IMPORT_UPLOAD_ROOT.resolve()
        if str(target).startswith(str(upload_root)) and target.exists() and target.is_file():
            return target

    normalized_path = normalize_asset_path(path)
    if normalized_path:
        direct_candidates = [
            safe_resolved_child(OUTPUT_ROOT, normalized_path),
            safe_resolved_child(IMPORT_UPLOAD_ROOT, normalized_path),
            safe_resolved_child(STORAGE_ROOT, normalized_path),
        ]
        for candidate in direct_candidates:
            if candidate:
                return candidate
        filename = Path(normalized_path).name
        if filename:
            for root in (OUTPUT_ROOT, IMPORT_UPLOAD_ROOT):
                for candidate in root.rglob(filename):
                    if candidate.is_file() and normalize_asset_path(candidate.as_posix()).endswith(normalized_path):
                        return candidate
            for root in (OUTPUT_ROOT, IMPORT_UPLOAD_ROOT):
                found = next((candidate for candidate in root.rglob(filename) if candidate.is_file()), None)
                if found:
                    return found
    return None


def export_question_image_paths(question: dict[str, Any]) -> list[Path]:
    """收集题目导出需要插入的图片路径。"""
    paths: list[Path] = []
    seen: set[str] = set()
    for image in normalize_question_images(question.get("images", [])):
        path = resolve_export_image_path(image)
        if not path:
            continue
        key = path.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def export_paper_docx_legacy(paper: dict[str, Any], questions: list[dict[str, Any]], include_answer: bool) -> Path:
    """使用 python-docx 旧路径导出 DOCX。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt

    export_path = EXPORT_ROOT / f"{paper['id']}.docx"
    document = Document()

    normal_style = document.styles["Normal"]
    normal_style.font.name = "宋体"
    normal_style.font.size = Pt(11)
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def add_text_paragraph(text: str, *, alignment: Any = WD_ALIGN_PARAGRAPH.LEFT, size: int = 11, space_before: int = 0, space_after: int = 4) -> None:
        """执行 add text paragraph 逻辑。"""
        paragraph = document.add_paragraph()
        paragraph.alignment = alignment
        paragraph.paragraph_format.space_before = Pt(space_before)
        paragraph.paragraph_format.space_after = Pt(space_after)
        paragraph.paragraph_format.line_spacing = 1.35
        run = paragraph.add_run(text)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(size)

    def add_image_paragraph(image_path: Path) -> None:
        """执行 add image paragraph 逻辑。"""
        try:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(6)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            paragraph.add_run().add_picture(str(image_path), width=Inches(4.8))
        except Exception:
            add_text_paragraph(f"[题图无法导出：{image_path.name}]", size=10)

    header_lines = paper_header_lines(paper, questions)
    add_text_paragraph(header_lines[0], alignment=WD_ALIGN_PARAGRAPH.CENTER, size=14, space_after=6)
    for line in header_lines[1:]:
        alignment = WD_ALIGN_PARAGRAPH.CENTER if "：" not in line or line.startswith(("学校：", "姓名：")) else WD_ALIGN_PARAGRAPH.LEFT
        add_text_paragraph(line, alignment=alignment)
    add_text_paragraph("", space_after=2)
    for index, question in enumerate(questions, start=1):
        image_paths = export_question_image_paths(question)
        for line_index, line in enumerate(render_question_lines(question, index, include_answer)):
            add_text_paragraph(line, space_before=6 if line_index == 0 else 0)
            if line_index == 0:
                for image_path in image_paths:
                    add_image_paragraph(image_path)
        add_text_paragraph("", space_after=2)
    document.save(export_path)
    return export_path


def wrap_pdf_line(text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    """按 PDF 可用宽度拆分文本行。"""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    current = ""
    for char in text:
        next_text = current + char
        if current and stringWidth(next_text, font_name, font_size) > max_width:
            lines.append(current)
            current = char
        else:
            current = next_text
    if current:
        lines.append(current)
    return lines or [""]


def export_paper_pdf_legacy(paper: dict[str, Any], questions: list[dict[str, Any]], include_answer: bool) -> Path:
    """使用 reportlab 旧路径导出 PDF。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from PIL import Image

    font_name = "Helvetica"
    regular_font_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for font_path in regular_font_candidates:
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("ExamRegular", str(font_path), subfontIndex=0))
            font_name = "ExamRegular"
            break
        except Exception:
            continue
    if font_name == "Helvetica":
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            font_name = "STSong-Light"
        except Exception:
            font_name = "Helvetica"
    export_path = EXPORT_ROOT / f"{paper['id']}.pdf"
    pdf = canvas.Canvas(str(export_path), pagesize=A4)
    width, height = A4
    margin_x = 54
    y = height - 54
    max_width = width - margin_x * 2
    title_size = 14
    body_size = 11
    line_height = 17

    def ensure_space(required: float = 16) -> None:
        """执行 ensure space 逻辑。"""
        nonlocal y
        if y < 54 + required:
            pdf.showPage()
            y = height - 54
            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont(font_name, body_size)

    def draw_question_image(image_path: Path) -> None:
        """执行 draw question image 逻辑。"""
        nonlocal y
        try:
            with Image.open(image_path) as image:
                image_width, image_height = image.size
            if image_width <= 0 or image_height <= 0:
                return
            max_image_width = min(max_width, 360)
            max_image_height = 210
            scale = min(max_image_width / image_width, max_image_height / image_height, 1.0)
            draw_width = image_width * scale
            draw_height = image_height * scale
            ensure_space(draw_height + 14)
            y -= 4
            pdf.drawImage(ImageReader(str(image_path)), margin_x, y - draw_height, width=draw_width, height=draw_height, preserveAspectRatio=True, mask="auto")
            y -= draw_height + 10
            pdf.setFont(font_name, body_size)
        except Exception:
            for wrapped in wrap_pdf_line(f"[题图无法导出：{image_path.name}]", font_name, body_size, max_width):
                ensure_space()
                pdf.drawString(margin_x, y, wrapped)
                y -= line_height

    header_lines = paper_header_lines(paper, questions)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(font_name, title_size)
    pdf.drawCentredString(width / 2, y, header_lines[0])
    y -= 24
    pdf.setFont(font_name, body_size)
    for line in header_lines[1:]:
        centered = line.startswith(("学校：", "姓名：")) or "：" not in line
        for wrapped in wrap_pdf_line(line, font_name, body_size, max_width):
            ensure_space()
            pdf.drawCentredString(width / 2, y, wrapped) if centered else pdf.drawString(margin_x, y, wrapped)
            y -= line_height
    y -= 10
    for index, question in enumerate(questions, start=1):
        image_paths = export_question_image_paths(question)
        for line_index, line in enumerate(render_question_lines(question, index, include_answer)):
            for wrapped in wrap_pdf_line(line, font_name, body_size, max_width):
                ensure_space()
                pdf.drawString(margin_x, y, wrapped)
                y -= line_height
            if line_index == 0:
                for image_path in image_paths:
                    draw_question_image(image_path)
        y -= 8
        ensure_space()
    pdf.save()
    return export_path


def strip_markdown_images_for_pandoc(markdown: str) -> str:
    """移除 Pandoc 输入中的 Markdown 图片。"""
    return "\n".join(line for line in str(markdown or "").splitlines() if not re.search(r"!\[[^\]]*\]\([^)]+\)", line)).strip()


def normalize_tasks_for_pandoc(markdown: str) -> str:
    """将 tasks 环境转换为 Pandoc 友好格式。"""
    text = str(markdown or "")

    def replace_tasks(match: re.Match[str]) -> str:
        """执行 replace tasks 逻辑。"""
        task_parts = re.split(r"\\task\b", match.group("body"))[1:]
        lines = [f"- {part.strip()}" for part in task_parts if part.strip()]
        return "\n".join(lines)

    return re.sub(
        r"\\begin\{tasks\}(?:\([^)]+\))?(?P<body>.*?)\\end\{tasks\}",
        replace_tasks,
        text,
        flags=re.S,
    )


def pandoc_markdown_text(markdown: Any) -> str:
    """规范化传给 Pandoc 的 Markdown 文本。"""
    text = strip_markdown_images_for_pandoc(str(markdown or ""))
    text = normalize_tasks_for_pandoc(text)
    return text.strip()


def pandoc_image_markdown(image_path: Path) -> str:
    """生成 Pandoc 图片 Markdown。"""
    return f"![](<{image_path.resolve().as_posix()}>)"


def export_question_markdown(question: dict[str, Any], number: int, include_answer: bool) -> str:
    """生成单题 Pandoc 导出 Markdown。"""
    raw_markdown = str(question.get("manualMarkdown") or question.get("stemMarkdown") or "")
    stem_markdown, task_options = split_tasks_options(raw_markdown)
    lines: list[str] = [f"## {number}. （{float(question.get('score', 0) or 0):g} 分）", ""]
    if stem_markdown.strip():
        lines.extend([pandoc_markdown_text(stem_markdown), ""])
    for image_path in export_question_image_paths(question):
        lines.extend([pandoc_image_markdown(image_path), ""])

    options = question.get("options") or task_options
    if options:
        for option in options:
            label = str(option.get("label") or "").strip()
            content = pandoc_markdown_text(option.get("content") or "")
            prefix = f"- **{label}.** " if label else "- "
            lines.append(f"{prefix}{content}".rstrip())
        lines.append("")

    if include_answer:
        if question.get("answer"):
            lines.extend(["**答案：**", "", pandoc_markdown_text(question.get("answer")), ""])
        if question.get("analysis"):
            lines.extend(["**解析：**", "", pandoc_markdown_text(question.get("analysis")), ""])
    return "\n".join(lines).strip()


def export_paper_markdown(paper: dict[str, Any], questions: list[dict[str, Any]], include_answer: bool) -> Path:
    """生成整张试卷的 Pandoc 输入 Markdown 文件。"""
    export_path = EXPORT_ROOT / f"{paper['id']}.md"
    header = paper.get("header") or {}
    total_score = sum(float(question.get("score", 0) or 0) for question in questions)
    lines = [
        f"# {paper.get('title') or '组卷'}",
        "",
    ]
    if header.get("subtitle"):
        lines.extend([f"**{header['subtitle']}**", ""])

    meta_parts: list[str] = []
    if header.get("school"):
        meta_parts.append(f"学校：{header['school']}")
    if header.get("duration"):
        meta_parts.append(f"考试时长：{header['duration']}")
    meta_parts.extend([f"满分：{total_score:g} 分", f"题量：{len(questions)} 题"])
    lines.extend(["　".join(meta_parts), "", "姓名：__________　班级：__________　考号：__________", ""])

    if header.get("instructions"):
        lines.extend(["## 考生须知", "", pandoc_markdown_text(header["instructions"]), ""])

    for index, question in enumerate(questions, start=1):
        lines.extend([export_question_markdown(question, index, include_answer), ""])

    export_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return export_path


def preferred_pandoc_cjk_font() -> str:
    """选择 Pandoc PDF 导出优先使用的中文字体。"""
    configured = os.getenv("PANDOC_CJK_FONT")
    if configured:
        return configured
    for font_name in ("Songti SC", "PingFang SC", "Heiti SC", "STSong", "Noto Serif CJK SC"):
        return font_name
    return "Songti SC"


def run_pandoc(markdown_path: Path, output_path: Path, output_format: str) -> None:
    """调用 Pandoc 生成指定格式文件。"""
    pandoc_command = shutil.which("pandoc")
    if not pandoc_command:
        raise RuntimeError("Pandoc is not installed or not available on PATH")

    command = [
        pandoc_command,
        str(markdown_path),
        "-f",
        "markdown+tex_math_dollars+tex_math_single_backslash",
        "--standalone",
        "-o",
        str(output_path),
    ]
    if output_format == "pdf":
        xelatex_command = shutil.which("xelatex")
        if not xelatex_command:
            raise RuntimeError("XeLaTeX is not installed or not available on PATH")
        command.extend(
            [
                "--pdf-engine",
                xelatex_command,
                "-V",
                f"CJKmainfont={preferred_pandoc_cjk_font()}",
                "-V",
                "geometry:margin=2cm",
            ]
        )

    completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        error_path = output_path.with_suffix(f".pandoc-error.txt")
        error_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
        raise RuntimeError(f"Pandoc export failed; see {error_path.name}")


def export_flow_status() -> dict[str, Any]:
    """返回导出能力运行时状态。"""
    pandoc_command = shutil.which("pandoc")
    xelatex_command = shutil.which("xelatex")
    return {
        "capability": "export-flow",
        "formats": ["markdown", "docx", "pdf"],
        "strategy": "markdown-pandoc",
        "pandocInstalled": pandoc_command is not None,
        "pandocCommand": pandoc_command,
        "xelatexInstalled": xelatex_command is not None,
        "xelatexCommand": xelatex_command,
        "cjkFont": preferred_pandoc_cjk_font(),
        "fallbackEnabled": True,
        "exportRoot": str(EXPORT_ROOT),
    }


def export_paper_docx(paper: dict[str, Any], questions: list[dict[str, Any]], include_answer: bool) -> Path:
    """使用 Pandoc 导出 DOCX。"""
    output_path = EXPORT_ROOT / f"{paper['id']}.docx"
    try:
        markdown_path = export_paper_markdown(paper, questions, include_answer)
        run_pandoc(markdown_path, output_path, "docx")
        return output_path
    except Exception:
        return export_paper_docx_legacy(paper, questions, include_answer)


def export_paper_pdf(paper: dict[str, Any], questions: list[dict[str, Any]], include_answer: bool) -> Path:
    """使用 Pandoc 导出 PDF。"""
    output_path = EXPORT_ROOT / f"{paper['id']}.pdf"
    try:
        markdown_path = export_paper_markdown(paper, questions, include_answer)
        run_pandoc(markdown_path, output_path, "pdf")
        return output_path
    except Exception:
        return export_paper_pdf_legacy(paper, questions, include_answer)
