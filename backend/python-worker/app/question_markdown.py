"""题目 Markdown、题图和选项归一化工具。

这些函数服务 OCR 拆题、人工校验和导出链路，保持纯函数形态，避免直接读写业务状态。
"""

from app.worker_base import *

def relative_file_url(job_id: str, path: Path) -> str:
    """把 OCR 输出文件路径转换为接口可访问的相对 URL。"""
    relative = path.relative_to(OUTPUT_ROOT / job_id).as_posix()
    return f"/api/ocr/jobs/{job_id}/files/{relative}"


def infer_question_type(section_title: str) -> str:
    """根据题目小节标题推断题型。"""
    if "选择" in section_title:
        return "choice"
    if "填空" in section_title:
        return "fill_blank"
    if "解答" in section_title or "证明" in section_title or "计算" in section_title:
        return "solution"
    return "unknown"


FILL_BLANK_HINT_RE = re.compile(r"填空|横线|空格|空白|空缺|补全|填写|填入|填上|写在|填在")
FILL_BLANK_MARKER_RE = re.compile(r"_{2,}|＿{2,}|\\_")
TRAILING_FILL_BLANK_TEXT_RE = re.compile(r"(算术平方根是|平方根是|取值范围是|实数.*?值是|值为|值是|为|是)\s*$")


def is_fill_blank_markdown(markdown: str) -> bool:
    """判断题干是否明显属于填空/补全过程题。"""
    text = str(markdown or "")
    return bool(FILL_BLANK_HINT_RE.search(text) or FILL_BLANK_MARKER_RE.search(text))


def refine_question_type_from_markdown(question_type: str, markdown: str) -> str:
    """用题干关键词修正从大题标题继承来的题型。"""
    normalized = str(question_type or "unknown").strip()
    if normalized == "choice":
        return normalized
    if is_fill_blank_markdown(markdown):
        return "fill_blank"
    return normalized if normalized in {"choice", "fill_blank", "solution", "unknown"} else "unknown"


def normalize_fill_blank_markdown(markdown: str, question_type: str) -> str:
    """保守恢复填空题中的空位占位，避免横线在 OCR/公式清洗后完全消失。"""
    text = str(markdown or "").strip()
    if question_type != "fill_blank" or not text:
        return text

    text = normalize_explicit_blank_markers(text)
    text = replace_blank_slot_noise_lines(text)
    text = restore_missing_blank_after_formula_equals(text)
    text = restore_missing_blank_at_line_end(text)
    return text.strip()


def normalize_explicit_blank_markers(markdown: str) -> str:
    """统一 OCR 已经识别出的显式空位符号。"""
    text = re.sub(r"[＿_]{2,}", "____", markdown)
    return re.sub(r"\(\s*(?:\\_+|_+|＿+|\$|[\"“”'])\s*\)", "(____)", text)


def replace_blank_slot_noise_lines(markdown: str) -> str:
    """把填空题中短噪声行转成空位，而不是保留为正文。"""
    lines = []
    for line in markdown.splitlines():
        lines.append("____" if is_blank_slot_noise_line(line) else line)
    return "\n".join(lines)


def is_blank_slot_noise_line(line: str) -> bool:
    """识别被 OCR 误读成短字母/数字/标点的空线。"""
    compact = re.sub(r"\s+", "", str(line or ""))
    if not compact or len(compact) > 8:
        return False
    if re.search(r"[\u4e00-\u9fff\\=+\-*/×÷^_{}]", compact):
        return False
    if not re.search(r"[A-Ha-h]", compact) or not re.search(r"[\)）\].。]", compact):
        return False
    return bool(re.fullmatch(r"[0-9Il|]{0,3}[A-Ha-h]?[\)）\].。]+", compact))


def restore_missing_blank_after_formula_equals(markdown: str) -> str:
    """为以等号结尾的行内公式补空位占位。"""
    text = re.sub(
        r"(\$[^$\n]*=\s*\$)(?!\s*(?:_{2,}|＿{2,}|\\_|____))",
        r"\1 ____",
        markdown,
    )
    return text


def restore_missing_blank_at_line_end(markdown: str) -> str:
    """为行尾明显等待填写的位置补空位占位。"""
    normalized_lines = []
    for line in markdown.splitlines():
        stripped = line.rstrip()
        if not re.search(r"_{2,}|＿{2,}|\\_", stripped):
            if re.search(r"=\s*$", stripped):
                stripped = f"{stripped} ____"
            elif TRAILING_FILL_BLANK_TEXT_RE.search(stripped):
                stripped = f"{stripped} ____"
        normalized_lines.append(stripped)
    return "\n".join(normalized_lines)


def fragment_to_markdown(fragment: dict[str, Any]) -> str:
    """将 OCR fragment 转换为 Markdown 文本。"""
    fragment_type = fragment.get("type")
    content = fragment.get("content", "")
    if fragment_type in {"equation_inline", "inline_equation"}:
        return f"${content}$"
    if fragment_type in {"equation_interline", "interline_equation"}:
        return f"\n\n$$\n{content}\n$$\n\n"
    return str(content)


def content_parts_to_markdown(parts: list[dict[str, Any]]) -> str:
    """将 content parts 列表转换为 Markdown。"""
    return "".join(fragment_to_markdown(part) for part in parts).strip()


def block_to_markdown(block: dict[str, Any]) -> str:
    """将 OCR block 转换为 Markdown。"""
    block_type = block.get("type")
    content = block.get("content", {})
    if block_type == "title":
        return content_parts_to_markdown(content.get("title_content", []))
    if block_type == "paragraph":
        return content_parts_to_markdown(content.get("paragraph_content", []))
    if block_type == "list":
        items = []
        for item in content.get("list_items", []):
            items.append(content_parts_to_markdown(item.get("item_content", [])))
        return "\n".join(item for item in items if item)
    if block_type == "equation_interline":
        math_content = content.get("math_content", "")
        return f"$$\n{math_content}\n$$".strip()
    return ""


def normalize_asset_path(path: str) -> str:
    """归一化 OCR 资源路径。"""
    return path.split("?", 1)[0].split("#", 1)[0].lstrip("./")


def image_from_path(image_path: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """根据图片路径和资源列表构造题图对象。"""
    normalized_image_path = normalize_asset_path(image_path)
    image_name = Path(normalized_image_path).name
    matched_asset = next(
        (
            asset
            for asset in assets
            if normalize_asset_path(asset["path"]) == normalized_image_path
            or normalize_asset_path(asset["path"]).endswith(f"/{normalized_image_path}")
            or asset["name"] == image_name
        ),
        None,
    )
    if matched_asset:
        return {
            "name": matched_asset["name"],
            "path": matched_asset["path"],
            "url": matched_asset["url"],
        }
    return {"name": image_name, "path": normalized_image_path, "url": None}


def split_choice_options(markdown: str, question_type: str) -> tuple[str, list[dict[str, str]]]:
    """从题干 Markdown 中拆分选择题选项。"""
    task_stem, task_options = split_tasks_options(markdown)
    if len(task_options) >= 2:
        return task_stem, task_options

    if question_type != "choice":
        return markdown.strip(), []

    matches = detect_choice_option_markers(markdown)

    option_matches: list[dict[str, Any]] = []
    for start_index, match in enumerate(matches):
        if match["label"] != "A":
            continue
        current = [match]
        expected = "B"
        for cursor in range(start_index + 1, len(matches)):
            if matches[cursor]["label"] == expected:
                current.append(matches[cursor])
                expected = chr(ord(expected) + 1)
                continue
            if current:
                break
        if len(current) >= 2:
            option_matches = current
            break

    if len(option_matches) < 2:
        return markdown.strip(), []

    stem = re.sub(r"[-*+]\s*$", "", markdown[: option_matches[0]["marker_start"]]).strip()
    options: list[dict[str, str]] = []
    trailing_image_block = ""
    for index, match in enumerate(option_matches):
        next_start = option_matches[index + 1]["marker_start"] if index + 1 < len(option_matches) else len(markdown)
        content = re.sub(r"^[\s\r\n\-*+]+", "", markdown[match["content_start"] : next_start]).strip()
        if index == len(option_matches) - 1:
            content, trailing_image_block = split_trailing_image_block(content)
        if content:
            options.append({"label": match["label"], "content": content})
    if trailing_image_block:
        stem = f"{stem}\n\n{trailing_image_block}".strip()
    return (stem, options) if len(options) >= 2 else (markdown.strip(), [])


def normalize_choice_label(value: str) -> str:
    """归一化半角/全角选项字母。"""
    if not value:
        return ""
    char = value[0]
    code = ord(char)
    if 0xFF21 <= code <= 0xFF28:
        return chr(code - 0xFF21 + ord("A"))
    if 0xFF41 <= code <= 0xFF48:
        return chr(code - 0xFF41 + ord("A"))
    return char.upper()


def detect_choice_option_markers(markdown: str) -> list[dict[str, Any]]:
    """识别稳定的选择题选项标记。"""
    label_pattern = r"[A-Ha-hＡ-Ｈａ-ｈ]"
    punctuated_pattern = re.compile(
        rf"(^|[\r\n]+|[ \t　]+|[。；;：:，,、?？）)]\s*)"
        rf"(?:[-*+]\s*)?(?:[（(]?({label_pattern})[）)]|({label_pattern})[\.．、:：])\s*"
    )
    bare_line_pattern = re.compile(rf"(^|[\r\n]+)\s*(?:[-*+]\s*)?({label_pattern})(?=\s+)")
    markers: list[dict[str, Any]] = []
    for match in punctuated_pattern.finditer(markdown):
        label = normalize_choice_label(match.group(2) or match.group(3) or "")
        if not label:
            continue
        markers.append(
            {
                "label": label,
                "marker_start": match.start() + len(match.group(1) or ""),
                "content_start": match.end(),
            }
        )
    for match in bare_line_pattern.finditer(markdown):
        label = normalize_choice_label(match.group(2) or "")
        if not label:
            continue
        markers.append(
            {
                "label": label,
                "marker_start": match.start() + len(match.group(1) or ""),
                "content_start": match.end(),
            }
        )
    deduped: dict[tuple[int, str], dict[str, Any]] = {}
    for marker in markers:
        deduped[(int(marker["marker_start"]), str(marker["label"]))] = marker
    return sorted(deduped.values(), key=lambda item: (item["marker_start"], item["content_start"]))


TRAILING_IMAGE_BLOCK_RE = re.compile(r"(?:\s*!\[[^\]]*]\([^)]+\)\s*)+$")


def split_trailing_image_block(content: str) -> tuple[str, str]:
    """把最后一个选项末尾独立题图移回题干，避免污染 D 选项。"""
    match = TRAILING_IMAGE_BLOCK_RE.search(str(content or ""))
    if not match:
        return content, ""
    before = content[: match.start()].rstrip()
    trailing = match.group(0).strip()
    if not before or not trailing:
        return content, ""
    return before, trailing


def normalize_image_ref(value: Any) -> str:
    """归一化题图引用字符串。"""
    try:
        return re.sub(r"[?#].*$", "", str(value or "")).replace("\\", "/").lstrip("./").lower()
    except Exception:
        return ""


def markdown_contains_question_image(markdown: str, image: dict[str, Any]) -> bool:
    """判断 Markdown 是否已包含指定题图。"""
    haystack = str(markdown or "").lower()
    for key in ("path", "name", "url"):
        normalized = normalize_image_ref(image.get(key))
        if not normalized:
            continue
        filename = normalized.rsplit("/", 1)[-1]
        if normalized in haystack or (filename and filename in haystack):
            return True
    return False


def question_image_markdown(image: dict[str, Any], index: int) -> str:
    """生成题图 Markdown 片段。"""
    src = str(image.get("path") or image.get("url") or image.get("name") or "").strip()
    if not src:
        return ""
    alt = re.sub(r"[\[\]\r\n]+", " ", str(image.get("name") or f"题图 {index + 1}")).strip()
    return f"![{alt}]({src})"


def append_question_images_to_markdown(markdown: str, images: Any) -> str:
    """将题图追加到题目 Markdown 末尾。"""
    base = str(markdown or "").strip()
    if not isinstance(images, list):
        return base
    image_lines = [
        line
        for index, image in enumerate(images)
        if isinstance(image, dict) and not markdown_contains_question_image(base, image)
        for line in [question_image_markdown(image, index)]
        if line
    ]
    if not image_lines:
        return base

    image_block = "\n\n".join(image_lines)
    tasks_match = re.search(r"\\begin\{t+asks\}", base, flags=re.I)
    if tasks_match:
        before_tasks = base[: tasks_match.start()].rstrip()
        after_tasks = base[tasks_match.start() :].lstrip()
        separator = "\n\n" if before_tasks else ""
        return f"{before_tasks}{separator}{image_block}\n\n{after_tasks}".strip()
    separator = "\n\n" if base else ""
    return f"{base}{separator}{image_block}".strip()


def strip_question_images_from_markdown(markdown: str, images: Any) -> str:
    """从 Markdown 中移除已结构化的题图片段。"""
    text = str(markdown or "")
    if not text or not isinstance(images, list):
        return text.strip()
    refs: set[str] = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        for key in ("path", "url", "name"):
            value = str(image.get(key) or "").strip()
            if not value:
                continue
            normalized = normalize_asset_path(value)
            refs.add(value)
            refs.add(normalized)
            refs.add(Path(normalized).name)
    if not refs:
        return text.strip()

    def should_remove(line: str) -> bool:
        """执行 should remove 逻辑。"""
        match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", line)
        if not match:
            return False
        src = match.group(1).strip()
        candidates = {src, normalize_asset_path(src), Path(normalize_asset_path(src)).name}
        return any(candidate and candidate in refs for candidate in candidates)

    return "\n".join(line for line in text.splitlines() if not should_remove(line)).strip()


def normalize_question_images(images: Any) -> list[dict[str, Any]]:
    """归一化题图列表结构。"""
    if not isinstance(images, list):
        return []
    normalized_images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        path = str(image.get("path") or image.get("url") or image.get("name") or "").strip()
        url = image.get("url")
        if not path and not url:
            continue
        name = str(image.get("name") or Path(normalize_asset_path(path)).name or f"题图 {index + 1}").strip()
        key = str(url or path)
        if key in seen:
            continue
        seen.add(key)
        normalized_image = {"name": name, "path": path, "url": url}
        for key in (
            "source",
            "size",
            "type",
            "storageFileId",
            "fileId",
            "imageId",
            "contentType",
            "imageDataUrl",
            "dataUrl",
            "data_url",
            "aiImageIncluded",
            "aiImageSkipReason",
        ):
            if key in image:
                normalized_image[key] = image[key]
        normalized_images.append(normalized_image)
    return normalized_images


def ensure_question_images_in_markdown(question: dict[str, Any]) -> bool:
    """确保题目 Markdown 中包含题图引用。"""
    changed = False
    images = question.get("images") or []
    if images:
        stem_markdown = str(question.get("stemMarkdown") or "")
        next_stem_markdown = strip_question_images_from_markdown(stem_markdown, images)
        if next_stem_markdown != stem_markdown:
            question["stemMarkdown"] = next_stem_markdown
            changed = True

        if question.get("manualMarkdown"):
            manual_markdown = str(question.get("manualMarkdown") or "")
            next_manual_markdown = strip_question_images_from_markdown(manual_markdown, images)
            if next_manual_markdown != manual_markdown:
                question["manualMarkdown"] = next_manual_markdown
                changed = True

    for child in question.get("children", []):
        if isinstance(child, dict):
            changed = ensure_question_images_in_markdown(child) or changed
    return changed


def question_to_edit_markdown(question: dict[str, Any]) -> str:
    """将题目转换为人工编辑 Markdown。"""
    if question.get("manualMarkdown"):
        return strip_question_images_from_markdown(str(question["manualMarkdown"]), question.get("images"))
    markdown = strip_question_images_from_markdown(str(question.get("stemMarkdown") or ""), question.get("images"))
    options = question.get("options") or []
    if options:
        option_lines = ["", r"\begin{tasks}(2)"]
        for option in options:
            if isinstance(option, dict):
                option_lines.append(rf"\task {option.get('content', '')}")
        option_lines.append(r"\end{tasks}")
        markdown = f"{markdown}\n".rstrip() + "\n".join(option_lines)
    return markdown


def normalize_tasks_environment(markdown: str) -> str:
    """规范化 LaTeX tasks 环境。"""
    return re.sub(
        r"\\(begin|end)\{t+asks\}",
        lambda match: f"\\{match.group(1)}{{tasks}}",
        str(markdown or ""),
        flags=re.I,
    )


def split_tasks_options(markdown: str) -> tuple[str, list[dict[str, str]]]:
    """从 tasks 环境中拆分选项。"""
    normalized = normalize_tasks_environment(markdown)
    match = re.search(r"\\begin\{tasks\}(?:\([^)]+\)|\[[^\]]+\])?(?P<body>.*?)\\end\{tasks\}", normalized, flags=re.S)
    stem_source = normalized
    if not match:
        task_matches = list(re.finditer(r"\\task\b", normalized))
        if len(task_matches) < 2:
            return normalized.strip(), []
        match = None
        stem_source = normalized
        body = normalized[task_matches[0].start() :]
        stem = normalized[: task_matches[0].start()].strip()
    else:
        body = match.group("body")
        stem = f"{stem_source[: match.start()]}\n{stem_source[match.end() :]}".strip()
    task_parts = re.split(r"\\task\b", body)[1:]
    options = [
        {"label": chr(65 + index), "content": content.strip()}
        for index, content in enumerate(task_parts)
        if content.strip()
    ]
    return stem, options


def apply_edit_markdown_to_question(question: dict[str, Any], markdown: str) -> None:
    """将人工编辑 Markdown 解析回题目结构。"""
    if question.get("type") == "choice":
        stem, options = split_tasks_options(markdown)
        if not options:
            stem, options = split_choice_options(markdown, question["type"])
        question["stemMarkdown"] = stem.strip()
        if options:
            question["options"] = options
        return
    question["stemMarkdown"] = markdown.strip()


def merge_question_markdown(question: dict[str, Any], markdown: str) -> None:
    """将新的 Markdown 内容合并到题目字段。"""
    if not markdown:
        return
    stem, options = split_choice_options(markdown, question["type"])
    if stem:
        question["stemMarkdown"] = f"{question['stemMarkdown']}\n\n{stem}".strip()
    if options:
        existing_labels = {option["label"] for option in question["options"]}
        for option in options:
            if option["label"] not in existing_labels:
                question["options"].append(option)
