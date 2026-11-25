import pytest

from shorts_engine.common.errors import EngineError
from shorts_engine.common.logging import redact_obj, redact_text
from shorts_engine.ingest.validate import sanitize_subtitle_lang, validate_source_url


def test_redaction_of_common_secret_shapes():
    assert "gsk_" not in redact_text("Authorization: Bearer gsk_abcdefghijklmnop")
    assert "sk-" not in redact_text("key sk-abcdefghijklmnop")
    assert "hunter2" not in redact_text("https://x.test/?api_key=hunter2&x=1")
    assert "supersecret" not in redact_text("plain", secrets=["supersecret"])
    assert redact_text("nothing here") == "nothing here"


def test_redaction_of_nested_objects():
    result = redact_obj({"headers": {"Authorization": "Bearer gsk_1234567890"}, "items": ["sk-1234567890"]})
    assert "gsk_" not in str(result)
    assert "sk-" not in str(result)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video",
        "http://localhost:8080/a",
        "https://youtu.be/abc123",
    ],
)
def test_valid_source_urls(url):
    assert validate_source_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["", "ftp://example.com/a", "not a url", "-oops", "https://", "https://example.com/" + "a" * 3000],
)
def test_invalid_source_urls_raise_engine_errors(url):
    with pytest.raises(EngineError) as info:
        validate_source_url(url)
    assert info.value.code == "URL_INVALID"


def test_subtitle_language_sanitizer():
    assert sanitize_subtitle_lang("en-US") == "en-US"
    assert sanitize_subtitle_lang("../etc/passwd") == "etcpasswd"
    assert sanitize_subtitle_lang("a" * 100) == "a" * 20
