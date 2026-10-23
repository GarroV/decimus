"""Транспорт MCP-сервера: HTTP на локальной петле, личный токен в заголовке.

Форма повторяет работающий `swarm-mcp` (D055): клиент говорит по stdio,
крохотный мост перекладывает строку в POST, сервер отвечает JSON-RPC. Разница
одна и она осознанная — сервер поднимается **локально**, а не Edge Function:
база проверок сегодня локальная (D061), наружу блок не публикуется, и
переезд в Edge Function будет сменой транспорта при тех же инструментах.

Слушаем только петлю (проверяет `config._parse_host`): площадка общая, рядом
живут чужие проекты, и открытый в сеть порт отдал бы им проверки партнёров.

Авторизация здесь, до разбора сообщения: **арендатор получается из токена**,
и ниже по коду его подменить нечем.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import traceback
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from src.domain.client_ip import forwarded_client
from src.domain.journal import truncate_user_agent
from src.domain.public_urls import OAUTH_SCOPE, PROTECTED_RESOURCE_PATH

from .audit import journal_write_call, log_write_call
from .checklist import Store
from .checklist_layout import DEFAULT_SPACE, space_of
from .config import MCP_FRONT_KEY_VAR, Settings, resolve_access
from .errors import AuthError
from .install import (
    BRIDGE_META_PATH,
    BRIDGE_SCRIPT_PATH,
    INSTALL_CONTENT_TYPE,
    INSTALL_PATH,
    InstallScriptError,
    bridge_meta,
    bridge_script,
    install_script,
)
from .ratelimit import CODE_RATE_LIMITED, RATE_LIMITED, McpRate, token_key
from .rpc import CODE_PARSE_ERROR, handle

#: Больше мегабайта читающему серверу присылать нечего: вопросы к базе
#: короткие. Предел стоит до чтения тела, иначе он не предел, а пожелание.
MAX_BODY_BYTES = 1 << 20

#: Заголовок, в котором Worker фронта шлёт ключ; Caddy проверяет его и пропускает дальше.
FRONT_KEY_HEADER = "X-Decimus-Front-Key"

#: Ответ на уведомление JSON-RPC: принято, тела нет.
_ACCEPTED = HTTPStatus.ACCEPTED

#: Строка запроса (всё за `?`) из лога вырезается (T116). Авторизация через
#: адрес не принимается — но клиент об этом не знает и вполне может дописать
#: туда токен, а лог переживёт и запрос, и клиента. Вырезается ровно кусок от
#: `?` до ближайшего пробела или кавычки, то есть сама строка запроса, а не
#: хвост сообщения.
_QUERY = re.compile(r"\?[^\s\"']*")

#: Чем строка запроса заменяется в логе: место видно, содержимое — нет.
_QUERY_HIDDEN = "?<скрыто>"

#: Сколько секунд ждём от клиента, который замолчал посреди запроса.
#:
#: Без этого предела соединение, открытое и брошенное, держит поток сервера
#: вечно — и держит его ДО проверки токена, потому что заголовки разбираются
#: раньше. Площадка общая: любой процесс на машине мог открыть сколько угодно
#: таких соединений без единого валидного токена и оставить без ответа всех
#: арендаторов сразу. Найдено разбором безопасности 03.09 живым запуском:
#: незавершённый заголовок держал поток бесконечно, `Content-Length` на пять
#: мегабайт при теле в два байта — тоже.
SOCKET_TIMEOUT_SEC = 15.0

#: Сколько соединений обслуживаем одновременно. Потоки `ThreadingHTTPServer`
#: ничем не ограничены, и таймаут выше сужает окно, но не число: сотня
#: одновременных подключений всё ещё создала бы сотню потоков. Читающему
#: серверу на одного человека столько не нужно.
MAX_CONNECTIONS = 16


class _Server(ThreadingHTTPServer):
    """`ThreadingHTTPServer`, знающий свои настройки.

    Настройки висят на сервере, а не на классе обработчика: обработчик
    создаётся заново на каждый запрос, а класс — общий на процесс, и настройки
    на нём означали бы, что два сервера в одном процессе (а это ровно тесты)
    делят одну карту токенов.
    """

    daemon_threads = True

    def __init__(self, address: tuple[str, int], settings: Settings) -> None:
        self.settings = settings
        # Ограниченный семафор — страховка: лишний release (счётчик выше предела)
        # падает громко, а не разъедает предел молча (F-118).
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.rate = McpRate(shared=True)
        super().__init__(address, _Handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        """Обслужить соединение, не давая их числу расти без предела.

        Ждать освободившийся слот нельзя: ожидание — это та же очередь, только
        невидимая. Свободных нет — закрываем сразу, и следующий клиент получит
        отказ соединения, а не молчание.
        """
        if not self._slots.acquire(blocking=False):
            # Слот не брали — и отпускать нечего: `shutdown_request` пришёл бы
            # в `close_request` и вернул бы чужой слот (F-118), поэтому
            # закрываем сокет напрямую.
            try:
                request.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            request.close()
            return
        super().process_request(request, client_address)

    def shutdown_request(self, request: Any) -> None:
        super().shutdown_request(request)

    def close_request(self, request: Any) -> None:
        super().close_request(request)
        self._slots.release()


class _Handler(BaseHTTPRequestHandler):
    """Один POST — одно сообщение JSON-RPC."""

    #: Клиент, замолчавший посреди запроса, отпускает поток через это время.
    timeout = SOCKET_TIMEOUT_SEC

    server_version = "dodo-audit-mcp"
    #: Своя версия питона в заголовке ответа не печатается: подсказывать
    #: версию интерпретатора тому, кто стучится, незачем.
    sys_version = ""

    #: Ответ этому запросу уже отправлен. Нужно заслону от пустого ответа
    #: (`_guarded`): второй ответ, дописанный после первого, склеивается с ним
    #: в поток, который клиент не разберёт вовсе.
    _answered = False

    @property
    def _settings(self) -> Settings:
        """Настройки сервера, которому принадлежит этот обработчик.

        Проверка типа явная, а не `assert`: без настроек обработчик не знает
        ни токенов, ни арендаторов, и продолжать ему нельзя — а `assert`
        исчезает при запуске с `-O`, то есть ровно в бою.
        """
        settings = getattr(self.server, "settings", None)
        if not isinstance(settings, Settings):
            raise RuntimeError("Обработчик MCP поднят без настроек сервера")
        return settings

    # Имя `format` задано сигнатурой базового класса и переименованию не подлежит.
    def log_message(self, format: str, *args: Any) -> None:
        """Короткая строка в stderr вместо стандартного лога.

        Ни заголовков, ни тела: в заголовке едет токен, в теле — вопросы про
        проверки партнёров (конституция, «в логах — идентификаторы, а не
        содержимое»). Строка запроса вырезается здесь, а не в одном месте
        печати пути (T116): она попадает в лог двумя разными дорогами —
        обычной записью запроса и отказом на кривую строку запроса, где
        базовый класс печатает её целиком.
        """
        print(f"[mcp] {self.command} {_QUERY.sub(_QUERY_HIDDEN, format % args)}", file=sys.stderr)

    def _send(self, status: HTTPStatus, payload: dict[str, Any] | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._answered = True
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if status == HTTPStatus.UNAUTHORIZED:
            self.send_header("WWW-Authenticate", _www_authenticate(self._settings))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _guarded(self, обработка: Callable[[], None]) -> None:
        """Обслужить запрос так, чтобы любой отказ стал кодом, а не молчанием.

        Необработанное исключение в обработчике `http.server` разрывает
        соединение без единого байта: клиент получает пустой ответ, а причина
        остаётся только в логе сервера. Ровно так выглядел `TypeError` на
        сравнении токенов (T115, issue #94) — и точно так же будет выглядеть
        любая следующая ошибка, если её не во что обернуть.

        Наружу уходит ТИП отказа и ничего больше: в тексте исключения может
        оказаться строка подключения к базе, а в трейсбеке — пути на машине.
        Трейсбек при этом печатается в свой лог: он остаётся на петле, у
        владельца, и без него чинить нечего.
        """
        try:
            обработка()
        except Exception as отказ:
            print(f"[mcp] необработанный отказ: {type(отказ).__name__}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self.close_connection = True
            if self._answered:
                # Ответ уже ушёл — дописывать второй нельзя, он склеится с
                # первым и клиент не разберёт ни одного.
                return
            try:
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"Внутренний отказ сервера ({type(отказ).__name__})"},
                )
            except OSError:
                # Сокет уже закрыт клиентом: сказать некому, и это не повод
                # уронить поток. Отказ при этом уже записан в лог выше.
                pass

    def _send_text(self, status: HTTPStatus, text: str, content_type: str) -> None:
        """Ответ не-JSON: установщик. Отдельно от `_send`, чтобы тот остался про JSON."""
        body = text.encode("utf-8")
        self._answered = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_install(self) -> None:
        """Отдать скрипт установки — публично, без токена.

        Секретов в нём нет: адрес и токен человек подставляет сам, запуская
        его. Требовать токен на скачивание значило бы требовать его до того,
        как человек узнал, куда вписывать (#244, D112).

        Отказ собрать скрипт — это 500, а не пустая страница: человек, чей
        `curl` молча вернул ноль байт, получит `bash`, которому нечего делать,
        и решит, что подключился.
        """
        try:
            текст = install_script()
        except InstallScriptError as отказ:
            print(f"[mcp] установщик не собран: {отказ}", file=sys.stderr)
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Скрипт установки на сервере не собран"},
            )
            return
        self._send_text(HTTPStatus.OK, текст, INSTALL_CONTENT_TYPE)

    def _authorized(self) -> bool:
        """Токен на GET: те же правила и те же пределы, что у `_post` (401 / 429 уже отправлены)."""
        rate: McpRate = self.server.rate  # type: ignore[attr-defined]
        try:
            resolve_access(self._settings, self.headers.get("Authorization"))
        except AuthError as отказ:
            if not rate.by_address.allow(str(self.client_address[0])):
                self._send_rate_limited()
                return False
            self._send(HTTPStatus.UNAUTHORIZED, {"error": str(отказ)})
            return False
        _, _, bearer = (self.headers.get("Authorization") or "").partition(" ")
        if not rate.by_token.allow(token_key(bearer.strip())):
            self._send_rate_limited()
            return False
        return True

    def _serve_bridge(self, script: bool) -> None:
        """Самообновление моста (D626): версия с отпечатком или сам файл — только с токеном."""
        if not self._authorized():
            return
        try:
            if script:
                self._send_text(HTTPStatus.OK, bridge_script(), INSTALL_CONTENT_TYPE)
            else:
                self._send(HTTPStatus.OK, bridge_meta())
        except InstallScriptError as отказ:
            print(f"[mcp] мост не отдан: {отказ}", file=sys.stderr)
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Мост на сервере не собран"})

    # Имена do_GET/do_POST задаёт BaseHTTPRequestHandler — он ищет их по имени.
    def do_GET(self) -> None:
        """Просматриваемых поверхностей три: установщик, мост (с токеном), документ ресурса OAuth.

        Остальное по-прежнему 405: сервер отвечает на JSON-RPC по POST, и
        расширять эту дверь нечем — за ней история проверок партнёров.
        Документ ресурса (RFC 9728, D417) публичен по устройству протокола:
        клиент читает его ДО входа, чтобы узнать, где входить; в нём только
        два внешних адреса и область доступа.
        """
        путь = self.path.split("?", 1)[0].rstrip("/") or "/"
        if путь == INSTALL_PATH:
            self._guarded(self._serve_install)
            return
        if путь in (BRIDGE_META_PATH, BRIDGE_SCRIPT_PATH):
            self._guarded(lambda: self._serve_bridge(путь == BRIDGE_SCRIPT_PATH))
            return
        if self._settings.oauth_enabled and _is_resource_document(путь):
            self._guarded(lambda: self._send(HTTPStatus.OK, protected_resource(self._settings)))
            return
        self._guarded(
            lambda: self._send(
                HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Сервер отвечает только на POST"}
            )
        )

    def do_POST(self) -> None:
        self._guarded(self._post)

    def _client_ip(self) -> str:
        """Адрес клиента для журнала действий: по цепочке своих звеньев, не по сырому заголовку."""
        return forwarded_client(
            str(self.client_address[0]),
            self.headers.get("X-Forwarded-For"),
            trusted_proxies=self._settings.trusted_proxies,
            trusted_addrs=self._settings.trusted_proxy_addrs,
            front_key=self._settings.front_key,
            given_key=self.headers.get(FRONT_KEY_HEADER),
        )

    def _send_rate_limited(self, request_id: Any = None) -> None:
        self.close_connection = True
        self._send(
            HTTPStatus.TOO_MANY_REQUESTS,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": CODE_RATE_LIMITED, "message": RATE_LIMITED},
            },
        )

    def _post(self) -> None:
        rate: McpRate = self.server.rate  # type: ignore[attr-defined]
        try:
            доступ = resolve_access(self._settings, self.headers.get("Authorization"))
        except AuthError as отказ:
            # Предел по адресу считает только НЕУДАЧНЫЕ попытки (перебор
            # токенов). Клиенты приходят через общий прокси, то есть с одного
            # адреса: стой адресный предел до токена, посторонний без токена
            # выедал бы его у всех, у кого токен есть.
            if not rate.by_address.allow(str(self.client_address[0])):
                self._send_rate_limited()
                return
            # Отпечаток клиента — в журнал сервера (#692): поток отказов иначе
            # не опознать. Адрес и программа клиента, без токена и без тела;
            # есть ли заголовок вообще — да/нет, без значения.
            print(
                f"[mcp] 401: адрес {self._client_ip()}, клиент "
                f"«{truncate_user_agent(self.headers.get('User-Agent')) or '—'}», "
                f"токен {'передан' if self.headers.get('Authorization') else 'не передан'}",
                file=sys.stderr,
            )
            # Ни имени арендатора, ни токена: по отказу нельзя перечислить,
            # какие партнёры вообще заведены на этом сервере.
            self._send(HTTPStatus.UNAUTHORIZED, {"error": str(отказ)})
            return

        _, _, bearer = (self.headers.get("Authorization") or "").partition(" ")
        if not rate.by_token.allow(token_key(bearer.strip())):
            self._send_rate_limited()
            return

        raw = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw)
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "Не разобрана длина тела запроса"})
            return
        if length > MAX_BODY_BYTES:
            # Ограниченный кусок всё же вычитывается и выбрасывается, а
            # соединение закрывается. Отказ без единого чтения выглядит для
            # клиента не отказом, а оборванным соединением: он ещё пишет тело
            # и получает broken pipe вместо внятного 413. Читаем не больше
            # того же предела — заявленный гигабайт дочитывать никто не будет.
            self.rfile.read(min(length, MAX_BODY_BYTES + 1))
            self.close_connection = True
            self._send(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": f"Тело больше {MAX_BODY_BYTES} байт: вопрос к базе таким не бывает"},
            )
            return

        body = self.rfile.read(length) if length > 0 else b""
        try:
            message = json.loads(body or b"null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(
                HTTPStatus.OK,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": CODE_PARSE_ERROR, "message": "Тело запроса не разбирается"},
                },
            )
            return

        answer = handle(
            message,
            tenant=доступ.tenant,
            checklist=_checklist_for(self._settings, доступ.tenant, доступ.role),
            source=_checklist_source_for(self._settings, доступ.tenant, доступ.role),
            may_retract=доступ.may_retract,
            imports=_imports_for(self._settings, доступ.tenant),
            actor=доступ.actor,
            role=доступ.role,
        )
        log_write_call(
            message, answer, actor=доступ.actor, role=доступ.role, label=доступ.token_label
        )
        journal_write_call(message, answer, access=доступ, ip=self._client_ip())
        if answer is None:
            self._send(_ACCEPTED)
            return
        self._send(HTTPStatus.OK, answer)


def _is_resource_document(path: str) -> bool:
    """Адрес документа ресурса: сам путь, с суффиксом ресурса (RFC 9728 §3.1) или под префиксом."""
    return (
        path == PROTECTED_RESOURCE_PATH
        or path.startswith(f"{PROTECTED_RESOURCE_PATH}/")
        or path.endswith(PROTECTED_RESOURCE_PATH)
    )


def protected_resource(settings: Settings) -> dict[str, Any]:
    """Документ защищённого ресурса (RFC 9728): кто я и где выдают токены ко мне."""
    return {
        "resource": settings.mcp_public_url,
        "authorization_servers": [settings.admin_public_url],
        "scopes_supported": [OAUTH_SCOPE],
        "bearer_methods_supported": ["header"],
    }


def _www_authenticate(settings: Settings) -> str:
    """Заголовок отказа 401. При OAuth — с адресом документа ресурса (RFC 9728 §5.1).

    По нему Claude узнаёт, где входить: без этого параметра подключение через
    сайт не начинается вовсе.
    """
    if not settings.oauth_enabled:
        return 'Bearer realm="dodo-audit-mcp"'
    документ = f"{settings.mcp_public_url}{PROTECTED_RESOURCE_PATH}"
    return f'Bearer realm="dodo-audit-mcp", resource_metadata="{документ}"'


def _checklist_for(settings: Settings, tenant: str, role: str | None = None) -> Store | None:
    """Хранилище версий методики — или `None`, если этому арендатору она не открыта.

    Право спрашивается здесь, на входе, по коду арендатора, разобранному из
    токена, — то есть на той же двери, что и граница арендаторов. Отдельного
    способа получить это право нет: ниже по коду `None` подменить нечем.

    Хранилище сразу наводится на пространство арендатора (`space_of`, волна 1,
    #340): правка партнёра адресуется в его пространство здесь, на входе, а не
    решается ниже по коду вместе с кодом чек-листа — иначе у обработчика был бы
    способ получить хранилище чужого пространства одной опечаткой в аргументе.
    """
    хранилище, методика = settings.checklist_store, settings.data_dir
    if хранилище is None or методика is None:
        return None
    if not settings.may_manage_checklist(tenant, role):
        return None
    return Store(root=хранилище, live=методика, space=space_of(tenant))


def _checklist_source_for(settings: Settings, tenant: str, role: str | None = None) -> Store | None:
    """Хранилище для ЧТЕНИЯ исходника эталона — или `None`, если методики нет.

    Отдельная подстановка, а не та же самая с флагом (T315, D132): вниз уходят
    два разных значения, и правящий инструмент получает только то, что пришло
    с правом на правку. Одно значение на оба вида означало бы, что правка
    открывается читательским правом при одной опечатке в разборе вида.

    `None` здесь — не «не открыто», а «читать неоткуда»: право на чтение имеет
    всякий заведённый арендатор, и отказывает этот путь только на сервере, где
    методика не настроена вовсе.

    Пространство здесь всегда `DEFAULT_SPACE`, а не `space_of(tenant)`: эталон
    один на всю сеть и лежит в пространстве УК, и партнёр читает его оттуда, а
    не из своего (волна 1, #340) — партнёрского эталона не существует, есть
    только чужая партнёру методика УК.
    """
    хранилище, методика = settings.checklist_store, settings.data_dir
    if хранилище is None or методика is None:
        return None
    if not settings.may_read_checklist(tenant, role):
        return None
    return Store(root=хранилище, live=методика, space=DEFAULT_SPACE)


def _imports_for(settings: Settings, tenant: str) -> Store | None:
    """Хранилище версий для инструментов загрузки — или `None`, если загрузка закрыта.

    Право спрашивается здесь, на входе, по арендатору из токена, как у
    методики (D305, `MCP_IMPORT_TENANTS`). Хранилище наведено на пространство
    арендатора; видимый ему эталон УК находит `checklist_layout.locate`.
    """
    хранилище, методика = settings.checklist_store, settings.data_dir
    if хранилище is None or методика is None or not settings.may_import(tenant):
        return None
    return Store(root=хранилище, live=методика, space=space_of(tenant))


def build_server(settings: Settings) -> ThreadingHTTPServer:
    """Собрать сервер на заданном адресе, но не запускать.

    Отдельно от `serve`, чтобы тест мог поднять сервер на порту, который
    выберет система (`port=0`): фиксированный номер в тестах сталкивается с
    соседней рабочей копией и с забытым процессом.
    """
    return _Server((settings.host, settings.port), settings)


def serve(settings: Settings) -> None:
    """Поднять сервер и обслуживать запросы до Ctrl-C.

    Печатается только адрес: токен в лог не попадает никогда.
    """
    httpd = build_server(settings)
    # Порт берётся у поднятого сокета, а не из настроек: при `port=0` его
    # выбирает система, и напечатанный из настроек ноль был бы ложью.
    port = int(httpd.server_address[1])
    print(
        f"[mcp] слушаю http://{settings.host}:{port}/ — "
        f"арендаторов заведено: {len(settings.tenants)}"
    )
    if settings.trusted_proxies > 0 and settings.trusted_proxy_addrs and not settings.front_key:
        print(
            f"[mcp] {MCP_FRONT_KEY_VAR} не задан: ключ фронта не проверяется, X-Forwarded-For "
            f"верим любому соседу по подсети звена (docs/08-deploy.md, §8.9)",
            file=sys.stderr,
        )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[mcp] остановлен")
    finally:
        httpd.server_close()
