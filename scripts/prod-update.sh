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
IFS=: read -r -a overlays <<<"${DECIMUS_OVERLAYS:-}"
for overlay in "${overlays[@]}"; do
    [ -n "$overlay" ] && compose+=(-f "$overlay")
done

step() { printf '\n== %s\n' "$1"; }

if [ "${PULL:-1}" != "0" ]; then
    step "код"
    git pull --ff-only
fi

sha=$(git rev-parse --short HEAD)
echo "версия кода: $sha"

# `--profile backup`: голая сборка пропускает выгрузку состояния, и ночная
# задача бэкапа крутила бы образ прошлой версии (та же ловушка, что в deploy.sh).
step "сборка образа с версией $sha"
BUILD_SHA="$sha" "${compose[@]}" --profile backup build

step "база и хранилище"
"${compose[@]}" up -d --wait db storage-live
"${compose[@]}" run --rm storage-init

# Накат до подъёма приложений: новый код на старой схеме — это отказ админки,
# а не «доедет само». Накат идемпотентен, повторный запуск ничего не ломает.
step "накат миграций"
"${compose[@]}" run --rm --no-deps bot python -m src.db.migrate

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
echo "готово: $sha"
