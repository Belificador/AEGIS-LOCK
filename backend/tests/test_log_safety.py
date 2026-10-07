from backend.core.log_safety import redact_sensitive_text


def test_redacts_bearer_headers_and_secret_assignments() -> None:
    message = 'Authorization: Bearer abc.def.ghi password=hunter2 API_KEY=private-key payload={"token": "json-token"}'
    safe = redact_sensitive_text(message)
    assert "abc.def.ghi" not in safe
    assert "hunter2" not in safe
    assert "private-key" not in safe
    assert "json-token" not in safe
    assert safe.count("[REDACTED]") == 4
