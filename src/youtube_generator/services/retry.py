"""OpenAI API 呼び出し用の限定的な指数バックオフ・リトライ。"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import ParamSpec, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError

from youtube_generator.logger import get_active_logger


P = ParamSpec("P")
T = TypeVar("T")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """リトライの回数と待機時間を表す設定値。"""

    max_attempts: int = 5
    initial_wait_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    timeout_seconds: float = 60.0

    @classmethod
    def from_settings(cls, settings: dict[str, object]) -> "RetryPolicy":
        return cls(
            max_attempts=int(settings["max_attempts"]),
            initial_wait_seconds=float(settings["initial_wait_seconds"]),
            backoff_multiplier=float(settings["backoff_multiplier"]),
            timeout_seconds=float(settings["timeout_seconds"]),
        )


class Retry:
    """指定された一時的な失敗だけを再試行するデコレータ。"""

    def __init__(self, policy: RetryPolicy, logger: logging.Logger) -> None:
        if policy.max_attempts < 1:
            raise ValueError("max_attempts は1以上にしてください。")
        self._policy = policy
        self._logger = logger

    def __call__(self, function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            wait_seconds = self._policy.initial_wait_seconds
            for attempt in range(1, self._policy.max_attempts + 1):
                try:
                    active_logger = get_active_logger()
                    if active_logger is not None:
                        active_logger.increment_api_calls()
                    return function(*args, **kwargs)
                except Exception as error:
                    if not self.is_retryable(error):
                        raise
                    if attempt == self._policy.max_attempts:
                        self._logger.exception("リトライ上限に達しました: %s", function.__name__)
                        raise

                    if active_logger is not None:
                        active_logger.increment_retries()
                    self._logger.warning(
                        "%s が一時的なエラーで失敗しました（%s/%s回目）。%.1f秒後に再試行します。",
                        function.__name__,
                        attempt,
                        self._policy.max_attempts,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    wait_seconds *= self._policy.backoff_multiplier
            raise RuntimeError("到達しないはずのリトライ状態です。")

        return wrapped

    @staticmethod
    def is_retryable(error: Exception) -> bool:
        """仕様で許可されたネットワーク・HTTP エラーだけを判定する。"""
        if isinstance(error, (APITimeoutError, APIConnectionError, TimeoutError, ConnectionError)):
            return True
        if getattr(error, "status_code", None) in {500, 502, 503, 504}:
            return True
        return isinstance(error, APIStatusError) and error.status_code in RETRYABLE_STATUS_CODES


def retry_on_failure(
    policy: RetryPolicy,
    retryable_exceptions: tuple[type[Exception], ...],
    logger: logging.Logger,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """既存の利用箇所を保つための ``Retry`` デコレータ用ファクトリ。"""
    del retryable_exceptions
    return Retry(policy, logger)
