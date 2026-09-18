"""Каталог текстов веб-админки: язык — параметр интерфейса, не константа.

Проверяется то же, что для бота (`tests/test_bot_texts.py`): текст берётся
по ключу, обе локали заполнены одновременно, набор подстановок в них
совпадает, а неизвестный ключ, язык или недостающий параметр — отказ, а не
подстановка по умолчанию. Отдельно — что у каждого раздела реестра
(`src.web.sections.SECTIONS`) есть заголовок в каталоге: разойдись они,
навигация показала бы пустой ярлык.
"""

from __future__ import annotations

from string import Formatter

import pytest

from src.web.errors import WebTextError
from src.web.sections import SECTIONS
from src.web.texts import TEXTS, UI_LANGS, default_ui_lang, lang_or_default, t


def _params(template: str) -> set[str]:
    """Имена параметров строки каталога: `{count}` и `{var}` из шаблона."""
    return {field for _, field, _, _ in Formatter().parse(template) if field}


@pytest.mark.parametrize("lang", UI_LANGS)
def test_every_key_is_filled_in_every_language(lang: str) -> None:
    missing = [key for key, langs in TEXTS.items() if not (langs.get(lang) or "").strip()]
    assert missing == [], f"нет перевода на «{lang}»: {missing}"


def test_every_language_of_a_key_takes_the_same_parameters() -> None:
    """Расхождение параметров между локалями — молча потерянная подстановка в переводе."""
    mismatched = {
        key: {lang: sorted(_params(text)) for lang, text in langs.items()}
        for key, langs in TEXTS.items()
        if len({frozenset(_params(text)) for text in langs.values()}) > 1
    }
    assert mismatched == {}, f"наборы параметров разошлись между языками: {mismatched}"


def test_every_section_has_a_title_key_in_the_catalogue() -> None:
    missing = [section.key for section in SECTIONS if f"section.{section.key}.title" not in TEXTS]
    assert missing == [], f"нет ключа заголовка у разделов: {missing}"


def test_unknown_key_is_refused_with_the_key_named() -> None:
    with pytest.raises(WebTextError, match="no-such-key"):
        t("no-such-key", "ru")


def test_unknown_language_is_refused() -> None:
    with pytest.raises(WebTextError, match="de"):
        t("app.name", "de")


def test_missing_parameter_is_refused_with_its_name() -> None:
    with pytest.raises(WebTextError, match="count"):
        t("registry.count", "ru")


def test_parameter_is_substituted() -> None:
    assert "3" in t("registry.count", "ru", count=3)


def test_default_ui_lang_is_russian_on_empty_environment() -> None:
    assert default_ui_lang({}) == "ru"


def test_default_ui_lang_reads_web_ui_lang() -> None:
    assert default_ui_lang({"WEB_UI_LANG": "en"}) == "en"


def test_default_ui_lang_refuses_unknown_language() -> None:
    with pytest.raises(WebTextError, match="de"):
        default_ui_lang({"WEB_UI_LANG": "de"})


def test_lang_or_default_keeps_a_known_language() -> None:
    assert lang_or_default("en", fallback="ru") == "en"


def test_lang_or_default_falls_back_when_language_is_none() -> None:
    assert lang_or_default(None, fallback="ru") == "ru"


def test_lang_or_default_falls_back_on_unknown_language() -> None:
    assert lang_or_default("de", fallback="ru") == "ru"
