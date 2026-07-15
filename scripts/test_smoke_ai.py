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
            smoke_ai.time, "monotonic", side_effect=[10.0, 10.0]
        ), patch.object(smoke_ai.time, "sleep") as sleep:
            result = self.wait_function()("task-1", "job-1", timeout_seconds=5, poll_interval_seconds=0.1)

        self.assertEqual(payloads[-1], result)
        self.assertEqual(
            [
                call("GET", "/api/import-tasks/task-1/standardization-jobs/job-1", timeout=30),
                call("GET", "/api/import-tasks/task-1/standardization-jobs/job-1", timeout=30),
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
                self.wait_function()("task-1", "job-1", timeout_seconds=5)

    def test_active_job_timeout_raises_with_last_payload(self) -> None:
        payload = {"status": "processing", "completedItems": 0, "totalItems": 2, "failedItems": 0}
        with patch.object(smoke_ai, "request", return_value=payload) as request, patch.object(
            smoke_ai.time, "monotonic", side_effect=[10.0, 10.0, 12.0]
        ), patch.object(smoke_ai.time, "sleep") as sleep:
            with self.assertRaisesRegex(TimeoutError, "processing.*completedItems.*0"):
                self.wait_function()("task-1", "job-1", timeout_seconds=1, poll_interval_seconds=0.1)

        self.assertEqual(2, request.call_count)
        sleep.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
