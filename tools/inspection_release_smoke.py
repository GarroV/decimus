"""Живой смоук перед выездами: демо-вход и экраны, публичные двери прода.

Запускать с машины вне сервера: python tools/inspection_release_smoke.py.
Боевые проверки не создаёт и не меняет. Проверяет HTTP и содержимое HTML,
не выполнение JavaScript и не интерфейс Telegram.
"""

from __future__ import annotations

import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request

DEMO = "https://decimus-demo.vasiliy-garro.workers.dev"
PROD = "https://decimus.vasiliy-garro.workers.dev"
MCP = "https://decimus-mcp.vasiliy-garro.workers.dev"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Проверка двери требует исходного 302, а не конечного 200 лендинга."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def main() -> int:
    """Проверить рабочие страницы снаружи; ошибка — ненулевой код возврата."""
    jar = http.cookiejar.CookieJar()
    demo = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    public = urllib.request.build_opener(NoRedirect())
    public.addheaders = [("User-Agent", "Decimus-release-smoke")]

    def read(path: str, *, post: bool = False) -> str:
        req = urllib.request.Request(  # noqa: S310 — фиксированный HTTPS-адрес демо
            DEMO + path,
            data=b"" if post else None,
            headers={"Origin": DEMO, "User-Agent": "Decimus-release-smoke"},
        )
        with demo.open(req, timeout=45) as response:
            body: str = response.read().decode()
            if response.status != 200 or "/login" in response.url:
                raise RuntimeError(f"демо {path}: вход или страница не открылись")
            return body

    try:
        read("/demo?lang=ru")
        read("/demo/admin?lang=ru", post=True)
        print("демо: вход администратором OK")
        paths = (
            "/overview?lang=ru",
            "/inspections?lang=ru",
            "/ratings/rs?lang=ru",
            "/ratings/rko?lang=ru",
            "/ratings/inspections?lang=ru",
            "/ratings/inspections?history_grain=month&history_year=2026&lang=ru",
            "/country/AM?lang=ru",
            "/tg/walk",
        )
        for path in paths:
            body = read(path)
            if any(
                word in body
                for word in (
                    "Could not load inspection history",
                    "Не удалось прочитать историю проверок",
                    "Traceback (most recent call last)",
                )
            ):
                raise RuntimeError(f"демо {path}: ошибка чтения или рендера")
            if (
                path.startswith(("/ratings/inspections", "/country/"))
                and "history_grain" not in body
            ):
                raise RuntimeError(f"демо {path}: истории проверок нет")
            print(f"демо {path}: OK")
        for path in ("/country/AZ", "/ratings/inspections"):
            try:
                public.open(PROD + path, timeout=30)
            except urllib.error.HTTPError as exc:
                target = urllib.parse.urlsplit(exc.headers.get("Location", "")).path
                if exc.code != 302 or target not in ("/welcome", "/login"):
                    raise RuntimeError(f"прод {path}: неверный отказ {exc.code}") from None
            else:
                raise RuntimeError(f"прод {path}: нет перенаправления на вход")
            print(f"прод {path}: граница входа OK")
        for path in ("/login", "/tg/walk"):
            with public.open(PROD + path, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"прод {path}: HTTP {response.status}")
            print(f"прод {path}: HTTP 200 OK")
        try:
            public.open(
                urllib.request.Request(MCP + "/mcp", data=b""),  # noqa: S310 — свой HTTPS
                timeout=30,
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError(f"MCP: неверный отказ {exc.code}") from None
        else:
            raise RuntimeError("MCP: нет отказа без токена")
        print("MCP снаружи: HTTP 401 без токена OK")
    except (OSError, RuntimeError) as exc:
        print(f"СМОУК КРАСНЫЙ: {type(exc).__name__}: {exc}")
        return 1
    print("HTTP-СМОУК ЗЕЛЁНЫЙ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
