"""Входы в Dodo IS (D640): правила без базы — токен ссылки, срок, состояние, цвет, когда продлевать.

Ядро безопасности ссылки (одноразовость, срок, отзыв) решается здесь и в `test_web_dodois.py`;
каждая проверка прогонялась на сломанной копии (что именно ломали — в комментарии теста).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain import dodois as rules
from src.domain.dodois import Invite, Login
from src.domain.health import GREEN, RED, YELLOW

СЕЙЧАС = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _ссылка(**поля: object) -> Invite:
    основа: dict[str, object] = {
        "id": 1,
        "country": "SI",
        "issued_by": "director",
        "issued_at": СЕЙЧАС - timedelta(hours=1),
        "expires_at": СЕЙЧАС + timedelta(hours=23),
        "used_at": None,
        "revoked_at": None,
    }
    return Invite(**{**основа, **поля})  # type: ignore[arg-type]


def _вход(**поля: object) -> Login:
    основа: dict[str, object] = {
        "country": "SI",
        "contour": "intl",
        "source": "invite",
        "issued_by": "director",
        "account_name": None,
        "account_email": None,
        "linked_at": СЕЙЧАС - timedelta(days=3),
        "scope": rules.SCOPES,
        "units_total": 10,
        "units_open": 10,
        "refreshed_at": СЕЙЧАС - timedelta(hours=10),
        "access_expires_at": СЕЙЧАС + timedelta(hours=14),
        "checked_at": СЕЙЧАС - timedelta(minutes=20),
        "state": rules.OK,
        "reason": None,
    }
    return Login(**{**основа, **поля})  # type: ignore[arg-type]


# --- токен ссылки --------------------------------------------------------------------------


def test_токен_случайный_и_не_короче_тридцати_двух_байт() -> None:
    # Сломанная копия: `TOKEN_BYTES = 8` — длина токена 11 знаков, форма не сходится.
    токены = {rules.new_token() for _ in range(50)}
    assert len(токены) == 50
    for токен in токены:
        assert rules.token_shape_ok(токен)
        assert len(токен) == 43  # 32 байта в base64url без заполнения


@pytest.mark.parametrize("плохой", ["", "a" * 42, "a" * 44, "a" * 42 + "=", "а" * 43, "a b" * 15])
def test_чужая_форма_токена_не_идёт_в_базу(плохой: str) -> None:
    assert not rules.token_shape_ok(плохой)


def test_в_базе_хэш_а_не_токен_и_хэши_сверяются_точно() -> None:
    токен = rules.new_token()
    хэш = rules.hash_token(токен)
    assert len(хэш) == 64 and токен not in хэш
    assert rules.hashes_equal(хэш, rules.hash_token(токен))
    assert not rules.hashes_equal(хэш, rules.hash_token(rules.new_token()))


# --- статус приглашения: срок, одноразовость, отзыв ---------------------------------------


def test_живая_ссылка_пригодна() -> None:
    assert _ссылка().status(СЕЙЧАС) == rules.INVITE_ACTIVE and _ссылка().usable(СЕЙЧАС)


def test_ссылка_живёт_ровно_до_срока() -> None:
    # Сломанная копия: `>` вместо `>=` в `status` — в точку срока ссылка ещё пригодна.
    ссылка = _ссылка(expires_at=СЕЙЧАС)
    assert ссылка.status(СЕЙЧАС) == rules.INVITE_EXPIRED and not ссылка.usable(СЕЙЧАС)
    assert ссылка.usable(СЕЙЧАС - timedelta(seconds=1))


def test_суточный_срок_по_умолчанию() -> None:
    assert rules.INVITE_TTL == timedelta(hours=24)


def test_погашенная_и_отозванная_непригодны_даже_до_срока() -> None:
    # Сломанная копия: не проверять `used_at`/`revoked_at` в `usable` — тест падает.
    assert not _ссылка(used_at=СЕЙЧАС).usable(СЕЙЧАС)
    assert not _ссылка(revoked_at=СЕЙЧАС).usable(СЕЙЧАС)
    assert _ссылка(used_at=СЕЙЧАС).status(СЕЙЧАС) == rules.INVITE_USED
    assert _ссылка(revoked_at=СЕЙЧАС).status(СЕЙЧАС) == rules.INVITE_REVOKED


def test_след_важнее_часов_погашенная_после_срока_остаётся_погашенной() -> None:
    ссылка = _ссылка(expires_at=СЕЙЧАС - timedelta(hours=1), used_at=СЕЙЧАС - timedelta(hours=2))
    assert ссылка.status(СЕЙЧАС) == rules.INVITE_USED


# --- страна и имена записей ----------------------------------------------------------------


@pytest.mark.parametrize("код", ["si", "SLO", "S", "S1", "", "SI ", "С1"])
def test_код_страны_только_две_заглавные_латинские(код: str) -> None:
    assert not rules.is_country(код)
    with pytest.raises(ValueError):
        rules.vault_names(код)


def test_имена_записей_ключей_входа_строчные() -> None:
    assert rules.vault_names("SI") == ("dodois.access.si", "dodois.refresh.si")


# --- состояние и цвет ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("всего", "открыто", "ожидаем"),
    [
        (10, 10, (rules.OK, None)),
        (10, 7, (rules.PARTIAL, None)),
        (10, 0, (rules.PARTIAL, None)),
        (0, 0, (rules.FAILED, "no_units")),
    ],
)
def test_состояние_по_счёту(всего: int, открыто: int, ожидаем: tuple[str, str | None]) -> None:
    # Сломанная копия: `<` заменить на `<=` — 10 из 10 станет «не всё».
    assert rules.counts_state(всего, открыто) == ожидаем


def test_цвет_работает_открыто_не_всё_истёк_сбой() -> None:
    зелёный = rules.status_of(_вход(), СЕЙЧАС)
    assert (зелёный.light, зелёный.reason) == (GREEN, "health.reason.dodois_ok")
    assert dict(зелёный.params) == {"open": 10, "total": 10}
    не_всё = rules.status_of(_вход(state=rules.PARTIAL, units_open=7), СЕЙЧАС)
    assert (не_всё.light, не_всё.reason) == (YELLOW, "health.reason.dodois_partial")
    assert dict(не_всё.params) == {"open": 7, "total": 10}
    истёк = rules.status_of(_вход(state=rules.EXPIRED, reason="refresh_rejected"), СЕЙЧАС)
    assert (истёк.light, истёк.reason) == (RED, "health.reason.dodois_expired")
    сбой = rules.status_of(_вход(state=rules.FAILED, reason="network"), СЕЙЧАС)
    assert (сбой.light, сбой.reason) == (RED, "health.reason.dodois_failed")


def test_проверка_которая_не_идёт_не_остаётся_зелёной() -> None:
    # Сломанная копия: убрать ветку `STALE_AFTER` — давняя проверка остаётся зелёной.
    давняя = _вход(checked_at=СЕЙЧАС - rules.STALE_AFTER - timedelta(minutes=1))
    assert rules.status_of(давняя, СЕЙЧАС).reason == "health.reason.stale"
    assert rules.status_of(_вход(checked_at=None), СЕЙЧАС).reason == "health.reason.stale"


def test_истёкший_вход_красный_даже_при_давней_проверке() -> None:
    давний = _вход(state=rules.EXPIRED, checked_at=СЕЙЧАС - timedelta(days=2))
    assert rules.status_of(давний, СЕЙЧАС).light == RED


# --- когда продлевать ----------------------------------------------------------------------


def _в(час: int) -> datetime:
    return СЕЙЧАС.replace(hour=час)


def test_ночью_раз_в_сутки() -> None:
    вчера = _в(3) - timedelta(hours=24)
    assert rules.refresh_due(вчера, _в(3) + timedelta(hours=1), _в(3))


def test_днём_не_продлеваем_пока_ключ_доступа_жив() -> None:
    assert not rules.refresh_due(_в(3) - timedelta(hours=30), _в(18) + timedelta(hours=2), _в(14))


def test_недавно_продлённый_ночью_не_продляется_снова() -> None:
    assert not rules.refresh_due(_в(3) - timedelta(hours=2), _в(3) + timedelta(hours=22), _в(3))


def test_истёкший_ключ_доступа_продлевается_в_любой_час() -> None:
    # Сломанная копия: убрать первую ветку `refresh_due` — днём истёкший вход не продлится.
    assert rules.refresh_due(_в(3) - timedelta(hours=30), _в(14) - timedelta(minutes=1), _в(14))


def test_вход_без_отметки_продления_продлевается_сразу() -> None:
    assert rules.refresh_due(None, None, _в(14))
