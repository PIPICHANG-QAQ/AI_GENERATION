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


def normalize_question_image_label(value: Any) -> str:
    """归一化题图标签为 图N。"""
    match = re.match(r"^(?:题图|图|#)?\s*([1-9]\d*)$", str(value or "").strip(), flags=re.I)
    return f"图{int(match.group(1))}" if match else ""


def question_image_label(image: dict[str, Any], index: int) -> str:
    """返回题图稳定标签。"""
    for key in ("label", "refLabel", "imageLabel"):
        label = normalize_question_image_label(image.get(key))
        if label:
            return label
    raw = image.get("raw")
    if isinstance(raw, dict):
        for key in ("label", "refLabel", "imageLabel"):
            label = normalize_question_image_label(raw.get(key))
            if label:
                return label
    name_label = normalize_question_image_label(image.get("name"))
    if name_label:
        return name_label
    return f"图{index + 1}"


def image_label_number(label: str) -> int:
    """返回 图N 中的 N。"""
    match = re.match(r"^图([1-9]\d*)$", str(label or "").strip())
    return int(match.group(1)) if match else 0


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
    glued_punctuated_pattern = re.compile(rf"(?<=[\u4e00-\u9fff）)\]}}])([B-Hb-hＢ-Ｈｂ-ｈ])[\.．、:：]\s*")
    bare_line_pattern = re.compile(rf"(^|[\r\n]+)\s*(?:[-*+]\s*)?({label_pattern})(?=\s+)")
    weak_inline_pattern = re.compile(
        rf"(?<=[\u4e00-\u9fff）)\]}}])[ \t　]+({label_pattern})[ \t]*"
        rf"(?=\r?\n(?:[ \t]*\r?\n)*[ \t]*(?:!\[|<!--\s*page-break))"
    )
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
                "strength": "strong",
                "reasons": ["punctuated-option-label"],
            }
        )
    for match in glued_punctuated_pattern.finditer(markdown):
        label = normalize_choice_label(match.group(1) or "")
        if not label:
            continue
        markers.append(
            {
                "label": label,
                "marker_start": match.start(1),
                "content_start": match.end(),
                "strength": "strong",
                "reasons": ["glued-punctuated-option-label"],
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
                "strength": "strong",
                "reasons": ["bare-line-option-label"],
            }
        )
    strong_markers = sorted(markers, key=lambda item: (item["marker_start"], item["content_start"]))
    for match in weak_inline_pattern.finditer(markdown):
        label = normalize_choice_label(match.group(1) or "")
        if not label or not has_expected_strong_prefix(strong_markers, label, match.start(1)):
            continue
        markers.append(
            {
                "label": label,
                "marker_start": match.start(1),
                "content_start": match.end(),
                "strength": "weak",
                "reasons": ["embedded-expected-label", "followed-by-layout-block"],
            }
        )
    deduped: dict[tuple[int, str], dict[str, Any]] = {}
    for marker in markers:
        deduped[(int(marker["marker_start"]), str(marker["label"]))] = marker
    return sorted(deduped.values(), key=lambda item: (item["marker_start"], item["content_start"]))


def has_expected_strong_prefix(markers: list[dict[str, Any]], label: str, before: int) -> bool:
    """弱标签仅在已有 A 起始的连续强标签链后生效。"""
    preceding = [marker for marker in markers if int(marker.get("marker_start") or 0) < before]
    for index, marker in enumerate(preceding):
        if marker.get("label") != "A":
            continue
        expected = "B"
        for current in preceding[index + 1 :]:
            if current.get("label") != expected:
                break
            expected = chr(ord(expected) + 1)
        if expected == label:
            return True
    return False


MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+['\"][^)]*['\"])?\s*\)")
TRAILING_IMAGE_BLOCK_RE = re.compile(r"(?:\s*!\[[^\]]*]\s*\([^)]+\)\s*)+$")
QUESTION_IMAGE_CUE_RE = re.compile(r"如图|下图|图中|图示|示意图|图形|标志|图[①②③④⑤⑥⑦⑧⑨⑩一二三四五六七八九十1-9]")


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
    label = question_image_label(image, int(image.get("index", 0) or 0))
    label_number = image_label_number(label)
    if label and re.search(rf"!\[[^\]]*]\s*\(\s*(?:{re.escape(label)}|题图{label_number}|#{label_number})\s*\)", str(markdown or "")):
        return True
    for key in ("path", "name", "url"):
        normalized = normalize_image_ref(image.get(key))
        if not normalized:
            continue
        filename = normalized.rsplit("/", 1)[-1]
        if normalized in haystack or (filename and filename in haystack):
            return True
    return False


def markdown_referenced_image_labels(markdown: str, images: Any) -> set[str]:
    """返回 Markdown 中已引用的题图标签。"""
    labels: set[str] = set()
    if not isinstance(images, list):
        return labels
    normalized_images = normalize_question_images(images)
    for index, image in enumerate(normalized_images):
        if isinstance(image, dict) and markdown_contains_question_image(markdown, image):
            label = question_image_label(image, index)
            if label:
                labels.add(label)
    return labels


def question_text_suggests_image(markdown: str) -> bool:
    """判断题干文字是否明显需要未定位题图。"""
    text = MARKDOWN_IMAGE_RE.sub("", str(markdown or ""))
    return bool(QUESTION_IMAGE_CUE_RE.search(text))


def filter_question_images_for_context(
    images: Any,
    stem_markdown: str,
    options: Any = None,
    *,
    question_type: str = "",
    answer: str = "",
    analysis: str = "",
) -> list[dict[str, Any]]:
    """过滤明显未被当前题引用的题图，避免相邻题题图污染。"""
    normalized_images = normalize_question_images(images)
    if not normalized_images:
        return []
    option_markdowns = option_texts(options)
    normalized_type = str(question_type or "").strip()
    stem_has_image_cue = question_text_suggests_image(stem_markdown)
    trusted_context_texts = [
        *option_markdowns,
        str(answer or ""),
        str(analysis or ""),
    ]
    if normalized_type != "choice" or stem_has_image_cue or not option_markdowns:
        trusted_context_texts.insert(0, str(stem_markdown or ""))
    referenced: list[dict[str, Any]] = []
    unreferenced: list[dict[str, Any]] = []
    for image in normalized_images:
        if any(markdown_contains_question_image(text, image) for text in trusted_context_texts):
            referenced.append(image)
        else:
            unreferenced.append(image)

    if not unreferenced:
        return normalized_images
    if normalized_type != "choice":
        return normalized_images
    if referenced:
        return referenced
    if stem_has_image_cue:
        return normalized_images
    return []


def remove_question_images_from_markdown(markdown: str, images: Any) -> str:
    """从 Markdown 中删除指定题图引用。"""
    text = str(markdown or "")
    normalized_images = normalize_question_images(images)
    if not text or not normalized_images:
        return text.strip()
    refs: set[str] = set()
    for index, image in enumerate(normalized_images):
        label = question_image_label(image, index)
        if label:
            refs.add(normalize_image_ref(label))
            label_number = image_label_number(label)
            if label_number:
                refs.add(normalize_image_ref(f"题图{label_number}"))
                refs.add(normalize_image_ref(f"#{label_number}"))
        for key in ("path", "url", "name"):
            value = str(image.get(key) or "").strip()
            if not value:
                continue
            normalized = normalize_asset_path(value)
            refs.add(normalize_image_ref(value))
            refs.add(normalize_image_ref(normalized))
            refs.add(normalize_image_ref(Path(normalized).name))

    def replace_ref(match: re.Match[str]) -> str:
        src = match.group(1).strip().strip("<>")
        normalized = normalize_image_ref(src)
        filename = normalize_image_ref(Path(normalize_asset_path(src)).name)
        if normalized in refs or filename in refs:
            return ""
        return match.group(0)

    return re.sub(r"\n{3,}", "\n\n", MARKDOWN_IMAGE_RE.sub(replace_ref, text)).strip()


def question_image_markdown(image: dict[str, Any], index: int) -> str:
    """生成题图 Markdown 片段。"""
    if not isinstance(image, dict):
        return ""
    return f"![]({question_image_label(image, index)})"


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


def strip_question_images_from_markdown(
    markdown: str,
    images: Any,
    *,
    append_missing: bool = True,
    sibling_texts: Any = None,
) -> str:
    """把 Markdown 题图引用规范为稳定 图N 标签，并补齐缺失引用。"""
    text = str(markdown or "")
    if not text or not isinstance(images, list):
        return text.strip()
    normalized_images = normalize_question_images(images)
    refs_by_label: dict[str, set[str]] = {}
    for index, image in enumerate(normalized_images):
        if not isinstance(image, dict):
            continue
        label = question_image_label(image, index)
        refs: set[str] = {normalize_image_ref(label)}
        label_number = image_label_number(label)
        if label_number:
            refs.add(normalize_image_ref(f"题图{label_number}"))
            refs.add(normalize_image_ref(f"#{label_number}"))
        for key in ("path", "url", "name"):
            value = str(image.get(key) or "").strip()
            if not value:
                continue
            normalized = normalize_asset_path(value)
            refs.add(value)
            refs.add(normalized)
            refs.add(Path(normalized).name)
        refs_by_label[label] = {normalize_image_ref(ref) for ref in refs if ref}
    if not refs_by_label:
        return text.strip()

    used_labels: set[str] = set()
    sibling_markdowns = [str(item or "") for item in sibling_texts] if isinstance(sibling_texts, list) else []
    sibling_labels: set[str] = set()
    for sibling_markdown in sibling_markdowns:
        sibling_labels.update(markdown_referenced_image_labels(sibling_markdown, normalized_images))

    def replace_ref(match: re.Match[str]) -> str:
        src = match.group(1).strip().strip("<>")
        normalized = normalize_image_ref(src)
        filename = Path(normalize_asset_path(src)).name.lower()
        for label, refs in refs_by_label.items():
            if normalized in refs or filename in refs:
                if label in sibling_labels:
                    return ""
                used_labels.add(label)
                return f"![]({label})"
        return match.group(0)

    normalized_text = re.sub(r"\n{3,}", "\n\n", MARKDOWN_IMAGE_RE.sub(replace_ref, text)).strip()
    if not append_missing:
        return normalized_text.strip()

    missing_lines = []
    for index, image in enumerate(normalized_images):
        label = question_image_label(image, index)
        is_referenced_elsewhere = any(markdown_contains_question_image(item, image) for item in sibling_markdowns)
        if label and label not in used_labels and not markdown_contains_question_image(normalized_text, image) and not is_referenced_elsewhere:
            missing_lines.append(question_image_markdown(image, index))
    if missing_lines:
        separator = "\n\n" if normalized_text.strip() else ""
        missing_block = "\n\n".join(missing_lines)
        normalized_text = f"{normalized_text.strip()}{separator}{missing_block}"
    return normalized_text.strip()


def first_text_value(*values: Any) -> str:
    """返回第一个非空文本值。"""
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def normalize_question_options_image_refs(options: Any, images: Any) -> list[dict[str, Any]]:
    """规范选择题选项中的题图引用，但不把缺失题图追加到选项里。"""
    if not isinstance(options, list):
        return []
    normalized_options: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for index, item in enumerate(options):
        raw = item if isinstance(item, dict) else {}
        fallback_label = chr(65 + index)
        label = normalize_choice_label(
            str(raw.get("label") or raw.get("key") or raw.get("name") or raw.get("option") or fallback_label)
            if isinstance(raw, dict)
            else fallback_label
        )
        content = (
            first_text_value(raw.get("contentMarkdown"), raw.get("markdown"), raw.get("text"), raw.get("content"), raw.get("value"))
            if isinstance(raw, dict)
            else str(item or "").strip()
        )
        if images:
            content = strip_question_images_from_markdown(content, images, append_missing=False)
        if not label or not content or label in seen_labels:
            continue
        seen_labels.add(label)
        normalized_options.append({"label": label, "content": content, "contentMarkdown": content})
    return normalized_options


def reconcile_choice_option_image_refs(question: dict[str, Any]) -> bool:
    """按可信放置结果原子化选择题选项中的题图与文字。"""
    if str(question.get("type") or "").strip() != "choice":
        return False
    images = normalize_question_images(question.get("images") or [])
    options = normalize_question_options_image_refs(question.get("options") or [], images)
    placements = [item for item in question.get("imagePlacements") or [] if isinstance(item, dict)]
    if len(options) < 2 or not images or not placements:
        return False

    images_by_id: dict[str, dict[str, Any]] = {}
    canonical_id_by_image: dict[int, str] = {}
    for image in images:
        canonical_id = ""
        for key in ("imageId", "path", "url", "name"):
            normalized = normalize_asset_path(str(image.get(key) or ""))
            if normalized:
                images_by_id[normalized] = image
                canonical_id = canonical_id or normalized
        if canonical_id:
            canonical_id_by_image[id(image)] = canonical_id

    option_labels = {str(option.get("label") or "").strip().upper() for option in options}
    candidates_by_image: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
    for fallback_order, placement in enumerate(placements):
        target = placement.get("target") if isinstance(placement.get("target"), dict) else {}
        option_label = normalize_choice_label(str(target.get("optionLabel") or ""))
        if target.get("kind") != "option" or not option_label:
            continue
        inference = placement.get("inference") if isinstance(placement.get("inference"), dict) else {}
        confidence = float(inference.get("confidence") or 0.0)
        review_status = str(placement.get("reviewStatus") or "").strip()
        if review_status not in {"confirmed", "overridden"} and (
            review_status == "needs_review" or confidence < 0.95
        ):
            continue
        image_id = normalize_asset_path(str(placement.get("imageId") or ""))
        image = images_by_id.get(image_id)
        if image is None:
            continue
        order = placement.get("order")
        canonical_id = canonical_id_by_image.get(id(image))
        if canonical_id:
            candidates_by_image.setdefault(canonical_id, []).append(
                (int(order) if isinstance(order, int) else fallback_order, option_label, image)
            )
    trusted = [
        candidates[0]
        for candidates in candidates_by_image.values()
        if len(candidates) == 1 and candidates[0][1] in option_labels
    ]
    if not trusted:
        return False

    trusted.sort(key=lambda item: item[0])
    trusted_images = [image for _order, _label, image in trusted]
    tokens_by_label: dict[str, list[str]] = {}
    for image_index, (_order, option_label, image) in enumerate(trusted):
        token = question_image_markdown(image, image_index)
        if token and token not in tokens_by_label.setdefault(option_label, []):
            tokens_by_label[option_label].append(token)

    next_options: list[dict[str, Any]] = []
    for option in options:
        label = str(option.get("label") or "").strip().upper()
        text = remove_question_images_from_markdown(option.get("content") or "", trusted_images)
        text = re.sub(r"\s+", " ", text).strip()
        content = " ".join([*tokens_by_label.get(label, []), text]).strip()
        next_options.append({**option, "content": content, "contentMarkdown": content})

    changed = next_options != options
    if changed:
        question["options"] = next_options
    return changed


def trailing_question_images(markdown: str, images: Any) -> list[dict[str, Any]]:
    """提取题干末尾连续题图块对应的题图。"""
    normalized_images = normalize_question_images(images)
    match = TRAILING_IMAGE_BLOCK_RE.search(str(markdown or ""))
    if not match or not normalized_images:
        return []
    matched_images: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for image_match in MARKDOWN_IMAGE_RE.finditer(match.group(0)):
        src = image_match.group(1).strip().strip("<>")
        probe = f"![]({src})"
        for image in normalized_images:
            label = question_image_label(image, len(matched_images))
            if label in seen_labels:
                continue
            if markdown_contains_question_image(probe, image):
                matched_images.append(image)
                seen_labels.add(label)
                break
    return matched_images


def attach_choice_images_to_text_options(
    stem_markdown: str,
    options: Any,
    images: Any,
    question_type: str,
) -> list[dict[str, Any]]:
    """把 OCR 识别到但堆在题干尾部的选项题图分配回 A/B/C/D 选项。"""
    normalized_images = normalize_question_images(images)
    normalized_options = normalize_question_options_image_refs(options, normalized_images)
    if str(question_type or "").strip() != "choice" or len(normalized_options) < 2 or not normalized_images:
        return normalized_options
    if any(markdown_referenced_image_labels(option.get("content") or "", normalized_images) for option in normalized_options):
        return normalized_options

    option_count = len(normalized_options)
    candidates = trailing_question_images(stem_markdown, normalized_images)
    if len(candidates) != option_count:
        candidates = normalized_images if len(normalized_images) == option_count else []
    if len(candidates) != option_count or not question_text_suggests_image(stem_markdown):
        return normalized_options

    attached_options: list[dict[str, Any]] = []
    for option, image in zip(normalized_options, candidates):
        content = str(option.get("content") or option.get("contentMarkdown") or "").strip()
        image_markdown = question_image_markdown(image, 0)
        next_content = f"{image_markdown}\n\n{content}".strip() if content else image_markdown
        attached_options.append({
            **option,
            "content": next_content,
            "contentMarkdown": next_content,
        })
    return attached_options


def option_texts(options: Any) -> list[str]:
    """提取选项正文，用于题图引用去重。"""
    if not isinstance(options, list):
        return []
    texts = []
    for option in options:
        if not isinstance(option, dict):
            continue
        content = first_text_value(option.get("contentMarkdown"), option.get("content"), option.get("markdown"), option.get("text"))
        if content:
            texts.append(content)
    return texts


def normalize_question_images(images: Any) -> list[dict[str, Any]]:
    """归一化题图列表结构。"""
    if not isinstance(images, list):
        return []
    normalized_images: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_label = 0
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
        label = question_image_label(image, index)
        label_number = image_label_number(label)
        if label_number <= max_label and not normalize_question_image_label(image.get("label")):
            label_number = max_label + 1
            label = f"图{label_number}"
        max_label = max(max_label, label_number)
        normalized_image = {"name": name, "path": path, "url": url, "label": label, "refLabel": label}
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
            "sourceEvidence",
            "pageIndex",
            "bbox",
        ):
            if key in image:
                normalized_image[key] = image[key]
        normalized_images.append(normalized_image)
    return normalized_images


def ensure_question_images_in_markdown(question: dict[str, Any]) -> bool:
    """确保题目 Markdown 中包含题图引用。"""
    changed = False
    images = normalize_question_images(question.get("images") or [])
    if images != (question.get("images") or []):
        question["images"] = images
        changed = True
    if question.get("options"):
        next_options = attach_choice_images_to_text_options(
            str(question.get("stemMarkdown") or question.get("manualMarkdown") or ""),
            question.get("options"),
            images,
            str(question.get("type") or ""),
        )
        if next_options != question.get("options"):
            question["options"] = next_options
            changed = True
    next_images = filter_question_images_for_context(
        images,
        str(question.get("stemMarkdown") or question.get("manualMarkdown") or ""),
        question.get("options"),
        question_type=str(question.get("type") or ""),
        answer=str(question.get("answer") or ""),
        analysis=str(question.get("analysis") or ""),
    )
    if next_images != images:
        next_keys = {str(image.get("url") or image.get("path") or image.get("name") or "") for image in next_images}
        dropped_images = [
            image
            for image in images
            if str(image.get("url") or image.get("path") or image.get("name") or "") not in next_keys
        ]
        if dropped_images:
            for field in ("stemMarkdown", "manualMarkdown"):
                value = question.get(field)
                if isinstance(value, str):
                    next_value = remove_question_images_from_markdown(value, dropped_images)
                    if next_value != value:
                        question[field] = next_value
                        changed = True
        images = next_images
        question["images"] = images
        changed = True
        if question.get("options"):
            next_options = attach_choice_images_to_text_options(
                str(question.get("stemMarkdown") or question.get("manualMarkdown") or ""),
                question.get("options"),
                images,
                str(question.get("type") or ""),
            )
            if next_options != question.get("options"):
                question["options"] = next_options
                changed = True
    if images:
        sibling_texts = option_texts(question.get("options")) + [
            str(question.get("answer") or ""),
            str(question.get("analysis") or ""),
        ]
        stem_markdown = str(question.get("stemMarkdown") or "")
        had_positioned_ref = any(markdown_contains_question_image(stem_markdown, image) for image in images)
        next_stem_markdown = strip_question_images_from_markdown(stem_markdown, images, sibling_texts=sibling_texts)
        if next_stem_markdown != stem_markdown:
            question["stemMarkdown"] = next_stem_markdown
            changed = True
            if not had_positioned_ref:
                add_question_image_warning(question)

        if question.get("manualMarkdown"):
            manual_markdown = str(question.get("manualMarkdown") or "")
            next_manual_markdown = strip_question_images_from_markdown(manual_markdown, images, sibling_texts=sibling_texts)
            if next_manual_markdown != manual_markdown:
                question["manualMarkdown"] = next_manual_markdown
                changed = True

    children = question.get("subQuestions")
    if not isinstance(children, list):
        children = question.get("children") if isinstance(question.get("children"), list) else []
    for child in children:
        if isinstance(child, dict):
            changed = ensure_question_images_in_markdown(child) or changed
    return changed


def add_question_image_warning(question: dict[str, Any]) -> None:
    """记录题图无 OCR 位置时的追加提示。"""
    warning = "OCR 已识别题图但未提供可靠插入位置，已追加到题干末尾，请人工复核题图位置"
    warnings = question.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    if warning not in warnings:
        warnings.append(warning)
    question["warnings"] = warnings


def question_to_edit_markdown(question: dict[str, Any]) -> str:
    """将题目转换为人工编辑 Markdown。"""
    options = normalize_question_options_image_refs(question.get("options") or [], question.get("images"))
    siblings = option_texts(options)
    source_markdown = str(question.get("manualMarkdown") or question.get("stemMarkdown") or "")
    markdown = strip_question_images_from_markdown(source_markdown, question.get("images"), sibling_texts=siblings)
    if options and not split_tasks_options(markdown)[1]:
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


MATH_SPAN_RE = re.compile(
    r"(?<!\\)\$\$.*?(?<!\\)\$\$|"
    r"(?<![$\\])\$(?!\$).*?(?<![$\\])\$(?!\$)|"
    r"\\\(.*?\\\)|"
    r"\\\[.*?\\\]",
    flags=re.S,
)
UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def is_math_position(content: str, position: int) -> bool:
    """判断位置是否落在受保护的数学公式中。"""
    return any(match.start() <= position < match.end() for match in MATH_SPAN_RE.finditer(content))


def has_unclosed_math_delimiter(content: str) -> bool:
    """判断内容是否包含未被完整数学公式消耗的开始分隔符。"""
    remaining = MATH_SPAN_RE.sub("", content)
    return bool(UNESCAPED_DOLLAR_RE.search(remaining) or r"\(" in remaining or r"\[" in remaining)


def next_glued_tasks_label_marker(content: str, start: int) -> tuple[str, int, int] | None:
    """查找 tasks 尾部粘连选项的下一个强标签。"""
    label_pattern = r"[A-H]"
    patterns = (
        re.compile(rf"(?<!\S)(?P<label>{label_pattern})[.．、:：](?=\s*\S)"),
        re.compile(rf"(?<!\S)(?P<label>{label_pattern})(?=\s+\$(?=[^$\r\n]*\$))"),
    )
    matches = sorted(
        (match for pattern in patterns for match in pattern.finditer(content, start)),
        key=lambda match: match.start(),
    )
    for match in matches:
        marker_start = match.start()
        prefix = content[:marker_start].rstrip()
        if is_math_position(content, marker_start) or prefix.endswith("点"):
            continue
        return match.group("label"), marker_start, match.end()
    return None


def recover_glued_tasks_options(task_parts: list[str]) -> list[str]:
    """保守拆分 tasks 各选项中连续粘连的后续标签。"""
    if (
        len(task_parts) < 2
        or any(not part.strip() for part in task_parts)
        or any(has_unclosed_math_delimiter(part) for part in task_parts)
    ):
        return task_parts

    recovered: list[str] = []
    for content in task_parts:
        expected_label = chr(ord("A") + len(recovered) + 1)
        if not content.strip() or expected_label > "H":
            recovered.append(content)
            continue

        markers: list[tuple[int, int]] = []
        cursor = 0
        while expected_label <= "H":
            marker = next_glued_tasks_label_marker(content, cursor)
            if not marker or marker[0] != expected_label:
                break
            markers.append((marker[1], marker[2]))
            cursor = marker[2]
            expected_label = chr(ord(expected_label) + 1)

        if len(markers) < 2:
            recovered.append(content)
            continue

        split_parts = [content[: markers[0][0]]]
        split_parts.extend(content[markers[index][1] : markers[index + 1][0]] for index in range(len(markers) - 1))
        split_parts.append(content[markers[-1][1] :])
        if any(not part.strip() for part in split_parts):
            recovered.append(content)
            continue
        recovered.extend(split_parts)
    return recovered


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
    if match:
        task_parts = recover_glued_tasks_options(task_parts)
    options = [
        {"label": chr(65 + index), "content": content}
        for index, content in enumerate(content.strip() for content in task_parts if content.strip())
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
