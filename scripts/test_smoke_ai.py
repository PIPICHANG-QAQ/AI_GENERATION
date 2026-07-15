#!/usr/bin/env python3
"""Unit tests for the deployed AI smoke polling behavior."""

from __future__ import annotations

import unittest
from unittest.mock import call, patch

import smoke_ai


class WaitStandardizationJobTest(unittest.TestCase):
    def wait_function(self):
        function = getattr(smoke_ai, "wait_standardization_job", None)
        self.assertIsNotNone(function, "wait_standardization_job is missing")
        return function

    def test_completed_job_passes_only_with_all_items_successful(self) -> None:
        payloads = [
            {"status": "running", "completedItems": 1, "totalItems": 2, "failedItems": 0},
            {"status": "completed", "completedItems": 2, "totalItems": 2, "failedItems": 0},
        ]
        with patch.object(smoke_ai, "request", side_effect=payloads) as request, patch.object(
            smoke_ai.time, "monotonic", return_value=10.0
        ), patch.object(smoke_ai.time, "sleep") as sleep:
            result = self.wait_function()(
                "task-1",
                "job-1",
                expected_total_items=2,
                timeout_seconds=5,
                poll_interval_seconds=0.1,
            )

        self.assertEqual(payloads[-1], result)
        self.assertEqual(
            [
                call("GET", "/api/import-tasks/task-1/standardization-jobs/job-1", timeout=5.0),
                call("GET", "/api/import-tasks/task-1/standardization-jobs/job-1", timeout=5.0),
            ],
            request.call_args_list,
        )
        sleep.assert_called_once_with(0.1)

    def test_partial_failed_job_raises_with_last_payload(self) -> None:
        payload = {"status": "partial_failed", "completedItems": 1, "totalItems": 2, "failedItems": 1}
        with patch.object(smoke_ai, "request", return_value=payload), patch.object(
            smoke_ai.time, "monotonic", return_value=10.0
        ), patch.object(smoke_ai.time, "sleep"):
            with self.assertRaisesRegex(AssertionError, "partial_failed.*failedItems.*1"):
                self.wait_function()("task-1", "job-1", expected_total_items=2, timeout_seconds=5)

    def test_active_job_timeout_raises_with_last_payload(self) -> None:
        payload = {"status": "processing", "completedItems": 0, "totalItems": 2, "failedItems": 0}
        with patch.object(smoke_ai, "request", return_value=payload) as request, patch.object(
            smoke_ai.time, "monotonic", side_effect=[10.0, 10.0, 10.0, 12.0]
        ), patch.object(smoke_ai.time, "sleep") as sleep:
            with self.assertRaisesRegex(TimeoutError, "processing.*completedItems.*0"):
                self.wait_function()(
                    "task-1",
                    "job-1",
                    expected_total_items=2,
                    timeout_seconds=1,
                    poll_interval_seconds=0.1,
                )

        self.assertEqual(1, request.call_count)
        sleep.assert_called_once_with(0.1)

    def test_zero_count_completed_job_is_rejected(self) -> None:
        payload = {"status": "completed", "completedItems": 0, "totalItems": 0, "failedItems": 0}
        with patch.object(smoke_ai, "request", return_value=payload), patch.object(
            smoke_ai.time, "monotonic", return_value=10.0
        ):
            with self.assertRaisesRegex((AssertionError, ValueError), "total|expected"):
                self.wait_function()("task-1", "job-1", expected_total_items=0, timeout_seconds=5)

    def test_final_total_must_match_creation_response(self) -> None:
        payload = {"status": "completed", "completedItems": 1, "totalItems": 1, "failedItems": 0}
        with patch.object(smoke_ai, "request", return_value=payload), patch.object(
            smoke_ai.time, "monotonic", return_value=10.0
        ):
            with self.assertRaisesRegex(AssertionError, "totalItems.*1"):
                self.wait_function()("task-1", "job-1", expected_total_items=2, timeout_seconds=5)

    def test_late_terminal_response_is_rejected_and_request_uses_remaining_budget(self) -> None:
        payload = {"status": "completed", "completedItems": 2, "totalItems": 2, "failedItems": 0}
        with patch.object(smoke_ai, "request", return_value=payload) as request, patch.object(
            smoke_ai.time, "monotonic", side_effect=[10.0, 10.0, 12.1]
        ):
            with self.assertRaisesRegex(TimeoutError, "completedItems.*2"):
                self.wait_function()("task-1", "job-1", expected_total_items=2, timeout_seconds=2)

        self.assertEqual(2.0, request.call_args.kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
