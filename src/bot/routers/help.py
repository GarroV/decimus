"""Краткая справка «как работать с ботом» (#257).

Отдельный роутер по образцу `version.py`: своего состояния диалога у справки
нет, обычного текста она не ждёт и на разбор материала не влияет.

**Язык — язык ЭТОГО чата**, а не стенда. Тем и отличается от `/version`: версию
сборки спрашивают, когда с продуктом что-то не так, и читает её чаще
администратор, а справку читает аудитор — на том языке, на котором ведёт
проверку. Чтение состояния здесь безопасно: `chat_ui_lang` испорченный файл не
роняет, а откатывает на язык стенда (`lang.py`, T126).

**Текст один на все входы и живёт в каталоге** — как и весь остальной
интерфейс. Собирать его из кусков по ходу (какие команды доступны, идёт ли
проверка) намеренно не стал: справка тем и полезна, что одинакова, и разбор
«почему у меня другой текст» стоил бы дороже пары лишних строк.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..lang import chat_ui_lang
from ..texts import t

#: Имя команды: одно место на роутер, меню и тесты.
HELP_COMMAND = "help"


def build_help_router() -> Router:
    """Роутер справки: одна команда и ничего больше."""
    router = Router(name="help")

    @router.message(Command(HELP_COMMAND))
    async def on_help(message: Message) -> None:
        await message.answer(t("help.text", chat_ui_lang(message.chat.id)))

    return router
