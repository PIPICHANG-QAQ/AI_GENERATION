"""数学公式和 LaTeX 归一化工具。

该模块处理 OCR 常见的公式分隔符、括号、命令和语义风险提示。
函数保持无外部副作用，供 OCR 结构化、AI 标准化和导出 worker 复用。
"""

from __future__ import annotations

import re
from typing import Any


MAX_NORMALIZE_PASSES = 4
MATH_COMMAND_RE = re.compile(r"\\(?:frac|sqrt|pi|angle|circ|leq|geq|times|div|cdot|bullet|left|right|textcircled)\b")


def normalize_structured_math(structured: dict[str, Any]) -> dict[str, Any]:
    """规范化结构化题目中的数学公式并汇总校验信息。"""
    seen_question_ids: set[str] = set()
    aggregate = {
        "status": "ok",
        "changedCount": 0,
        "warningCount": 0,
        "fixedCount": 0,
        "questionsWithWarnings": [],
    }

    for section in structured.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []):
            if isinstance(question, dict):
                normalize_question_math(question, aggregate, seen_question_ids)

    if not seen_question_ids:
        for question in structured.get("questions", []):
            if isinstance(question, dict):
                normalize_question_math(question, aggregate, seen_question_ids)

    if aggregate["warningCount"] > 0:
        aggregate["status"] = "warning"
    elif aggregate["fixedCount"] > 0:
        aggregate["status"] = "fixed"
    return aggregate


def normalize_question_math(question: dict[str, Any], aggregate: dict[str, Any], seen_question_ids: set[str]) -> None:
    """规范化单道题及其子题中的数学公式字段。"""
    question_id = str(question.get("id") or id(question))
    if question_id in seen_question_ids:
        return
    seen_question_ids.add(question_id)

    field_results: list[dict[str, Any]] = []
    if question.get("manualMarkdown"):
        manual_result = normalize_math_markdown(str(question.get("manualMarkdown") or ""))
        question["manualMarkdown"] = manual_result["markdown"]
        field_results.append({"field": "manualMarkdown", **without_markdown(manual_result)})
    else:
        stem_result = normalize_math_markdown(str(question.get("stemMarkdown") or ""))
        question["stemMarkdown"] = stem_result["markdown"]
        field_results.append({"field": "stemMarkdown", **without_markdown(stem_result)})

        for option in question.get("options", []):
            if not isinstance(option, dict):
                continue
            option_result = normalize_math_markdown(str(option.get("content") or ""))
            option["content"] = option_result["markdown"]
            field_results.append({"field": f"options.{option.get('label', '')}", **without_markdown(option_result)})

    for child in question.get("children", []):
        if isinstance(child, dict):
            normalize_question_math(child, aggregate, seen_question_ids)

    issues = [issue for result in field_results for issue in result["issues"]]
    changed = any(result["changed"] for result in field_results)
    status = "warning" if issues else "ok"
    if status == "ok" and changed:
        status = "fixed"
    question["mathValidation"] = {
        "status": status,
        "changed": changed,
        "issues": issues,
        "fields": field_results,
    }

    if changed:
        aggregate["changedCount"] += 1
    if status == "fixed":
        aggregate["fixedCount"] += 1
    if issues:
        aggregate["warningCount"] += len(issues)
        aggregate["questionsWithWarnings"].append(question.get("id"))


def without_markdown(result: dict[str, Any]) -> dict[str, Any]:
    """返回去除 Markdown 文本后的校验摘要。"""
    return {
        "status": result["status"],
        "changed": result["changed"],
        "passCount": result["passCount"],
        "fixes": result["fixes"],
        "issues": result["issues"],
    }


def normalize_math_markdown(markdown: str) -> dict[str, Any]:
    """规范化一段 Markdown 中的数学公式。"""
    original = markdown
    current = markdown
    fixes: list[str] = []
    pass_count = 0

    for pass_index in range(1, MAX_NORMALIZE_PASSES + 1):
        next_text, pass_issues = normalize_once(current)
        pass_count = pass_index
        for issue in pass_issues:
            if issue not in fixes:
                fixes.append(issue)
        if next_text == current:
            break
        current = next_text

    validation_issues = validate_math_markdown(current)
    issues = list(dict.fromkeys(validation_issues))
    status = "warning" if issues else "ok"
    if status == "ok" and current != original:
        status = "fixed"

    return {
        "markdown": current,
        "status": status,
        "changed": current != original,
        "passCount": pass_count,
        "fixes": fixes,
        "issues": issues,
    }


def normalize_once(markdown: str) -> tuple[str, list[str]]:
    """执行一轮 Markdown 数学公式规范化。"""
    issues: list[str] = []
    text = markdown
    if "$$" in text:
        fixed = re.sub(r"(?<=[^\s$])\$\$(?=[^\s$])", r"$ $", text)
        fixed = re.sub(r"(?<!\$)\$\$(?=\\[A-Za-z])", r"$ $", fixed)
        fixed = re.sub(r"(?<=\})\$\$(?=\\[A-Za-z])", r"$ $", fixed)
        if fixed != text:
            issues.append("修复相邻公式之间的 $$ 分隔符")
        text = fixed

    text, wrapped_count = wrap_naked_math_commands(text)
    if wrapped_count:
        issues.append(f"为 {wrapped_count} 个裸露 LaTeX 片段补充公式分隔符")

    text, normalized_count = normalize_math_segments(text)
    if normalized_count:
        issues.append(f"标准化 {normalized_count} 个公式片段")

    single_dollar_count = count_single_dollars(text)
    if single_dollar_count % 2 == 1:
        text = f"{text}$"
        issues.append("补齐缺失的行内公式结束分隔符")

    return text, issues


def wrap_naked_math_commands(markdown: str) -> tuple[str, int]:
    """将裸露 LaTeX 命令包裹为数学片段。"""
    parts = split_math(markdown)
    wrapped = 0
    output: list[str] = []
    for is_math, content, delimiter in parts:
        if is_math:
            output.append(f"{delimiter}{content}{delimiter}")
            continue
        fixed = content
        fixed, count = re.subn(
            r"(?<!\$)(?P<expr>(?:[-+]\s*)?(?:\{?\s*)?\\(?:frac|sqrt|pi|angle|leq|geq|times|div|cdot|bullet|textcircled)\b(?:\s*(?:\[[^\]]+\]|\{[^{}]*\}|[A-Za-z0-9+\-^_]+))*)",
            lambda match: f"${match.group('expr').strip()}$",
            fixed,
        )
        wrapped += count
        output.append(fixed)
    return "".join(output), wrapped


def normalize_math_segments(markdown: str) -> tuple[str, int]:
    """规范化 Markdown 中已有数学片段。"""
    parts = split_math(markdown)
    changed = 0
    output: list[str] = []
    for is_math, content, delimiter in parts:
        if not is_math:
            output.append(content)
            continue
        normalized = normalize_latex_content(content)
        if normalized != content:
            changed += 1
        output.append(f"{delimiter}{normalized}{delimiter}")
    return "".join(output), changed


def normalize_latex_content(content: str) -> str:
    """规范化 LaTeX 片段内部内容。"""
    text = content.strip()
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    text = re.sub(r"\\([A-Za-z]+)\s+(?=[{\[])", r"\\\1", text)
    text = re.sub(r"\{\s+", "{", text)
    text = re.sub(r"\s+\}", "}", text)
    text = re.sub(r"\}\s+\{", "}{", text)
    text = re.sub(r"\[\s+", "[", text)
    text = re.sub(r"\s+\]", "]", text)
    text = re.sub(r"\]\s+\{", "]{", text)
    text = re.sub(r"\^\s*\{", "^{", text)
    text = re.sub(r"_\s*\{", "_{", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text


def validate_math_markdown(markdown: str) -> list[str]:
    """校验 Markdown 中数学公式的基本括号和分隔符风险。"""
    issues: list[str] = []
    if re.search(r"(?<=[^\s$])\$\$(?=[^\s$])", markdown):
        issues.append("仍存在连续 $$，需要人工检查公式边界")
    if re.search(r"\b[\dA-Za-z]\s*[\"“”]\s*(?:=|，|,|、|\)|$)", markdown):
        issues.append("存在疑似指数被识别为引号，建议使用 AI 语义标准化或人工复核")
    if count_single_dollars(markdown) % 2 == 1:
        issues.append("行内公式分隔符数量不匹配")

    for is_math, content, _delimiter in split_math(markdown):
        if is_math:
            if not is_balanced(content, "{", "}"):
                issues.append("公式花括号不匹配")
            if not is_balanced(content, "[", "]"):
                issues.append("公式方括号不匹配")
        elif MATH_COMMAND_RE.search(content):
            issues.append("仍存在未包裹的 LaTeX 命令")
    return issues


def split_math(markdown: str) -> list[tuple[bool, str, str]]:
    """把 Markdown 拆分为数学片段和普通文本片段。"""
    parts: list[tuple[bool, str, str]] = []
    index = 0
    while index < len(markdown):
        start = markdown.find("$", index)
        if start == -1:
            parts.append((False, markdown[index:], ""))
            break
        if start > index:
            parts.append((False, markdown[index:start], ""))
        delimiter = "$$" if markdown.startswith("$$", start) else "$"
        content_start = start + len(delimiter)
        end = markdown.find(delimiter, content_start)
        if end == -1:
            parts.append((False, markdown[start:], ""))
            break
        parts.append((True, markdown[content_start:end], delimiter))
        index = end + len(delimiter)
    return parts


def count_single_dollars(markdown: str) -> int:
    """统计未转义的单美元符数量。"""
    return len(re.findall(r"(?<!\$)\$(?!\$)", markdown))


def is_balanced(content: str, left: str, right: str) -> bool:
    """判断文本中指定左右符号是否平衡。"""
    depth = 0
    for char in content:
        if char == left:
            depth += 1
        elif char == right:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
