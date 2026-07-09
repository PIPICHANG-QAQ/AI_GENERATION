#!/usr/bin/env python3
"""Offline regression checks for OCR-flow hybrid LLM routing.

The script intentionally avoids network/model calls. It checks that risk
scoring and local evidence detection still classify the known hard cases that
drive local-vs-external routing decisions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "python-worker"))

from app.llm_splitter import llm_risk_score, route_llm_endpoints  # noqa: E402
from app.question_boundary import detect_local_boundaries, evaluate_boundary_confidence  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def configure_router() -> None:
    os.environ["ENABLE_LLM_SPLIT"] = "true"
    os.environ["LLM_ROUTER_MODE"] = "hybrid"
    os.environ["LOCAL_LLM_ENABLED"] = "true"
    os.environ["LOCAL_LLM_BASE_URL"] = "http://127.0.0.1:8001/v1"
    os.environ["LOCAL_LLM_MODEL"] = "aux-qwen3-32b-fp8"
    os.environ["DASHSCOPE_API_KEY"] = "test-key"
    os.environ["DASHSCOPE_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    os.environ["DASHSCOPE_MODEL"] = "deepseek-v4-pro"


def check_choice_option_misread() -> None:
    markdown = "## 一、选择题\n1. 若 $5^m=3$，$5^n=4$，则 $5^{3m-2n}$ 的值是() A. 27/16 B. 9/8 C. 3/2"
    boundaries = detect_local_boundaries(markdown, [])
    confidence = evaluate_boundary_confidence(markdown, boundaries, [])
    score = llm_risk_score("boundary-refine", confidence)
    assert_true("unstable-choice-options" in confidence["reasons"], "choice option conflict must be detected")
    assert_true(score >= 0.7, "unstable choices must be high enough for guarded routing")


def check_sub_question_missing() -> None:
    markdown = "2. 如图，已知三角形 ABC。\n(1) 求角 A。\n(2) 证明 AB=AC。"
    boundaries = detect_local_boundaries(markdown, [])
    questions = boundaries.get("questions") or []
    assert_true(bool(questions), "parent question must be detected")
    assert_true(len(questions[0].get("subQuestions") or []) == 2, "sub-question labels must be detected")


def check_fill_blank_missing() -> None:
    score = llm_risk_score(
        "standardize",
        {
            "markdown": "3. 若函数 $f(x)$ 的最小值为 ，则实数 a 的取值范围为 。",
            "structuredHints": {"type": "fill_blank"},
        },
    )
    assert_true(score >= 0.68, "fill-blank OCR missing slots must escalate beyond trivial risk")


def check_answer_analysis_leak() -> None:
    score = llm_risk_score(
        "standardize",
        {
            "markdown": "4. 解方程 $x^2=4$。【答案】$x=\\pm2$【解析】移项开方即可。",
            "structuredHints": {"type": "solution"},
        },
    )
    assert_true(score >= 0.64, "answer/analysis leakage must be routed as risky standardization")


def check_image_path_conflict() -> None:
    confidence = evaluate_boundary_confidence(
        "5. 如图求阴影面积。\n![](images/missing.png)",
        {
            "questions": [{"id": "q_5", "number": 5, "type": "solution", "start": 0, "end": 27}],
            "images": [{"path": "images/missing.png", "start": 11, "end": 33}],
        },
        [],
    )
    assert_true("unknown-image-path" in confidence["reasons"], "unknown image paths must be caught")


def check_router_order() -> None:
    configure_router()
    endpoints = route_llm_endpoints("boundary-refine", {"reasons": ["unstable-choice-options"], "questionCount": 1})
    roles = [endpoint.get("role") for endpoint in endpoints]
    assert_true(roles[:2] == ["local", "external"], f"expected local-first external-fallback routing, got {roles}")
    high_risk = route_llm_endpoints("boundary-refine", {"reasons": ["no-question-boundaries"], "questionCount": 0})
    assert_true(high_risk and high_risk[0].get("role") == "external", "high-risk boundary work should start with external model")


def main() -> None:
    check_choice_option_misread()
    check_sub_question_missing()
    check_fill_blank_missing()
    check_answer_analysis_leak()
    check_image_path_conflict()
    check_router_order()
    print("ocr-flow-router regression passed")


if __name__ == "__main__":
    main()
