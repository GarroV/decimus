"""Synthetic evidence indices refer only to the images actually sent, never all images."""

from __future__ import annotations

import pytest

from src.recognize.classify import finish, prepare_request
from src.recognize.client import ModelAnswer
from src.recognize.config import load_recognize_settings
from src.recognize.provenance import frame_indices


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([0], (0,)),
        ([1, 0], (1, 0)),
        ([], ()),
        (None, None),
        ([True], None),
        ([1.0], None),
        ([2], None),
        ([-1], None),
        ([0, 0], None),
        ("0", None),
        (["0"], None),
    ],
)
def test_indices_are_validated_as_a_complete_set(raw, expected):
    assert frame_indices(raw, 2) == expected


def test_empty_image_set_never_accepts_nonempty_evidence():
    assert frame_indices([0], 0) is None
    assert frame_indices([], 0) == ()


def test_primary_and_additional_evidence_are_parsed_against_sent_images(domain_env):
    request = prepare_request(
        "Synthetic observations",
        photos=[b"frame-zero", b"frame-one"],
        chat_id=None,
        settings=load_recognize_settings({"OPENAI_API_KEY": "synthetic-no-network"}),
    )
    item = request.ask.schema["properties"]["records"]["items"]["properties"]["item"]["enum"][0]
    record = {"item": item, "zone": "hot_kitchen", "wording": "Synthetic", "confidence": 0.9}
    found = finish(
        request,
        ModelAnswer(
            payload={
                "records": [{**record, "frame_indices": [1]}],
                "also_seen": [{**record, "frame_indices": [0]}],
            },
            usage={},
        ),
    )
    assert found.frame_count == 2
    assert found.candidates[0].frame_indices == (1,)
    assert found.also_seen[0].frame_indices == (0,)
    # Same returned number is invalid if no image was actually attached to the request.
    without_images = prepare_request(
        "Synthetic words only",
        chat_id=None,
        settings=load_recognize_settings({"OPENAI_API_KEY": "synthetic-no-network"}),
    )
    assert (
        finish(
            without_images,
            ModelAnswer(payload={"records": [{**record, "frame_indices": [0]}]}, usage={}),
        )
        .candidates[0]
        .frame_indices
        is None
    )
