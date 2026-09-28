"""Сжатые копии для кадров, выгруженных до D219 — разовый доливщик.

Копия кадра (`photos.preview_path`) делается при выгрузке (`upload_photos`).
Кадры, выгруженные раньше, копии не имеют, и в карточке у их записей фото не
видно. Оригиналы этих кадров лежат в хранилище — копия делается из них, без
телеграма.

Строка выгруженного кадра заморожена политикой `photos_uploaded_only_once`,
и ослаблять её ради разовой доливки нельзя: исключение осталось бы навсегда.
Поэтому доливщик идёт под учёткой наката схемы (`DATABASE_ADMIN_URL`), и
пишет он ровно одну колонку и только там, где она пуста.

    python tools/backfill_previews.py            # сухой прогон: что будет сделано
    python tools/backfill_previews.py --apply    # сделать

Повторяем: второй прогон берёт только кадры без копии. Убранные кадры
(`purged_at`, снятые проверки) не трогает — их оригиналов в хранилище нет.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from src.db.config import load_storage_settings
from src.db.errors import StorageError
from src.db.migrate import admin_dsn
from src.db.previews import PREVIEW_CONTENT_TYPE, make_preview
from src.db.storage import S3PhotoStorage, key_of_uri, preview_key

_PENDING_SQL = """
select id, inspection_id, storage_path
from photos
where storage_path is not null and preview_path is null and purged_at is null
order by created_at, id
"""

_SET_PREVIEW_SQL = """
update photos set preview_path = %s where id = %s and preview_path is null
"""


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--apply", action="store_true", help="сделать, а не показать")
    apply = args.parse_args(argv).apply

    dsn = admin_dsn()
    if dsn is None:
        print("DATABASE_ADMIN_URL не задан — доливать нечем", file=sys.stderr)
        return 2
    store = S3PhotoStorage(load_storage_settings())

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_PENDING_SQL)
            pending = cur.fetchall()
        print(f"кадров без копии: {len(pending)}")
        if not apply:
            print("сухой прогон — ничего не записано; сделать: --apply")
            return 0

        done = failed = 0
        for photo_id, inspection_id, storage_path in pending:
            try:
                copy = make_preview(store.get(key_of_uri(str(storage_path))))
                uri = store.put(
                    preview_key(str(inspection_id), str(photo_id)),
                    copy,
                    content_type=PREVIEW_CONTENT_TYPE,
                )
            except StorageError as exc:
                # Один нечитаемый кадр не останавливает остальные, но и не
                # проходит молча: он назван, и итог это покажет.
                print(f"  кадр {photo_id}: пропущен — {exc}", file=sys.stderr)
                failed += 1
                continue
            with conn.cursor() as cur:
                cur.execute(_SET_PREVIEW_SQL, (uri, photo_id))
            conn.commit()
            done += 1
        print(f"сделано копий: {done}, не вышло: {failed}")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
