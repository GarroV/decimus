# Общая сверка для update.sh и reset.sh (#1246): работать можно только в дереве демо.
# Подключается через `source` после `cd` в корень дерева; сам ничего не запускает.
#
# Скрипты берут `.env` из корня того дерева, где лежат. Запущенные из боевого
# (`/srv/decimus/deploy/demo/update.sh`), они собрали бы демо с боевыми паролями,
# ключами хранилища и токеном бота (23.10 и 26.10.2026), а `reset.sh` перед этим
# снёс бы демо-стенд. Пускаем, если дерево — `/srv/decimus-demo` ИЛИ в `.env` методика
# демо (`AUDIT_DATA_DIR` на `demo/data`; у боевого дерева там закрытая методика).
# Значения `.env` не печатаются: `grep -q`.
DEMO_TREE=${DECIMUS_DEMO_TREE:-/srv/decimus-demo}

require_demo_tree() {
    local here
    here=$(pwd -P)
    if [ "$here" = "$DEMO_TREE" ]; then
        return 0
    fi
    if [ -f .env ] && grep -Eq '^AUDIT_DATA_DIR=.*demo/data' .env; then
        return 0
    fi
    echo "отказ: $here — не дерево демо ($DEMO_TREE), и в .env нет AUDIT_DATA_DIR=./demo/data." >&2
    echo "Демо собралось бы с боевым .env. Запускать из $DEMO_TREE." >&2
    exit 1
}
