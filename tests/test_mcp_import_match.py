"""#1033: `import_match_findings` — конвейер бота над изданием черновика, модель на заглушке.

Сеть не участвует: подменён `ask_model` (единственная точка вызова провайдера).
Методика — синтетическая `tests/methodology`. Закреплено то, что важно: класс
определяется вторым вопросом по критериям (а не первым ответом), «нет пункта»
отдаётся как `no_item`, а недоступная модель — откатом с явным `fallback`.
"""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from src.domain.models import Zone
from src.mcp import import_draft as dr
from src.mcp import import_match as im
from src.mcp import import_suggest as sug
from src.mcp.errors import ToolError
from src.recognize.client import ModelAnswer
from src.recognize.cues import load_cues
from src.recognize.errors import ModelUnavailable

МЕТОДИКА = Path(__file__).parent / "methodology"


def _stage1(item: str, zone: str = "hot_kitchen", question: str = "") -> dict[str, Any]:
    return {
        "records": [
            {
                "item": item,
                "zone": zone,
                "wording": "слова аудитора",
                "reason": "r",
                "confidence": 0.9,
                "reading_c": None,
            }
        ],
        "question": question,
    }


class _Модель:
    """Заглушка `ask_model`: первый вопрос (есть `records`) и второй (класс) — разные ответы."""

    def __init__(
        self, first: dict[str, Any], level: dict[str, Any] | None = None, delay: float = 0.0
    ) -> None:
        self.first = first
        self.level = level or {"level": "D2", "need_fact": "", "reason": "по критериям"}
        self.delay = delay
        self.questions: list[str] = []
        self.running = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, **kw: Any) -> ModelAnswer:
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        time.sleep(self.delay)
        with self._lock:
            self.running -= 1
        self.questions.append(kw["question"])
        if "records" in kw["schema"]["properties"]:
            return ModelAnswer(payload=self.first, usage={})
        return ModelAnswer(payload=self.level, usage={})


@pytest.fixture
def черновик(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> dr.Draft:
    with (МЕТОДИКА / "checklist.csv").open(encoding="utf-8-sig", newline="") as f:
        строки = [dict(r) for r in csv.DictReader(f)]
    with (МЕТОДИКА / "zones.csv").open(encoding="utf-8-sig", newline="") as f:
        зоны = [
            Zone(code=r["code"], title_ru=r["name_ru"], title_en=r["name_en"], share_pct=0.0)
            for r in csv.DictReader(f)
        ]
    monkeypatch.setattr(
        im.store_api,
        "read_item",
        lambda s, code, version=None: {"criteria": f"{code}: D1 — одно; D2 — два или три"},
    )
    monkeypatch.setattr(dr.store_api, "read_item", im.store_api.read_item)
    return dr.Draft(
        ident="i1",
        history=False,
        version="v1",
        lang="ru",
        store=object(),  # type: ignore[arg-type]
        rows=строки,
        zones=зоны,
        cues=load_cues(МЕТОДИКА / "photo-cues.md", chat_id=None),
        data_dir=МЕТОДИКА,
    )


def _подменить(monkeypatch: pytest.MonkeyPatch, модель: Any) -> None:
    monkeypatch.setattr("src.recognize.classify.ask_model", модель)


def test_класс_определяется_вторым_вопросом_по_критериям(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    модель = _Модель(_stage1("PRD01:D1"), {"level": "D2", "need_fact": "", "reason": "два"})
    _подменить(monkeypatch, модель)

    [строка] = im.match_texts(черновик, [("заготовки без ярлыка", None)])

    assert строка["code"] == "PRD01"
    assert строка["level"] == "D2"  # не D1 из первого ответа
    assert строка["zone"] == "hot_kitchen"
    assert строка["item_label"] == "Заготовки 1"
    assert строка["item_title"]
    assert "no_item" not in строка and "fallback" not in строка
    assert any("PRD01: D1 — одно" in q for q in модель.questions)  # критерии ушли модели


def test_недостающий_факт_доходит_одной_фразой(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    _подменить(
        monkeypatch,
        _Модель(
            _stage1("PRD01:D1"), {"level": "D1", "need_fact": "Сколько тар?", "reason": "нет числа"}
        ),
    )

    [строка] = im.match_texts(черновик, [("заготовки без ярлыка", None)])

    assert строка["level"] == "D1"
    assert строка["need_fact"] == "Сколько тар?"


def test_у_одноклассового_пункта_нет_need_fact_и_зона_берётся_из_пункта(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PRD15: класс только D1, зоны «hot_kitchen,cold_kitchen,...»; модель зону не назвала
    # и задала вопрос — он не доходит до человека.
    модель = _Модель(_stage1("PRD15:D1", zone="UNKNOWN", question="Где это было?"))
    _подменить(monkeypatch, модель)

    [строка] = im.match_texts(черновик, [("заготовки без ярлыка", None)])

    assert строка["code"] == "PRD15"
    assert "need_fact" not in строка
    assert строка["zone"] == "hot_kitchen"
    assert строка["zone_assumed"] is True
    assert len(модель.questions) == 1  # второго вопроса про класс нет


def test_единственная_зона_пункта_не_считается_допущением(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    _подменить(monkeypatch, _Модель(_stage1("CLN12:D1", zone="UNKNOWN")))

    [строка] = im.match_texts(черновик, [("на полу мусор", None)])

    assert строка["zone"] == "dining"
    assert "zone_assumed" not in строка and "need_fact" not in строка


def test_зона_из_слов_замечания_без_допущения(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    _подменить(monkeypatch, _Модель(_stage1("PRD15:D1", zone="UNKNOWN")))

    [строка] = im.match_texts(черновик, [("повар без перчаток режет пиццу", None)])

    assert строка["zone"] == "hot_kitchen"
    assert "zone_assumed" not in строка and "need_fact" not in строка


def test_вопрос_про_класс_у_многоклассового_идёт_на_языке_замечания(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    модель = _Модель(_stage1("PRD01:D1"), {"level": "D1", "need_fact": "Сколько?", "reason": "r"})
    _подменить(monkeypatch, модель)

    [строка] = im.match_texts(черновик, [("заготовки без ярлыка", None)])

    assert строка["need_fact"] == "Сколько?"
    assert any("ЯЗЫК ВОПРОСА need_fact: ru" in q for q in модель.questions)


def test_пункта_нет_отдаётся_как_no_item(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    _подменить(monkeypatch, _Модель(_stage1("NONE")))

    [строка] = im.match_texts(черновик, [("нет номера столика", None)])

    assert строка["no_item"] is True
    assert строка["reason"].startswith("В этом издании")  # язык замечания, не английский
    assert "code" not in строка


def test_модель_недоступна_откат_на_карту_слов_явно(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    def упала(**kw: Any) -> ModelAnswer:
        raise ModelUnavailable("нет сети")

    _подменить(monkeypatch, упала)

    [строка] = im.match_texts(черновик, [("печь грязная", None)])

    assert строка["fallback"] == "word_map"
    assert строка["fallback_reason"]
    assert "level" not in строка  # класс без модели не выдумывается
    assert "CLN05" in [c["code"] for c in строка["candidates"]]


def test_замечания_идут_пакетом_а_не_по_очереди(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    модель = _Модель(_stage1("PRD01:D1"), delay=0.2)
    _подменить(monkeypatch, модель)

    итог = im.match_texts(черновик, [(f"заготовки без ярлыка {i}", None) for i in range(5)])

    assert [r["n"] for r in итог] == [1, 2, 3, 4, 5]
    assert модель.peak >= 3  # по очереди было бы 1


def test_обработчик_отказывает_на_пустом_и_слишком_длинном_списке() -> None:
    with pytest.raises(ToolError):
        im.import_match_findings(
            tenant="HQ",
            store=object(),
            actor="a",
            inspection_id="i",
            findings=[],  # type: ignore[arg-type]
        )
    with pytest.raises(ToolError, match="не больше 50"):
        im.import_match_findings(
            tenant="HQ",
            store=object(),  # type: ignore[arg-type]
            actor="a",
            inspection_id="i",
            findings=[{"text": "x"}] * 51,
        )


def test_обработчик_ставит_fallback_и_на_весь_ответ(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    def упала(**kw: Any) -> ModelAnswer:
        raise ModelUnavailable("нет сети")

    _подменить(monkeypatch, упала)
    monkeypatch.setattr(im, "load_draft", lambda **kw: черновик)

    ответ = im.import_match_findings(
        tenant="HQ",
        store=object(),  # type: ignore[arg-type]
        actor="a",
        inspection_id="i",
        findings=[{"text": "печь грязная"}],
    )

    assert ответ["fallback"] == "word_map"
    assert ответ["results"][0]["fallback"] == "word_map"  # type: ignore[index]


def test_suggest_идёт_тем_же_конвейером_и_отдаёт_одного_кандидата(
    черновик: dr.Draft, monkeypatch: pytest.MonkeyPatch
) -> None:
    _подменить(monkeypatch, _Модель(_stage1("PRD01:D1")))
    monkeypatch.setattr(sug, "load_draft", lambda **kw: черновик)

    ответ = sug.import_suggest_items(
        tenant="HQ",
        store=object(),  # type: ignore[arg-type]
        actor="a",
        inspection_id="i",
        text="заготовки без ярлыка",
    )

    [кандидат] = ответ["candidates"]  # type: ignore[misc]
    assert (кандидат["code"], кандидат["level"]) == ("PRD01", "D2")
    assert ответ["single"] is True
