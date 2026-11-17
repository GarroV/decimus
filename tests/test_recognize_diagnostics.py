"""External diagnostics are reduced before domain errors reach logs or journals.

Synthetic markers test the boundary; they do not establish a past provider leak.
"""

from __future__ import annotations

import importlib
import logging
import traceback
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError, RateLimitError
from test_recognize_client import _SCHEMA, _settings

from src.recognize import client
from src.recognize.errors import ModelKeyRejected, ModelUnavailable, TranscriptionFailed

transcription = importlib.import_module("src.recognize.transcribe")
PRIVATE = "SYNTHETIC_EXTERNAL_DIAGNOSTIC"


def provider_error(*, key=False, unknown_code=False):
    error_class = AuthenticationError if key else RateLimitError
    response = httpx.Response(
        401 if key else 429, request=httpx.Request("POST", "https://api.invalid")
    )
    return error_class(
        PRIVATE,
        response=response,
        body={"message": PRIVATE, "code": PRIVATE if unknown_code else "rate_limit_exceeded"},
    )


def fail(error):
    def create(*args, **kwargs):
        raise error

    return create


@pytest.mark.parametrize("boundary", ["model", "voice", "verify", "verify-key"])
@pytest.mark.parametrize("unknown_code", [False, True])
def test_provider_text_and_exception_cause_do_not_cross_the_domain_boundary(
    monkeypatch, caplog, boundary, unknown_code
):
    error = provider_error(key=boundary == "verify-key", unknown_code=unknown_code)
    create = fail(error)
    fake = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        models=SimpleNamespace(list=create),
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)),
    )
    monkeypatch.setattr(client, "_new_client", lambda settings: fake)
    monkeypatch.setattr(client, "OpenAI", lambda **kwargs: fake)
    monkeypatch.setattr(transcription, "OpenAI", lambda **kwargs: fake)
    monkeypatch.setattr(transcription, "_reencode", lambda *args: b"synthetic wav")
    monkeypatch.setattr(client, "_note", lambda *args, **kwargs: None)
    monkeypatch.setattr(transcription, "_note", lambda *args, **kwargs: None)
    with pytest.raises((ModelUnavailable, TranscriptionFailed, ModelKeyRejected)) as caught:
        if boundary == "model":
            client.ask_model(
                kind="recognize",
                instructions="",
                question="",
                schema=_SCHEMA,
                photo=None,
                settings=_settings(),
            )
        elif boundary == "voice":
            transcription.transcribe(b"synthetic ogg", settings=_settings())
        else:
            client.verify_key("synthetic key")
    rendered = "".join(traceback.format_exception(caught.value))
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in rendered
    # Exercise the same exception formatting used by downstream operational logs.
    logging.getLogger(__name__).error("safe failure", exc_info=caught.value)
    assert PRIVATE not in caplog.text
    if boundary != "verify-key":
        assert "429" in str(caught.value)
        assert "RateLimitError" in str(caught.value)
        assert ("rate_limit_exceeded" in str(caught.value)) is not unknown_code


def test_audio_metadata_in_ffmpeg_stderr_is_not_copied_into_the_failure(monkeypatch):
    import subprocess

    error = subprocess.CalledProcessError(1, "ffmpeg", stderr=PRIVATE.encode())
    monkeypatch.setattr(transcription.subprocess, "run", fail(error))
    with pytest.raises(TranscriptionFailed) as caught:
        transcription._reencode(b"synthetic audio", "ffmpeg")
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))
    assert "не смог перекодировать" in str(caught.value)
