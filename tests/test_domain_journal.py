"""Правила записи журналов (D462): что в сводку цели не попадает никогда и чей это адрес.

Чистый Python, без базы. Ядро: журнал действий лежит 365 дней и читается главным
админом, поэтому пароль, токен, ключ и свободный текст в него попасть не должны, как бы
ни назвали поле новой формы.
"""

from __future__ import annotations

import pytest

from src.domain.client_ip import forwarded_client, peer_trusted
from src.domain.journal import HIDDEN, MAX_TARGET, is_hidden_field, summarize_target

СЕКРЕТНЫЕ_ПОЛЯ = [
    "password",
    "new_password",
    "current_password",
    "passwd",
    "token",
    "access_token",
    "api_key",
    "secret",
    "csrf_token",
    "Authorization",
    "email",
    "comment",
    "note",
    "message",
    "description",
]


@pytest.mark.parametrize("имя", СЕКРЕТНЫЕ_ПОЛЯ)
def test_значение_секретного_поля_в_сводку_не_попадает(имя: str) -> None:
    сводка = summarize_target({имя: "ЗНАЧЕНИЕ-КОТОРОГО-НЕ-ДОЛЖНО-БЫТЬ"})

    assert "ЗНАЧЕНИЕ-КОТОРОГО-НЕ-ДОЛЖНО-БЫТЬ" not in сводка
    assert f"{имя}={HIDDEN}" in сводка, "имя поля должно остаться: видно, что оно было"


def test_идентификаторы_и_коды_попадают_как_есть() -> None:
    сводка = summarize_target({"country": "GE", "state": "archived"}, ids={"code": "kitchen"})

    assert сводка == "code=kitchen; country=GE; state=archived"


def test_часть_пути_показана_даже_если_имя_похоже_на_секрет() -> None:
    assert summarize_target(ids={"key_id": "17"}) == "key_id=17"


def test_длинное_и_многострочное_значение_это_текст_а_не_номер() -> None:
    сводка = summarize_target({"a": "x" * 500, "b": "первая\nвторая", "c": ["вложенное"]})

    assert "xxxx" not in сводка
    assert "первая" not in сводка
    assert "вложенное" not in сводка
    assert сводка == f"a={HIDDEN}; b={HIDDEN}; c={HIDDEN}"


def test_сводка_усечена() -> None:
    assert len(summarize_target({f"поле{n}": "1" for n in range(500)})) == MAX_TARGET


def test_имена_без_секретного_куска_не_скрываются() -> None:
    assert not is_hidden_field("country")
    assert is_hidden_field("OLD_PASSWORD")


# --- чей адрес ---------------------------------------------------------------


def test_заголовок_от_постороннего_не_принимается() -> None:
    адрес = forwarded_client(
        "203.0.113.9", "1.1.1.1", trusted_proxies=1, trusted_addrs=("172.19.0.0/16",)
    )

    assert адрес == "203.0.113.9", "адрес выбрал отправитель"


def test_заголовок_от_своего_звена_считается_с_конца_цепочки() -> None:
    адрес = forwarded_client(
        "172.19.0.4",
        "6.6.6.6, 198.51.100.7",
        trusted_proxies=1,
        trusted_addrs=("172.19.0.0/16",),
    )

    assert адрес == "198.51.100.7", "взят левый край цепочки, который пишет клиент"


def test_два_звена_берут_предпоследний_адрес() -> None:
    адрес = forwarded_client(
        "172.19.0.4",
        "6.6.6.6, 198.51.100.7, 172.19.0.2",
        trusted_proxies=2,
        trusted_addrs=("172.19.0.0/16",),
    )

    assert адрес == "198.51.100.7"


@pytest.mark.parametrize(
    ("звеньев", "цепочка"),
    [(0, "1.1.1.1"), (1, None), (1, ""), (2, "1.1.1.1")],
)
def test_без_обещанных_звеньев_берётся_адрес_соединения(звеньев: int, цепочка: str | None) -> None:
    адрес = forwarded_client(
        "172.19.0.4", цепочка, trusted_proxies=звеньев, trusted_addrs=("172.19.0.0/16",)
    )

    assert адрес == "172.19.0.4"


def test_звено_узнаётся_по_адресу_и_по_подсети() -> None:
    assert peer_trusted("172.19.0.4", ("172.19.0.0/16",))
    assert peer_trusted("10.0.0.1", ("10.0.0.1",))
    assert not peer_trusted("172.20.0.4", ("172.19.0.0/16",))
    assert not peer_trusted("не-адрес", ("172.19.0.0/16",))
