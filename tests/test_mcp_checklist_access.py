"""T098: кому открыта методика — настройка, вход и заслон на границе арендаторов.

До этой задачи MCP умел только читать проверки, и это было его гарантией.
Здесь появляется запись в методику управляющей компании — одну на всю сеть, —
поэтому проверяется не «работает ли инструмент», а **кого до него пускают**:

* методика выключена, пока её не открыли явно двумя переменными;
* половина настройки — отказ на старте, а не молчаливо выключенный доступ;
* токен партнёра, которому методику не открывали, получает отказ по-прежнему
  читая свои проверки;
* арендатор по-прежнему приходит только из токена: ни `tenant`, ни `store`
  аргументом вызова назвать нельзя.

Запросы в разделе про сервер идут по настоящему HTTP через настоящий сокет:
заслон живёт на входе, и вызов функции напрямую его бы не задел.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.catalogue import KIND_CHECKLIST, TOOLS
from src.mcp.checklist import Store
from src.mcp.config import (
    DATA_DIR_VAR,
    MCP_CHECKLIST_STORE_VAR,
    MCP_CHECKLIST_TENANTS_VAR,
    MCP_TOKENS_VAR,
    MIN_TOKEN_LENGTH,
    Settings,
    load_settings,
)
from src.mcp.errors import McpConfigError
from src.mcp.rpc import CHECKLIST_CLOSED, CODE_INVALID_PARAMS, handle
from src.mcp.server import _checklist_for, build_server

ТОКЕН_УК = "u" * MIN_TOKEN_LENGTH
ТОКЕН_ПАРТНЁРА = "p" * MIN_TOKEN_LENGTH
УК = "укашка"
ПАРТНЁР = "партнёр-б"


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    return build_methodology(tmp_path / "живая-методика")


@pytest.fixture
def store(tmp_path: Path, методика: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=методика)


@pytest.fixture
def настройки(tmp_path: Path, методика: Path) -> Settings:
    """Сервер, на котором методика открыта управляющей компании и только ей."""
    return Settings(
        tokens={ТОКЕН_УК: УК, ТОКЕН_ПАРТНЁРА: ПАРТНЁР},
        tenants=(ПАРТНЁР, УК),
        host="127.0.0.1",
        port=0,
        checklist_store=tmp_path / "хранилище",
        checklist_tenants=(УК,),
        data_dir=методика,
    )


# --- настройка ----------------------------------------------------------------


def _окружение(**прочее: str) -> dict[str, str]:
    return {MCP_TOKENS_VAR: f"{УК}={ТОКЕН_УК},{ПАРТНЁР}={ТОКЕН_ПАРТНЁРА}", **прочее}


def test_без_настройки_методика_выключена_целиком() -> None:
    """Запись в методику включается явно. Оказаться включённой по умолчанию
    она не может: сервер, отвечавший только на вопросы, таким и остаётся."""
    настройки = load_settings(_окружение())

    assert настройки.checklist_store is None
    assert настройки.checklist_tenants == ()
    assert not настройки.may_manage_checklist(УК)


def test_сказано_кому_но_не_сказано_куда_это_отказ_на_старте(tmp_path: Path) -> None:
    """Названная наполовину настройка — худший исход: человек считает правку
    включённой, а инструменты молча отказывают всем."""
    with pytest.raises(McpConfigError) as отказ:
        load_settings(_окружение(**{MCP_CHECKLIST_TENANTS_VAR: УК, DATA_DIR_VAR: str(tmp_path)}))

    assert MCP_CHECKLIST_STORE_VAR in str(отказ.value)


def test_сказано_куда_но_не_сказано_кому_это_отказ_на_старте(tmp_path: Path) -> None:
    with pytest.raises(McpConfigError) as отказ:
        load_settings(_окружение(**{MCP_CHECKLIST_STORE_VAR: str(tmp_path / "s")}))

    assert MCP_CHECKLIST_TENANTS_VAR in str(отказ.value)


def test_неизвестный_арендатор_в_списке_это_отказ_на_старте(tmp_path: Path) -> None:
    """Опечатка в коде арендатора означала бы доступ, выданный никому, — и
    выглядела бы ровно как работающая настройка."""
    with pytest.raises(McpConfigError) as отказ:
        load_settings(
            _окружение(
                **{
                    MCP_CHECKLIST_STORE_VAR: str(tmp_path / "s"),
                    MCP_CHECKLIST_TENANTS_VAR: "укашкa",
                    DATA_DIR_VAR: str(tmp_path),
                }
            )
        )

    assert "нет среди токенов" in str(отказ.value)


def test_методика_без_каталога_боевого_набора_это_отказ_на_старте(tmp_path: Path) -> None:
    """С боевого набора начинается хранилище версий, и по нему же проверяется,
    увидит ли движок публикацию."""
    with pytest.raises(McpConfigError) as отказ:
        load_settings(
            _окружение(
                **{
                    MCP_CHECKLIST_STORE_VAR: str(tmp_path / "s"),
                    MCP_CHECKLIST_TENANTS_VAR: УК,
                }
            )
        )

    assert DATA_DIR_VAR in str(отказ.value)


def test_настроенная_методика_открыта_только_названным(tmp_path: Path) -> None:
    настройки = load_settings(
        _окружение(
            **{
                MCP_CHECKLIST_STORE_VAR: str(tmp_path / "s"),
                MCP_CHECKLIST_TENANTS_VAR: УК,
                DATA_DIR_VAR: str(tmp_path),
            }
        )
    )

    assert настройки.may_manage_checklist(УК)
    assert not настройки.may_manage_checklist(ПАРТНЁР)


def test_нескольким_арендаторам_методику_открыть_можно(tmp_path: Path) -> None:
    настройки = load_settings(
        _окружение(
            **{
                MCP_CHECKLIST_STORE_VAR: str(tmp_path / "s"),
                MCP_CHECKLIST_TENANTS_VAR: f"{УК}\n{ПАРТНЁР}",
                DATA_DIR_VAR: str(tmp_path),
            }
        )
    )

    assert настройки.may_manage_checklist(УК)
    assert настройки.may_manage_checklist(ПАРТНЁР)


def test_токены_в_repr_настроек_не_печатаются_и_с_методикой(настройки: Settings) -> None:
    """`repr` настроек уезжает в трейсбек, а трейсбек — в лог."""
    assert ТОКЕН_УК not in repr(настройки)
    assert ТОКЕН_ПАРТНЁРА not in repr(настройки)


# --- вход ---------------------------------------------------------------------


def test_хранилище_подставляется_только_тому_кому_открыто(настройки: Settings) -> None:
    assert _checklist_for(настройки, УК) is not None
    assert _checklist_for(настройки, ПАРТНЁР) is None


def test_без_каталога_методики_хранилище_не_подставляется(настройки: Settings) -> None:
    """Настройки, собранные мимо `load_settings` (а это ровно тесты и будущий
    вызывающий), могут оказаться неполными: половина настройки означает
    выключенную методику, а не наполовину работающую."""
    from dataclasses import replace

    assert _checklist_for(replace(настройки, data_dir=None), УК) is None
    assert _checklist_for(replace(настройки, checklist_store=None), УК) is None


def _вызов(имя: str, аргументы: dict[str, Any], *, checklist: Store | None) -> Any:
    return handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=УК,
        checklist=checklist,
    )


def test_инструмент_методики_без_доступа_это_помеченный_отказ() -> None:
    """Отказ приходит помеченным (`isError`), а не пустой выдачей: пустую
    агент перескажет как «в методике ничего нет»."""
    ответ = _вызов("checklist_versions", {}, checklist=None)

    assert ответ["result"]["isError"] is True
    assert ответ["result"]["content"][0]["text"] == CHECKLIST_CLOSED


def test_отказ_не_называет_ни_арендаторов_ни_путей() -> None:
    """По отказу нельзя перечислить, кому методика открыта и где она лежит."""
    ответ = _вызов("checklist_versions", {}, checklist=None)
    текст = ответ["result"]["content"][0]["text"]

    assert УК not in текст
    assert ПАРТНЁР not in текст


def test_чтение_проверок_без_доступа_к_методике_работает_по_прежнему() -> None:
    """Закрытая методика не закрывает вопросы о проверках: инструмент чтения
    доходит до слоя чтения и падает уже на отсутствии базы, а не на заслоне."""
    ответ = _вызов("network_summary", {}, checklist=None)

    assert ответ["result"]["content"][0]["text"] != CHECKLIST_CLOSED


def test_с_доступом_инструмент_методики_отвечает(store: Store) -> None:
    ответ = _вызов("checklist_versions", {}, checklist=store)

    выдача = json.loads(ответ["result"]["content"][0]["text"])
    assert выдача["tenant"] == УК
    assert выдача["current"].startswith("local-")


def test_tenant_аргументом_у_инструмента_методики_это_отказ(store: Store) -> None:
    """Тот же запрет, что у инструментов чтения: арендатора называет токен, а
    не собеседник. Тихо отброшенный, аргумент выглядел бы работающей защитой
    ровно до того дня, когда его добавят в разбор «для гибкости»."""
    ответ = _вызов("checklist_versions", {"tenant": ПАРТНЁР}, checklist=store)

    assert ответ["error"]["code"] == CODE_INVALID_PARAMS


def test_store_аргументом_это_отказ(store: Store) -> None:
    """Хранилище подставляет вход. Названное аргументом, оно увело бы правку
    методики в любой каталог на машине."""
    ответ = _вызов("checklist_versions", {"store": "/чужой/каталог"}, checklist=store)

    assert ответ["error"]["code"] == CODE_INVALID_PARAMS


def test_отказ_методики_доходит_помеченным_а_не_кодом_протокола(store: Store) -> None:
    """Отказ правки — это результат вызова с пометкой, а не ошибка протокола.
    Ошибку протокола агент читает как «сервер сломался» и пересказывает
    человеку именно так, вместо «методику с такой правкой движок не принял»."""
    ответ = _вызов(
        "add_checklist_item",
        {
            "process": "Проба",
            "question_ru": "Проба пера",
            "levels": "D1",
            "kind": "off",
            "version_name": "imf",
        },
        checklist=store,
    )

    assert "error" not in ответ
    assert ответ["result"]["isError"] is True
    assert "Вид пункта" in ответ["result"]["content"][0]["text"]


def test_каждый_инструмент_методики_закрыт_одним_и_тем_же_заслоном(store: Store) -> None:
    """Заслон стоит по виду инструмента, а не по списку имён: инструмент,
    забытый в списке, был бы дырой, которую видно только чтением списка."""
    for spec in TOOLS:
        if spec.kind != KIND_CHECKLIST:
            continue
        ответ = _вызов(spec.name, {}, checklist=None)
        assert ответ["result"]["content"][0]["text"] == CHECKLIST_CLOSED, spec.name


# --- сервер -------------------------------------------------------------------


@pytest.fixture
def сервер(настройки: Settings) -> Iterator[str]:
    httpd: ThreadingHTTPServer = build_server(настройки)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


def _спросить(адрес: str, токен: str, имя: str, аргументы: dict[str, Any]) -> Any:
    тело = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        }
    ).encode("utf-8")
    запрос = urllib.request.Request(  # noqa: S310 — адрес свой, петля
        адрес,
        data=тело,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {токен}"},
    )
    with urllib.request.urlopen(запрос, timeout=10) as ответ:  # noqa: S310
        return json.loads(ответ.read().decode("utf-8"))


def test_через_сервер_методика_открыта_только_своему_токену(сервер: str) -> None:
    """Главная проверка файла и настоящая дверь: один и тот же вызов двумя
    токенами даёт две разные судьбы, и решает это токен, а не аргумент."""
    свой = _спросить(сервер, ТОКЕН_УК, "checklist_versions", {})
    чужой = _спросить(сервер, ТОКЕН_ПАРТНЁРА, "checklist_versions", {})

    assert "isError" not in свой["result"]
    assert чужой["result"]["isError"] is True
    assert чужой["result"]["content"][0]["text"] == CHECKLIST_CLOSED


def test_через_сервер_правка_доходит_до_новой_версии(сервер: str) -> None:
    ответ = _спросить(
        сервер,
        ТОКЕН_УК,
        "add_checklist_item",
        {
            "process": "Проба",
            "question_ru": "Проба пера",
            "levels": "D1",
            "zones": "fridge",
            "days": 5,
            "criteria": "D1: проба",
            "version_name": "imf",
        },
    )

    выдача = json.loads(ответ["result"]["content"][0]["text"])
    assert выдача["version"].startswith("imf-")
    assert выдача["published"] is False


def test_через_сервер_чужой_токен_методику_не_меняет(сервер: str, настройки: Settings) -> None:
    """Проверяется не только текст отказа, но и то, что после него в
    хранилище ничего не появилось."""
    _спросить(
        сервер,
        ТОКЕН_ПАРТНЁРА,
        "add_checklist_item",
        {
            "process": "Проба",
            "question_ru": "Чужая правка",
            "levels": "D1",
            "criteria": "D1: проба",
            "version_name": "imf",
        },
    )

    assert настройки.checklist_store is not None
    assert not настройки.checklist_store.exists()


# --- исходник эталона: чтение без правки (T315, D132) --------------------------
#
# Право на методику до T315 было одно на чтение и на правку: хранилище
# подставлялось только названным в `MCP_CHECKLIST_TENANTS`, а через него шли и
# читающие инструменты. Партнёру при этом полагается ровно чтение — «базово он
# должен будет видеть исходник» (D132), — и ошибка здесь дорога в обе стороны:
# закрытое чтение прячет от партнёра эталон, по которому его проверяют, а
# открытая правка даёт ему менять эталон управляющей компании.


def _вызов_партнёра(имя: str, аргументы: dict[str, Any], *, настройки: Settings) -> Any:
    """Вызов ОТ ИМЕНИ ПАРТНЁРА через те же подстановки, что делает транспорт."""
    from src.mcp.server import _checklist_for, _checklist_source_for

    return handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=ПАРТНЁР,
        checklist=_checklist_for(настройки, ПАРТНЁР),
        source=_checklist_source_for(настройки, ПАРТНЁР),
    )


def test_исходник_эталона_подставляется_и_тому_кому_правка_не_открыта(
    настройки: Settings,
) -> None:
    """Чтение эталона и правка эталона — два разных права на одной настройке
    хранилища: партнёру подставляется исходник и не подставляется правка."""
    from src.mcp.server import _checklist_for, _checklist_source_for

    assert _checklist_source_for(настройки, ПАРТНЁР) is not None
    assert _checklist_for(настройки, ПАРТНЁР) is None
    assert _checklist_source_for(настройки, УК) is not None


def test_без_хранилища_исходник_не_подставляется_никому(настройки: Settings) -> None:
    """Права на чтение хватает не всегда: выключенная целиком методика
    означает, что читать неоткуда, а не «читать можно пусто»."""
    from dataclasses import replace

    from src.mcp.server import _checklist_source_for

    assert _checklist_source_for(replace(настройки, checklist_store=None), ПАРТНЁР) is None
    assert _checklist_source_for(replace(настройки, data_dir=None), ПАРТНЁР) is None


def test_партнёр_читает_эталон_по_которому_его_проверяют(настройки: Settings) -> None:
    """То, ради чего задача и делалась: партнёрским токеном видно пункты,
    зоны, классы нарушений и сроки."""
    ответ = _вызов_партнёра("checklist_source", {}, настройки=настройки)

    assert "isError" not in ответ["result"]
    выдача = json.loads(ответ["result"]["content"][0]["text"])
    assert выдача["tenant"] == ПАРТНЁР
    assert выдача["count"] > 0
    assert выдача["zones"]
    пункт = выдача["items"][0]
    assert {"code", "levels", "days", "zones"} <= set(пункт)


def test_партнёр_видит_критерии_одного_пункта(настройки: Settings) -> None:
    """Класс нарушения — это не буква в колонке, а условия, при которых пункт
    D1, а при каких D2 (`docs/02-domain.md`). Без них партнёр видит вычет, но
    не видит, из чего он вышел."""
    перечень = json.loads(
        _вызов_партнёра("checklist_source", {}, настройки=настройки)["result"]["content"][0]["text"]
    )
    код = перечень["items"][0]["code"]

    ответ = _вызов_партнёра("checklist_source_item", {"code": код}, настройки=настройки)

    выдача = json.loads(ответ["result"]["content"][0]["text"])
    assert выдача["item"]["code"] == код
    assert "criteria" in выдача["item"]


def test_партнёру_чтение_эталона_не_даёт_ни_одной_правки(настройки: Settings) -> None:
    """Главная проверка задачи. Чтение открыто всем, правка — только названным:
    ни один инструмент правки не должен стать доступен заодно с исходником."""
    for spec in TOOLS:
        if spec.kind != KIND_CHECKLIST:
            continue
        ответ = _вызов_партнёра(spec.name, {}, настройки=настройки)
        assert ответ["result"]["isError"] is True, spec.name
        assert ответ["result"]["content"][0]["text"] == CHECKLIST_CLOSED, spec.name


def test_исходник_не_отдаёт_колонок_управляющей_компании(настройки: Settings) -> None:
    """В файле методики рядом с эталоном лежат собственные колонки УК (T109,
    T289) — произвольные и заведомо не предназначенные партнёру. Исходник
    отдаёт названные поля эталона, а не строку файла как она лежит."""
    методика = настройки.data_dir
    assert методика is not None
    исходный = (методика / "checklist.csv").read_text(encoding="utf-8").splitlines()
    (методика / "checklist.csv").write_text(
        "\n".join(
            [исходный[0] + ",Внутренняя пометка"]
            + [строка + ",секрет УК" for строка in исходный[1:] if строка.strip()]
        )
        + "\n",
        encoding="utf-8",
    )

    выдача = json.loads(
        _вызов_партнёра("checklist_source", {}, настройки=настройки)["result"]["content"][0]["text"]
    )

    assert выдача["count"] > 0
    for пункт in выдача["items"]:
        assert "Внутренняя пометка" not in пункт
        assert "секрет УК" not in json.dumps(пункт, ensure_ascii=False)


def test_через_сервер_исходник_открыт_партнёрскому_токену(сервер: str) -> None:
    """Через настоящий сокет: тот самый токен, которому правка отказывает,
    получает эталон."""
    правка = _спросить(сервер, ТОКЕН_ПАРТНЁРА, "checklist_versions", {})
    чтение = _спросить(сервер, ТОКЕН_ПАРТНЁРА, "checklist_source", {})

    assert правка["result"]["isError"] is True
    assert "isError" not in чтение["result"]
    assert json.loads(чтение["result"]["content"][0]["text"])["count"] > 0
