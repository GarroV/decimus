#!/bin/bash
# Мост stdio ↔ HTTP для MCP-сервера проверок (T095).
#
# Claude говорит с MCP построчным JSON по stdio, наш сервер — по HTTP
# JSON-RPC. Мосту достаточно переложить строку в POST и вернуть ответ: bash и
# curl есть на любой машине, и это ровно тот же приём, которым уже работает
# swarm-mcp (D055) — своей зависимости и своего Node ради одного перекладывания
# строк не заводится.
#
# Как подключить (Claude Code, разово):
#   claude mcp add decimus -- /путь/к/репозиторию/tools/mcp_bridge.sh
# Переменные берутся из окружения запускающего:
#   DECIMUS_MCP_URL   — адрес поднятого сервера, например http://127.0.0.1:8265/
#   DECIMUS_MCP_TOKEN — ваш токен доступа. Их бывает два вида, и мосту всё
#                    равно какой: личный, выпущенный в вебе («Настройки» →
#                    «Claude (MCP)» даёт готовую строку с ним внутри, T253,
#                    D626), либо токен стороны из карты MCP_TOKENS в .env
#
# Прежние имена DODO_MCP_URL / DODO_MCP_TOKEN работают как запасные: у людей
# мост уже прописан с ними в настройках Claude Desktop (переименование 20.10.2026).
#
# Токен в этот файл не вписывается никогда: файл лежит в публичном
# репозитории, значения живут только в .env и в окружении (конституция).
#
# И в аргументы curl он тоже не попадает. Аргументы процесса видны на машине
# всем через `ps` — а площадка общая, рядом живут чужие проекты. Мост
# перезапускает curl на КАЖДУЮ строку от Claude, то есть окно, в котором токен
# виден в списке процессов, повторялось бы десятки раз за сессию. Поэтому
# заголовок уходит файлом конфигурации curl с правами только для владельца.
# Найдено разбором безопасности 03.09 живым запуском: `ps -eo command` печатал
# «Authorization: Bearer <токен>» открытым текстом.
set -u
URL="${DECIMUS_MCP_URL:-${DODO_MCP_URL:-}}"
TOKEN="${DECIMUS_MCP_TOKEN:-${DODO_MCP_TOKEN:-}}"
: "${URL:?не задан DECIMUS_MCP_URL — адрес поднятого MCP-сервера}"
: "${TOKEN:?не задан DECIMUS_MCP_TOKEN — личный токен доступа}"

# Заголовок с секретом — в файл, а не в argv. `mktemp` создаёт файл с правами
# 600 по умолчанию, но проверять это на слово нельзя: ставим явно.
AUTH_FILE="$(mktemp "${TMPDIR:-/tmp}/mcp-auth.XXXXXX")"
chmod 600 "$AUTH_FILE"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/mcp-work.XXXXXX")"
trap 'rm -f "$AUTH_FILE"; rm -rf "$WORK"' EXIT HUP INT TERM
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > "$AUTH_FILE"


# --- Локальные инструменты (D583) ----------------------------------------------
#
# Модель не может передать байты фото аргументом инструмента, а мост работает на
# машине человека и файлы читать может. Поэтому два инструмента выполняет САМ мост
# и на сервер они не уходят: `local_photo_folder` (показать модели снимки из папки)
# и `local_attach_photos` (отправить оригиналы к записям черновика). Нужны штатные
# macOS-утилиты: jq, sips, base64, curl. Нет jq — локальные инструменты не
# объявляются, всё остальное работает как раньше.
#
# bash здесь 3.2 (macOS): без mapfile, без ассоциативных массивов, пустой массив
# под `set -u` раскрывается только через `${a[@]+"${a[@]}"}`.
JQ=""
# DECIMUS_MCP_JQ=none выключает локальные инструменты (так проверяется машина без jq).
if [ "${DECIMUS_MCP_JQ:-}" = "none" ]; then :
elif [ -x /usr/bin/jq ]; then JQ=/usr/bin/jq
elif command -v jq >/dev/null 2>&1; then JQ="$(command -v jq)"; fi
[ -n "$JQ" ] || printf 'mcp_bridge: нет jq — локальные инструменты для фото отключены\n' >&2

HOME_REAL="$(cd "$HOME" 2>/dev/null && pwd -P)"
# Без настоящей домашней папки граница чтения теряет смысл (HOME пуст или «/»):
# тогда локальные инструменты выключаются, а не читают весь диск.
if [ -z "$HOME_REAL" ] || [ "$HOME_REAL" = "/" ]; then
  JQ=""
  printf 'mcp_bridge: нет домашней папки — локальные инструменты для фото отключены\n' >&2
fi
MAX_LIST=60              # снимков за один вызов local_photo_folder
DEFAULT_LIST=20
THUMB_MAX=768            # длинная сторона уменьшенной копии, px
THUMB_QUALITY=70
BATCH_BYTES=$((20 * 1024 * 1024))  # предел тела одного запроса на сервере — 25 МБ

LOCAL_TOOLS='[
 {"name":"local_photo_folder",
  "description":"Look at the photos in a folder on the person'"'"'s own computer (this tool runs on their machine). Give the folder as the person said it: an absolute path, a path relative to the home folder, or just Downloads. Only JPEG, PNG, HEIC and WebP files directly in the folder are read (no subfolders), only inside the home folder. The answer lists the file names in order and shows each photo as a reduced copy, so you can see them and assign them to findings. Large folders come in pages: use offset and limit, the answer says where the next page starts.",
  "inputSchema":{"type":"object","properties":{
    "path":{"type":"string","description":"Folder with photos, e.g. Downloads/audit or /Users/name/Pictures/trip"},
    "offset":{"type":"integer","minimum":0,"description":"How many photos to skip (default 0)"},
    "limit":{"type":"integer","minimum":1,"maximum":60,"description":"How many photos to show (default 20)"}},
   "required":["path"],"additionalProperties":false}},
 {"name":"local_attach_photos",
  "description":"Attach photos from a folder on the person'"'"'s own computer (this tool runs on their machine) to the findings of ONE imported draft. Use the file names shown by local_photo_folder. The originals are sent, not the reduced copies. Findings must be recorded first and the draft not yet accepted. The answer says how many photos were attached to which finding and what was refused and why. Never mention addresses or links to the person. To swap reduced copies for the originals pass replace=true: for each finding the previous photos are removed ONLY if all its new photos were stored (the answer says replaced true or false per finding; on false nothing changed); give all photos of a finding together, at most 10 per finding.",
  "inputSchema":{"type":"object","properties":{
    "inspection_id":{"type":"string","description":"The imported draft"},
    "replace":{"type":"boolean","description":"true: the photos replace the frames the listed findings already have (all-or-nothing per finding). Default: they are added."},
    "folder":{"type":"string","description":"The same folder that was given to local_photo_folder"},
    "items":{"type":"array","minItems":1,"items":{"type":"object","properties":{
      "n":{"type":"integer","minimum":1,"maximum":999,"description":"Finding number in the draft"},
      "files":{"type":"array","minItems":1,"items":{"type":"string","description":"File name from the folder, no path"}}},
     "required":["n","files"],"additionalProperties":false}}},
   "required":["inspection_id","folder","items"],"additionalProperties":false}}
]'

# Обмен с сервером. $1 — тело запроса. Результат в HTTP_CODE и HTTP_BODY (код отдельно:
# без него 404 от чужого сервера, 401 и обрыв связи выглядят одинаково — пустым ответом,
# на который клиент ждёт минуту и пишет «Request timed out», ни словом не называя
# причину, #535: так полдня искали устаревший адрес в конфиге).
REPLACE=""
HTTP_CODE=""; HTTP_BODY=""
post_server() {
  local out
  out="$(printf '%s' "$1" | curl -sS --max-time 120 -X POST "$URL" \
      -H "Content-Type: application/json" \
      --config "$AUTH_FILE" \
      --data-binary @- -w '\n%{http_code}' 2>&1)"
  HTTP_CODE="${out##*$'\n'}"
  HTTP_BODY="${out%$'\n'*}"
}

# Ответ инструмента одним блоком текста. $1 — id запроса (JSON), $2 — текст, $3 — 1 если отказ.
reply_text() {
  "$JQ" -nc --argjson id "$1" --arg t "$2" --argjson e "${3:-0}" \
    '{jsonrpc:"2.0",id:$id,result:({content:[{type:"text",text:$t}]}
      + (if $e == 1 then {isError:true} else {} end))}'
}

# Имя файла годится, если в нём нет пути, управляющих знаков, кавычек и обратной косой.
safe_name() {
  case "$1" in
    ''|*/*|.*|*'"'*|*'\'*|*$'\n'*|*$'\r'*|*$'\t'*) return 1 ;;
  esac
  return 0
}

is_image_name() {
  case "$1" in
    *.[jJ][pP][gG]|*.[jJ][pP][eE][gG]|*.[pP][nN][gG]|*.[hH][eE][iI][cC]|*.[hH][eE][iI][fF]|*.[wW][eE][bB][pP]) return 0 ;;
  esac
  return 1
}

# Папка из слов человека → физический путь внутри $HOME (в DIR) или причина отказа (в WHY,
# возврат 1). «Загрузки»/Downloads → ~/Downloads; относительный путь — от ~.
DIR=""; WHY=""
resolve_dir() {
  local p="$1" first rest dir
  WHY=""
  p="${p#"${p%%[![:space:]]*}"}"; p="${p%"${p##*[![:space:]]}"}"
  [ -n "$p" ] || { WHY="folder is empty"; return 1; }
  case "/$p/" in */../*|*/./*) WHY="the folder path must not contain . or .. parts"; return 1 ;; esac
  case "$p" in
    "~") p="$HOME" ;;
    "~/"*) p="$HOME/${p#"~/"}" ;;
    /*) ;;
    *) first="${p%%/*}"; rest=""
       [ "$first" != "$p" ] && rest="/${p#*/}"
       case "$first" in
         Загрузки|загрузки|ЗАГРУЗКИ|Downloads|downloads|DOWNLOADS) first="Downloads" ;;
       esac
       p="$HOME/$first$rest" ;;
  esac
  case "$p" in
    "$HOME/Загрузки"|"$HOME/Загрузки/"*) p="$HOME/Downloads${p#"$HOME/Загрузки"}" ;;
    "$HOME/загрузки"|"$HOME/загрузки/"*) p="$HOME/Downloads${p#"$HOME/загрузки"}" ;;
  esac
  [ -d "$p" ] || { WHY="folder not found in the home folder of the person"; return 1; }
  dir="$(cd "$p" 2>/dev/null && pwd -P)" || { WHY="folder cannot be opened"; return 1; }
  case "$dir/" in
    "$HOME_REAL"/*) ;;
    *) WHY="only folders inside the home folder can be read"; return 1 ;;
  esac
  case "${dir#"$HOME_REAL"}/" in */.*) WHY="hidden folders are not read"; return 1 ;; esac
  DIR="$dir"
  return 0
}

# Имена снимков папки (без подпапок, без скрытых, без символических ссылок) по одному в строке.
list_images() {
  local f name
  for f in "$1"/*; do
    if [ -f "$f" ] && [ ! -L "$f" ]; then
      name="${f##*/}"
      if safe_name "$name" && is_image_name "$name"; then printf '%s\n' "$name"; fi
    fi
  done
}

# Уменьшенная копия: JPEG, длинная сторона до THUMB_MAX. $1 — исходник, $2 — куда.
make_thumb() {
  local src="$1" out="$2" w h
  local -a resize=()
  w="$(sips -g pixelWidth "$src" 2>/dev/null </dev/null | awk '/pixelWidth/{print $2}')"
  h="$(sips -g pixelHeight "$src" 2>/dev/null </dev/null | awk '/pixelHeight/{print $2}')"
  case "$w$h" in ''|*[!0-9]*) return 1 ;; esac
  if [ "$w" -gt "$THUMB_MAX" ] || [ "$h" -gt "$THUMB_MAX" ]; then resize=(-Z "$THUMB_MAX"); fi
  sips -s format jpeg -s formatOptions "$THUMB_QUALITY" ${resize[@]+"${resize[@]}"} \
    "$src" --out "$out" >/dev/null 2>&1 </dev/null && [ -s "$out" ]
}

tool_photo_folder() {
  local id="$1" args="$2" path offset limit total i end name next
  local -a all=()
  command -v sips >/dev/null 2>&1 || { reply_text "$id" "This computer has no sips tool, so photos cannot be shown from here" 1; return; }
  path="$(printf '%s' "$args" | "$JQ" -r '.path // ""')"
  offset="$(printf '%s' "$args" | "$JQ" -r '(.offset // 0) | floor')"
  limit="$(printf '%s' "$args" | "$JQ" -r "(.limit // $DEFAULT_LIST) | floor")"
  case "$offset$limit" in ''|*[!0-9]*) reply_text "$id" "offset and limit must be whole numbers" 1; return ;; esac
  [ "$limit" -ge 1 ] || limit=$DEFAULT_LIST
  [ "$limit" -le "$MAX_LIST" ] || limit=$MAX_LIST
  resolve_dir "$path" || { reply_text "$id" "$WHY" 1; return; }
  while IFS= read -r name; do all+=("$name"); done < <(list_images "$DIR")
  total=${#all[@]}
  if [ "$total" -eq 0 ]; then
    reply_text "$id" "No photos (JPEG, PNG, HEIC, WebP) directly in this folder" 1; return
  fi
  if [ "$offset" -ge "$total" ]; then
    reply_text "$id" "offset is past the end: the folder has $total photos" 1; return
  fi
  end=$((offset + limit)); [ "$end" -le "$total" ] || end=$total
  : > "$WORK/items.ndjson"
  for ((i = offset; i < end; i++)); do
    name="${all[$i]}"
    if make_thumb "$DIR/$name" "$WORK/thumb.jpg"; then
      "$JQ" -nc --arg t "$((i + 1)). $name" '{type:"text",text:$t}' >> "$WORK/items.ndjson"
      base64 < "$WORK/thumb.jpg" | tr -d '\n' > "$WORK/thumb.b64"
      "$JQ" -nc --rawfile d "$WORK/thumb.b64" '{type:"image",data:$d,mimeType:"image/jpeg"}' >> "$WORK/items.ndjson"
    else
      "$JQ" -nc --arg t "$((i + 1)). $name (cannot be read as an image)" '{type:"text",text:$t}' >> "$WORK/items.ndjson"
    fi
    rm -f "$WORK/thumb.jpg" "$WORK/thumb.b64"
  done
  next="none, this was the last page"; [ "$end" -lt "$total" ] && next="offset $end"
  "$JQ" -nc --arg t "Photos in the folder: $total. Shown: $((offset + 1))-$end (reduced copies; the file name is given before each photo). Next page: $next. Use these file names in local_attach_photos." \
    '{type:"text",text:$t}' > "$WORK/head.json"
  "$JQ" -sc --argjson id "$id" '{jsonrpc:"2.0",id:$id,result:{content:.}}' "$WORK/head.json" "$WORK/items.ndjson"
}

# Одна отправка пачки файлов к находке. $1 — адрес загрузки, $2 — номер находки, остальное —
# пути файлов. Итог дописывается в $WORK/results.ndjson. Адрес — в файл конфигурации curl, а не
# в argv: он подписан и работает как пропуск.
send_batch() {
  local target="$1" n="$2" code body f why
  shift 2
  local -a form=() names=()
  [ "${REPLACE:-}" = "1" ] && form+=(-F "replace=1")
  for f in "$@"; do form+=(-F "file=@\"$f\""); names+=("${f##*/}"); done
  printf 'url = "%s"\n' "$target" > "$WORK/upload.cfg"; chmod 600 "$WORK/upload.cfg"
  body="$(curl -sS --max-time 300 --config "$WORK/upload.cfg" -F "n=$n" "${form[@]}" \
      -w '\n%{http_code}' </dev/null 2>&1)"
  rm -f "$WORK/upload.cfg"
  code="${body##*$'\n'}"; body="${body%$'\n'*}"
  if printf '%s' "$body" | "$JQ" -e '.attached' >/dev/null 2>&1; then
    printf '%s' "$body" | "$JQ" -c --argjson n "$n" \
      '{n:$n,attached:[.attached[].file],refused:[.refused[]|{file,reason}]}
       + (if has("replaced") then {replaced:.replaced} else {} end)' >> "$WORK/results.ndjson"
    return
  fi
  case "$code" in
    403) why="the upload permission was not accepted" ;;
    410) why="the draft is already accepted, photos can no longer be attached" ;;
    429) why="too many requests, try again in a minute" ;;
    413) why="the photos are larger than the limit" ;;
    000) why="no connection to the service" ;;
    *) why="the service answered with an error ($code)" ;;
  esac
  printf '%s\n' "${names[@]}" | "$JQ" -Rsc --argjson n "$n" --arg w "$why" \
    '{n:$n,attached:[],refused:(split("\n")|map(select(length>0))|map({file:.,reason:$w}))}' >> "$WORK/results.ndjson"
}

tool_attach_photos() {
  local id="$1" args="$2" ident folder text target name size total rec rec_n bad overflow
  local -a files=() paths=()
  ident="$(printf '%s' "$args" | "$JQ" -r '.inspection_id // ""')"
  folder="$(printf '%s' "$args" | "$JQ" -r '.folder // ""')"
  case "$ident" in ''|*[!A-Za-z0-9_.:-]*) reply_text "$id" "inspection_id is missing or malformed" 1; return ;; esac
  if ! printf '%s' "$args" | "$JQ" -e '(.items|type=="array") and (.items|length>0)
      and all(.items[]; (.n|type=="number") and (.n==(.n|floor)) and .n>=1 and .n<=999
        and (.files|type=="array") and (.files|length>0) and all(.files[]; type=="string"))
      and ((.replace // false)|type=="boolean")' >/dev/null 2>&1; then
    reply_text "$id" "items must be a list of {n: finding number 1..999, files: [file names]}; replace, if given, true or false" 1; return
  fi
  # Режим замены: прежние кадры записи снимает сервер, только если легли все новые.
  REPLACE="$(printf '%s' "$args" | "$JQ" -r 'if .replace == true then "1" else "" end')"
  resolve_dir "$folder" || { reply_text "$id" "$WHY" 1; return; }
  # Адрес загрузки выдаёт сам сервер: мост просит его тем же запросом, что и модель.
  post_server "$("$JQ" -nc --arg i "$ident" \
    '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:"import_upload_photos",arguments:{inspection_id:$i}}}')"
  case "$HTTP_CODE" in
    2??) ;;
    *) reply_text "$id" "The service could not be reached to prepare the upload (HTTP $HTTP_CODE)" 1; return ;;
  esac
  text="$(printf '%s' "$HTTP_BODY" | "$JQ" -r '.result.content[0].text // .error.message // ""' 2>/dev/null)"
  if [ "$(printf '%s' "$HTTP_BODY" | "$JQ" -r '.result.isError // false' 2>/dev/null)" = "true" ] \
     || [ -z "$text" ]; then
    reply_text "$id" "${text:-upload is not available}" 1; return
  fi
  target="$(printf '%s' "$text" | "$JQ" -r '.upload_target // empty' 2>/dev/null)"
  [ -n "$target" ] || { reply_text "$id" "The service did not prepare an upload; photos can be skipped for now" 1; return; }
  : > "$WORK/results.ndjson"
  # Записи с одним номером сливаются: один запрос на находку (на сервере 30 запросов в минуту).
  while IFS= read -r rec; do
    rec_n="$(printf '%s' "$rec" | "$JQ" -r '.n')"
    files=(); paths=(); size=0; bad=0; overflow=0
    while IFS= read -r name; do files+=("$name"); done < <(printf '%s' "$rec" | "$JQ" -r '.files[]')
    for name in ${files[@]+"${files[@]}"}; do
      if ! safe_name "$name" || ! is_image_name "$name" || [ ! -f "$DIR/$name" ] || [ -L "$DIR/$name" ]; then
        bad=1
        [ "$REPLACE" = "1" ] && continue
        printf '%s' "$name" | "$JQ" -Rsc --argjson n "$rec_n" \
          '{n:$n,attached:[],refused:[{file:.,reason:"not an image file of the chosen folder"}]}' >> "$WORK/results.ndjson"
        continue
      fi
      total="$(wc -c < "$DIR/$name" | tr -d ' ')"
      if [ "${#paths[@]}" -gt 0 ] && [ $((size + total)) -gt "$BATCH_BYTES" ]; then
        # Замена ложится одним запросом: два запроса снесли бы кадры первого вторым.
        if [ "$REPLACE" = "1" ]; then overflow=1; break; fi
        send_batch "$target" "$rec_n" "${paths[@]}"; paths=(); size=0
      fi
      paths+=("$DIR/$name"); size=$((size + total))
    done
    if [ "$REPLACE" = "1" ] && { [ "$bad" = "1" ] || [ "$overflow" = "1" ]; }; then
      printf '%s\n' "${files[@]}" | "$JQ" -Rsc --argjson n "$rec_n" \
        '{n:$n,attached:[],replaced:false,refused:(split("\n")|map(select(length>0))|map({file:.,reason:"replace needs every photo of the finding to be an image file of the folder and to go in one upload (20 MB at most); nothing was changed"}))}' >> "$WORK/results.ndjson"
      continue
    fi
    if [ "${#paths[@]}" -gt 0 ]; then send_batch "$target" "$rec_n" "${paths[@]}"; fi
  done < <(printf '%s' "$args" | "$JQ" -c '.items | group_by(.n) | map({n:.[0].n, files:(map(.files)|add)}) | .[]')
  text="$("$JQ" -sc --arg i "$ident" '
    (group_by(.n) | map({n:.[0].n, attached:(map(.attached)|add), refused:(map(.refused)|add)}
        + (map(select(has("replaced")) | .replaced) | if length == 0 then {} else {replaced: all} end))) as $r
    | {inspection_id:$i, attached_total:($r|map(.attached|length)|add // 0),
       refused_total:($r|map(.refused|length)|add // 0), findings:$r}' "$WORK/results.ndjson")"
  reply_text "$id" "$text" 0
}

while IFS= read -r line; do
  [ -n "$line" ] || continue
  # Уведомление (нет "id") ответа не требует — по JSON-RPC отвечать на него
  # нельзя, ответ выбивает клиента.
  case "$line" in
    *'"id"'*) want_reply=1 ;;
    *) want_reply=0 ;;
  esac
  # Локальные инструменты: вызов с их именем обрабатывает мост, на сервер он не идёт.
  method=""
  if [ -n "$JQ" ]; then
    case "$line" in
      *'"tools/'*) method="$(printf '%s' "$line" | "$JQ" -r '.method // empty' 2>/dev/null)" ;;
    esac
  fi
  if [ "$method" = "tools/call" ] && [ "$want_reply" = "1" ]; then
    tool="$(printf '%s' "$line" | "$JQ" -r '.params.name // empty' 2>/dev/null)"
    case "$tool" in
      local_photo_folder|local_attach_photos)
        req_id="$(printf '%s' "$line" | "$JQ" -c '.id')"
        req_args="$(printf '%s' "$line" | "$JQ" -c '.params.arguments // {}')"
        if [ "$tool" = "local_photo_folder" ]; then
          tool_photo_folder "$req_id" "$req_args" </dev/null
        else
          tool_attach_photos "$req_id" "$req_args" </dev/null
        fi
        continue
        ;;
    esac
  fi
  post_server "$line"
  code="$HTTP_CODE"
  resp="$HTTP_BODY"
  case "$code" in
    2??) ok=1 ;;
    *) ok=0 ;;
  esac
  if [ "$ok" = "1" ]; then
    if [ "$want_reply" = "1" ] && [ -n "$resp" ]; then
      # К списку инструментов сервера дописываются локальные.
      if [ "$method" = "tools/list" ]; then
        resp="$(printf '%s' "$resp" | "$JQ" -c --argjson extra "$LOCAL_TOOLS" \
            'if (.result.tools | type) == "array" then .result.tools += $extra else . end' 2>/dev/null)" \
          || resp="$HTTP_BODY"
      fi
      printf '%s\n' "$resp"
    fi
    continue
  fi
  # Отказ — в stderr (Claude пишет его в лог сервера) и, если запрос ждёт
  # ответа, ошибкой JSON-RPC с тем же id: клиент показывает её сразу.
  reason="HTTP $code от $URL: $(printf '%s' "$resp" | tr -d '\r\n"\\' | cut -c1-200 | iconv -c -f UTF-8 -t UTF-8)"
  [ "$code" = "000" ] && reason="нет связи с $URL: $(printf '%s' "$resp" | tr -d '\r\n"\\' | cut -c1-200 | iconv -c -f UTF-8 -t UTF-8)"
  printf 'mcp_bridge: %s\n' "$reason" >&2
  if [ "$want_reply" = "1" ] && [[ "$line" =~ \"id\"[[:space:]]*:[[:space:]]*(\"[^\"]*\"|-?[0-9]+) ]]; then
    printf '{"jsonrpc":"2.0","id":%s,"error":{"code":-32000,"message":"%s"}}\n' \
      "${BASH_REMATCH[1]}" "$reason"
  fi
done
