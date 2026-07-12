import shutil
from pathlib import Path

import pytest

from app.export_service import answer_space_height, export_paper_markdown, export_paper_pdf, export_paper_pdf_xelatex, export_question_markdown, latex_markdown_text, pandoc_markdown_text, render_latex_inline, render_question_lines


def test_image_placement_keeps_stem_and_option_images_at_their_targets(monkeypatch):
    question = {
        "id": "q-images",
        "score": 4,
        "stemMarkdown": "选择正确图片",
        "images": [
            {"imageId": "stem.png", "path": "stem.png"},
            {"imageId": "a.png", "path": "a.png"},
            {"imageId": "b.png", "path": "b.png"},
            {"imageId": "orphan.png", "path": "orphan.png"},
        ],
        "imagePlacements": [
            {"imageId": "stem.png", "target": {"kind": "stem"}, "order": 0},
            {"imageId": "a.png", "target": {"kind": "option", "optionLabel": "A"}, "order": 1},
            {"imageId": "b.png", "target": {"kind": "option", "optionLabel": "B"}, "order": 2},
            {"imageId": "orphan.png", "target": {"kind": "unassigned"}, "order": 3},
        ],
        "options": [{"label": "A", "content": "甲"}, {"label": "B", "content": "乙"}],
    }
    monkeypatch.setattr("app.export_service.resolve_export_image_path", lambda image: Path("/tmp") / str(image["path"]))

    content = export_question_markdown(question, 1, include_answer=False)

    assert content.index("stem.png") < content.index("**A.**")
    assert content.index("**A.**") < content.index("a.png") < content.index("**B.**")
    assert content.index("**B.**") < content.index("b.png")
    assert "orphan.png" not in content


def compound_question() -> dict:
    return {
        "id": "q_compound",
        "score": 10,
        "manualMarkdown": "阅读下面材料，完成问题。",
        "subQuestions": [
            {
                "id": "sub_1",
                "label": "(1)",
                "stemMarkdown": "求 $f(0)$。",
                "answer": "1",
                "analysis": "代入计算。",
            },
            {
                "id": "sub_2",
                "label": "(2)",
                "stemMarkdown": "证明 $f(x)$ 单调递增。",
                "answer": "成立",
                "analysis": "按定义证明。",
            },
        ],
    }


def test_export_markdown_renders_selected_sub_questions_only():
    paper = {
        "id": "test_export_selected_subquestions",
        "title": "小问导出测试",
        "header": {},
        "subSelections": {"q_compound": ["sub_2"]},
    }

    path = export_paper_markdown(paper, [compound_question()], include_answer=True)
    try:
        content = Path(path).read_text(encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)

    assert "阅读下面材料" in content
    assert "**(2)** 证明 $f(x)$ 单调递增。" in content
    assert "成立" in content
    assert "求 $f(0)$" not in content
    assert "代入计算" not in content


def test_legacy_question_lines_render_sub_questions_and_answers():
    lines = render_question_lines(compound_question(), 1, include_answer=True)
    content = "\n".join(lines)

    assert "1. 阅读下面材料" in content
    assert "(1) 求 f(0)。" in content
    assert "(2) 证明 f(x) 单调递增。" in content
    assert "(1) 答案：1" in content
    assert "(2) 解析：按定义证明。" in content


def test_pandoc_markdown_text_keeps_display_math_as_single_block():
    markdown = r"""(1) 解不等式组。

$$


\left\{ \begin{array} { l l } { \displaystyle { \frac { 5 x - 1 } { 6 } } + 2 \geq \displaystyle { \frac { x + 5 } { 4 } } . } \\ { \displaystyle { 2 x + 5 \leq 3 ( 5 - x ) } } \end{array} \right.
$$"""

    normalized = pandoc_markdown_text(markdown)

    assert "$$\n\n" not in normalized
    assert "\n\n\\left" not in normalized
    assert r"\begin{array}{ll}" in normalized
    assert r"\displaystyle" not in normalized


def test_export_markdown_keeps_sub_question_label_separate_from_display_math():
    paper = {
        "id": "test_export_subquestion_display_math",
        "title": "小问公式导出测试",
        "header": {},
    }
    question = {
        "id": "q_math",
        "score": 5,
        "manualMarkdown": "解答下列问题。",
        "subQuestions": [
            {
                "id": "sub_math_1",
                "label": "(1)",
                "stemMarkdown": "$$\n\nx+1=2\n$$",
            }
        ],
    }

    path = export_paper_markdown(paper, [question], include_answer=False)
    try:
        content = Path(path).read_text(encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)

    assert "**(1)** $$" not in content
    assert "**(1)**\n\n$$\nx+1=2\n$$" in content


def test_pdf_export_uses_preview_style_renderer():
    paper = {
        "id": "test_pdf_preview_style",
        "title": "预览样式 PDF",
        "header": {},
    }

    path = export_paper_pdf(paper, [compound_question()], include_answer=False)
    try:
        assert Path(path).exists()
        assert Path(path).read_bytes().startswith(b"%PDF")
    finally:
        Path(path).unlink(missing_ok=True)


def test_answer_space_height_only_targets_solution_questions():
    choice = {"type": "choice", "score": 5}
    solution = {"type": "solution", "score": 8}
    unknown_sub = {"type": "unknown", "score": 0}

    assert answer_space_height(choice) == 0
    assert answer_space_height(solution) >= 118
    assert answer_space_height(unknown_sub, fallback_type="solution", is_sub_question=True) >= 72


def test_latex_markdown_text_preserves_math_commands():
    rendered = latex_markdown_text(r"化简： $\left( \frac{a^2}{a-2} - \frac{2a}{a+2} \right)$")

    assert r"\frac{a^2}{a-2}" in rendered
    assert r"\left(" in rendered
    assert r"\textbackslash" not in rendered


def test_latex_markdown_text_preserves_proof_line_breaks():
    markdown = """证明：∵ $\\angle BAE = \\angle E$

∴ ____ // ____ (____)

∴ $\\angle B = \\angle ____$ (____).

又： $\\angle B = \\angle D$

∴ $AD//BC$ (____)."""

    rendered = latex_markdown_text(markdown)

    assert rendered.count(r"\par") >= 4
    assert r"证明：∵ $\angle BAE = \angle E$" in rendered
    assert r"∴ \_\_\_\_ // \_\_\_\_ (\_\_\_\_)" in rendered
    assert r"\angle \underline{\hspace{1.2cm}}" in rendered
    assert r"∴ $AD//BC$ (\_\_\_\_)." in rendered


def test_xelatex_pdf_export_path_compiles_math_pdf():
    if not shutil.which("xelatex"):
        pytest.skip("XeLaTeX is not installed")
    paper = {
        "id": "test_xelatex_pdf_math",
        "title": "公式 PDF",
        "header": {},
    }

    path = export_paper_pdf_xelatex(paper, [compound_question()], include_answer=False)
    try:
        assert Path(path).exists()
        assert Path(path).read_bytes().startswith(b"%PDF")
    finally:
        Path(path).unlink(missing_ok=True)


def test_render_latex_inline_does_not_turn_left_into_leq_text():
    rendered = render_latex_inline(r"\left\{ \begin{array}{ll} \frac{5x-1}{6}+2 \geq \frac{x+5}{4} \\ 2x+5 \leq 3(5-x) \end{array} \right.")

    assert "≤ft" not in rendered
    assert "≥" in rendered
    assert "≤" in rendered
    assert "array" not in rendered
