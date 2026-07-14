"""Parity contract for the staged AI runtime module split."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app import llm_splitter
from app.ai import runtime


class AiRuntimeParityTest(unittest.TestCase):
    def test_runtime_exports_the_legacy_functions_by_identity(self):
        for name in (
            "llm_runtime_options",
            "llm_status",
            "route_llm_endpoints",
            "llm_api_key",
            "infer_provider",
            "external_llm_status",
            "local_llm_status",
            "router_mode",
            "endpoint_timeout_seconds",
            "endpoint_semaphore",
            "task_semaphore",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(runtime, name), getattr(llm_splitter, name))

    def test_runtime_uses_the_single_legacy_state_objects(self):
        for name in (
            "LLM_ROUTER_CACHE",
            "LLM_ROUTER_CACHE_LOCK",
            "LLM_ENDPOINT_SEMAPHORES",
            "LLM_ENDPOINT_SEMAPHORES_LOCK",
            "LLM_TASK_SEMAPHORES",
            "LLM_TASK_SEMAPHORES_LOCK",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(runtime, name), getattr(llm_splitter, name))

    def test_runtime_options_and_status_match_for_same_environment(self):
        values = {
            "ENABLE_LLM_SPLIT": "true",
            "LLM_ROUTER_MODE": "hybrid",
            "LLM_MAX_CONCURRENCY": "3",
            "LLM_STANDARDIZE_MAX_CONCURRENCY": "5",
            "LLM_ANALYSIS_MAX_CONCURRENCY": "4",
            "LOCAL_LLM_ENABLED": "true",
            "LOCAL_LLM_BASE_URL": "http://local-llm/v1",
            "LOCAL_LLM_MODEL": "aux-qwen3-32b-fp8",
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(runtime.llm_runtime_options(), llm_splitter.llm_runtime_options())
            self.assertEqual(runtime.llm_status(), llm_splitter.llm_status())
            context = {"markdownChars": 1200, "questionCount": 2}
            self.assertEqual(
                runtime.route_llm_endpoints("boundary-refine", context),
                llm_splitter.route_llm_endpoints("boundary-refine", context),
            )


if __name__ == "__main__":
    unittest.main()
