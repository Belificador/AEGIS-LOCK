"""Redact common credentials before untrusted text reaches logs."""

import re


_AUTH_PATTERN = re.compile(r"(?i)(\bauthorization\s*[:=]\s*(?:bearer\s+)?|\bbearer\s+)([A-Za-z0-9._~+/=-]+)")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)([\"']?\b(?:password|passwd|secret|token|api[_-]?key)\b[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'}]+)"
)


def redact_sensitive_text(value: str) -> str:
    redacted = _AUTH_PATTERN.sub(r"\1[REDACTED]", value)
    return _ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", redacted)
