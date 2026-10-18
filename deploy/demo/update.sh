#!/usr/bin/env bash
# Обновить код открытого демо (D524) до main и пересобрать демо с нуля.
set -euo pipefail
cd "$(dirname "$0")/../.."

git pull --ff-only
sha=$(git rev-parse --short HEAD)
BUILD_SHA="$sha" docker compose -p decimus-demo -f docker-compose.yml -f docker-compose.prod.yml \
    -f deploy/demo/compose.demo.yaml --profile migrate --profile seed build
exec deploy/demo/reset.sh
