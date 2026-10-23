#!/usr/bin/env bash
# Обновление прода на Linux (VPS) — запускается НА САМОМ СЕРВЕРЕ из каталога
# репозитория. Порядок и почему он такой — docs/08-deploy.md, §8.
#
#   scripts/prod-update.sh
#
# Надстройки площадки (подключение к общему прокси из vps-infra) передаются
# списком через двоеточие:
#
#   DECIMUS_OVERLAYS=/srv/decimus/compose.edge.yaml scripts/prod-update.sh
#
# PULL=0 — не тянуть код (проверка стека с нуля на своей машине).
#
# Шаги те же, что у scripts/deploy.sh для MUSPELHEIM, и по той же причине
# одной командой: `up -d --build` пересборку пропускает, а накат миграций,
# забытый между сборкой и подъёмом, роняет админку на странице «схема отстаёт».
set -euo pipefail

cd "$(dirname "$0")/.."

compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
# Забытая надстройка площадки роняет прод молча: `web` теряет сеть общего прокси,
# снаружи 502 (21.10.2026, около 18 минут). Поэтому без DECIMUS_OVERLAYS надстройка,
# лежащая рядом, подключается сама; пустая строка (`DECIMUS_OVERLAYS=`) — осознанный
# отказ от неё.
if [ -z "${DECIMUS_OVERLAYS+set}" ] && [ -f compose.edge.yaml ]; then
    DECIMUS_OVERLAYS="$PWD/compose.edge.yaml"
    echo "надстройка площадки: $DECIMUS_OVERLAYS (DECIMUS_OVERLAYS не задан)" >&2
fi
IFS=: read -r -a overlays <<<"${DECIMUS_OVERLAYS:-}"
for overlay in "${overlays[@]}"; do
    [ -n "$overlay" ] && compose+=(-f "$overlay")
done

step() { printf '\n== %s\n' "$1"; }

# Одна выкатка за раз (#729). 12.10.2026 две сессии запустили выкатку с разницей
# в минуту: второй накат повторил уже применённую миграцию, compose оставил бота
# в `Created`, и бот стоял, пока выкатку не перезапустили. Замок держится на
# дескрипторе 9 и переживает `exec` ниже; повторный запуск после `exec` замок не
# берёт заново (иначе ждал бы сам себя). Вторая выкатка ждёт первую, а не
# дождалась за DEPLOY_LOCK_WAIT_S — отказ с понятным текстом.
if [ -z "${DECIMUS_DEPLOY_LOCKED:-}" ]; then
    exec 9>"$(git rev-parse --git-dir)/prod-update.lock"
    if ! flock -w "${DEPLOY_LOCK_WAIT_S:-900}" 9; then
        echo "другая выкатка ещё идёт: замок не освободился за ${DEPLOY_LOCK_WAIT_S:-900} с" >&2
        exit 1
    fi
    export DECIMUS_DEPLOY_LOCKED=1
fi

# После `git pull` скрипт перезапускает САМ СЕБЯ: bash читает файл по ходу
# выполнения, и обновлённый под ним скрипт доигрывался бы старой версией —
# так 28.09 новый шаг проверки хранилища (#404) в первой же раскатке не
# выполнился, а итог был «готово».
if [ "${PULL:-1}" != "0" ]; then
    step "код"
    git pull --ff-only
    exec env PULL=0 "$0" "$@"
fi

sha=$(git rev-parse --short HEAD)
echo "версия кода: $sha"

# Собирается ровно `main` с GitHub, а не то, что лежит в дереве (см. GHSA-7gm6-hc9m-w3vc).
# Стоит и после `PULL=0`: этот режим тоже собирает образ из дерева.
step "сверка источника"
scripts/verify-source.sh

# Боевая методика есть только здесь: в CI её нет, и тест утечки там
# пропускается молча (#854). Поэтому проверка — шаг выкатки, до сборки:
# цитата методики в публичном репозитории останавливает раскатку, пока её не
# уберут. Только отслеживаемое — на сервере лежат свои неотслеживаемые файлы.
# Осознанный обход (срочная починка прода) — LEAK_CHECK=0, и он печатается.
step "утечка методики"
if [ "${LEAK_CHECK:-1}" = "0" ]; then
    echo "ПРОВЕРКА УТЕЧКИ ПРОПУЩЕНА (LEAK_CHECK=0)" >&2
else
    python3 tools/methodology_leak.py data --tracked-only
fi

# `--profile backup`: голая сборка пропускает выгрузку состояния, и ночная
# задача бэкапа крутила бы образ прошлой версии (та же ловушка, что в deploy.sh).
# `--profile migrate` — по той же причине: накат идёт собственным сервисом, и без
# сборки он катил бы схему кодом прошлой версии.
step "сборка образа с версией $sha"
BUILD_SHA="$sha" "${compose[@]}" --profile backup --profile migrate build

step "база"
"${compose[@]}" up -d --wait db

# Хранилище кадров — своё, на VPS (D635; с 30.09 по 23.10.2026 оно было на
# MUSPELHEIM). Поднимается и заводится до приложений: бот и админка читают и пишут
# в него с первой секунды. Заведение корзины и пользователя приложения
# идемпотентно.
step "хранилище кадров"
"${compose[@]}" up -d --wait storage-live
"${compose[@]}" run --rm --no-deps storage-init

# Накат до подъёма приложений: новый код на старой схеме — это отказ админки,
# а не «доедет само». Накат идемпотентен, повторный запуск ничего не ломает.
step "накат миграций"
# Сервис `migrate` — единственный, кому `docker-compose.yml` отдаёт владельца
# схемы (`DATABASE_ADMIN_URL`); у бота, админки, MCP и обхода его нет (F-002).
"${compose[@]}" run --rm --no-deps migrate

step "подъём"
"${compose[@]}" up -d --wait --remove-orphans

# Смоук с самого сервера по петле: вход админки отвечает страницей, MCP без
# токена отказывает. Порт на хосте берётся у compose, а не из окружения.
step "смоук"
web_port=$("${compose[@]}" port web "${WEB_PORT:-8267}" | cut -d: -f2)
mcp_port=$("${compose[@]}" port mcp "${MCP_PORT:-8265}" | cut -d: -f2)
web_code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$web_port/login")
mcp_code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$mcp_port/mcp")
echo "админка /login: $web_code (ждём 200)"
echo "MCP без токена: $mcp_code (ждём 401)"
if [ "$web_code" != "200" ] || [ "$mcp_code" != "401" ]; then
    echo "смоук: провал — смотреть '${compose[*]} logs web mcp'" >&2
    exit 1
fi
# Смоук по HTTP не видит, что разделу нечего показать: «Методика» без
# хранилища версий отвечает 200 с плашкой «не настроено» (#404 — так прод
# на VPS и простоял после переезда). Поэтому настройка проверяется из самого
# контейнера: переменная задана, каталог есть и в него пишется. Именно
# пробной записью, а не `test -w`: админка работает от root, и для root
# `test -w` отвечает «да» даже на томе, смонтированном только на чтение.
step "хранилище версий методики"
if ! "${compose[@]}" exec -T web sh -c \
    'test -n "$MCP_CHECKLIST_STORE" && test -d "$MCP_CHECKLIST_STORE" && touch "$MCP_CHECKLIST_STORE/.probe" && rm -f "$MCP_CHECKLIST_STORE/.probe"'; then
    echo "админка не видит хранилища версий: MCP_CHECKLIST_STORE не задана или каталог не открыт на запись — см. docker-compose.yml, сервис web" >&2
    exit 1
fi
echo "админка видит хранилище версий"
# Мини-апп обхода пишет в идущие проверки своим сервисом `walk`, админка их
# только читает (docs/08-deploy.md, §8.14). Проверяется пробной записью, а не
# `test -w`, по той же причине, что выше. Страница обхода — через админку: она
# передаёт `/tg/walk*` сервису, и 200 значит, что дошло до него.
step "мини-апп обхода"
if "${compose[@]}" exec -T web sh -c 'touch /app/state/.walk-probe 2>/dev/null'; then
    "${compose[@]}" exec -T web sh -c 'rm -f /app/state/.walk-probe'
    echo "админка пишет в состояние проверок — у сервиса web том state обязан быть :ro" >&2
    exit 1
fi
if ! "${compose[@]}" exec -T walk sh -c 'touch /app/state/.walk-probe && rm -f /app/state/.walk-probe'; then
    echo "сервис обхода не пишет в состояние проверок — см. docker-compose.yml, сервис walk" >&2
    exit 1
fi
walk_code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$web_port/tg/walk")
echo "обход /tg/walk через админку: $walk_code (ждём 200)"
if [ "$walk_code" != "200" ]; then
    echo "смоук обхода: провал — смотреть '${compose[*]} logs web walk'" >&2
    exit 1
fi
echo "готово: $sha"
