"""OpenAI API 向けリトライのテスト。"""

import logging
import unittest
from unittest.mock import patch

import httpx
from openai import APIStatusError

from youtube_generator.services.retry import Retry, RetryPolicy


class RetryTests(unittest.TestCase):
    def test_retries_connection_errors_with_exponential_backoff(self) -> None:
        calls = 0

        @Retry(RetryPolicy(max_attempts=5), logging.getLogger(__name__))
        def request() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ConnectionError("temporary connection issue")
            return "completed"

        with patch("youtube_generator.services.retry.time.sleep") as sleep:
            result = request()

        self.assertEqual(result, "completed")
        self.assertEqual(calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    def test_does_not_retry_non_retryable_error(self) -> None:
        calls = 0

        @Retry(RetryPolicy(max_attempts=5), logging.getLogger(__name__))
        def request() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("invalid request")

        with self.assertRaisesRegex(ValueError, "invalid request"):
            request()
        self.assertEqual(calls, 1)

    def test_retries_only_configured_http_statuses(self) -> None:
        retryable = APIStatusError("temporary", response=self._response(503), body=None)
        not_retryable = APIStatusError("unsupported", response=self._response(501), body=None)

        self.assertTrue(Retry.is_retryable(retryable))
        self.assertFalse(Retry.is_retryable(not_retryable))

    @staticmethod
    def _response(status_code: int) -> httpx.Response:
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        return httpx.Response(status_code, request=request)


if __name__ == "__main__":
    unittest.main()
