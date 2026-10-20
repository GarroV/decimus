"""T033: голосовое сообщение аудитора → текст.

Telegram отдаёт голосовые в OGG/Opus; API транскрипции формат не отвергает
впрямую, но в бою нам нужен ровно тот путь, что уже проверен вручную — WAV,
16 кГц, моно — поэтому перед вызовом файл перекодируется `ffmpeg`. Он вызван
подпроцессом, а не библиотекой: `ffmpeg` уже выбран решением D008 и живёт в
образе бота (задача T070), тянуть для этого же ещё и python-обвязку незачем.

Любой отказ — не найден `ffmpeg`, кодек не разобрал файл, сеть, пустой текст —
превращается в `TranscriptionFailed`. Проверку это не роняет: аудитора просят
написать текстом, а не останавливают фиксацию (контракт блока).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI, OpenAIError, omit

from src.db import model_usage
from src.domain.model_usage import KIND_TRANSCRIBE, build_call

from .config import RecognizeSettings, load_recognize_settings
from .errors import TranscriptionFailed

#: Таймаут перекодировки. Голосовые аудитора короткие (секунды-десятки
#: секунд); минута — щедрый запас на медленный старт ffmpeg в контейнере.
REENCODE_TIMEOUT = 60.0

#: Частота и число каналов на выходе перекодировки. API транскрипции сам
#: понижает частоту при необходимости, но заранее — меньше данных на вход.
_SAMPLE_RATE = "16000"
_CHANNELS = "1"

#: Потолки голосового (F-123): оно идёт в ffmpeg и в платную транскрипцию.
#: Голосовые аудитора — секунды-десятки секунд (OGG/Opus ≈ 4 КБ/с); сообщения
#: Telegram и так не больше 20 МБ, так что размер — страховка от файла в обход бота.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
#: Длительность: десять минут — на порядок больше обычной реплики. WAV на выходе
#: при этом ~19 МБ, в пределе API транскрипции (25 МБ).
MAX_AUDIO_SECONDS = 600
#: Байт WAV в секунду: 16 кГц × 16 бит × моно.
_WAV_BYTES_PER_SECOND = 32_000
_WAV_HEADER_BYTES = 44


def _reencode(audio: bytes, ffmpeg: str) -> bytes:
    """OGG/Opus (или что угодно, что понимает ffmpeg) → WAV."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.audio"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(audio)
        try:
            subprocess.run(  # noqa: S603 — путь к бинарю и флаги собраны здесь, ввода извне нет
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(src),
                    "-ar",
                    _SAMPLE_RATE,
                    "-ac",
                    _CHANNELS,
                    # Не пишем дальше потолка (+1 с, чтобы превышение было видно):
                    # длинный файл не раздувается в гигабайты WAV.
                    "-t",
                    str(MAX_AUDIO_SECONDS + 1),
                    str(dst),
                ],
                check=True,
                capture_output=True,
                timeout=REENCODE_TIMEOUT,
            )
        except FileNotFoundError as exc:
            raise TranscriptionFailed(
                f"Не найден ffmpeg ({ffmpeg}). Голосовое не перекодировано, "
                "попросите аудитора написать текстом"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TranscriptionFailed(
                f"Перекодировка не уложилась в {REENCODE_TIMEOUT:.0f} с. "
                "Голосовое не разобрано, попросите написать текстом"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            raise TranscriptionFailed(
                f"ffmpeg не смог перекодировать голосовое: {stderr.strip() or exc}. "
                "Попросите написать текстом"
            ) from exc
        data = dst.read_bytes()
        if not data:
            raise TranscriptionFailed(
                "Перекодировка дала пустой файл. Голосовое не разобрано, попросите написать текстом"
            )
        return data


def _note(model: str, usage: object | None, *, ok: bool) -> None:
    """Учесть расшифровку (D537): токены, если провайдер их отдал, иначе секунды звука."""
    seconds = getattr(usage, "seconds", None)
    model_usage.record(
        build_call(
            KIND_TRANSCRIBE,
            model,
            ok=ok,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            audio_seconds=float(seconds) if isinstance(seconds, int | float) else None,
        )
    )


def transcribe(
    audio: bytes, *, lang: str | None = None, settings: RecognizeSettings | None = None
) -> str:
    """Голосовое → текст. Пустая расшифровка — тоже отказ: разбирать нечего.

    `lang` — язык речи проверки (`Inspection.speech_lang`, D393, #538): код
    ISO-639-1 уходит модели подсказкой, без неё она угадывает язык по звуку и
    на коротких репликах путает русский с соседними. Проверки нет — `None`,
    и язык определяется сам, как раньше.

    `settings` — тот же шов, что и у `classify`: тесты подменяют настройки,
    бот вызывает без аргумента и получает конфиг из окружения.
    """
    cfg = settings or load_recognize_settings()
    if not cfg.api_key:
        raise TranscriptionFailed(
            "Не задан ключ модели (экран «Подключения» или OPENAI_API_KEY). "
            "Голосовое не распознано, "
            "попросите аудитора написать текстом"
        )
    if len(audio) > MAX_AUDIO_BYTES:
        raise TranscriptionFailed(
            f"Голосовое слишком большое ({len(audio) / 1024 / 1024:.0f} МБ, предел "
            f"{MAX_AUDIO_BYTES // 1024 // 1024} МБ). Не разобрано, попросите написать текстом"
        )
    wav = _reencode(audio, cfg.ffmpeg)
    if (len(wav) - _WAV_HEADER_BYTES) / _WAV_BYTES_PER_SECOND > MAX_AUDIO_SECONDS:
        raise TranscriptionFailed(
            f"Голосовое слишком длинное (предел {MAX_AUDIO_SECONDS // 60} мин). "
            "Не разобрано, попросите написать текстом"
        )

    client = OpenAI(api_key=cfg.api_key, timeout=cfg.timeout)
    try:
        result = client.audio.transcriptions.create(
            model=cfg.transcribe_model,
            file=("audio.wav", wav, "audio/wav"),
            language=lang or omit,
        )
    except OpenAIError as exc:
        _note(cfg.transcribe_model, None, ok=False)
        raise TranscriptionFailed(f"Транскрипция не ответила: {exc}") from exc

    text = result.text.strip()
    _note(cfg.transcribe_model, getattr(result, "usage", None), ok=bool(text))
    if not text:
        raise TranscriptionFailed(
            "Транскрипция вернула пустой текст. Голосовое, возможно, без речи — "
            "попросите написать текстом"
        )
    return text
