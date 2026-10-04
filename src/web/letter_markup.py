"""Разметка письма партнёру: белый список из четырёх элементов (T353, D169, #332).

Владелец просил «очень простое форматирование» — жирный, курсив, зачёркнутый,
ссылку, — чтобы письмо копировалось в почту, не теряя вида. Ровно это здесь и
разрешено, больше ничего.

**Форма хранения.** Текст, в котором перевод строки — значимый `\\n`, плюс
строчная разметка `<b>`, `<i>`, `<s>`, `<a href>`; символы `& < >` текста
экранированы. Блоков (`<div>`, `<p>`) в ней нет: строки письма — это строки
текста, как в заготовке движка. Отсюда два следствия, ради которых форма и
выбрана: заготовка становится разметкой одним экранированием (`from_plain`), а
письма, сохранённые до форматирования простым текстом, читаются этой же формой
без миграции — стоящий отдельно `<`, `<5` и `<Пицца>` разбор оставляет текстом.

**Как чистится.** Вход разбирается `html.parser` из стандартной библиотеки, а
вывод строится ЗАНОВО из разобранного: входная строка наружу не попадает ни
куском, поэтому обойти очистку кавычкой или кодировкой нечем. Разрешённый тег
выходит с одним атрибутом (`href`), который экранируется заново; всё прочее —
снимается. Вывод всегда сбалансирован: незакрытая ссылка в сохранённом письме
проглотила бы остаток страницы.

Почему не библиотека: `bleach` с 2023 года в архиве, а `nh3` (обёртка над
Rust-овым `ammonia`) — компилируемая зависимость ради белого списка из четырёх
тегов и одного атрибута. Пересборка на разборщике стандартной библиотеки
короче, чем её настройка, и проверяется целиком (`tests/test_web_letter_markup.py`).

**Где стоит очистка.** При сохранении (`inspections.remember_letter`) И при
каждом выводе: экран, файл выгрузки, черновик Gmail. Запись могла лечь в базу в
обход сохранения — руками, старой версией, — и вывод не верит ей на слово.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlsplit

#: Разрешённые элементы и их синонимы, которые пишут браузеры: Chrome ставит
#: зачёркивание тегом `<strike>`, вставка из почты приносит `<strong>`.
_INLINE = {
    "b": "b",
    "strong": "b",
    "i": "i",
    "em": "i",
    "s": "s",
    "strike": "s",
    "del": "s",
    "a": "a",
}

#: Схемы ссылок, которые доезжают. Без схемы ссылка тоже снимается: письмо
#: читают вне админки, и путь `/inspections/...` у партнёра не ведёт никуда.
ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})

#: Элементы, чьё СОДЕРЖИМОЕ не текст письма: код, стили, скрытое. Снимаются
#: целиком — оставить «alert(1)» словами в письме партнёру значит испортить его.
_DROP_WITH_CONTENT = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "template",
        "noscript",
        "textarea",
        "title",
        "head",
        "select",
        "frameset",
        "noembed",
        "noframes",
        "xmp",
    }
)

#: Элементы, которые редактор и вставка приносят как строки. Становятся
#: переводом строки — иначе две строки письма слиплись бы в одну.
_BLOCKS = frozenset(
    {
        "div",
        "p",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "tr",
        "table",
        "section",
        "article",
        "header",
        "footer",
        "dd",
        "dt",
        "dl",
        "hr",
    }
)

#: Пустые элементы: закрывающего тега у них нет, и `<br>` — единственный из
#: них, у которого есть смысл в тексте письма.
_VOID = frozenset({"br", "img", "input", "hr", "meta", "link", "wbr", "source", "area", "col"})


def _escape_text(text: str) -> str:
    return html.escape(text, quote=False)


def safe_href(raw: str | None) -> str | None:
    """Адрес ссылки, если его можно оставить, иначе `None`.

    Сущности (`&#106;`) разборщик уже раскрыл. Управляющие символы — отказ
    целиком, а не вырезание: браузер сам выбрасывает табуляцию и перевод строки
    из адреса, и `java\\tscript:` у него становится `javascript:`.
    """
    if raw is None:
        return None
    адрес = raw.strip()
    if not адрес or any(ord(знак) < 0x20 or ord(знак) == 0x7F for знак in адрес):
        return None
    try:
        части = urlsplit(адрес)
    except ValueError:
        return None
    if части.scheme.lower() not in ALLOWED_SCHEMES:
        return None
    if части.scheme.lower() in {"http", "https"} and not части.netloc:
        return None
    return адрес


class _Cleaner(HTMLParser):
    """Пересборка входа по белому списку. Выход — `result()`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        #: Открытые разрешённые элементы, по каноническому имени.
        self._stack: list[str] = []
        #: Сколько открыто элементов, чьё содержимое выбрасывается.
        self._dropping = 0
        self._at_line_start = True
        self._need_break = False
        #: Сколько открыто снятых ссылок: их `</a>` не должен закрыть внешнюю.
        self._skipped_links = 0

    # --- строки -----------------------------------------------------------

    def _block_edge(self) -> None:
        if not self._at_line_start:
            self._need_break = True

    def _flush_break(self) -> None:
        if self._need_break:
            self._out.append("\n")
            self._at_line_start = True
            self._need_break = False

    def _newline(self) -> None:
        self._flush_break()
        self._out.append("\n")
        self._at_line_start = True

    # --- разбор -----------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_WITH_CONTENT:
            self._dropping += 1
            return
        if self._dropping:
            return
        if tag == "br":
            self._newline()
            return
        if tag in _BLOCKS:
            self._block_edge()
            return
        имя = _INLINE.get(tag)
        if имя is None:
            return
        if имя == "a":
            self._open_link(attrs)
            return
        self._flush_break()
        self._stack.append(имя)
        self._out.append(f"<{имя}>")

    def _open_link(self, attrs: list[tuple[str, str | None]]) -> None:
        # Ссылка в ссылке не вкладывается: внутренняя снимается, текст остаётся.
        # Иначе у слова было бы два адреса, а увидит партнёр только один.
        адрес = None if "a" in self._stack else safe_href(dict(attrs).get("href"))
        if адрес is None:
            self._skipped_links += 1
            return
        self._flush_break()
        self._stack.append("a")
        self._out.append(f'<a href="{html.escape(адрес, quote=True)}">')

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<br/>`, `<b/>`: самозакрытый разрешённый элемент пуст — выводить нечего.
        if tag == "br" and not self._dropping:
            self._newline()
        elif tag in _BLOCKS and not self._dropping:
            self._block_edge()

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_WITH_CONTENT:
            if self._dropping:
                self._dropping -= 1
            return
        if self._dropping:
            return
        if tag in _BLOCKS:
            self._block_edge()
            return
        имя = _INLINE.get(tag)
        if имя == "a" and self._skipped_links:
            self._skipped_links -= 1
            return
        if имя is None or имя not in self._stack:
            # Лишний закрывающий тег — шум, а не повод закрыть чужое.
            return
        while self._stack:
            открытый = self._stack.pop()
            self._out.append(f"</{открытый}>")
            if открытый == имя:
                break

    def handle_data(self, data: str) -> None:
        if self._dropping or not data:
            return
        self._flush_break()
        self._out.append(_escape_text(data))
        self._at_line_start = data.endswith("\n")

    # Комментарии, `<!DOCTYPE>`, `<?…?>`, `<![CDATA[…]]>` не переопределены
    # намеренно: у `HTMLParser` их обработчики ничего не делают, то есть в
    # вывод они не попадают — это и нужно (проверено тестом).

    def result(self) -> str:
        self.close()
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out)


def sanitize(raw: str) -> str:
    """Любая строка → каноническая разметка письма (см. модуль)."""
    чистильщик = _Cleaner()
    чистильщик.feed(raw)
    return чистильщик.result()


def from_plain(text: str) -> str:
    """Простой текст (заготовка движка) → разметка: экранирование и только."""
    return _escape_text(text)


class _PlainText(HTMLParser):
    """Разметка → текст. Ссылка показывает адрес рядом со словом."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._link = (dict(attrs).get("href") or "", [])

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._link is None:
            return
        адрес, куски = self._link
        self._link = None
        слова = "".join(куски)
        показ = адрес.removeprefix("mailto:")
        self._out.append(слова if слова.strip() == показ else f"{слова} ({показ})")

    def handle_data(self, data: str) -> None:
        (self._link[1] if self._link is not None else self._out).append(data)

    def result(self) -> str:
        self.close()
        if self._link is not None:
            self._out.extend(self._link[1])
        return "".join(self._out)


def to_plain(markup: str) -> str:
    """Текстовый вариант письма — честный: без разметки и без спрятанных адресов.

    Его видит получатель, чья почта HTML не показывает, и его же кладёт в
    буфер копирование «как текст». Слово ссылки без адреса там превратилось
    бы в обещание, которое некуда нажать.
    """
    читатель = _PlainText()
    читатель.feed(sanitize(markup))
    return читатель.result()


def to_email_html(markup: str) -> str:
    """HTML-часть письма. Строки письма — `<br>`: почтовые клиенты режут стили."""
    тело = sanitize(markup).replace("\n", "<br>\n")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        f"<body><div>{тело}</div></body></html>"
    )
