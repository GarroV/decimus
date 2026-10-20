"""Реестр ключей сервисов (D576): имена совпадают с `check` миграции, нет повторов."""

from __future__ import annotations

import re
from pathlib import Path

from src.domain import service_keys as registry

МИГРАЦИЯ = (
    Path(__file__).resolve().parents[1] / "src" / "db" / "migrations" / "0084_service_keys.sql"
)


def test_имена_реестра_равны_check_миграции() -> None:
    sql = МИГРАЦИЯ.read_text(encoding="utf-8")
    check = sql[sql.index("add constraint") :]
    assert set(re.findall(r"'([^']+)'", check)) == set(registry.VAULT_NAMES)


def test_имена_и_коды_не_повторяются() -> None:
    имена = [f.vault_name for s in registry.SERVICES for f in s.fields]
    assert len(имена) == len(set(имена))
    assert len({s.code for s in registry.SERVICES}) == len(registry.SERVICES)
    окружение = [f.env_var for s in registry.SERVICES for f in s.fields]
    assert len(окружение) == len(set(окружение))


def test_ключ_модели_сохранил_прежнее_имя_записи() -> None:
    assert registry.field_of("openai", "api_key").vault_name == "model_key"  # type: ignore[union-attr]


def test_неизвестное_не_находится() -> None:
    assert registry.service("evil") is None
    assert registry.field_of("ispring", "nope") is None
    assert registry.field_of("evil", "api_key") is None


def test_форма_значения() -> None:
    assert registry.is_acceptable("abc-123")
    # не-ASCII роняет заголовок запроса в http.client (500 вместо отказа)
    for плохое in ("", "a b", "a\nb", "x" * (registry.MAX_LENGTH + 1), "ключ", "sk-é"):
        assert not registry.is_acceptable(плохое)


def test_имя_поля_формы_содержит_secret() -> None:
    from src.domain.journal import is_hidden_field

    for s in registry.SERVICES:
        for f in s.fields:
            assert is_hidden_field(registry.form_name(f.code))
