"""Смоук подбора пункта конвейером бота (#1033): пять фраз → код, класс, зона, время.

Гоняется ВНУТРИ контейнера mcp на проде (там ключ модели, хранилище и методика):

    docker compose exec -T mcp python tools/smoke_match.py [--tenant HQ] [--version V]

Ни базы, ни черновика не нужно: берётся действующее издание эталона из хранилища
(`MCP_CHECKLIST_STORE`), а конвейер тот же, что у инструмента `import_match_findings`.
Фразы можно заменить: `--text "..."` (повторяется). Ключ модели не печатается.

Ждём на пяти фразах по умолчанию: «Три мясных продукта на линии 14 градусов» — FSB03
(D2/D3, зона горячий цех), «Грязная мебель в зале» — CLN13 D1, «Нет номера столика» —
no_item, мусор на полу (CLN12, зона зал) и повар без перчаток (PRD15, зона горячий цех
по слову «повар») — пункты по методике; у них одно семейство классов, поэтому `need_fact`
быть не должно, а зону не спрашивают. Код возврата 1,
если хоть одна строка ушла в откат на карту слов (модель не ответила).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_TEXTS = (
    "Три мясных продукта на линии 14 градусов",
    "Грязная мебель в зале",
    "Нет номера столика",
    "На полу в зале мусор",
    "Повар без перчаток режет пиццу",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", default="HQ")
    parser.add_argument("--version", default=None, help="версия методики; по умолчанию действующая")
    parser.add_argument("--lang", default="ru")
    parser.add_argument("--text", action="append", help="своя фраза (можно несколько)")
    args = parser.parse_args()

    from src.domain.model_usage import usage_scope
    from src.mcp.checklist_layout import DEFAULT_SPACE, Store
    from src.mcp.import_draft import draft_from_store
    from src.mcp.import_match import match_texts

    root, live = os.environ.get("MCP_CHECKLIST_STORE"), os.environ.get("AUDIT_DATA_DIR")
    if not root or not live:
        print("Нужны MCP_CHECKLIST_STORE и AUDIT_DATA_DIR (запускать в контейнере mcp)")
        return 2
    store = Store(root=Path(root), live=Path(live), space=DEFAULT_SPACE)
    draft = draft_from_store(store, tenant=args.tenant, version=args.version, lang=args.lang)
    texts = tuple(args.text) if args.text else DEFAULT_TEXTS

    started = time.monotonic()
    with usage_scope(tenant=args.tenant):
        results = match_texts(draft, [(t, None) for t in texts])
    elapsed = time.monotonic() - started

    print(f"версия {draft.version}, замечаний {len(texts)}, {elapsed:.1f} с вместе")
    fallbacks = 0
    for r in results:
        if r.get("fallback"):
            fallbacks += 1
            print(f"  {r['n']}. ОТКАТ {r['fallback']}: {r['fallback_reason']} | {r['text']}")
        elif r.get("no_item"):
            print(f"  {r['n']}. нет пункта: {r['reason']} | {r['text']}")
        else:
            extra = "".join(
                f" [{k}: {r[k]}]" for k in ("need_fact", "zone_assumed", "doubt") if k in r
            )
            print(
                f"  {r['n']}. {r['code']} {r['level']} зона={r['zone']} "
                f"via={r['via']} | {r['text']}{extra}"
            )
    return 1 if fallbacks else 0


if __name__ == "__main__":
    sys.exit(main())
