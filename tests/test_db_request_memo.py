"""Память одного запроса (`src/db/request_memo.py`): прочитанное живёт ровно один запрос.

Главное, что здесь сторожится, — граница: память не должна пережить запрос и не
должна склеить читающих с разным охватом. Базы тесту не нужно.
"""

from __future__ import annotations

import pytest
from flask import Flask

from src.db import queries, request_memo
from src.db.reach import Reach
from src.web.app import _install_request_memo


class _Счёт:
    def __init__(self) -> None:
        self.вызовов = 0

    def __call__(self) -> int:
        self.вызовов += 1
        return self.вызовов


def test_вне_запроса_каждое_чтение_идёт_в_базу() -> None:
    счёт = _Счёт()

    первое = request_memo.memoized("k", счёт)
    второе = request_memo.memoized("k", счёт)

    assert (первое, второе) == (1, 2)


def test_внутри_запроса_одно_чтение_на_ключ() -> None:
    счёт = _Счёт()

    with request_memo.scope():
        первое = request_memo.memoized("k", счёт)
        второе = request_memo.memoized("k", счёт)
        другое = request_memo.memoized("other", счёт)

    assert (первое, второе, другое) == (1, 1, 2)


def test_после_запроса_память_забыта() -> None:
    счёт = _Счёт()

    with request_memo.scope():
        request_memo.memoized("k", счёт)
    with request_memo.scope():
        снова = request_memo.memoized("k", счёт)

    assert снова == 2


def test_отказ_чтения_не_запоминается() -> None:
    вызовов = []

    def падает() -> int:
        вызовов.append(1)
        raise RuntimeError("база не ответила")

    with request_memo.scope():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                request_memo.memoized("k", падает)

    assert len(вызовов) == 2


def test_география_разных_охватов_не_склеивается(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключ — весь охват: читающий другого пространства или страны своё и получит."""
    прочитано: list[Reach] = []

    def читать(охват: Reach) -> dict[str, tuple[str, str]]:
        прочитано.append(охват)
        return {f"точка {охват.tenant}": ("RS", "Белград")}

    monkeypatch.setattr(queries, "_read_unit_geography", читать)
    хк = Reach("HQ", None, None)
    партнёр = Reach("partner-a", ("partner-a",), ("RS",))
    другой_партнёр = Reach("partner-b", ("partner-b",), ("PL",))

    with request_memo.scope():
        a1 = queries.unit_geography(reach=хк)
        a2 = queries.unit_geography(reach=хк)
        b = queries.unit_geography(reach=партнёр)
        c = queries.unit_geography(reach=другой_партнёр)

    assert прочитано == [хк, партнёр, другой_партнёр]
    assert a1 == a2 == {"точка HQ": ("RS", "Белград")}
    assert b == {"точка partner-a": ("RS", "Белград")}
    assert c == {"точка partner-b": ("RS", "Белград")}


def test_география_отдаётся_копией(monkeypatch: pytest.MonkeyPatch) -> None:
    """Блок, который правит свой словарь, не портит его соседу по странице."""
    monkeypatch.setattr(queries, "_read_unit_geography", lambda охват: {"т": ("RS", "Белград")})
    охват = Reach("HQ", None, None)

    with request_memo.scope():
        первый = queries.unit_geography(reach=охват)
        первый["чужая"] = ("XX", "")
        второй = queries.unit_geography(reach=охват)

    assert "чужая" not in второй


def _приложение() -> tuple[Flask, _Счёт]:
    app = Flask(__name__)
    _install_request_memo(app)
    счёт = _Счёт()

    @app.route("/read", methods=["GET", "POST"])
    def read() -> str:
        # Два блока страницы читают одно и то же.
        a = request_memo.memoized("k", счёт)
        b = request_memo.memoized("k", счёт)
        return f"{a},{b}"

    return app, счёт


def test_get_читает_один_раз_и_забывает_к_следующему_запросу() -> None:
    app, счёт = _приложение()
    client = app.test_client()

    первый = client.get("/read").get_data(as_text=True)
    второй = client.get("/read").get_data(as_text=True)

    assert (первый, второй) == ("1,1", "2,2")
    assert счёт.вызовов == 2


def test_post_память_не_открывает() -> None:
    """Запрос, который пишет, читает как раньше: после записи устаревшему взяться неоткуда."""
    app, счёт = _приложение()

    ответ = app.test_client().post("/read").get_data(as_text=True)

    assert ответ == "1,2"
    assert счёт.вызовов == 2
