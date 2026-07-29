from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from requests import Response


class OracleConfigurationError(ValueError):
    pass


@dataclass(slots=True)
class ResponseOracle:
    mode: str = "status"
    true_statuses: frozenset[int] = frozenset({200})
    marker: str | None = None
    pattern: Pattern[str] | None = None
    expected_length: int | None = None
    length_tolerance: int = 0

    @classmethod
    def from_options(
        cls,
        *,
        mode: str,
        true_statuses: set[int],
        marker: str | None = None,
        regex: str | None = None,
        expected_length: int | None = None,
        length_tolerance: int = 0,
    ) -> "ResponseOracle":
        if mode == "marker" and marker is None:
            raise OracleConfigurationError("--true-marker is required for marker mode")
        if mode == "regex" and regex is None:
            raise OracleConfigurationError("--true-regex is required for regex mode")
        if mode == "length" and expected_length is None:
            raise OracleConfigurationError("--true-length is required for length mode")
        compiled = re.compile(regex) if regex else None
        return cls(
            mode=mode,
            true_statuses=frozenset(true_statuses),
            marker=marker,
            pattern=compiled,
            expected_length=expected_length,
            length_tolerance=length_tolerance,
        )

    def evaluate(self, response: Response) -> bool:
        if self.mode == "status":
            return response.status_code in self.true_statuses
        if self.mode == "marker":
            return bool(self.marker and self.marker in response.text)
        if self.mode == "regex":
            return bool(self.pattern and self.pattern.search(response.text))
        if self.mode == "length":
            assert self.expected_length is not None
            return abs(len(response.content) - self.expected_length) <= self.length_tolerance
        raise OracleConfigurationError(f"Unsupported oracle mode: {self.mode}")

    def fingerprint(self, response: Response) -> str:
        return (
            f"status={response.status_code}, bytes={len(response.content)}, "
            f"url={response.url}"
        )
