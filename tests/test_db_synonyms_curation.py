"""T292: неверный синоним снимается и переправляется — правом, а не накатом.

T284 завела карту синонимов и намеренно не дала роли приложения ни `UPDATE`,
ни `DELETE`: выученное не должно переписываться ошибкой одного аудитора. Цена
этого выбора была названа тогда же — убрать неверную строку стало нечем, и она
продолжала уводить поиск к чужому пункту. Здесь цена и закрывается: правка
карты — работа управляющей компании, и приходит она под ролью администратора
(`DATABASE_RETRACTION_URL`), а не под ролью приложения.

Свойства, которые проверяются ниже:

* снятие — ПОМЕТКА, а не удаление строки (тем же приёмом, что снятие проверки,
  D089): видно, что синоним был и почему его больше нет;
* снятую формулировку машина не выучивает заново — иначе следующий же обход
  вернул бы ровно ту ошибку, ради снятия которой всё и затевалось;
* заведённое человеком (`MANUAL`) и накопленное машиной (`LEARNED`) снимаются
  ОДИНАКОВО: неверный синоним неверен независимо от того, кто его завёл;
* правка пункта записывает, куда строка вела раньше, — промах модели остаётся
  виден после исправления.

Разграничение ролей здесь проверяется продуктовыми вызовами. То, что его
держит база, а не эти вызовы, — тема соседнего файла
(`test_db_synonyms_policies.py`): там всё идёт сырым SQL под обеими ролями.

Формулировки в оснастке выдуманы целиком: связывание проверяется кодом пункта,
а не тем, что это за пункт (`tests/test_methodology_leak.py` не пускает в
публичный репозиторий ни одной настоящей формулировки методики).
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import RETRACTION_URL_VAR, set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.errors import ConfigError, SynonymError  # noqa: E402
from src.db.synonyms import (  # noqa: E402
    ALREADY_POINTED,
    ALREADY_RETRACTED,
    LEARNED,
    MANUAL,
    REPOINTED,
    RESTORED,
    RETRACTED,
    list_phrases,
    lookup_phrase,
    remember_phrase,
    repoint_phrase,
    retract_phrase,
)

pytestmark = requires_db

#: Выдуманные коды пунктов. Настоящие коды методики сюда не попадают намеренно:
#: связывание проверяется кодом как таковым, а не тем, какой он.
ПУНКТ = "ZZ9.1"
ДРУГОЙ_ПУНКТ = "ZZ9.2"
ТРЕТИЙ_ПУНКТ = "ZZ9.3"

ФРАЗА = "жёлтый зонт под потолком"
ПРИЧИНА = "увело не к тому пункту"


@pytest.fixture
def curation_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Подключение администратора рядом с подключением приложения.

    Однострочная обёртка над помощником из `db_harness` — почему не общая
    фикстура, написано там же. Карту правит та же роль, что снимает проверки
    (`dodo_audit_admin`), и приходит она той же переменной окружения.
    """
    return set_retraction_env(db_env, monkeypatch)


# --- снятие: пометка, а не удаление -------------------------------------------


def test_снятый_синоним_остаётся_строкой_с_причиной(curation_env: str) -> None:
    """Строка не удаляется: видно, что синоним был и почему его больше нет.

    По пустому месту не видно ничего — ни того, что машина однажды выучила эту
    формулировку, ни того, кто и зачем её убрал (тот же довод, что у снятия
    проверки, D089).
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    снято = retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    assert снято.outcome == RETRACTED
    assert снято.alias.retracted_at is not None
    assert снято.alias.retraction_reason == ПРИЧИНА
    assert снято.alias.item_code == ПУНКТ, "снятие не трогает код пункта"


def test_снятый_синоним_не_находится_поиском(curation_env: str) -> None:
    """Главное, ради чего задача и делается: строка перестаёт уводить поиск."""
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    assert lookup_phrase(ФРАЗА, lang="ru") is None


def test_снятого_синонима_нет_в_карте_а_с_признанием_он_виден(curation_env: str) -> None:
    """Карта по умолчанию отдаёт только живые строки.

    Потребитель (T285) берёт карту разом и сопоставляет по ней; попади туда
    снятая строка, снятие не значило бы ничего — поиск шёл бы мимо базы, но по
    тем же данным.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    живые = list_phrases(lang="ru")
    все = list_phrases(lang="ru", include_retracted=True)

    assert [строка.phrase for строка in живые] == []
    assert [строка.phrase for строка in все] == [ФРАЗА]
    assert все[0].retraction_reason == ПРИЧИНА


def test_повторное_снятие_причину_не_переписывает(curation_env: str) -> None:
    """Иначе снятие превратилось бы в способ править основание задним числом.

    Тот же довод и тот же исход, что у повторного снятия проверки: возвращается
    ЗАПИСАННАЯ причина, а не переданная вызовом.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    повтор = retract_phrase(ФРАЗА, lang="ru", reason="совсем другая причина")

    assert повтор.outcome == ALREADY_RETRACTED
    assert повтор.alias.retraction_reason == ПРИЧИНА


def test_причина_снятия_обязательна(curation_env: str) -> None:
    """Без причины снятие неотличимо от подчистки карты (D089 для проверок).

    Отказ обязан назвать, чего не хватает, а не прийти текстом нарушенного
    ограничения схемы: ограничение — второй заслон, а не сообщение человеку.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    with pytest.raises(SynonymError) as отказ:
        retract_phrase(ФРАЗА, lang="ru", reason="   ")

    assert "причин" in str(отказ.value).lower()
    assert lookup_phrase(ФРАЗА, lang="ru") is not None, "отказ не должен ничего менять"


@pytest.mark.parametrize("происхождение", [LEARNED, MANUAL])
def test_заведённое_человеком_и_машиной_снимается_одинаково(
    curation_env: str, происхождение: str
) -> None:
    """Неверный синоним неверен независимо от того, кто его завёл.

    Два разных снятия означали бы два места, где можно ошибиться, и вопрос «а
    этот кем заведён» перед каждой правкой. Разница между происхождениями
    появляется ПОСЛЕ снятия, а не в нём (см. тест про повторное выучивание):
    машина своё выучила бы заново, человек — нет.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru", origin=происхождение)

    снято = retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    assert снято.outcome == RETRACTED
    assert снято.alias.origin == происхождение, "снятие не переписывает происхождение"
    assert lookup_phrase(ФРАЗА, lang="ru") is None


def test_снятую_формулировку_машина_заново_не_выучивает(curation_env: str) -> None:
    """Иначе следующий обход вернул бы ровно ту ошибку, ради которой снимали.

    Машина приходит с тем же непрямым совпадением и тем же неверным кодом —
    ответ ей исход `RETRACTED`, а не новая строка: место занято снятой
    записью, и занято оно навсегда.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    повтор = remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    assert повтор.outcome == RETRACTED
    assert повтор.alias.retraction_reason == ПРИЧИНА
    assert lookup_phrase(ФРАЗА, lang="ru") is None
    assert len(list_phrases(lang="ru", include_retracted=True)) == 1, "второй строки нет"


def test_снятую_формулировку_не_выучивает_и_другой_пункт(curation_env: str) -> None:
    """Снятая строка держит ключ и против ДРУГОГО кода.

    Разночтение (`CONFLICT`) тут не при чём: карта не спорит о пункте, она
    говорит, что эта формулировка снята управляющей компанией.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    повтор = remember_phrase(ФРАЗА, item_code=ДРУГОЙ_ПУНКТ, lang="ru")

    assert повтор.outcome == RETRACTED
    assert повтор.alias.item_code == ПУНКТ, "в базе лежит снятая строка, а не новая"


# --- правка пункта ------------------------------------------------------------


def test_синоним_переправляется_на_другой_пункт(curation_env: str) -> None:
    """Вторая половина дыры: строка не только снимается, но и чинится на месте."""
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    правка = repoint_phrase(ФРАЗА, lang="ru", item_code=ДРУГОЙ_ПУНКТ, reason=ПРИЧИНА)

    assert правка.outcome == REPOINTED
    assert правка.alias.item_code == ДРУГОЙ_ПУНКТ
    найден = lookup_phrase(ФРАЗА, lang="ru")
    assert найден is not None
    assert найден.item_code == ДРУГОЙ_ПУНКТ


def test_правка_оставляет_видимым_куда_строка_вела_раньше(curation_env: str) -> None:
    """Промах модели должен остаться виден после исправления.

    Иначе разбор «что машина навыучивала неверно» упирается в карту, где все
    строки выглядят правильными: исправленные от изначально верных ничем не
    отличаются.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    правка = repoint_phrase(ФРАЗА, lang="ru", item_code=ДРУГОЙ_ПУНКТ, reason=ПРИЧИНА)

    assert правка.alias.previous_item_code == ПУНКТ
    assert правка.alias.correction_reason == ПРИЧИНА
    assert правка.alias.corrected_at is not None
    assert правка.alias.origin == LEARNED, "кто завёл строку, правкой не меняется"
    assert правка.alias.phrase == ФРАЗА, "сказанное человеком правка не переписывает"


def test_правка_на_тот_же_пункт_ничего_не_меняет(curation_env: str) -> None:
    """«Уже ведёт туда» — это исход, а не правка.

    Записанная как правка, она сделала бы строку «исправленной», не исправив
    ничего, и `previous_item_code` указывал бы сам на себя.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    правка = repoint_phrase(ФРАЗА, lang="ru", item_code=ПУНКТ, reason=ПРИЧИНА)

    assert правка.outcome == ALREADY_POINTED
    assert правка.alias.previous_item_code is None
    assert правка.alias.corrected_at is None


def test_причина_правки_обязательна(curation_env: str) -> None:
    """Правка карты — такое же действие управляющей компании, как снятие."""
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    with pytest.raises(SynonymError) as отказ:
        repoint_phrase(ФРАЗА, lang="ru", item_code=ДРУГОЙ_ПУНКТ, reason="")

    assert "причин" in str(отказ.value).lower()
    найден = lookup_phrase(ФРАЗА, lang="ru")
    assert найден is not None
    assert найден.item_code == ПУНКТ, "отказ не должен ничего менять"


def test_правка_возвращает_снятую_строку_в_работу(curation_env: str) -> None:
    """Снятое по ошибке не становится мёртвым навсегда.

    Место в карте занято снятой строкой, и заново её не заведёт никто: машине
    ключ не отдадут, человеку тоже. Единственный путь назад — эта правка, и
    она называет исход отдельно, чтобы «переправил» не выглядело тем же, чем
    «вернул в работу».
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    возврат = repoint_phrase(ФРАЗА, lang="ru", item_code=ТРЕТИЙ_ПУНКТ, reason="разобрались")

    assert возврат.outcome == RESTORED
    assert возврат.alias.retracted_at is None
    assert возврат.alias.retraction_reason is None
    assert возврат.alias.previous_item_code == ПУНКТ
    найден = lookup_phrase(ФРАЗА, lang="ru")
    assert найден is not None
    assert найден.item_code == ТРЕТИЙ_ПУНКТ


def test_возврат_снятой_строки_с_тем_же_пунктом(curation_env: str) -> None:
    """Сняли по ошибке и вернули как было — это тоже возврат, а не «уже ведёт».

    Строка снята, то есть поиском не находится; ответить «уже ведёт туда» и
    ничего не сделать означало бы оставить её снятой, сказав обратное.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")
    retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    возврат = repoint_phrase(ФРАЗА, lang="ru", item_code=ПУНКТ, reason="сняли по ошибке")

    assert возврат.outcome == RESTORED
    assert возврат.alias.retracted_at is None
    assert возврат.alias.previous_item_code is None, "код не менялся — и правки кода не было"
    assert lookup_phrase(ФРАЗА, lang="ru") is not None


# --- границы: чего править нельзя ---------------------------------------------


def test_незнакомую_формулировку_снять_нельзя(curation_env: str) -> None:
    """Отказ, а не тихое «сняли ноль строк»: вызывающий просил конкретную строку."""
    with pytest.raises(SynonymError) as отказ:
        retract_phrase("такого в карте нет", lang="ru", reason=ПРИЧИНА)

    assert "карт" in str(отказ.value).lower()
    assert list_phrases(include_retracted=True) == []


def test_незнакомую_формулировку_переправить_нельзя(curation_env: str) -> None:
    """Правка не заводит строку: завести синоним — другая операция и другое право."""
    with pytest.raises(SynonymError):
        repoint_phrase("такого в карте нет", lang="ru", item_code=ПУНКТ, reason=ПРИЧИНА)

    assert list_phrases(include_retracted=True) == []


def test_чужого_арендатора_правка_не_достаёт(curation_env: str) -> None:
    """Карта одного партнёра не правится через карту другого (T110).

    Ключ карты начинается с арендатора, и правка обязана уважать его так же,
    как поиск: иначе управляющая компания одной сети чинила бы синонимы
    другой, не подозревая об этом.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru", tenant="default")

    with pytest.raises(SynonymError):
        retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА, tenant="другой")

    assert lookup_phrase(ФРАЗА, lang="ru", tenant="default") is not None


def test_правка_находит_строку_по_другому_написанию(curation_env: str) -> None:
    """Ключ у правки тот же, что у поиска и у записи.

    Разойдись они хоть на знак — управляющая компания не нашла бы для снятия
    ровно ту строку, которую видит в карте.
    """
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    снято = retract_phrase("  Жёлтый   Зонт  Под Потолком. ", lang="RU", reason=ПРИЧИНА)

    assert снято.outcome == RETRACTED
    assert lookup_phrase(ФРАЗА, lang="ru") is None


def test_пустая_формулировка_ничего_не_снимает(curation_env: str) -> None:
    """Пустой ключ совпал бы с чем угодно — отказ раньше похода в базу."""
    with pytest.raises(SynonymError):
        retract_phrase("   ", lang="ru", reason=ПРИЧИНА)


def test_правка_без_подключения_администратора_отказывает(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Молчаливой правки под ролью приложения не бывает.

    Не задана переменная — отказ называет её, а не роняет запрос отказом прав
    посреди транзакции. «Карта не правится» и «вам её править нечем» — разные
    ответы.
    """
    monkeypatch.delenv(RETRACTION_URL_VAR, raising=False)
    remember_phrase(ФРАЗА, item_code=ПУНКТ, lang="ru")

    with pytest.raises(ConfigError) as отказ:
        retract_phrase(ФРАЗА, lang="ru", reason=ПРИЧИНА)

    assert RETRACTION_URL_VAR in str(отказ.value)
    assert lookup_phrase(ФРАЗА, lang="ru") is not None
