# Бэкап и восстановление

Что бэкапится на проде, чем и куда, как проверить, что бэкап жив. Для того, кто отвечает за сохранность данных.
Восстановление по шагам — раздел «Восстановление из бэкапа по шагам» ниже; что и как копируется — разделы §8.5, §4.7, §4.8.

**Содержание** (генерируется `make map`, руками не править):

<!-- map:begin toc -->
- [8.5. Бэкапы на VPS](#85-бэкапы-на-vps)
- [Восстановление из бэкапа по шагам](#восстановление-из-бэкапа-по-шагам)
- [4.7. Бэкап состояния — том `state` (задача #233)](#47-бэкап-состояния--том-state-задача-233)
- [4.8. Бэкап базы проверок — задача площадки (T281, #246)](#48-бэкап-базы-проверок--задача-площадки-t281-246)
<!-- map:end -->

## 8.5. Бэкапы на VPS

**Сейчас (30.09):** ночной бэкап площадки VPS уходит restic'ом на MUSPELHEIM —
база, `state`, `.env`, кадры; список целей — `/etc/vps-backup/targets.conf` (канон
`GarroV/vps-infra`). Кадры (том `decimus_storage-data`) бэкапятся с 23.10.2026 (D635, отменил D259).
Ниже — что из этого закрывает сам продукт.

- **База:** у службы `db` метка `backup.pgdump=true` — её ищет дамп площадки.
- **`decimus_state` — не дамп Postgres**, меткой не помечен: его берёт площадка
  строкой `vol decimus-state decimus_state` в `targets.conf`. Том кадров
  `decimus_storage-data` — строкой `vol decimus-frames decimus_storage-data` (D635); не путать
  с томом `decimus_frames` (копии кадров бота на 7 дней, #367, в бэкап не входят намеренно).

## Восстановление из бэкапа по шагам

Для того, кто поднимает продукт из бэкапа: после потери базы, тома или всего сервера. Скрипты ночного бэкапа и пробного восстановления
живут не здесь, а в репозитории `GarroV/vps-infra` (`backup/vps-backup.sh`, `backup/restore-test.sh`, `backup/lib.sh`); команды ниже взяты
из них и из `docker-compose*.yml`. Что проверено восстановлением на деле, а что только выведено из скриптов — в конце раздела, не пропускать.

**Что лежит в бэкапе** (одна ночь = каталог `/var/backups/vps/<дата>/` на сервере, 7 дней; тот же каталог — снимок restic на MUSPELHEIM, хост `vps-contabo`, тег `nightly`):

| Файл | Что внутри |
|---|---|
| `pg-decimus.dump` | `pg_dump -Fc` базы проверок (контейнер `decimus-db-1`) |
| `pg-decimus.counts` | число строк по каждой таблице схемы `public` на момент дампа — эталон для сверки |
| `vol-decimus-state.tgz` | том `decimus_state`: папки идущих проверок, `access/roster.json` |
| `vol-decimus-frames.tgz` | том `decimus_storage-data`: кадры проверок (MinIO) |
| `vol-decimus-methodology.tgz` | том `decimus_methodology`: версии методики админки |
| `files-config.tgz` | `/srv/decimus/.env` и `/srv/decimus/compose.edge.yaml` (с абсолютными путями), среди файлов других проектов сервера |

Не в бэкапе намеренно: том `decimus_frames` (копии кадров бота на 7 дней, #367). Демо-стенд не бэкапится — пересобирается из выдуманных данных.

**Главное правило.** Дамп **не** восстанавливают поверх рабочей базы: записи, сделанные людьми после дампа, пропадут. Восстановление — в **новую пустую** базу (новый VPS или чистый том),
а прежнюю не трогать, пока не сверили результат. Откат кода без отката базы — не это, а раздел «Откат» в [`08-deploy.md`](08-deploy.md).

### Шаг 0. Подготовка

На новом VPS сначала то, что даёт `GarroV/vps-infra` (`docs/bootstrap.md`, `backup/README.md`): Docker, общий прокси и сеть `edge-decimus`, установленный restic, ключи `/etc/vps-backup/{rest-pass,restic-pass}`
и доступ к MUSPELHEIM. **Копия `restic-pass` — у владельца** (на его компьютере, `~/.config/vps-infra/`); без неё бэкап не расшифровать — это единственное, чего нельзя восстановить. Звать владельца до начала.
Затем клон репозитория и окружение:

```bash
cd /srv && git clone <адрес репозитория GarroV/decimus> decimus && cd decimus     # ветка main
```

### Шаг 1. Достать файлы бэкапа

С живого сервера, где нужная ночь ещё в локальных копиях (7 дней), восстанавливать из restic не нужно: берём `/var/backups/vps/<дата>/`. Иначе из restic на MUSPELHEIM (от root; `lib.sh` задаёт репозиторий и пароль):

```bash
sudo bash -c 'source /opt/vps-backup/lib.sh; restic snapshots --host vps-contabo'                       # выбрать снимок (дата ночи)
sudo bash -c 'source /opt/vps-backup/lib.sh; restic restore <id снимка> --target /tmp/r --include "/var/backups/vps/*/*decimus*"'
ls /tmp/r/var/backups/vps/*/                                                                           # pg-decimus.dump, vol-decimus-*.tgz
```

Ручной restic запускать под `tmux`: убитый обрывом SSH процесс оставляет лок (`restic unlock`). Шаблон `--include` и форма `restic restore latest --host vps-contabo` те же, что в `restore-test.sh`
(он берёт `latest`; выбор конкретного снимка по `<id>` — обычный restic, здесь не проверялся).

### Шаг 2. Окружение

`.env` и надстройка площадки лежат в `files-config.tgz` среди файлов других проектов — достаём только свои, остальное не разворачиваем:

```bash
mkdir -p /tmp/cfg && tar xzf /tmp/r/var/backups/vps/<дата>/files-config.tgz -C /tmp/cfg \
  srv/decimus/.env srv/decimus/compose.edge.yaml 2>&1 | head
install -m 600 /tmp/cfg/srv/decimus/.env /srv/decimus/.env
cp /tmp/cfg/srv/decimus/compose.edge.yaml /srv/decimus/compose.edge.yaml
```

(GNU tar при распаковке отбрасывает ведущий `/` у путей; если в архиве пути без `srv/`, сначала `tar tzf … | grep decimus`.) `.env` содержит все ключи — не печатать и не копировать в чат. Не восстановился `SECRETS_KEY` —
зашифрованные в базе ключи сервисов и входы Dodo IS не откроются (придётся вставить ключи заново и выпустить новые ссылки входа стран).

### Шаг 3. База

```bash
cd /srv/decimus
dc() { docker compose -f docker-compose.yml -f docker-compose.prod.yml -f compose.edge.yaml "$@"; }
dc up -d --wait db                                                    # пустая база из POSTGRES_* в .env
# роли приложения кластерные и в дамп не входят, а права в дампе ссылаются на них: завести до pg_restore
dc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "create role dodo_audit_app login" -c "create role dodo_audit_admin login"'
dc exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < /tmp/r/var/backups/vps/<дата>/pg-decimus.dump
```

`pg_restore` напишет предупреждения (расширения, роли) и может вернуть код 1 — код выхода не показателен, судят по сверке строк:

```bash
dc exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<< "$(source /opt/vps-backup/lib.sh; echo "$ROW_COUNTS_SQL")" \
  | diff - /tmp/r/var/backups/vps/<дата>/pg-decimus.counts && echo "строки совпали"
```

Накат миграций отдельно не нужен: его делает `scripts/prod-update.sh` на шаге 5. Он идемпотентен, выставит пароли ролей из `.env` (`DATABASE_APP_PASSWORD`, `DATABASE_RETRACTION_PASSWORD`)
и добавит миграции, которых не было на момент дампа.

### Шаг 4. Тома

Тома создаются пустыми и наполняются архивами; после распаковки владелец — `10001:10001` (образ идёт не от root, [`08-deploy.md`](08-deploy.md) §8.3.1):

```bash
for v in state methodology; do
  docker volume create decimus_$v
  docker run --rm -v decimus_$v:/v -v /tmp/r/var/backups/vps/<дата>/vol-decimus-$v.tgz:/a.tgz:ro alpine \
    sh -c 'tar xzf /a.tgz -C /v && chown -R 10001:10001 /v'
done
docker volume create decimus_storage-data
docker run --rm -v decimus_storage-data:/v -v /tmp/r/var/backups/vps/<дата>/vol-decimus-frames.tgz:/a.tgz:ro alpine \
  sh -c 'tar xzf /a.tgz -C /v'          # данные MinIO, владельца не менять
```

Имена архивов — `vol-decimus-state`, `vol-decimus-methodology`, `vol-decimus-frames` (последний — в том `decimus_storage-data`); имя проекта compose — `decimus`, поэтому тома получают префикс `decimus_`.

### Шаг 5. Подъём и проверка

```bash
dc up -d --wait storage-live && dc run --rm --no-deps storage-init       # корзина и пользователь приложения — идемпотентно
DECIMUS_OVERLAYS=/srv/decimus/compose.edge.yaml scripts/prod-update.sh    # собрать образы, накатить, поднять, смоук
```

`prod-update.sh` тянет `main` с GitHub, собирает образы, накатывает миграции, поднимает всё и делает смоук (админка `/login` — 200, MCP без токена — 401, запись обхода, хранилище методики) — это и есть проверка «поднялось».
Дальше глазами: вход в админку; «Подключения» (после восстановления входы Dodo IS и ключи сервисов открываются, если сохранился `SECRETS_KEY`); карточка недавней проверки с кадрами; счётчики
на «Рейтингах» совпадают со старыми. Выкатка на живой прод — только по «да» владельца и в окне ([`08-deploy.md`](08-deploy.md)); восстановление **нового** сервера выкаткой не является, пока на него не переключён адрес.

### Что проверено восстановлением на деле, а что нет

- **Проверено (само, каждое воскресенье):** `vps-restore-test` достаёт последний снимок с MUSPELHEIM, поднимает временный контейнер Postgres того же образа, делает `pg_restore --no-owner --no-privileges` и сверяет число строк по каждой таблице
  с `pg-decimus.counts`; итог — `/var/lib/vps-backup/last_restore`, тревога при расхождении. Это доказывает, что **данные** базы восстанавливаются.
- **Не проверено на деле (выведено из скриптов и compose):** роли и права после `pg_restore` без `--no-privileges` (шаг 3 с созданием ролей до дампа); накат `migrate` поверх восстановленной базы (шаг 5); распаковка томов `state`, `methodology`, кадров
  и запуск MinIO из распакованного тома; извлечение `.env` и `compose.edge.yaml` из `files-config.tgz`; полный прогон на новом VPS целиком. Первый, кто проходит эти шаги по-настоящему, правит этот раздел по факту.
- **Требует владельца:** `restic-pass` и `rest-pass`, значения `.env`, `SECRETS_KEY`.

## 4.7. Бэкап состояния — том `state` (задача #233)

**Почему отдельным шагом.** Бэкап площадки умеет ровно одно: дампы Postgres.
Задача по расписанию обходит контейнеры с меткой `backup.pgdump=true` и
складывает дампы в `C:\backups`. Том `state` в неё не входит вовсе — а в нём
лежат папки идущих проверок и связки доступа `access/roster.json`. Чем
оборачивается потеря связок, разобрано в [§4.2](history/deploy-muspelheim-2026.md), и «перестанут входить» —
наименьшая из трёх бед.

**Том `frames` в бэкап не входит намеренно** (#367, D179). В нём копии
присланных кадров для разбора, срок владельца — 7 дней, бот убирает их сам.
Бэкап хранится 14 дней, и копии с лицами сотрудников прожили бы в нём вдвое
дольше. Потеря тома стоит только материала для разбора: отчёт берёт кадры у
телеграма, а не отсюда.

**Что делает выгрузка.** Сервис `state-backup` (профиль `backup`) собирает том
состояния в архив `decimus-state-<дата>-<время>.tar.gz` и кладёт его в каталог
`BACKUP_DIR` на хосте. Состояние смонтировано **только на чтение**: задача
бэкапа снимает копию, а не правит то, что копирует. После записи архив
перечитывается и сверяется с тем, что в него клали; негодный удаляется, а
прогон краснеет — битый бэкап хуже отсутствующего, потому что выглядит
бэкапом. Отдельной строкой сообщается судьба связок: попали в архив или на
этом стенде ещё никого не приглашали.

**Один раз: две строки в `.env`** (имена и объяснения — в `.env.example`):

| Переменная | Что писать | Что будет, если забыть |
|---|---|---|
| `BACKUP_DIR` | `C:\backups` — тот же каталог, куда кладёт дампы задача Postgres | архивы лягут в `./backups` рядом с копией репозитория и не попадут ни в какой перенос |
| `BACKUP_KEEP_DAYS` | `14`, как у дампов Postgres | без строки берётся те же 14; `0` означает «не удалять ничего», и место кончится молча |

Каталог бэкапа на площадке **общий с чужими проектами**. Поэтому по сроку
хранения удаляются только файлы своего имени (`decimus-state-*.tar.gz`) и
ничьи больше.

**Это не прод-бэкап.** Архив — открытый `tar.gz` без шифрования (права файла
0600, инструмент пишет предупреждение в вывод). На проде том `state` уходит
через restic с шифрованием (§8.5); `state-backup` — для ноутбука и ручного
случая, архив держать только в каталоге с закрытым доступом.

**Собрать образ.** Образ у выгрузки свой: compose именует образы по сервису, и
пара `build bot mcp` его не собирает — первый же прогон полез бы собирать сам,
посреди ночного расписания. Собирается тем же порядком и с той же версией:

```powershell
$env:BUILD_SHA=(git rev-parse --short HEAD)
docker compose build bot mcp state-backup
```

**Прогон руками** (на своей машине — `make state-backup`):

```powershell
docker compose run --rm -T state-backup
```

`-T` означает «без терминала». Задача по расписанию терминала не имеет, и
команда у неё обязана быть той же самой, что прогоняют руками, — иначе «у меня
работает» и «ночью не пошло» разойдутся именно на этой мелочи.

**По расписанию — шаги для площадки, здесь НЕ ВЫПОЛНЯЛИСЬ.** Заводится задача
рядом с «PG Docker Backup», временем позже неё, чтобы два тяжёлых обхода не
шли разом:

```powershell
$action = New-ScheduledTaskAction -Execute "docker" `
    -Argument "compose run --rm -T state-backup" -WorkingDirectory "C:\projects\decimus"
$trigger = New-ScheduledTaskTrigger -Daily -At 03:50
Register-ScheduledTask -TaskName "Decimus State Backup" -Action $action -Trigger $trigger
```

Помнить про сон машины: у площадки выключены таймеры пробуждения, и задача,
пришедшаяся на сон, просто не идёт — это известное свойство площадки, а не
поломка выгрузки.

**Проверка восстановлением — обязательна, иначе бэкапа нет.** Архив, который
никто не разворачивал, бэкапом не является: он может годами лежать пустым или
битым, и узнают об этом ровно в тот день, когда он нужен.

```powershell
# что внутри
docker run --rm -v C:\backups:/backup alpine:3.22 tar -tzf /backup/<архив> | Select-Object -First 20

# развернуть в ОТДЕЛЬНЫЙ том и посмотреть глазами
docker volume create state-restore-check
docker run --rm -v state-restore-check:/state -v C:\backups:/backup alpine:3.22 `
    tar -xzf /backup/<архив> -C /state
docker run --rm -v state-restore-check:/state alpine:3.22 cat /state/access/roster.json
docker volume rm state-restore-check
```

**Разворачивать прямо в рабочий том нельзя.** Распаковка ляжет поверх
сегодняшнего состояния, и проверки, начатые после архива, пропадут молча.
Сначала отдельный том, посмотреть, и только потом решать.

## 4.8. Бэкап базы проверок — задача площадки (T281, #246)

Дампы баз снимает не проект, а сама площадка: задача `PG Docker Backup` в
03:30, скрипт `C:\backups\pg_backup.ps1`, `pg_dumpall` в
`C:\backups\<контейнер>\`, хранение 14 дней.

**Сверено фактом 17.09.2026, а не по описанию.** Дамп базы проверок на месте:
`C:\backups\decimus-infra-db-1\decimus-infra-db-1_2026-09-17_0330.sql`, 67 КБ,
внутри 11 таблиц с данными (`inspections`, `findings`, `photos`, `units`,
`translations`, `schema_migrations` и остальные).

**Но попадает она туда по запасному правилу, а не по метке.** Скрипт берёт
контейнеры двумя путями: по метке `backup.pgdump=true` и, вдобавок, все, в чьём
имени образа есть `postgres` или `pgvector`. В списке по метке сегодня восемь
чужих контейнеров и ни одного нашего — нас спасает второе правило и имя образа
`postgres:16.14-alpine`. Это опора на чужое имя: переход на `pgvector`, на
свою сборку или на образ с другим именем выкинет базу проверок из бэкапа
**молча**, и узнают об этом в день, когда дамп понадобится.

Метка добавлена в `docker-compose.yml` и закрыта проверкой
`test_database_is_marked_for_the_platform_backup`. **На площадке она начнёт
действовать только после пересоздания контейнера** — метки ставятся при
создании:

```powershell
docker compose --profile db up -d --force-recreate db
docker ps --filter label=backup.pgdump=true --format "{{.Names}}"   # ждём decimus-infra-db-1
```

Пересоздание контейнера данные не трогает — они в томе `pgdata`. **Запрещено:
`down -v`** (см. [§4.5](history/deploy-muspelheim-2026.md)).

Отдельно от бэкапа, но по тому же поводу: в корне `C:\backups` лежит
`mcp-token-20260908-002820.txt` (48 байт, 08.09). Каталог общий для всех
проектов машины, и файлу с токеном там не место — значение не читал, решение за
владельцем.
