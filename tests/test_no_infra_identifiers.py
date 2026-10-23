"""В публичном репозитории нет адресов и идентификаторов боевой инфраструктуры (D431, F-011).

Репозиторий публичный (D001, D431): IP сервера, служебные хосты, tailnet, ID
сервиса Workers VPC и проект Google в нём не хранятся. Тест просматривает все
отслеживаемые файлы и красный, пока хоть одно значение осталось. БД не нужна.

Тест не содержит самих значений (иначе он сам публиковал бы то, что прячет):
только общие шаблоны. Адрес workers.dev — публичный адрес продукта (D304), его не
трогаем.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HINT = (
    "значение инфраструктуры в репозиторий не кладётся (D431): в документах — заглушка "
    "(<VPS_IP>, <ORIGIN_HOST>, <TAILNET_HOST>, <GCP_PROJECT>, <VPC_SERVICE_ID>), в "
    "конфигах и коде — переменная окружения / front/.deploy.env (docs/08-deploy.md §8.9)"
)

#: (название, регулярное выражение)
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("служебный хост sslip.io / nip.io", re.compile(r"\b(?:sslip|nip)\.io\b", re.IGNORECASE)),
    ("tailnet-имя ts.net", re.compile(r"\bts\.net\b", re.IGNORECASE)),
    ("имя tailnet tailXXXXXX", re.compile(r"\btail[0-9a-f]{6}\b")),
    # Диапазон CGNAT 100.64.0.0/10, из которого Tailscale раздаёт адреса.
    (
        "tailnet-адрес 100.64.0.0/10",
        re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.])"),
    ),
    (
        "проект Google Cloud (имя-цифры)",
        re.compile(r"(?:проект|project)[^\n]{0,40}?\b[a-z][a-z0-9]*-\d{6,}\b", re.IGNORECASE),
    ),
)

IPV4 = re.compile(r"(?<![\d.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
#: Строки конфигов Cloudflare, где UUID — идентификатор инфраструктуры.
CLOUDFLARE_ID_LINE = re.compile(r"service_id|vpc|tunnel", re.IGNORECASE)
#: Не адреса сервера: сама сеть CGNAT (код проверяет попадание в неё), условный адрес
#: из тестов и публичный DNS.
ALLOWED_ADDRESSES = frozenset({"100.64.0.0", "100.64.1.2", "8.8.8.8", "1.1.1.1"})
#: Версия, а не адрес: `Chrome/141.0.0.0`, `socat:1.8.0.0`, пин lock-файла `brotlicffi==1.2.1.0`.
VERSION_PREFIX = re.compile(r"(?:[A-Za-z][/:v]|[=<>~!]=)$")

SELF = "tests/test_no_infra_identifiers.py"


def is_public_ipv4(text: str, start: int) -> bool:
    match = IPV4.match(text, start)
    if match is None or VERSION_PREFIX.search(text[max(0, start - 2) : start]):
        return False
    try:
        address = ipaddress.ip_address(match.group(0))
    except ValueError:
        return False  # не адрес: 999.1.1.1, номер версии
    return address.is_global and match.group(0) not in ALLOWED_ADDRESSES


def scan(files: Iterable[tuple[str, str]]) -> list[str]:
    """Вернуть строки `файл:строка: что нашли` по всем совпадениям."""
    found: list[str] = []
    for path, text in files:
        for number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                if any(m.group(0) not in ALLOWED_ADDRESSES for m in pattern.finditer(line)):
                    found.append(f"{path}:{number}: {name}")
            if any(is_public_ipv4(line, m.start()) for m in IPV4.finditer(line)):
                found.append(f"{path}:{number}: публичный IPv4-адрес")
            if CLOUDFLARE_ID_LINE.search(line) and UUID.search(line):
                found.append(f"{path}:{number}: ID инфраструктуры Cloudflare (UUID)")
    return found


def tracked_texts() -> list[tuple[str, str]]:
    names = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 — git из PATH, как в соседних тестах
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    texts: list[tuple[str, str]] = []
    for name in filter(None, names):
        path = ROOT / name
        if name == SELF or not path.is_file():
            continue
        try:
            texts.append((name, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue  # бинарный файл
    return texts


def test_tracked_files_have_no_infra_identifiers() -> None:
    found = scan(tracked_texts())
    assert not found, "\n".join([*found, "", HINT])


# Проверка самой проверки: на заведомо плохом входе она обязана краснеть.
# Входы выдуманные (документационные диапазоны и случайные имена).
BAD_LINES = {
    "public-ip": "host 93.184.216.34",
    "sslip": "a.b.203-0-113-7.sslip.io",
    "nip": "a.203.0.113.7.nip.io",
    "tailnet": "m.tailabc123.ts.net",
    "cgnat": "addr 100.101.2.3",
    "gcp": "проект myapp-123456",
    "cloudflare-id": '"service_id": "123e4567-e89b-12d3-a456-426614174000"',
}


@pytest.mark.parametrize("line", list(BAD_LINES.values()), ids=list(BAD_LINES))
def test_scanner_flags_bad_line(line: str) -> None:
    found = scan([("doc.md", line)])
    assert found and found[0].startswith("doc.md:1: ")


def test_scanner_ignores_public_product_address_versions_and_doc_ranges() -> None:
    text = (
        "https://decimus.vasiliy-garro.workers.dev Chrome/141.0.0.0 socat:1.8.0.0 "
        "brotlicffi==1.2.1.0 x>=2.3.4.5 "
        "203.0.113.7 198.51.100.7 192.0.2.1 127.0.0.1 10.0.0.5 100.64.1.2 "
        '"id": "123e4567-e89b-12d3-a456-426614174000" <ORIGIN_HOST>'
    )
    assert not scan([("doc.md", text)])
