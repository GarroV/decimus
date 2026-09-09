# Ренейм dodo_audit_service → decimus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переименовать GitHub-репозиторий и локальную папку проекта `dodo_audit_service` → `decimus`, ничего не потеряв и не сломав (git, ~/.claude.json, память Claude Code, ~30 worktree, пакет Python), не трогая массово функции/классы/имена модулей.

**Architecture:** От безопасного к рискованному. Сначала уборка мёртвых worktree (иначе перенос папки сломает их все). Затем GitHub (redirect делает это низкорисковым) → локальная папка → миграция конфигов Claude Code, которые ключуются абсолютным путём (иначе память и настройки проекта осиротеют молча). Затем идентификаторы пакета (`pyproject.toml`, единственный вызов `version()`, тестовые константы имени compose-проекта). Затем обязательная регрессия проекта. Раскатка на боевой MUSPELHEIM и решение по имени боевого docker-compose проекта — вынесены за рамки этого плана как отдельная, явно гейтованная фаза (см. «Отложено» в конце).

**Tech Stack:** git, git worktree, gh CLI, jq, Python (pytest, setuptools), Make

**Spec:** `docs/forge/decisions.md` — D108 (это решение), D106/D107 (исходная рамка ребрендинга DECIMUS), issue #231

## Global Constraints

- Меняются только технические имена верхнего уровня (репозиторий, папка, имя пакета). Функции, классы, имена модулей и переменных НЕ переименовываются массово в этом заходе (D108) — новый код может ориентироваться на новое имя, старый трогать не нужно.
- Docker-compose `name: dodo_audit_service-infra` и `POSTGRES_DB` НЕ трогаются в этом плане: тома `state`/`demo-state`/`pgdata` не имеют явного `name:` в `docker-compose.yml`, и смена имени проекта compose на следующем `up` создаст НОВЫЕ пустые тома, осиротив боевые данные молча. Если нужно синхронизировать и это — отдельное решение владельца, не часть текущего.
- Раскатка на MUSPELHEIM выполняется только по явному «да» владельца в этом же разговоре и только 23:00–05:59 (deploy-window). Она НЕ входит в этот прогон плана — см. «Отложено».
- После любого изменения движка/данных обязателен регрессионный чек-лист проекта: `examples/belgrade-1` → 97.5%, A, 5×D1; `examples/belgrade-2` → 97.0%, A, 6×D1 (корневой `CLAUDE.md`, автоматизировано в `make regress`).
- Правило git-безопасности: перед любым `git worktree remove`/`branch -d` проверять `git status --porcelain` (чисто) и содержательную эквивалентность main (`git cherry main <branch>` пусто), а не только `--merged` — так уже один раз ошибочно снесли чужую рабочую копию (`progress.md:488`).
- Секреты и токены нигде не печатать и не логировать при работе с `~/.claude.json` — только ключи и структурные операции (`jq` без вывода значений).

---

## Файлы, которые трогает план

| Файл | Что меняется |
|---|---|
| `pyproject.toml` | `name = "dodo-audit-service"` → `name = "decimus"` |
| `src/mcp/rpc.py:64` | `version("dodo-audit-service")` → `version("decimus")` |
| `tests/test_db_stand.py:51` | `PROJECT = "dodo_audit_service-tests"` → `"decimus-tests"` |
| `tests/test_bot_ui_lang.py:40` | `COMPOSE_PROJECT = "dodo_audit_service-tests"` → `"decimus-tests"` |
| `~/.claude.json` | ключ `projects["/Users/garva/Documents/projects/dodo_audit_service"]` → переносится на новый путь |
| `~/.claude/projects/-Users-garva-Documents-projects-dodo_audit_service/` | память Claude Code — переносится на новый слаг пути |
| GitHub | репозиторий `GarroV/dodo_audit_service` → `GarroV/decimus` |
| ~30 `git worktree` в `~/Documents/workbench/worktrees/dodo_audit_service-*` | удаляются (мёртвые остатки завершённой стройки, см. проверку ниже) |

**Не трогаются в этом плане:** `docker-compose.yml` (`name:`, `POSTGRES_DB`), `scripts/deploy.sh`/`scripts/smoke.sh` (`REMOTE_DIR` default), `docs/08-deploy.md`, `.claude/settings.local.json`, `progress.md`, записи `docs/forge/decisions.md` до D108 — это исторический журнал и боевая площадка, они входят в отложенную фазу.

---

### Task 1: Уборка мёртвых git worktree

Перенос папки сломает связь `.git` у каждого существующего worktree (git worktree хранит абсолютный путь в обе стороны). Проще снести мёртвые сейчас, чем чинить 30 штук после переноса.

**Files:** нет кода — операции над `~/Documents/workbench/worktrees/dodo_audit_service-*`

**Уже проверено при подготовке этого плана** (см. предыдущий шаг разговора): все 30 worktree чисты (`git status --porcelain` пусто) и содержательно не отличаются от main — `git branch --merged main` даёт 1 для 29 из них, а единственный расходящийся (`feat/domain3`) даёт пустой `git cherry main feat/domain3`, то есть все его коммиты патч-эквивалентны уже попавшим в main через другую ветку.

- [ ] **Step 1: Повторно снять список и подтвердить чистоту (страховка на случай, если что-то изменилось между планированием и исполнением)**

```bash
for wt in $(git worktree list --porcelain | awk '/^worktree/{print $2}' | grep -v '^/Users/garva/Documents/projects/dodo_audit_service$'); do
  branch=$(git -C "$wt" branch --show-current 2>/dev/null)
  dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  cherry=$(git cherry main "$branch" 2>/dev/null | grep -c '^+')
  echo "$wt | branch=$branch | uncommitted=$dirty | commits_not_in_main=$cherry"
done
```

Ожидание: у каждой строки `uncommitted=0` и `commits_not_in_main=0`. Если у какой-то строки одно из чисел не ноль — остановиться и не удалять именно эту копию, доложить владельцу, что именно найдено (не решать самостоятельно).

- [ ] **Step 2: Удалить подтверждённо мёртвые worktree и их локальные ветки**

```bash
for wt in $(git worktree list --porcelain | awk '/^worktree/{print $2}' | grep -v '^/Users/garva/Documents/projects/dodo_audit_service$'); do
  branch=$(git -C "$wt" branch --show-current 2>/dev/null)
  git worktree remove "$wt"
  git branch -d "$branch" 2>/dev/null
done
```

- [ ] **Step 3: Убрать устаревшие ссылки и проверить, что список пуст**

```bash
git worktree prune
git worktree list
```

Ожидание: единственная строка — основная копия `/Users/garva/Documents/projects/dodo_audit_service`.

---

### Task 2: Переименование репозитория на GitHub

**Files:** нет — операция над GitHub API через `gh`, локальный `git remote` внутри текущей копии

- [ ] **Step 1: Переименовать репозиторий**

```bash
gh repo rename decimus --yes
```

`gh repo rename`, запущенный внутри рабочей копии, сам обновляет `origin` в текущем `.git/config` — отдельно трогать `git remote set-url` не нужно.

- [ ] **Step 2: Проверить новый адрес и что remote обновился**

```bash
gh repo view --json url,name
git remote -v
```

Ожидание: `url` = `https://github.com/GarroV/decimus`, `name` = `decimus`; `origin` в выводе `git remote -v` указывает на `github.com/GarroV/decimus.git`.

- [ ] **Step 3: Убедиться, что редирект со старого имени работает (на случай внешних ссылок/поиска)**

```bash
curl -s -o /dev/null -w "%{http_code} -> %{redirect_url}\n" https://github.com/GarroV/dodo_audit_service
```

Ожидание: код `301`/`302` с `redirect_url`, ведущим на `.../decimus`.

---

### Task 3: Перенос локальной папки и миграция конфигов Claude Code

Два конфига Claude Code ключуются АБСОЛЮТНЫМ путём к папке проекта. Без переноса они не потеряются физически, но станут недостижимы для будущих сессий в новой папке — это ровно то «незаметно потеряется», от которого просил застраховаться владелец.

**Files:**
- `~/.claude.json` — ключ `projects."/Users/garva/Documents/projects/dodo_audit_service"`
- `~/.claude/projects/-Users-garva-Documents-projects-dodo-audit-service/` — память этого проекта (MEMORY.md и файлы памяти)

- [ ] **Step 1: Бэкап `~/.claude.json` перед хирургией (файл общий на все проекты — ошибка здесь задевает не только этот)**

```bash
cp ~/.claude.json ~/.claude.json.bak-rename-decimus-$(date +%Y%m%d%H%M%S)
```

- [ ] **Step 2: Перенести папку**

```bash
mv /Users/garva/Documents/projects/dodo_audit_service /Users/garva/Documents/projects/decimus
```

- [ ] **Step 3: Перенести ключ проекта в `~/.claude.json` через jq — значение не печатается и не читается, переносится программно**

```bash
jq '
  .projects["/Users/garva/Documents/projects/decimus"] = .projects["/Users/garva/Documents/projects/dodo_audit_service"]
  | del(.projects["/Users/garva/Documents/projects/dodo_audit_service"])
' ~/.claude.json > ~/.claude.json.tmp && mv ~/.claude.json.tmp ~/.claude.json
```

- [ ] **Step 4: Проверить перенос ключа (только наличие/отсутствие ключа, не значение)**

```bash
jq -e '.projects["/Users/garva/Documents/projects/decimus"]' ~/.claude.json >/dev/null && echo "новый ключ есть"
jq -e '.projects["/Users/garva/Documents/projects/dodo_audit_service"]' ~/.claude.json >/dev/null 2>&1 && echo "СТАРЫЙ КЛЮЧ ЕЩЁ ЕСТЬ — откатить" || echo "старый ключ убран, ок"
```

Если старый ключ всё ещё есть — восстановить `~/.claude.json` из бэкапа Step 1 и не продолжать, пока jq-выражение не исправлено.

- [ ] **Step 5: Перенести директорию памяти на новый слаг пути**

```bash
mv ~/.claude/projects/-Users-garva-Documents-projects-dodo-audit-service \
   ~/.claude/projects/-Users-garva-Documents-projects-decimus
```

- [ ] **Step 6: Убедиться, что репозиторий в новой папке жив**

```bash
cd /Users/garva/Documents/projects/decimus
git status
git log -1 --oneline
```

Ожидание: чистое дерево, тот же последний коммит, что и до переноса.

---

### Task 4: Имя пакета — `pyproject.toml` и единственная точка чтения версии

Единственный код, читающий имя пакета — `_version()` в `src/mcp/rpc.py`; тестов, жёстко проверяющих строку `"dodo-audit-service"`, нет (проверено при подготовке плана — `tests/test_mcp_no_paths.py` не завязан на буквальное имя пакета). Значит формальный RED-шаг не нужен: это парная замена двух значений, которые обязаны совпадать, с функциональной проверкой после.

**Files:**
- Modify: `pyproject.toml:2`
- Modify: `src/mcp/rpc.py:64`

- [ ] **Step 1: Переименовать пакет**

В `pyproject.toml`:
```toml
[project]
name = "decimus"
```

- [ ] **Step 2: Обновить точку чтения версии**

В `src/mcp/rpc.py`:
```python
def _version() -> str:
    """Версия продукта из метаданных пакета, а не переписанная сюда числом."""
    try:
        return version("decimus")
    except PackageNotFoundError:  # pragma: no cover — пакет не установлен
        return "0"
```

- [ ] **Step 3: Переустановить пакет в editable-режиме, чтобы метаданные подхватили новое имя, и убрать устаревший egg-info**

```bash
rm -rf src/dodo_audit_service.egg-info
./.venv/bin/pip install -e . --no-deps -q
```

- [ ] **Step 4: Проверить функционально, что версия читается под новым именем, а не падает в заглушку "0"**

```bash
./.venv/bin/python -c "from src.mcp.rpc import _version; v = _version(); assert v != '0', f'метаданные не найдены: {v!r}'; print('OK', v)"
```

Ожидание: строка вида `OK 0.1.0`, не `0`.

---

### Task 5: Тестовые константы имени compose-проекта

Это ИЗОЛИРОВАННЫЕ имена для тестового стенда (`-tests`), не боевой `dodo_audit_service-infra` — переименовать их безопасно, они не касаются реальных контейнеров/томов.

**Files:**
- Modify: `tests/test_db_stand.py:51`
- Modify: `tests/test_bot_ui_lang.py:40`

- [ ] **Step 1: Переименовать константу в обоих файлах**

`tests/test_db_stand.py:51`:
```python
#: Своё имя проекта: без него вызов разговаривал бы с контейнерами соседней
#: рабочей копии. Здесь ничего не поднимается, только читается конфигурация.
PROJECT = "decimus-tests"
```

`tests/test_bot_ui_lang.py:40`:
```python
COMPOSE_PROJECT = "decimus-tests"
```

- [ ] **Step 2: Прогнать эти два теста (пропустятся без Docker — это ожидаемо и не провал)**

```bash
./.venv/bin/pytest tests/test_db_stand.py tests/test_bot_ui_lang.py -v
```

Ожидание: PASSED либо SKIPPED (маркер `requires_docker`), ни одного FAILED.

---

### Task 6: Полная регрессия и калибровочный чек-лист проекта

Обязательный гейт по корневому `CLAUDE.md` — любое расхождение чисел на `belgrade-1`/`belgrade-2` считается регрессией.

**Files:** нет новых — прогон существующих проверок

- [ ] **Step 1: Полный набор проверок проекта**

```bash
cd /Users/garva/Documents/projects/decimus
make check
```

Ожидание: `fmt`, `lint`, `types`, `test`, `dead`, `bounds` — все зелёные. Если `test` показывает провалы, не связанные с этим переименованием, — остановиться и разобраться (systematic-debugging), не списывать на «уже было так».

- [ ] **Step 2: Регрессионный якорь движка**

```bash
make regress
```

Ожидание по `CLAUDE.md`: belgrade-1 → 97.5%, A, 5×D1; belgrade-2 → 97.0%, A, 6×D1. Совпадение обязательно.

- [ ] **Step 3: Коммит переименования кода**

```bash
git add pyproject.toml src/mcp/rpc.py tests/test_db_stand.py tests/test_bot_ui_lang.py
git commit -m "chore(rename): пакет и тестовые стенды называются decimus, не dodo-audit-service

Часть ребрендинга DECIMUS (D108): GitHub-репозиторий и локальная папка уже
переименованы. Docker-compose проекта боевого стенда и POSTGRES_DB здесь
намеренно не тронуты — тома без явного name: осиротели бы молча."
git push
```

---

### Task 7: Финальная сверка — не осталось ли забытых упоминаний

**Files:** нет — только чтение/аудит

- [ ] **Step 1: Повторный поиск по всему репозиторию**

```bash
grep -rln "dodo_audit_service\|dodo-audit-service" --include="*.md" --include="*.py" --include="*.json" --include="*.yml" --include="*.yaml" --include="*.toml" --include="*.sh" . 2>/dev/null | grep -v '^\./\.git/'
```

Ожидание: остаются только файлы отложенной фазы и историческая летопись — `docker-compose.yml`, `scripts/deploy.sh`, `scripts/smoke.sh`, `docs/08-deploy.md`, `.claude/settings.local.json`, `progress.md`, старые записи `docs/forge/decisions.md` (до D108 включительно — история не переписывается). Любой другой файл в списке — недосмотр, разобрать адресно.

- [ ] **Step 2: Завести issue про отложенную фазу (боевой MUSPELHEIM), чтобы не потерялась между сессиями**

```bash
gh issue create --title "Ренейм decimus: перенос боевого стенда на MUSPELHEIM (отложено, требует deploy-window)" --body "$(cat <<'EOF'
Часть D108. GitHub-репозиторий и локальная папка уже переименованы в decimus
(этот план: docs/superpowers/plans/2026-09-09-rename-to-decimus.md).

Отложено сознательно, отдельная фаза:
- перенос C:\projects\dodo_audit_service → C:\projects\decimus на MUSPELHEIM
- обновление REMOTE_DIR по умолчанию в scripts/deploy.sh и scripts/smoke.sh — в ТОМ ЖЕ коммите, что физический перенос, иначе окно с несуществующим путём по умолчанию
- обновление docs/08-deploy.md
- обновление .claude/settings.local.json (не в git, локальные пути SSH-команд)
- отдельное решение, нужно ли также переименовывать docker-compose `name:` (`dodo_audit_service-infra`) и POSTGRES_DB — тома без явного name: не переживут смену имени проекта молча, нужен осознанный план миграции данных, а не просто рестарт

Выполняется только после явного «да» владельца в этом разговоре и только в
окно 23:00–05:59 (deploy-window). Смоук — scripts/smoke.sh — обязателен после.
EOF
)"
```

---

## Отложено (НЕ выполняется этим планом)

**Фаза production-редеплоя на MUSPELHEIM** — требует:
1. Явного «да» владельца в этом же разговоре, когда до неё дойдёт очередь.
2. Ночного окна 23:00–05:59 (deploy-window).
3. Отдельного решения: переименовывать ли boевой docker-compose `name:`/`POSTGRES_DB` — риск молчаливой потери тома `pgdata`/`state`, если не сделать миграцию данных явно.

Задача заведена в Task 7 Step 2, чтобы не забыть об этой границе между сессиями.

---

## Self-Review

- **Покрытие:** каждый файл из «Файлы, которые трогает план» закрыт задачей (Task 1–7); каждая явная граница («не трогается») повторена в Global Constraints и подтверждена в Task 7 Step 1.
- **Плейсхолдеры:** команды и код везде конкретные, без TODO/TBD.
- **Согласованность имён:** `decimus` (пакет), `decimus-tests` (тестовый compose-стенд), `GarroV/decimus` (репозиторий), `/Users/garva/Documents/projects/decimus` (папка) — использованы одинаково во всех задачах.
