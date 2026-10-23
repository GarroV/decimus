"""Локальные инструменты моста: фото из папки на машине человека (D583).

Мост (`tools/mcp_bridge.sh`) сам обрабатывает `local_photo_folder` и
`local_attach_photos`, остальное отдаёт серверу. Здесь он запускается по-настоящему —
в подставном доме, с поддельным сервером на случайном порту, — потому что ломается
такой скрипт на исполнении (bash 3.2, jq, sips), а не при разборе.

Нужны штатные утилиты macOS: `sips`, `jq`. Без них тест пропускается ГРОМКО — с
причиной в сводке: пропущенная проверка ничего не проверила.
"""

# ruff: noqa: S603 — аргументы subprocess здесь собраны из путей подставного дома, чужого ввода нет
from __future__ import annotations

import base64
import email.parser
import email.policy
import json
import shutil
import struct
import subprocess
import threading
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / "tools" / "mcp_bridge.sh"
UPLOAD_PATH = "/photo-upload/SIGNED"
INSPECTION = "IMP-1"
SIPS = "/usr/bin/sips"

pytestmark = pytest.mark.skipif(
    shutil.which("sips") is None or not (Path("/usr/bin/jq").exists() or shutil.which("jq")),
    reason="нужны sips и jq (macOS): локальные инструменты моста здесь НЕ проверены",
)


@dataclass
class _Seen:
    uploads: list[dict[str, object]] = field(default_factory=list)
    rpc_methods: list[str] = field(default_factory=list)
    upload_had_auth: list[bool] = field(default_factory=list)


def _png(path: Path, width: int, height: int) -> None:
    """Однотонный PNG без зависимостей: проверяется перекладывание, а не картинка."""
    row = b"\x00" + b"\x20\x80\xd0" * width
    raw = zlib.compress(row * height)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    )


@pytest.fixture
def сервер() -> Iterator[tuple[str, _Seen]]:
    seen = _Seen()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _send(self, status: int, body: dict[str, object]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == UPLOAD_PATH:
                seen.upload_had_auth.append("Authorization" in self.headers)
                message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw
                )
                n = ""
                replace = ""
                files: list[tuple[str, int]] = []
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if name == "n":
                        n = part.get_content().strip()
                    elif name == "replace":
                        replace = part.get_content().strip()
                    elif name == "file":
                        files.append(
                            (part.get_filename() or "", len(part.get_payload(decode=True)))
                        )
                seen.uploads.append({"n": n, "files": files, "replace": replace})
                self._send(
                    200,
                    {
                        "attached": [{"file": f, "n": int(n)} for f, _ in files],
                        "refused": [],
                        **({"replaced": True} if replace == "1" else {}),
                    },
                )
                return
            request = json.loads(raw)
            seen.rpc_methods.append(request["method"])
            if request["method"] == "tools/list":
                result: dict[str, object] = {"tools": [{"name": "route"}]}
            else:
                target = f"http://127.0.0.1:{self.server.server_address[1]}{UPLOAD_PATH}"
                text = json.dumps({"id": INSPECTION, "upload_target": target})
                result = {"content": [{"type": "text", "text": text}]}
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/", seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


@pytest.fixture
def дом(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    папка = home / "Downloads" / "test"
    папка.mkdir(parents=True)
    _png(папка / "wide.png", 1000, 600)
    _png(папка / "small.png", 100, 80)
    _png(tmp_path / "seed.png", 300, 200)
    subprocess.run(
        [SIPS, "-s", "format", "jpeg", str(tmp_path / "seed.png"), "--out", str(папка / "a.jpg")],
        check=True,
        capture_output=True,
    )
    (папка / "notes.txt").write_text("не картинка")
    (home / "Documents").mkdir()
    return home


def _run(home: Path, url: str, calls: list[dict[str, object]]) -> list[dict[str, object]]:
    """Прогнать мост по-настоящему: строки в stdin, ответы из stdout."""
    stdin = "".join(json.dumps(c) + "\n" for c in calls)
    прогон = subprocess.run(
        ["/bin/bash", str(BRIDGE)],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "DECIMUS_MCP_URL": url,
            "DECIMUS_MCP_TOKEN": "t" * 40,
        },
    )
    assert прогон.returncode == 0, f"мост упал: {прогон.stderr}"
    return [json.loads(строка) for строка in прогон.stdout.splitlines() if строка.strip()]


def _call(call_id: int, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _jpeg_long_side(data: bytes, tmp: Path) -> int:
    файл = tmp / "decoded.jpg"
    файл.write_bytes(data)
    вывод = subprocess.run(
        [SIPS, "-g", "pixelWidth", "-g", "pixelHeight", str(файл)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    размеры = [int(s.split(":")[1]) for s in вывод.splitlines() if "pixel" in s]
    return max(размеры)


def test_список_инструментов_дополнен_локальными(сервер: tuple[str, _Seen], дом: Path) -> None:
    url, seen = сервер

    [ответ] = _run(дом, url, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])

    имена = [t["name"] for t in ответ["result"]["tools"]]  # type: ignore[index]
    assert имена == ["route", "local_photo_folder", "local_attach_photos"]
    assert seen.rpc_methods == ["tools/list"]


def test_папка_отдаёт_имена_и_уменьшенные_снимки(
    сервер: tuple[str, _Seen], дом: Path, tmp_path: Path
) -> None:
    url, seen = сервер

    [ответ] = _run(дом, url, [_call(2, "local_photo_folder", {"path": "Загрузки/test"})])

    assert "isError" not in ответ["result"], ответ  # type: ignore[operator]
    блоки = ответ["result"]["content"]  # type: ignore[index]
    картинки = [b for b in блоки if b["type"] == "image"]
    подписи = [b["text"] for b in блоки if b["type"] == "text"]
    assert len(картинки) == 3, "ждали три снимка (txt не картинка)"
    assert "Photos in the folder: 3" in подписи[0]
    assert [s.split(". ", 1)[1] for s in подписи[1:]] == ["a.jpg", "small.png", "wide.png"]
    assert all(b["mimeType"] == "image/jpeg" for b in картинки)
    декодированные = [base64.b64decode(b["data"]) for b in картинки]
    assert all(d[:2] == b"\xff\xd8" for d in декодированные), "это не JPEG"
    assert _jpeg_long_side(декодированные[2], tmp_path) == 768, "wide.png не уменьшен до 768"
    assert _jpeg_long_side(декодированные[1], tmp_path) == 100, "малый снимок растянут"
    assert seen.rpc_methods == [], "локальный вызов ушёл на сервер"


def test_папка_отдаётся_порциями(сервер: tuple[str, _Seen], дом: Path) -> None:
    url, _ = сервер

    [первая, вторая] = _run(
        дом,
        url,
        [
            _call(3, "local_photo_folder", {"path": "~/Downloads/test", "limit": 2}),
            _call(4, "local_photo_folder", {"path": "~/Downloads/test", "offset": 2, "limit": 2}),
        ],
    )

    assert sum(b["type"] == "image" for b in первая["result"]["content"]) == 2  # type: ignore[index]
    assert "Next page: offset 2" in первая["result"]["content"][0]["text"]  # type: ignore[index]
    assert sum(b["type"] == "image" for b in вторая["result"]["content"]) == 1  # type: ignore[index]
    assert "last page" in вторая["result"]["content"][0]["text"]  # type: ignore[index]


def test_за_пределы_дома_мост_не_ходит(
    сервер: tuple[str, _Seen], дом: Path, tmp_path: Path
) -> None:
    url, _ = сервер
    снаружи = tmp_path / "outside"
    снаружи.mkdir()
    _png(снаружи / "secret.png", 50, 50)
    (дом / "Downloads" / "link").symlink_to(снаружи)

    ответы = _run(
        дом,
        url,
        [
            _call(5, "local_photo_folder", {"path": "/etc"}),
            _call(6, "local_photo_folder", {"path": "Downloads/../../outside"}),
            _call(7, "local_photo_folder", {"path": "Downloads/link"}),
            _call(8, "local_photo_folder", {"path": str(снаружи)}),
        ],
    )

    for ответ in ответы:
        assert ответ["result"]["isError"] is True, ответ  # type: ignore[index]
        assert all(b["type"] == "text" for b in ответ["result"]["content"])  # type: ignore[index]


def test_кадры_уходят_на_адрес_загрузки_с_номерами_находок(
    сервер: tuple[str, _Seen], дом: Path
) -> None:
    url, seen = сервер

    [ответ] = _run(
        дом,
        url,
        [
            _call(
                9,
                "local_attach_photos",
                {
                    "inspection_id": INSPECTION,
                    "folder": "Downloads/test",
                    "items": [
                        {"n": 2, "files": ["a.jpg", "wide.png"]},
                        {"n": 5, "files": ["small.png", "../seed.png", "notes.txt"]},
                    ],
                },
            )
        ],
    )

    assert "isError" not in ответ["result"], ответ  # type: ignore[operator]
    итог = json.loads(ответ["result"]["content"][0]["text"])  # type: ignore[index]
    assert итог["attached_total"] == 3
    assert итог["refused_total"] == 2
    отказы = {r["file"] for f in итог["findings"] for r in f["refused"]}
    assert отказы == {"../seed.png", "notes.txt"}, "имя вне папки или не картинка прошло"
    отправлено = {u["n"]: [f for f, _ in u["files"]] for u in seen.uploads}  # type: ignore[union-attr]
    assert отправлено == {"2": ["a.jpg", "wide.png"], "5": ["small.png"]}
    размеры = {f: s for u in seen.uploads for f, s in u["files"]}  # type: ignore[union-attr]
    assert размеры["wide.png"] == (дом / "Downloads" / "test" / "wide.png").stat().st_size, (
        "ушёл не оригинал"
    )
    assert seen.upload_had_auth == [False, False], "токен MCP ушёл на адрес загрузки"
    assert "tools/call" in seen.rpc_methods


def test_без_jq_всё_остальное_работает_как_раньше(сервер: tuple[str, _Seen], дом: Path) -> None:
    """Нет jq — локальные инструменты не объявляются, а мост по-прежнему перекладывает строки."""
    url, seen = сервер
    прогон = subprocess.run(
        ["/bin/bash", str(BRIDGE)],
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={
            "HOME": str(дом),
            "PATH": "/usr/bin:/bin",
            "DECIMUS_MCP_JQ": "none",
            "DECIMUS_MCP_URL": url,
            "DECIMUS_MCP_TOKEN": "t" * 40,
        },
    )

    assert прогон.returncode == 0, прогон.stderr
    assert [t["name"] for t in json.loads(прогон.stdout)["result"]["tools"]] == ["route"]
    assert "нет jq" in прогон.stderr
    assert seen.rpc_methods == ["tools/list"]


def test_heic_превращается_в_jpeg(сервер: tuple[str, _Seen], дом: Path, tmp_path: Path) -> None:
    url, _ = сервер
    папка = дом / "Downloads" / "heic"
    папка.mkdir()
    _png(tmp_path / "h.png", 900, 700)
    сделан = subprocess.run(
        [SIPS, "-s", "format", "heic", str(tmp_path / "h.png"), "--out", str(папка / "P1.HEIC")],
        check=False,
        capture_output=True,
    )
    if сделан.returncode != 0 or not (папка / "P1.HEIC").exists():
        pytest.skip("sips на этой машине не пишет HEIC: HEIC НЕ проверен")

    [ответ] = _run(дом, url, [_call(10, "local_photo_folder", {"path": "Downloads/heic"})])

    [картинка] = [b for b in ответ["result"]["content"] if b["type"] == "image"]  # type: ignore[index]
    данные = base64.b64decode(картинка["data"])
    assert данные[:2] == b"\xff\xd8", "HEIC не стал JPEG"
    assert _jpeg_long_side(данные, tmp_path) == 768


def test_замена_передаётся_серверу_и_итог_replaced_доходит_до_модели(
    сервер: tuple[str, _Seen], дом: Path
) -> None:
    url, seen = сервер

    [ответ] = _run(
        дом,
        url,
        [
            _call(
                11,
                "local_attach_photos",
                {
                    "inspection_id": INSPECTION,
                    "folder": "Downloads/test",
                    "replace": True,
                    "items": [{"n": 3, "files": ["a.jpg", "wide.png"]}],
                },
            )
        ],
    )

    assert "isError" not in ответ["result"], ответ  # type: ignore[operator]
    итог = json.loads(ответ["result"]["content"][0]["text"])  # type: ignore[index]
    assert итог["findings"][0]["replaced"] is True
    assert [(u["n"], u["replace"]) for u in seen.uploads] == [("3", "1")]  # type: ignore[union-attr]


def test_без_replace_кадры_добавляются_и_поля_замены_нет(
    сервер: tuple[str, _Seen], дом: Path
) -> None:
    url, seen = сервер

    [ответ] = _run(
        дом,
        url,
        [
            _call(
                12,
                "local_attach_photos",
                {
                    "inspection_id": INSPECTION,
                    "folder": "Downloads/test",
                    "items": [{"n": 3, "files": ["a.jpg"]}],
                },
            )
        ],
    )

    итог = json.loads(ответ["result"]["content"][0]["text"])  # type: ignore[index]
    assert "replaced" not in итог["findings"][0]
    assert [u["replace"] for u in seen.uploads] == [""]  # type: ignore[union-attr]


def test_замена_с_негодным_файлом_ничего_не_отправляет(
    сервер: tuple[str, _Seen], дом: Path
) -> None:
    """Старые кадры не должны уйти из-за урезанного набора: негодный файл рушит всю замену."""
    url, seen = сервер

    [ответ] = _run(
        дом,
        url,
        [
            _call(
                13,
                "local_attach_photos",
                {
                    "inspection_id": INSPECTION,
                    "folder": "Downloads/test",
                    "replace": True,
                    "items": [{"n": 4, "files": ["a.jpg", "notes.txt"]}],
                },
            )
        ],
    )

    итог = json.loads(ответ["result"]["content"][0]["text"])  # type: ignore[index]
    assert seen.uploads == [], "замена с негодным файлом ушла на сервер"
    assert итог["attached_total"] == 0
    assert итог["findings"][0]["replaced"] is False
    assert {r["file"] for r in итог["findings"][0]["refused"]} == {"a.jpg", "notes.txt"}


def test_replace_не_булев_отказ(сервер: tuple[str, _Seen], дом: Path) -> None:
    url, seen = сервер

    [ответ] = _run(
        дом,
        url,
        [
            _call(
                14,
                "local_attach_photos",
                {
                    "inspection_id": INSPECTION,
                    "folder": "Downloads/test",
                    "replace": "yes",
                    "items": [{"n": 4, "files": ["a.jpg"]}],
                },
            )
        ],
    )

    assert ответ["result"]["isError"] is True  # type: ignore[index]
    assert seen.uploads == []
