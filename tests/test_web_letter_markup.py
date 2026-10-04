"""Разметка письма партнёру: белый список из четырёх элементов (T353, #332).

Это ядро в смысле конституции: текст письма читает партнёр, а тот же текст
отображается в админке. Ошибка здесь молчит дважды — пропущенный `javascript:`
выглядит обычной ссылкой, а потерянное слово выглядит законченным письмом.
Поэтому сторожится не вид разметки, а три обещания:

* наружу не выходит ничего, кроме `<b>`, `<i>`, `<s>`, `<a href>` со схемой
  `http`/`https`/`mailto`, — как бы вход ни был собран;
* текст человека не теряется: снятый тег оставляет свои слова, старое письмо
  простым текстом читается без потерь;
* текстовый вариант письма честный — без разметки и без спрятанных адресов.
"""

from __future__ import annotations

import pytest

from src.web.letter_markup import from_plain, sanitize, to_email_html, to_plain

# --- что разрешено, доезжает ------------------------------------------------


def test_четыре_разрешённых_вида_доезжают_как_есть() -> None:
    вход = (
        '<b>жирный</b> <i>курсив</i> <s>зачёркнутый</s> <a href="https://dodo.example/x">ссылка</a>'
    )

    assert sanitize(вход) == вход


def test_синонимы_браузера_сводятся_к_четырём() -> None:
    """Браузеры пишут жирный то `<b>`, то `<strong>`: хранится одно имя."""
    вход = "<strong>a</strong><em>b</em><strike>c</strike><del>d</del>"

    assert sanitize(вход) == "<b>a</b><i>b</i><s>c</s><s>d</s>"


@pytest.mark.parametrize(
    "адрес",
    ["https://dodo.example/a?b=1&c=2", "http://dodo.example", "mailto:partner@dodo.example"],
)
def test_ссылки_разрешённых_схем_остаются(адрес: str) -> None:
    вывод = sanitize(f'<a href="{адрес}">тут</a>')

    assert вывод == f'<a href="{адрес.replace("&", "&amp;")}">тут</a>'


# --- ссылки: только http, https, mailto ------------------------------------


@pytest.mark.parametrize(
    "адрес",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "  javascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "&#106;avascript:alert(1)",
        "&#x6A;avascript&colon;alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//evil.example/x",
        "/inspections/1",
        "",
    ],
)
def test_ссылка_чужой_схемы_снимается_а_текст_остаётся(адрес: str) -> None:
    вывод = sanitize(f'до <a href="{адрес}">нажми</a> после')

    assert вывод == "до нажми после"


def test_ссылка_без_адреса_снимается() -> None:
    assert sanitize("<a>текст</a>") == "текст"


def test_кавычка_в_адресе_не_выходит_из_атрибута() -> None:
    вывод = sanitize("<a href='https://dodo.example/\" onclick=\"alert(1)'>x</a>")

    # Кавычек в выводе ровно две — обе свои, вокруг адреса.
    assert вывод.count('"') == 2
    assert вывод.startswith('<a href="https://dodo.example/&quot; onclick=&quot;alert(1)">')


# --- скрипты и обработчики -------------------------------------------------


@pytest.mark.parametrize(
    "вход",
    [
        "<script>alert(1)</script>",
        "<SCRIPT SRC=//evil.example/x.js></SCRIPT>",
        "<style>body{display:none}</style>",
        "<iframe src=https://evil.example>фрейм</iframe>",
        "<object data=x>объект</object>",
        "<template><b>скрытое</b></template>",
        "<noscript><b>скрытое</b></noscript>",
        "<textarea>поле</textarea>",
        "<title>заголовок</title>",
    ],
)
def test_исполняемое_выбрасывается_вместе_с_содержимым(вход: str) -> None:
    assert sanitize(f"до{вход}после") == "допосле"


@pytest.mark.parametrize(
    "вход",
    [
        '<b onclick="alert(1)">t</b>',
        "<b onmouseover=alert(1)>t</b>",
        '<b style="background:url(javascript:alert(1))">t</b>',
        '<b class="x" id="y" data-x="z">t</b>',
    ],
)
def test_атрибуты_кроме_href_снимаются(вход: str) -> None:
    assert sanitize(вход) == "<b>t</b>"


@pytest.mark.parametrize(
    "вход",
    [
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)>",
        "<body onload=alert(1)>",
        "<input autofocus onfocus=alert(1)>",
        "<!-- <script>alert(1)</script> -->",
        "<![CDATA[<script>alert(1)</script>]]>",
        "<!DOCTYPE html>",
        "<?xml version='1.0'?>",
    ],
)
def test_прочие_теги_и_служебное_не_доезжают(вход: str) -> None:
    вывод = sanitize(f"a{вход}b")

    assert "<" not in вывод.replace("&lt;", "")
    assert "alert" not in вывод or "&lt;" in вывод
    assert вывод.startswith("a") and вывод.endswith("b")


def test_у_ссылки_остаётся_только_href() -> None:
    вывод = sanitize(
        '<a href="https://dodo.example" onclick="alert(1)" target="_blank" '
        'style="color:red" xlink:href="javascript:alert(1)">x</a>'
    )

    assert вывод == '<a href="https://dodo.example">x</a>'


# --- вложенная разметка ----------------------------------------------------


def test_вложенное_очищается_на_каждом_уровне() -> None:
    вход = (
        '<b><a href="javascript:alert(1)"><i onmouseover="alert(1)">t'
        "<script>alert(1)</script></i></a></b>"
    )

    assert sanitize(вход) == "<b><i>t</i></b>"


def test_вложенные_разрешённые_сохраняются() -> None:
    вход = '<b><i><s>все три</s></i></b> и <a href="https://dodo.example"><b>жирная ссылка</b></a>'

    assert sanitize(вход) == вход


def test_ссылка_внутри_ссылки_не_вкладывается() -> None:
    вход = '<a href="https://a.example">x<a href="https://b.example">y</a>z</a>'

    assert sanitize(вход) == '<a href="https://a.example">xyz</a>'


@pytest.mark.parametrize(
    ("вход", "ожидание"),
    [
        ("<b><i>x</b>y</i>", "<b><i>x</i></b>y"),
        (
            '<a href="https://dodo.example">незакрытая',
            '<a href="https://dodo.example">незакрытая</a>',
        ),
        ("<b>незакрытый", "<b>незакрытый</b>"),
        ("лишний</b> конец</a>", "лишний конец"),
    ],
)
def test_вывод_всегда_сбалансирован(вход: str, ожидание: str) -> None:
    """Незакрытая ссылка в сохранённом письме проглотила бы остаток страницы."""
    assert sanitize(вход) == ожидание


def test_глубокая_вложенность_не_роняет_разбор() -> None:
    вход = "<b>" * 5000 + "x" + "</b>" * 5000

    вывод = sanitize(вход)

    assert to_plain(вывод) == "x"


# --- текст не теряется -----------------------------------------------------


@pytest.mark.parametrize(
    "текст",
    [
        "Уважаемые коллеги,\n\nоценка 97.5 %, буква A.\n\nСрок: 5 дней",
        "R&D и t<5°C, а также <Пицца> и a < b > c",
        "  отступ\n\n\nтри пустые строки",
        "&amp; написано буквально",
    ],
)
def test_простой_текст_проходит_без_потерь(текст: str) -> None:
    """Заготовка движка и старые письма — простой текст, и он не искажается."""
    разметка = from_plain(текст)

    assert sanitize(разметка) == разметка
    assert to_plain(разметка) == текст


@pytest.mark.parametrize(
    "текст",
    [
        "Уважаемые коллеги,\n\nоценка 97.5 %.",
        "t<5°C и <Пицца> и a < b",
        "R&D",
    ],
)
def test_старое_письмо_простым_текстом_читается_как_есть(текст: str) -> None:
    """Письма до форматирования лежат в базе текстом, миграции у них нет."""
    assert to_plain(sanitize(текст)) == текст


def test_снятый_тег_оставляет_свои_слова() -> None:
    assert sanitize("<span><u>важно</u></span> <font color=red>очень</font>") == "важно очень"


def test_блоки_редактора_становятся_строками() -> None:
    """Так пишет `contenteditable` в Chrome после Enter."""
    вход = "Строка 1<div>Строка 2</div><div><br></div><div>Строка <b>4</b></div>"

    assert sanitize(вход) == "Строка 1\nСтрока 2\n\nСтрока <b>4</b>"


def test_перенос_br_и_абзацы() -> None:
    assert sanitize("a<br>b<br/>c<p>d</p><p>e</p>") == "a\nb\nc\nd\ne"


def test_очистка_идемпотентна() -> None:
    образцы = [
        '<b onclick=x>a<i>b</b>c</i><a href="javascript:x">d</a><div>e</div>&amp;<f',
        "<script>x</script>&lt;b&gt;",
    ]
    for образец in образцы:
        один = sanitize(образец)
        assert sanitize(один) == один


# --- что получает почта ----------------------------------------------------


def test_текстовый_вариант_без_разметки() -> None:
    разметка = sanitize("<b>Жирно</b>, <i>курсив</i>, <s>старое</s>\nстрока &amp; ещё")

    assert to_plain(разметка) == "Жирно, курсив, старое\nстрока & ещё"


@pytest.mark.parametrize(
    ("разметка", "текст"),
    [
        ('<a href="https://dodo.example/plan">план</a>', "план (https://dodo.example/plan)"),
        (
            '<a href="https://dodo.example/plan">https://dodo.example/plan</a>',
            "https://dodo.example/plan",
        ),
        ('<a href="mailto:a@dodo.example">a@dodo.example</a>', "a@dodo.example"),
        ('<a href="mailto:a@dodo.example">почта</a>', "почта (a@dodo.example)"),
    ],
)
def test_ссылка_в_тексте_не_прячет_адрес(разметка: str, текст: str) -> None:
    """Получатель без HTML должен видеть, куда ведёт ссылка, а не только слово."""
    assert to_plain(разметка) == текст


def test_html_часть_несёт_переводы_строк_и_разметку() -> None:
    html = to_email_html(sanitize("Строка <b>1</b>\nR&amp;D <script>x</script>"))

    assert "Строка <b>1</b><br>" in html
    assert "R&amp;D" in html
    assert "<script" not in html


def test_html_часть_очищает_даже_неочищенный_вход() -> None:
    """Вывод санитизирует сам: ему могли передать запись в обход сохранения."""
    html = to_email_html('<a href="javascript:alert(1)" onclick=x>a</a><img src=x onerror=y>')

    assert "javascript" not in html
    assert "onclick" not in html
    assert "<img" not in html


# --- незакрытое выбрасываемое не съедает письмо (ревью) ---------------------


@pytest.mark.parametrize(
    "вход",
    [
        "до<style>x после",
        "до<title>заг после",
        "до<select><option>1</option> после",
        "до<script>a</script после",
        "до<iframe>x после",
    ],
)
def test_незакрытое_выбрасываемое_не_съедает_остаток(вход: str) -> None:
    """Без закрывающего тега это не код, а текст человека — он остаётся."""
    вывод = sanitize(вход)

    assert вывод.startswith("до")
    assert "после" in вывод
    assert "<style" not in вывод and "<script" not in вывод and "<title" not in вывод


def test_незакрытое_выбрасываемое_оставляет_разметку_после_себя() -> None:
    assert sanitize("<b>а</b><style>x <i>курсив</i>") == "<b>а</b>x <i>курсив</i>"


def test_закрытое_выбрасываемое_по_прежнему_выбрасывается_целиком() -> None:
    assert sanitize("до<style>x</style>после<script>y</script>") == "допосле"


@pytest.mark.parametrize("вход", ["a <b c", "a </b c", "t <5 и <x"])
def test_недописанный_тег_в_конце_остаётся_текстом(вход: str) -> None:
    assert to_plain(sanitize(вход)) == вход
