"""Порча второй ступени входа (D463): каждая сломанная защита обязана уронить свой тест.

Запуск: `.venv/bin/python tools/porcha_second_factor.py` из корня репозитория
(`make porcha-second-factor`, нужна тестовая база — как у `make test`). Каждый случай
подменяет одну строку кода, гоняет ровно её тест и возвращает файл на место.
«НЕ ПРИМЕНИЛАСЬ» — код уехал, и порчу надо обновить: молча зелёный прогон без подмены и
есть та ложь, ради которой скрипт заведён.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`): порча того же размера в ту же секунду
подхватила бы кэш, и тест «поймал» бы исправный код.
"""

import os
import pathlib
import subprocess
import sys

T = "tests/"
J = T + "test_web_second_factor_journeys.py::"
D = T + "test_db_second_factor.py::"
R = T + "test_webauthn_rp.py::"
Z = T + "test_second_factor_domain.py::"
cases = [
    # Полувход не открывает ни одного маршрута.
    (
        "src/web/auth.py",
        "        if вторая is not None:\n            return вторая\n"
        "        session = open_session(account, ip=откуда, user_agent=браузер)",
        "        session = open_session(account, ip=откуда, user_agent=браузер)",
        J + "test_полувход_не_открывает_ни_одного_маршрута",
    ),
    # Сама open_session не выдаёт полную сессию без второй ступени.
    (
        "src/db/web_access.py",
        "     where %(second)s\n        or not (exists",
        "     where true\n        or not (exists",
        D + "test_полная_сессия_человеку_со_способом_без_второй_ступени_не_выдаётся",
    ),
    # Новый путь входа, открывающий сессию мимо списка, ловится перечислением.
    (
        "src/web/second_step.py",
        "        session = open_session(account, ip=откуда, user_agent=браузер, second_step=True)",
        "        session = open_session(account, ip=откуда, user_agent=браузер, second_step=True)\n"
        "        open_session(account, ip=откуда, user_agent=браузер, second_step=True)",
        T + "test_session_issuers.py::test_полную_сессию_открывают_только_названные_места",
    ),
    # Админ без способа не обходит подключение.
    (
        "src/web/auth.py",
        "            second_step.must_enroll(account)\n            and request.endpoint",
        "            False\n            and request.endpoint",
        J + "test_админ_без_способа_не_обходит_подключение",
    ),
    # Резервный код одноразовый.
    (
        "src/db/second_factor.py",
        '" where user_id = %s and code_hash = %s and used_at is null"',
        '" where user_id = %s and code_hash = %s"',
        J + "test_резервный_код_одноразовый",
    ),
    (
        "src/db/second_factor.py",
        '" where user_id = %s and code_hash = %s and used_at is null"',
        '" where user_id = %s and code_hash = %s"',
        D + "test_резервный_код_одноразовый",
    ),
    # Повтор кода приложения.
    (
        "src/db/second_factor.py",
        '" and (last_step is null or last_step < %s)",',
        '" and (true or last_step < %s)",',
        J + "test_верный_код_выдаёт_сессию_а_повтор_того_же_кода_отвергается",
    ),
    (
        "src/db/second_factor.py",
        '" and (last_step is null or last_step < %s)",',
        '" and (true or last_step < %s)",',
        D + "test_шаг_totp_повторно_не_принимается",
    ),
    # Откат счётчика ключа: библиотека и своя гонка.
    (
        "src/web/webauthn_rp.py",
        "credential_current_sign_count=sign_count,",
        "credential_current_sign_count=0,",
        R + "test_откат_счётчика_подписей_отвергается",
    ),
    (
        "src/web/webauthn_rp.py",
        "credential_current_sign_count=sign_count,",
        "credential_current_sign_count=0,",
        J + "test_откат_счётчика_ключа_отвергается",
    ),
    (
        "src/db/second_factor.py",
        '" where id = %s and sign_count = %s",',
        '" where id = %s and %s >= 0",',
        D + "test_счётчик_ключа_принимается_только_от_прежнего",
    ),
    # Чужое происхождение.
    (
        "src/web/webauthn_rp.py",
        "            expected_origin=party.origin,\n            require_user_verification=True,",
        '            expected_origin=[party.origin, "https://evil.example.test"],\n'
        "            require_user_verification=True,",
        R + "test_регистрация_с_чужого_происхождения_отвергается",
    ),
    (
        "src/web/webauthn_rp.py",
        "            expected_origin=party.origin,\n            credential_public_key=public_key,",
        '            expected_origin=[party.origin, "https://evil.example.test",'
        ' "https://evil.example"],\n            credential_public_key=public_key,',
        R + "test_вход_с_чужого_происхождения_отвергается",
    ),
    (
        "src/web/webauthn_rp.py",
        "            expected_origin=party.origin,\n            credential_public_key=public_key,",
        '            expected_origin=[party.origin, "https://evil.example.test",'
        ' "https://evil.example"],\n            credential_public_key=public_key,',
        J + "test_чужое_происхождение_подписи_отвергается",
    ),
    # Проверка человека (Touch ID / PIN).
    (
        "src/web/webauthn_rp.py",
        "            credential_current_sign_count=sign_count,\n"
        "            require_user_verification=True,",
        "            credential_current_sign_count=sign_count,\n"
        "            require_user_verification=False,",
        R + "test_вход_без_проверки_пользователя_отвергается",
    ),
    # Вызов одноразовый.
    (
        "src/db/second_factor.py",
        '            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s"\n'
        '            " returning challenge, user_id, expires_at > now()",',
        '            "select challenge, user_id, expires_at > now() from web_webauthn_challenges"\n'
        '            " where bound_fp = %s and purpose = %s",',
        D + "test_вызов_ключа_снимается_один_раз",
    ),
    (
        "src/db/second_factor.py",
        '            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s"\n'
        '            " returning challenge, user_id, expires_at > now()",',
        '            "select challenge, user_id, expires_at > now() from web_webauthn_challenges"\n'
        '            " where bound_fp = %s and purpose = %s",',
        J + "test_повтор_вызова_ключа_отвергается",
    ),
    # Последний способ админа и чужой ключ.
    (
        "src/domain/second_factor.py",
        "    return remaining_factors > 0 or not is_required(role)",
        "    return True",
        D + "test_админу_последний_ключ_не_снять",
    ),
    (
        "src/db/second_factor.py",
        '"delete from web_passkeys where id = %s and user_id = %s",',
        '"delete from web_passkeys where id = %s and %s::text is not null",',
        J + "test_чужой_номер_ключа_в_адресе_ничего_не_снимает",
    ),
    # Аудит экрана «Вход и защита»: окно, снятие, чужие сессии, сброс, CSRF.
    (
        "src/domain/second_factor.py",
        "    if is_required(role) and not has_factor:\n        return PENDING_TTL\n",
        "",
        Z + "test_у_админа_без_способа_окно_пять_минут",
    ),
    (
        "src/domain/second_factor.py",
        "    if is_required(role) and not has_factor:\n        return PENDING_TTL\n",
        "",
        J + "test_админ_без_способа_подключает_только_в_первые_пять_минут",
    ),
    (
        "src/domain/second_factor.py",
        "    return passed_second_step and is_fresh_login(",
        "    return is_fresh_login(",
        Z + "test_снимать_способ_можно_только_после_второй_ступени_и_свежим_входом",
    ),
    (
        "src/domain/second_factor.py",
        "    return passed_second_step and is_fresh_login(",
        "    return is_fresh_login(",
        J + "test_сессия_первой_ступени_снять_способ_не_может",
    ),
    (
        "src/web/security_screen.py",
        "    def security_totp_remove() -> Response | tuple[Response, int]:\n"
        "        refuse_foreign_origin()\n        account = _me()\n"
        "        if not may_remove(account):",
        "    def security_totp_remove() -> Response | tuple[Response, int]:\n"
        "        refuse_foreign_origin()\n        account = _me()\n"
        "        if not is_fresh(account):",
        J + "test_сессия_первой_ступени_снять_способ_не_может",
    ),
    (
        "src/db/second_factor.py",
        "    if строка is None or int(строка[0]) > 0:\n        return\n",
        "    return\n",
        J + "test_первый_способ_закрывает_другие_сессии_человека",
    ),
    (
        "src/web/users_screen.py",
        "        if вошедший is None or not may_remove_factor(вошедший):",
        "        if вошедший is None:",
        J + "test_сброс_чужой_ступени_сессией_без_второй_ступени_отвергается",
    ),
]

bad = 0
for path, old, new, test in cases:
    p = pathlib.Path(path)
    orig = p.read_text(encoding="utf-8")
    if old not in orig:
        print("НЕ ПРИМЕНИЛАСЬ:", path, repr(old[:60]))
        bad += 1
        continue
    p.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run(  # noqa: S603 — свой pytest и свои пути из списка выше
            [
                ".venv/bin/pytest",
                "-q",
                "-x",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                "-p",
                "no:randomly",
                test,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
    finally:
        p.write_text(orig, encoding="utf-8")
    ok = r.returncode != 0
    line = [row for row in r.stdout.splitlines() if row.startswith("E ")][:1]
    print(
        ("ЛОВИТ " if ok else "НЕ ЛОВИТ ") + test.split("::")[1],
        "|",
        (line[0][:110] if line else ""),
    )
    bad += 0 if ok else 1
sys.exit(1 if bad else 0)
