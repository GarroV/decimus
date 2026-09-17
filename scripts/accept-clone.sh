#!/bin/bash
# Свежий клон main для приёмки: клонирует, подкладывает данные вне git, ставит окружение.
# Пользоваться: bash accept-clone.sh <каталог назначения> [порт БД]
set -e
DST="${1:?нужен каталог назначения}"
PORT="${2:-5480}"
SRC="/Users/garva/Documents/projects/decimus"
rm -rf "$DST"
git clone -q "$SRC" "$DST"
cp -R "$SRC/data" "$DST/data"
cp -R "$SRC/examples" "$DST/examples"
PW="$(openssl rand -hex 12)"; APP_PW="$(openssl rand -hex 12)"; RET_PW="$(openssl rand -hex 12)"
cat > "$DST/.env" <<EOF
# Окружение приёмочного клона. Боевых секретов НЕ содержит.
TELEGRAM_BOT_TOKEN=stub-not-a-real-token
OPENAI_API_KEY=stub-not-a-real-key
AUDIT_DATA_DIR=./data
STATE_DIR=./.state
ALLOWED_TELEGRAM_IDS=
BOT_MODE=polling
TZ=Europe/Belgrade
POSTGRES_DB=dodo_audit_service
POSTGRES_USER=dodo_audit
POSTGRES_PASSWORD=$PW
POSTGRES_PORT=$PORT
DATABASE_ADMIN_URL=postgresql://dodo_audit:$PW@127.0.0.1:$PORT/dodo_audit_service
DATABASE_URL=postgresql://dodo_audit_app:$APP_PW@127.0.0.1:$PORT/dodo_audit_service
DATABASE_APP_PASSWORD=$APP_PW
DATABASE_RETRACTION_URL=postgresql://dodo_audit_retraction:$RET_PW@127.0.0.1:$PORT/dodo_audit_service
DATABASE_RETRACTION_PASSWORD=$RET_PW
EOF
python3 -m venv "$DST/.venv"
(cd "$DST" && ./.venv/bin/pip -q install -e ".[dev]")
echo "клон готов: $DST (порт БД $PORT, стенд поднимать под именем decimus-accept)"
