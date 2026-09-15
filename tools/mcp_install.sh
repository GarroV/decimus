#!/bin/bash
# Установщик подключения к MCP-серверу проверок (#244, решение D112).
#
# Запускается человеком одной строкой, которую присылает бот:
#   curl -fsSL https://<адрес>/setup | DODO_MCP_TOKEN='...' bash
#
# Форма повторяет соседний продукт (swarm-brain, `functions/v1/swarm-setup`):
# публичный GET отдаёт этот скрипт, токен приезжает ОКРУЖЕНИЕМ, а не в
# аргументах — в `argv` его видно через `ps`, в окружении чужого процесса на
# маке нет. Скрипт в репозитории лежит отдельным файлом ровно по той же
# причине, что и у них: его можно проверить `bash -n` и прогнать тестами
# слияния конфига, чего нельзя сделать со строкой внутри сообщения.
#
# Что делает: кладёт мост stdio↔HTTP и прописывает сервер там, где найдёт
# клиента, — Claude Code и Claude Desktop настраиваются РАЗНЫМИ способами, и
# угадывать не нужно: скрипт видит машину, а бот не видит.
#
# ИМЕНА ПЕРЕМЕННЫХ ЗДЕСЬ ТОЛЬКО ЛАТИНИЦЕЙ, в отличие от остального кода
# продукта. Bash допускает в именах лишь [A-Za-z0-9_]: строка `ТОКЕН="$1"`
# для него не присваивание, а попытка запустить команду с таким именем, и
# падает она уже у человека — `command not found`. `bash -n` этого не видит,
# синтаксис-то верный. Поймано живым прогоном 15.09.2026, после того как
# проверка `bash -n` дала зелёный свет на неработающем скрипте.
#
# Плейсхолдер `@BRIDGE@` подставляет сервер при раздаче
# (`src/mcp/install.py`) — тело моста берётся единственным источником из
# `tools/mcp_bridge.sh`. Адрес и токен приезжают окружением из строки бота.
set -eu

TOKEN="${DODO_MCP_TOKEN:?не задан DODO_MCP_TOKEN — возьмите команду в боте, пункт «Установка MCP»}"
URL="${DODO_MCP_URL:?не задан DODO_MCP_URL — возьмите команду в боте целиком}"
NAME="dodo-audit"
BRIDGE="$HOME/.dodo-audit/bin/mcp_bridge.sh"
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

mkdir -p "$(dirname "$BRIDGE")"
cat > "$BRIDGE" <<'DODO_BRIDGE_EOF'
@BRIDGE@
DODO_BRIDGE_EOF
chmod 700 "$BRIDGE"

installed=0

# --- Claude Code: прямой HTTP, мост ему не нужен -----------------------------
#
# Проверено живым подключением 15.09.2026: клиент ходит к нашему серверу по
# HTTP сам. Прежняя запись снимается перед добавлением — иначе `add` отказывает
# на уже существующем имени, и повторный запуск установщика (а он задуман
# повторяемым, как у соседей) не обновлял бы токен.
if command -v claude >/dev/null 2>&1; then
  claude mcp remove "$NAME" --scope user >/dev/null 2>&1 || true
  if claude mcp add --transport http "$NAME" "$URL" \
      --header "Authorization: Bearer $TOKEN" --scope user >/dev/null 2>&1; then
    echo "Claude Code: сервер $NAME прописан"
    installed=1
  else
    echo "Claude Code: не удалось прописать сервер — скажите об этом в боте" >&2
  fi
fi

# --- Claude Desktop: только мост ---------------------------------------------
#
# Приложение удалённый сервер по HTTP НЕ понимает. Больше того, соседний
# продукт поймал на этом живой отказ: поле `"type":"http"` в его файле настроек
# заставляет Claude Desktop молча стереть весь блок `mcpServers` целиком
# (anthropics/claude-code#37286). Поэтому здесь — только форма `command`+`args`
# с мостом, и никогда `url`.
#
# Правится КОПИЯ файла, и только удавшаяся копия переименовывается на место:
# у человека в этом файле свои серверы, и обрыв посреди записи оставил бы
# обрезанный JSON, то есть сломал бы их все разом. Неразбираемый файл `plutil`
# не трогает вовсе и возвращает отказ — падать, а не чинить.
if [ -d "$HOME/Library/Application Support/Claude" ]; then
  TMP="$CFG.dodo-tmp"
  trap 'rm -f "$TMP"' EXIT
  if [ -f "$CFG" ]; then cp "$CFG" "$TMP"; else printf '{"mcpServers":{}}' > "$TMP"; fi
  plutil -extract mcpServers json -o /dev/null "$TMP" 2>/dev/null \
    || plutil -insert mcpServers -json '{}' "$TMP"
  ENTRY="{\"command\":\"/bin/bash\",\"args\":[\"$BRIDGE\"],\"env\":{\"DODO_MCP_URL\":\"$URL\",\"DODO_MCP_TOKEN\":\"$TOKEN\"}}"
  if plutil -replace "mcpServers.$NAME" -json "$ENTRY" "$TMP" \
     && plutil -convert json -r -o "$TMP" "$TMP"; then
    mv "$TMP" "$CFG"
    echo "Claude Desktop: сервер $NAME прописан — перезапустите приложение (Cmd+Q и открыть заново)"
    installed=1
  else
    echo "Claude Desktop: файл настроек не разобран, он оставлен как был" >&2
  fi
fi

if [ "$installed" = "0" ]; then
  echo "Ни Claude Code, ни Claude Desktop на этой машине не найдены — ставить некуда" >&2
  exit 1
fi
