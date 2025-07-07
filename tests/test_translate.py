import pytest
import logging
from deddie_metering.helpers.translate import translate, TRANSLATIONS


@pytest.mark.parametrize(
    "key,language,expected",
    [
        (
            "config.success_notification",
            "en",
            TRANSLATIONS["en"]["config.success_notification"],
        ),
        (
            "config.success_notification",
            "el",
            TRANSLATIONS["el"]["config.success_notification"],
        ),
        ("sensor.attr_info", "en", TRANSLATIONS["en"]["sensor.attr_info"]),
        ("sensor.attr_info", "el", TRANSLATIONS["el"]["sensor.attr_info"]),
    ],
)
def test_translate_existing_keys(key, language, expected):
    """
    Test that existing translation keys return the correct string.
    """
    result = translate(key, language)
    assert result == expected


def test_translate_missing_key_logs_warning(monkeypatch, caplog):
    """
    Missing keys should log a warning and return the key itself.
    """
    caplog.set_level(logging.WARNING)
    missing_key = "nonexistent.key"
    result = translate(missing_key, "en")
    assert result == missing_key
    # Check that a warning was logged about missing translation key
    assert any(missing_key in rec.getMessage() for rec in caplog.records)


def test_translate_format_error(monkeypatch, caplog):
    """
    If placeholder formatting fails, translate returns unformatted value and logs error.
    """
    # Introduce a bad translation entry
    TRANSLATIONS.setdefault("en", {})["bad.format"] = "Value: {unknown}"
    caplog.set_level(logging.ERROR)
    result = translate("bad.format", "en", nothing=123)
    # Should return the unformatted template string
    assert result == "Value: {unknown}"
    assert any("Translation format error" in rec.getMessage() for rec in caplog.records)
