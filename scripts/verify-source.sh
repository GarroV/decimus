#!/usr/bin/env bash
# Сверка источника перед сборкой образа (см. GHSA-7gm6-hc9m-w3vc). Вызывается скриптами выкатки
# (scripts/prod-update.sh, deploy/demo/update.sh) после `git pull`, до `build`.
#
#   scripts/verify-source.sh
#
# Образ собирается из рабочего дерева сервера. Без сверки в него уезжает всё,
# что там лежит: коммит, которого нет на GitHub, или правка отслеживаемого файла,
# сделанная руками «на минуту». Проверяются два факта:
#
#  1. HEAD совпадает с `main` на GitHub. Адрес берётся у самого GitHub
#     (`git ls-remote`), а не из локальной ветки `origin/main`, которая бывает
#     устаревшей.
#  2. Отслеживаемые файлы не изменены. Неотслеживаемые не считаются: на сервере
#     лежат свои (`compose.edge.yaml`, `data/`, `.env`), и они в git не идут.
#
# Подписей коммитов у проекта нет, поэтому подпись не сверяется: сверка
# подтверждает, что собирается ровно `main` с GitHub, но не кто его написал.
#
# Осознанный обход (срочная правка на самом сервере, проверка стека с локальной
# правкой) — ALLOW_UNVERIFIED_SOURCE=1; он печатается, как LEAK_CHECK=0.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "${ALLOW_UNVERIFIED_SOURCE:-0}" = "1" ]; then
    echo "СВЕРКА ИСТОЧНИКА ПРОПУЩЕНА (ALLOW_UNVERIFIED_SOURCE=1): образ соберётся из того, что лежит в дереве" >&2
    exit 0
fi

head_sha=$(git rev-parse HEAD)
remote_sha=$(git ls-remote origin refs/heads/main | cut -f1)
if [ -z "$remote_sha" ]; then
    echo "сверка источника: не удалось узнать main на GitHub (git ls-remote origin пуст или недоступен) — сборка отменена" >&2
    exit 1
fi
if [ "$head_sha" != "$remote_sha" ]; then
    echo "сверка источника: HEAD ($head_sha) не совпадает с main на GitHub ($remote_sha) — сборка отменена." >&2
    echo "Скорее всего, на сервере другая ветка или локальный коммит. Исправить: git checkout main && git pull --ff-only" >&2
    exit 1
fi

dirty=$(git status --porcelain --untracked-files=no)
if [ -n "$dirty" ]; then
    echo "сверка источника: в дереве есть изменённые отслеживаемые файлы — сборка отменена:" >&2
    echo "$dirty" >&2
    echo "Убрать правку (git checkout -- <файл>) или внести её в main через PR." >&2
    exit 1
fi

echo "источник сверен: HEAD = main на GitHub (${head_sha:0:8}), дерево чистое"
