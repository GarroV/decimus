"""Предписание по шаблону в базе: нарушения, версия шаблона, защита (0089, D601, D602, D606).

Ядро — что партнёр прочтёт как факт. Держит БАЗА, а не экран:

- нарушения лежат строками снимка в порядке документа, версия шаблона запоминается;
- правятся только у неотправленного, с подписью; правка согласованного снимает согласование;
- запись обязана быть из проверки-основания этого предписания;
- предписание по шаблону без единого включённого нарушения не согласуется;
- версия шаблона только добавляется, а предписание берёт последнюю.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from test_db_prescriptions import СРОК, _hq, _положено, _принятая

psycopg = pytest.importorskip("psycopg")

from src.db import mail_templates  # noqa: E402
from src.db import prescriptions as rx  # noqa: E402
from src.db import prescriptions_write as rxw  # noqa: E402
from src.db.errors import PrescriptionError  # noqa: E402
from src.report import notice_template  # noqa: E402

pytestmark = requires_db

АВТОР = "dev-anna"
ОСБ = "osb-vera"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> dict[str, str]:
    точки = {"Batumi-1": точка_справочника("Batumi-1", country="GE", city="Batumi")}
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    return точки


def _sql(dsn: str, текст: str, параметры: tuple[Any, ...] = (), *, подпись: str = "") -> list[Any]:
    with psycopg.connect(dsn) as conn:
        if подпись:
            conn.execute("select set_config('decimus.prescription_actor', %s, true)", (подпись,))
        cur = conn.execute(текст, параметры)
        rows = cur.fetchall() if cur.description else []
        conn.commit()
    return rows


def _записи(dsn: str, проверка: str) -> list[str]:
    return [
        str(r[0])
        for r in _sql(
            dsn, "select id from findings where inspection_id = %s order by n", (проверка,)
        )
    ]


def _строка(
    проверка: str, запись: str, *, позиция: int = 1, включено: bool = True
) -> rx.FindingPick:
    return rx.FindingPick(
        inspection_id=проверка,
        finding_id=запись,
        position=позиция,
        object_name="Batumi-1",
        level="D2",
        clause="Batches of different runs stand in separate tubs",
        description="Tubs stand together",
        description_translated=True,
        due_on=СРОК,
        engine_due_on=СРОК - timedelta(days=5),
        suggested=включено,
        included=включено,
    )


def _драфт(проверка: str, *строки: rx.FindingPick, **поля: Any) -> rx.Draft:
    основа: dict[str, Any] = {
        "country": "GE",
        "due_on": СРОК,
        "recipients": "ops@ge.example.com",
        "subject": "Notice",
        "body": "Cover text",
        "inspection_ids": (проверка,),
        "findings": строки,
    }
    return rx.Draft(**{**основа, **поля})


def _с_нарушением(admin_env: str, **поля: Any) -> tuple[str, str, str]:
    проверка = _принятая()
    запись = _записи(admin_env, проверка)[0]
    ident = rxw.create_draft(_драфт(проверка, _строка(проверка, запись), **поля), actor=АВТОР)
    return ident, проверка, запись


def _согласовать(ident: str) -> None:
    rxw.request_review(ident, actor=АВТОР)
    rxw.approve(ident, actor=ОСБ)


def test_нарушения_ложатся_снимком_а_версия_шаблона_запоминается(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident, проверка, запись = _с_нарушением(admin_env)

    p = _hq(ident)
    assert p.kind == "inspection" and p.has_document
    (строка,) = p.findings
    assert (строка.finding_id, строка.inspection_id, строка.included) == (запись, проверка, True)
    assert строка.clause == "Batches of different runs stand in separate tubs"
    # Версия — встроенный текст, легший первой версией: предписание помнит точный текст.
    версия = mail_templates.get(p.template_version_id)
    assert версия is not None and версия.version == 1
    assert версия.body == notice_template.BUILTIN_PRESCRIPTION_INSPECTION


def test_предписание_берёт_последнюю_загруженную_версию(
    сеть: dict[str, str], admin_env: str
) -> None:
    загружена = mail_templates.add_version(
        notice_template.TEMPLATE_KIND, "en", "# T2\n\n{{date}}\n", actor="osb"
    )
    ident, _, _ = _с_нарушением(admin_env)
    assert _hq(ident).template_version_id == загружена.id and загружена.version == 1
    вторая = mail_templates.add_version(
        notice_template.TEMPLATE_KIND, "en", "# T3\n\n{{date}}\n", actor="osb"
    )
    assert вторая.version == 2
    последняя = mail_templates.latest(notice_template.TEMPLATE_KIND, "en")
    assert последняя is not None and последняя.id == вторая.id
    # Прежнее предписание остаётся на своей версии.
    assert _hq(ident).template_version_id == загружена.id


def test_версия_шаблона_не_правится_и_не_удаляется(сеть: dict[str, str], admin_env: str) -> None:
    mail_templates.add_version(notice_template.TEMPLATE_KIND, "en", "# T\n", actor="osb")
    for текст in ("update mail_templates set body = 'x'", "delete from mail_templates"):
        with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
            _sql(admin_env, текст)


def test_без_включённого_нарушения_предписание_не_создаётся(
    сеть: dict[str, str], admin_env: str
) -> None:
    проверка = _принятая()
    запись = _записи(admin_env, проверка)[0]
    with pytest.raises(PrescriptionError, match="хотя бы одно нарушение"):
        rxw.create_draft(_драфт(проверка, _строка(проверка, запись, включено=False)), actor=АВТОР)


def test_запись_чужой_проверки_отклоняется_базой(сеть: dict[str, str], admin_env: str) -> None:
    ident, проверка, _ = _с_нарушением(admin_env)
    чужая = _принятая()
    чужая_запись = _записи(admin_env, чужая)[0]
    вставка = (
        "insert into prescription_findings (prescription_id, inspection_id, finding_id, position,"
        " object_name, level, clause, description_translated, due_on, suggested, included)"
        " values (%s, %s, %s, 2, 'x', 'D2', 'c', true, current_date + 5, false, true)"
    )
    # Проверка не основание предписания — составной внешний ключ.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _sql(admin_env, вставка, (ident, чужая, чужая_запись), подпись=АВТОР)
    # Основание то же, а запись из другой проверки — триггер.
    with pytest.raises(psycopg.errors.CheckViolation, match="не из проверки"):
        _sql(admin_env, вставка, (ident, проверка, чужая_запись), подпись=АВТОР)


def test_правка_нарушений_без_подписи_отказ(сеть: dict[str, str], admin_env: str) -> None:
    ident, _, _ = _с_нарушением(admin_env)
    with pytest.raises(psycopg.errors.CheckViolation, match="с подписью"):
        _sql(
            admin_env,
            "update prescription_findings set included = false where prescription_id = %s",
            (ident,),
        )


def test_правка_согласованного_снимает_согласование(сеть: dict[str, str], admin_env: str) -> None:
    ident, _, _ = _с_нарушением(admin_env)
    _согласовать(ident)
    assert _hq(ident).status == "approved"

    _sql(
        admin_env,
        "update prescription_findings set due_on = due_on + 1 where prescription_id = %s",
        (ident,),
        подпись=ОСБ,
    )

    p = _hq(ident)
    assert p.status == "review" and p.approved_by is None


def test_отправленное_не_правится_и_у_прямого_sql(сеть: dict[str, str], admin_env: str) -> None:
    ident, _, _ = _с_нарушением(admin_env)
    _согласовать(ident)
    rxw.issue(ident, actor=ОСБ, put_draft=_положено([]))
    for текст in (
        "update prescription_findings set included = false where prescription_id = %s",
        "delete from prescription_findings where prescription_id = %s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation, match="неотправленного"):
            _sql(admin_env, текст, (ident,), подпись=ОСБ)
    assert len(_hq(ident).findings) == 1


def test_без_включённых_нарушений_не_согласуется(сеть: dict[str, str], admin_env: str) -> None:
    ident, _, _ = _с_нарушением(admin_env)
    _sql(
        admin_env,
        "update prescription_findings set included = false where prescription_id = %s",
        (ident,),
        подпись=АВТОР,
    )
    with pytest.raises(PrescriptionError, match="нет ни одного нарушения"):
        _согласовать(ident)
    assert _hq(ident).status == "review"


def test_правка_пересобирает_нарушения_а_руками_вписанное_их_не_принимает(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident, проверка, запись = _с_нарушением(admin_env)
    правка = _драфт(проверка, _строка(проверка, запись, включено=False), body="New cover")
    with pytest.raises(PrescriptionError, match="хотя бы одно нарушение"):
        rxw.update_draft(ident, правка, actor=АВТОР)

    новый_срок = СРОК + timedelta(days=3)
    строка = _строка(проверка, запись)
    rxw.update_draft(
        ident,
        _драфт(проверка, rx.FindingPick(**{**строка.__dict__, "due_on": новый_срок}), body="New"),
        actor=АВТОР,
    )
    assert _hq(ident).findings[0].due_on == новый_срок

    # Предписание без шаблона (текст руками) нарушений не принимает.
    руками = rxw.create_draft(_драфт(проверка, subject="By hand", findings=()), actor=АВТОР)
    assert _hq(руками).kind == "other" and not _hq(руками).has_document
    with pytest.raises(PrescriptionError, match="руками"):
        rxw.update_draft(руками, _драфт(проверка, _строка(проверка, запись)), actor=АВТОР)


def _tool() -> Any:
    import importlib.util

    путь = Path(__file__).resolve().parents[1] / "tools" / "prescription_template.py"
    spec = importlib.util.spec_from_file_location("prescription_template_tool", путь)
    assert spec and spec.loader
    модуль = importlib.util.module_from_spec(spec)
    # Инструмент при импорте читает `.env` репозитория; в тесте окружение — тестовой базы.
    окружение = dict(os.environ)
    try:
        spec.loader.exec_module(модуль)
    finally:
        os.environ.clear()
        os.environ.update(окружение)
    return модуль


def test_инструмент_шаблона_set_заводит_новую_версию_а_show_её_печатает(
    сеть: dict[str, str], admin_env: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    инструмент = _tool()
    файл = tmp_path / "t.txt"
    файл.write_text("# Notice of {{date}}\n\n{{findings_table}}\n", encoding="utf-8")
    было = len(mail_templates.versions(notice_template.TEMPLATE_KIND, "zz"))

    # Act
    код = инструмент.main(
        ["set", "--file", str(файл), "--kind", notice_template.TEMPLATE_KIND, "--lang", "zz"]
    )
    вывод_set = capsys.readouterr()
    код_show = инструмент.main(["show", "--kind", notice_template.TEMPLATE_KIND, "--lang", "zz"])
    вывод_show = capsys.readouterr().out

    # Assert
    assert код == 0, вывод_set.err
    assert код_show == 0
    assert f"версия {было + 1}" in вывод_set.out
    assert f"версия {было + 1}" in вывод_show and "# Notice of {{date}}" in вывод_show
    assert len(mail_templates.versions(notice_template.TEMPLATE_KIND, "zz")) == было + 1


def test_инструмент_шаблона_неизвестная_подстановка_не_пишет_версию(
    сеть: dict[str, str], admin_env: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    инструмент = _tool()
    файл = tmp_path / "bad.txt"
    файл.write_text("# T\n\n{{no_such_token}}\n", encoding="utf-8")
    было = len(mail_templates.versions(notice_template.TEMPLATE_KIND, "zz"))

    код = инструмент.main(
        ["set", "--file", str(файл), "--kind", notice_template.TEMPLATE_KIND, "--lang", "zz"]
    )

    assert код == 1 and "неизвестные подстановки" in capsys.readouterr().err
    assert len(mail_templates.versions(notice_template.TEMPLATE_KIND, "zz")) == было
