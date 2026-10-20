"""Тексты страницы загрузки кадров к черновику по ссылке из Claude (`photo_upload.py`).

Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

PHOTO_UPLOAD_TEXTS: dict[str, dict[str, str]] = {
    "photo_upload.title": {"ru": "Фото к находкам", "en": "Photos for the findings"},
    "photo_upload.lead": {
        "ru": "Выберите или перетащите фото в поле нужной находки и нажмите «Загрузить». "
        "JPEG, PNG, WebP или HEIC, до {mb} МБ каждое. "
        "Ссылка работает, пока проверка не принята.",
        "en": "Choose or drop photos into the field of the right finding and press "
        "“Upload”. JPEG, PNG, WebP or HEIC, up to {mb} MB each. "
        "The link works until the inspection is accepted.",
    },
    "photo_upload.no_findings": {
        "ru": "В черновике пока нет находок — фото прикладывать не к чему.",
        "en": "The draft has no findings yet — nothing to attach photos to.",
    },
    "photo_upload.pick": {"ru": "Фото к находке №{n}", "en": "Photos for finding #{n}"},
    "photo_upload.send": {"ru": "Загрузить", "en": "Upload"},
    "photo_upload.attached": {
        "ru": "Фото «{name}» приложено к находке №{n}.",
        "en": "Photo “{name}” attached to finding #{n}.",
    },
    "photo_upload.refused": {
        "ru": "Фото «{name}» не приложено: {reason}.",
        "en": "Photo “{name}” was not attached: {reason}.",
    },
}
