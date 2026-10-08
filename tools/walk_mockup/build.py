"""Кликабельный макет мини-аппа обхода (#418) — один HTML-файл для отзывов коллег.

Экран и форма в макете — настоящие стили и скрипты мини-аппа (`src/web/static/walk*`),
данные — настоящий `walk_payload` на синтетической методике `tests/methodology` и
выдуманной пиццерии. Сервер подменён в браузере (`tools/walk_mockup/mock.js`):
те же адреса и ответы, что у веба, поэтому запись, правка, фото, повтор и сведения
о визите работают без бэкенда. Записанное остаётся в браузере смотрящего.

Экран поменялся — макет пересобирается этой же командой и публикуется заново:

    .venv/bin/python tools/walk_mockup/build.py <куда положить .html>
"""

# Разметка и стили макета — длинными строками, как они лягут в файл.
# ruff: noqa: E501

from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import sys
import tempfile
from datetime import date
from pathlib import Path


def generate(repo: Path) -> dict:
    """Данные экрана: настоящий build_walk на синтетической методике во временной папке."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["AUDIT_DATA_DIR"] = str(repo / "tests/methodology")
    os.environ["STATE_DIR"] = str(tmp / "state")
    os.environ.pop("MCP_CHECKLIST_STORE", None)
    os.chdir(tmp)
    sys.path.insert(0, str(repo))
    tmp = Path(tempfile.mkdtemp())
    os.environ["AUDIT_DATA_DIR"] = str(repo / "tests/methodology")
    os.environ["STATE_DIR"] = str(tmp / "state")
    os.environ.pop("MCP_CHECKLIST_STORE", None)
    os.chdir(tmp)
    sys.path.insert(0, str(repo))
    from PIL import Image, ImageDraw, ImageFilter

    from src import domain
    from src.db.models import PreviousFinding, PreviousFindings
    from src.web import walk

    CHAT = 999_000_000_777
    pics = {}

    def frame(label, base):
        im = Image.new("RGB", (900, 1200), base)
        d = ImageDraw.Draw(im)
        r = random.Random(label)  # noqa: S311 — узор картинки, не секрет
        for _ in range(40):
            x, y = r.randint(0, 900), r.randint(0, 1200)
            s = r.randint(30, 160)
            c = tuple(max(0, min(255, v + r.randint(-40, 40))) for v in base)
            d.ellipse((x, y, x + s, y + s), fill=c)
        im = im.filter(ImageFilter.GaussianBlur(14))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 1040, 900, 1200), fill=(0, 0, 0))
        d.text((40, 1100), label, fill=(255, 255, 255))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=70)
        raw = b.getvalue()
        ref = domain.save_upload(raw, domain.check_environment())
        small = im.resize((450, 600))
        b2 = io.BytesIO()
        small.save(b2, "JPEG", quality=62)
        pics[ref] = "data:image/jpeg;base64," + base64.b64encode(b2.getvalue()).decode()
        return ref

    domain.start_inspection(
        CHAT,
        unit="Пиццерия на Садовой",
        kind="planned",
        report_lang="ru",
        ui_lang="ru",
        speech_lang="ru",
        date=date.today().isoformat(),
        city="Энск",
        auditor="Макет",
        tenant="default",
    )
    domain.add_finding(
        CHAT,
        "CLN05",
        "D1",
        "hot_kitchen",
        "Нагар на задней стенке печи.",
        comment="Чистить печь по графику в конце смены.",
        photos=[frame("oven", (120, 90, 70))],
    )
    domain.add_finding(
        CHAT,
        "PRD06",
        "D1",
        "cold_kitchen",
        "Гастроёмкость с овощами без крышки.",
        photos=[frame("gn", (150, 170, 140))],
    )
    prev = PreviousFindings(
        date=date(2026, 9, 16),
        findings=(
            PreviousFinding(
                "CLN12", "D1", "dining", "Два стола у окна не протёрты, крошки и разводы."
            ),
            PreviousFinding(
                "CLN05",
                "D1",
                "hot_kitchen",
                "Нагар на задней стенке печи, жировые потёки у вытяжки.",
            ),
            PreviousFinding(
                "PRD09", "D2", "fridge", "Три контейнера с заготовками без даты маркировки."
            ),
            PreviousFinding("CLN02", "D1", "dishwashing", "Налёт на смесителе у второй раковины."),
        ),
    )
    walk.queries.previous_findings = lambda **_: prev
    walk.handed_over = lambda _c: False
    payload = walk.walk_payload(CHAT, fallback_lang="ru")
    return {"payload": payload, "pics": pics}


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    out = Path(sys.argv[1]).resolve()
    static = repo / "src/web/static"
    seed = generate(repo)
    p = seed["payload"]
    fix_items = {
        "PRD01": "Заготовка промаркирована ярлыком",
        "PRD13": "Соусы разлиты по дозаторам",
        "INF10": "Замер температуры холодильника",
        "INF11": "Снимок настроек печи",
    }
    for it in p["items"]:
        it["q"] = fix_items.get(it["code"], it["q"])
    # Замеры по зонам, как в боевой методике: холодильник — в своих шкафах,
    # настройки печи — в горячем цехе. В синтетической они общие.
    fix_zones = {"INF10": ["fridge", "freezer"], "INF11": ["hot_kitchen"]}
    for it in p["items"]:
        it["zones"] = fix_zones.get(it["code"], it["zones"])
    # Пример рекомендации без нарушения (D201): сервер её пока не пишет (#375),
    # поэтому она кладётся в данные макета напрямую.
    for zone in p["zones"]:
        if zone["code"] == "hot_kitchen":
            zone["recorded"].append(
                {
                    "n": 99,
                    "code": "TEH05",
                    "level": "R",
                    "text": "Смазать петли крышки линии начинки — открывается туго.",
                    "comment": "",
                    "repeat": False,
                    "unusual": False,
                    "photos": [],
                }
            )
    fix_info = {
        "INF01": "Состав смены",
        "INF03": "Выдано предписание",
        "INF04": "Точка закрывалась во время визита",
        "INF05": "Дата и время созвона с партнёром",
        "INF06": "Что улучшить",
        "INF07": "Срок плана действий",
        "INF08": "Отзыв о тестовом заказе",
    }
    for f in p["info"]:
        f["q"] = fix_info.get(f["code"], f["q"])

    def css(name):
        text = (static / name).read_text()

        def inline(m):
            f = static / m.group(1)
            return "url(data:font/woff2;base64," + base64.b64encode(f.read_bytes()).decode() + ")"

        return re.sub(r"url\('(fonts/[^']+)'\)", inline, text)

    styles = "\n".join(
        css(n) for n in ["dodo-ds.css", "decimus-domain.css", "walk.css", "walk-record.css", "walk-menu.css"]
    )
    scripts = "\n".join(
        (static / n).read_text()
        for n in ["walk-core.js", "walk-photo.js", "walk-menu.js", "walk-sheet.js", "walk.js"]
    )
    mock = (Path(__file__).parent / "mock.js").read_text()
    seed_js = json.dumps(seed, ensure_ascii=False).replace("</", "<\\/")
    bar_css = """
    :root{--mk-bg:#fff4d6;--mk-fg:#4a3500;--mk-btn:#4a3500;--mk-btn-fg:#fff4d6}
    @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--mk-bg:#3a2c08;--mk-fg:#ffe29a;--mk-btn:#ffe29a;--mk-btn-fg:#3a2c08}}
    :root[data-theme="dark"]{--mk-bg:#3a2c08;--mk-fg:#ffe29a;--mk-btn:#ffe29a;--mk-btn-fg:#3a2c08}
    .mk-bar{background:var(--mk-bg);color:var(--mk-fg);font:500 13px/1.4 'Golos Text',system-ui,sans-serif;padding:8px 16px;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
    .mk-bar p{margin:0;min-width:0;flex:1 1 220px}
    .mk-bar button{background:var(--mk-btn);color:var(--mk-btn-fg);border:0;border-radius:8px;padding:6px 12px;font:inherit;font-weight:600;cursor:pointer}
    .mk-bar button:focus-visible{outline:2px solid var(--mk-fg);outline-offset:2px}
    """
    page = f"""<title>Обход точки — макет</title>
    <meta name="color-scheme" content="light dark">
    <style>{styles}
    {bar_css}</style>
    <div class="mk-bar" role="note"><p><b>Макет для отзывов.</b> Пиццерия выдуманная, фото учебные. Всё, что вы запишете, остаётся только в этом браузере.</p><button type="button" id="mk-reset">Начать заново</button></div>
    <main id="walk" class="walk__root" data-endpoint="/mock/data" data-photo="/mock/photo" data-photo-view="/mock/photo/view" data-finding="/mock/finding" data-info="/mock/info" data-suggest="/mock/suggest"><p class="walk__loading">…</p></main>
    <script>window.__MOCK_SEED__ = {seed_js};</script>
    <script>{mock}</script>
    <script>document.body.classList.add("walk");document.getElementById("mk-reset").addEventListener("click",function(){{window.__mockReset();}});</script>
    <script>{scripts}</script>
    """
    out.write_text(page)
    print(f"Макет собран: {out} ({len(page) // 1024} КБ)")


if __name__ == "__main__":
    main()
