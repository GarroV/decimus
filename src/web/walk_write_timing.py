"""Numeric-only, request-local HTTP write timing, including early/raised refusals."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from flask import current_app
from werkzeug.exceptions import HTTPException

from src.recognize.timing import collect

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")

# Stable numeric operation labels: no request body, identity or reference is logged.
FINDING = 1
INFO = 2
PHOTO = 3


def timed_write(operation: int) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(view: Callable[P, R]) -> Callable[P, R]:
        @wraps(view)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with collect() as timing:
                status = 500
                try:
                    result = view(*args, **kwargs)
                    status = current_app.make_response(result).status_code  # type: ignore[arg-type]
                    return result
                except HTTPException as exc:
                    status = exc.code or 500
                    raise
                finally:
                    logger.info(
                        "Обход: время записи operation=%s status=%s timing=%s",
                        operation,
                        status,
                        timing.report(),
                    )

        return wrapped

    return decorate
