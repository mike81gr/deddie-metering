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


def test_translate_with_placeholders():
    """
    Test that translate correctly fills in placeholders.
    """
    key = "config.success_title"
    # English placeholder
    result_en = translate(key, "en", supply="123456789")
    assert "123456789" in result_en
    # Greek placeholder
    result_el = translate(key, "el", supply="987654321")
    assert "987654321" in result_el


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


def test_translate_unknown_language_defaults_to_en():
    key = "sensor.attr_info"
    # Η μετάφραση στα αγγλικά είναι "Info:"
    result = translate(key, "fr")
    assert result == TRANSLATIONS["en"][key]


@pytest.mark.parametrize("lang_code", ["EL", "El", "eL", "EN-us", "Es"])
def test_translate_language_codes_case_insensitive(lang_code):
    key = "config.success_notification"
    expected = TRANSLATIONS["el" if lang_code.lower().startswith("el") else "en"][key]
    assert translate(key, lang_code) == expected


@pytest.mark.parametrize(
    "key",
    [
        "options.token_updated_title",
        "api.token_expired_title",
    ],
)
def test_translate_other_placeholder_keys(key):
    supply = "ABC123"
    for lang in ("en", "el"):
        result = translate(key, lang, supply=supply)
        assert supply in result


def test_translate_no_placeholders_ignores_extra_kwargs():
    key = "sensor.attr_info"  # δεν έχει κανένα placeholder
    result = translate(key, "en", foo="bar", supply="123")
    assert result == TRANSLATIONS["en"][key]
