#!/usr/bin/env bash
# Выкладка фронта на Cloudflare Workers (D431): собирает рабочий конфиг из
# шаблона и локальных значений и вызывает `wrangler deploy`.
#   ./deploy.sh admin|mcp|stand [--dry-run]
# Значения — в неотслеживаемом front/.deploy.env (образец: .deploy.env.example).
set -euo pipefail
cd "$(dirname "$0")"

target="${1:-}"
case "$target" in
  admin | mcp | stand | demo) shift ;;
  *) echo "usage: $0 admin|mcp|stand|demo [wrangler deploy args]" >&2; exit 2 ;;
esac

[ -f .deploy.env ] || { echo "нет front/.deploy.env — см. .deploy.env.example" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.deploy.env
set +a

host_var="ORIGIN_HOST"
[ "$target" = mcp ] && host_var="MCP_ORIGIN_HOST"
[ "$target" = stand ] && host_var="STAND_ORIGIN_HOST"
[ "$target" = demo ] && host_var="DEMO_ORIGIN_HOST"
for name in VPC_SERVICE_ID "$host_var"; do
  [ -n "${!name:-}" ] || { echo "в .deploy.env не задано $name" >&2; exit 1; }
done

out="wrangler.$target.jsonc"
sed -e "s|<VPC_SERVICE_ID>|$VPC_SERVICE_ID|g" \
    -e "s|<ORIGIN_HOST>|${ORIGIN_HOST:-}|g" \
    -e "s|<MCP_ORIGIN_HOST>|${MCP_ORIGIN_HOST:-}|g" \
    -e "s|<STAND_ORIGIN_HOST>|${STAND_ORIGIN_HOST:-}|g" \
    -e "s|<DEMO_ORIGIN_HOST>|${DEMO_ORIGIN_HOST:-}|g" \
    "wrangler.$target.template.jsonc" > "$out"
if grep -q '<[A-Z_]*>' <(grep -v '^ *//' "$out"); then
  echo "в $out остались незаполненные заглушки" >&2; exit 1
fi
npx wrangler deploy -c "$out" "$@"
