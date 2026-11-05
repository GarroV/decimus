#!/bin/bash
# Установщик decimus для настольного ChatGPT на Mac (D695, #1439).
#
# Форма — как у соседа (swarm-brain, `chatgpt-setup-script.ts`), проверенная там вживую:
# настольный ChatGPT читает MCP-серверы из `~/.codex/config.toml` (встроенный Codex)
# и показывает их ТОЛЬКО во вкладке Work; ручное «Plugins → Add MCP server» вход
# OAuth не запускает. Поэтому серверу нужен мост stdio↔HTTP с личным токеном, а
# регистрирует его штатный `codex mcp add` из самого приложения ChatGPT.
#
# Запускается одной строкой из «Настроек» → «Нейросети» → ChatGPT: скачать
# `https://<адрес>/setup/chatgpt`, сверить SHA-256 и запустить с токеном в окружении
# (в аргументах токен виден через `ps`, в окружении чужого процесса — нет).
#
# Не зависит от установки Claude: свой каталог `~/.decimus/chatgpt` со своей копией
# моста, файлом токена (права 600) и `launch.sh`. Токена нет ни в аргументах Codex,
# ни в его `config.toml`. Тело моста — тот же `tools/mcp_bridge.sh`, подставляется
# сервером при раздаче на место `@BRIDGE@` (`src/mcp/install.py`).
#
# Порядок: найти Codex → проверить токен у сервера → только потом писать на диск.
# Токен не принят — ни один файл не тронут. `config.toml` перед правкой копируется.
#
# ИМЕНА ПЕРЕМЕННЫХ — ТОЛЬКО ЛАТИНИЦЕЙ (bash не принимает других; см. `mcp_install.sh`).
# DECIMUS_CODEX_CLI — путь к `codex` вручную: для нестандартной установки и для
# тестов, которым нельзя трогать настоящий ChatGPT на машине.
set -eu
umask 077

say() { printf '%s\n' "$*"; }
die() { say "$*" >&2; exit 1; }

TOKEN="${DECIMUS_MCP_TOKEN:-}"
URL="${DECIMUS_MCP_URL:-}"
[ -n "$TOKEN" ] || die 'Нет токена: возьмите команду в decimus — «Настройки» → «Нейросети» → ChatGPT. / Missing token: get the command in decimus — Settings → AI assistants → ChatGPT.'
[ -n "$URL" ] || die 'Нет адреса сервера: возьмите команду в decimus целиком. / Missing server address: copy the whole command from decimus.'
case "$TOKEN" in *[!A-Za-z0-9_-]*) die 'Неверный формат токена. / Invalid token format.' ;; esac
case "$URL" in http://*|https://*) ;; *) die 'Адрес сервера должен начинаться с http:// или https://. / The server address must start with http:// or https://.' ;; esac
case "$URL" in *[[:space:]\"\'\\\`\$]*) die 'Неверный адрес сервера. / Invalid server address.' ;; esac

# --- Где Codex: внутри приложения ChatGPT, иначе в PATH ----------------------------
CLI="${DECIMUS_CODEX_CLI:-}"
if [ -z "$CLI" ]; then
  for app in /Applications/ChatGPT.app "$HOME/Applications/ChatGPT.app"; do
    candidate="$app/Contents/Resources/codex-cli/bin/codex"
    if [ -x "$candidate" ]; then CLI="$candidate"; break; fi
  done
fi
if [ -z "$CLI" ]; then CLI="$(command -v codex || true)"; fi
[ -n "$CLI" ] || die 'Сначала установите или обновите настольное приложение ChatGPT. / Install or update the ChatGPT desktop app first.'
"$CLI" mcp list --json >/dev/null 2>&1 || die 'Не удалось прочитать настройки MCP в ChatGPT; файлы не изменены. / Could not read the MCP settings in ChatGPT; no files were changed.'

# --- Токен проверяется ДО записи -----------------------------------------------------
# Заголовок идёт конфигом curl со стандартного ввода: ни в argv, ни на диск.
CODE="$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl --config - -sS --max-time 20 \
  -o /dev/null -w '%{http_code}' -X POST "$URL" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"decimus-chatgpt-setup","version":"1"}}}' 2>/dev/null)" \
  || die 'Нет связи с сервером decimus; файлы не изменены. / The decimus server is unreachable; no files were changed.'
case "$CODE" in
  200) ;;
  401) die 'Сервер не принял токен. Получите новую команду в «Настройках». / The server rejected the token. Get a new command in Settings.' ;;
  429) die 'Слишком много попыток, повторите через минуту. / Too many attempts, retry in a minute.' ;;
  *) die "Сервер ответил кодом $CODE; файлы не изменены. / The server answered with code $CODE; no files were changed." ;;
esac

# --- Каталог: своя копия моста, токен, адрес и запуск -------------------------------
ROOT="$HOME/.decimus/chatgpt"
mkdir -p "$ROOT"
chmod 700 "$ROOT"
TMP="$(mktemp "$ROOT/.bridge.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'DECIMUS_BRIDGE_EOF'
@BRIDGE@
DECIMUS_BRIDGE_EOF
bash -n "$TMP" || die 'Мост не разобрался; установка остановлена. / The bridge did not parse; installation stopped.'
chmod 700 "$TMP"
mv -f "$TMP" "$ROOT/mcp_bridge.sh"
printf '%s' "$TOKEN" > "$ROOT/token"
printf '%s' "$URL" > "$ROOT/url"
chmod 600 "$ROOT/token" "$ROOT/url"
cat > "$ROOT/launch.sh" <<'DECIMUS_LAUNCH_EOF'
#!/bin/bash
set -e
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export DECIMUS_MCP_URL="$(cat "$ROOT/url")"
export DECIMUS_MCP_TOKEN="$(cat "$ROOT/token")"
exec /bin/bash "$ROOT/mcp_bridge.sh"
DECIMUS_LAUNCH_EOF
chmod 700 "$ROOT/launch.sh"

# --- Регистрация штатной командой Codex; прежний config.toml — в копию ---------------
CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
if [ -f "$CONFIG_DIR/config.toml" ]; then
  BACKUP="$(mktemp "$CONFIG_DIR/config.toml.decimus-backup.XXXXXX")"
  cat "$CONFIG_DIR/config.toml" > "$BACKUP"
  say "Копия настроек: $BACKUP / Settings backup: $BACKUP"
fi
# Запись с этим именем могла остаться от прежнего способа (по адресу, без моста): без
# снятия `add` отказал бы, а повторный запуск должен обновлять токен.
"$CLI" mcp remove decimus >/dev/null 2>&1 || true
"$CLI" mcp add decimus -- /bin/bash "$ROOT/launch.sh" >/dev/null \
  || die 'Не удалось зарегистрировать decimus в ChatGPT; настройки можно вернуть из копии. / Could not register decimus in ChatGPT; the settings can be restored from the backup.'
"$CLI" mcp get decimus >/dev/null \
  || die 'decimus записан, но ChatGPT его не видит. / decimus was written but ChatGPT does not see it.'

say 'Готово: decimus подключён к настольному ChatGPT. / Done: decimus is connected to the ChatGPT desktop app.'
say 'Полностью закройте ChatGPT (⌘Q) и откройте снова. Сервер виден во вкладке Work, в Chat его нет. Проверьте просьбой «кто я в decimus». / Quit ChatGPT (⌘Q) and reopen it. The server shows in the Work tab, not in Chat. Check by asking "who am I in decimus".'
