"""#1252: one fresh catalog per preparation step, with no cache across requests."""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

from src.recognize.classify import prepare_request
from src.recognize.config import NO_CHAT, load_recognize_settings


def _request():
    return prepare_request(
        "synthetic surface observation",
        zone_hint="dining",
        chat_id=NO_CHAT,
        settings=load_recognize_settings({"OPENAI_API_KEY": "synthetic-no-network"}),
    )


def test_preparation_does_not_reread_catalog_for_each_candidate(domain_env, monkeypatch):
    opened = Path.open
    reads = []

    def counted(path, *args, **kwargs):
        if path.name == "checklist.csv":
            reads.append(path)
        return opened(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    request = _request()
    assert len(request.shortlist) > 20
    # Shortlist (all + zone), schema and catalog: bounded by stages, not items/classes.
    assert len(reads) <= 4, f"{len(reads)} catalog reads for one request"


def test_next_request_sees_changed_text_and_allowed_levels(domain_env, monkeypatch, tmp_path):
    edition = tmp_path / "synthetic-edition"
    shutil.copytree(os.environ["AUDIT_DATA_DIR"], edition)
    monkeypatch.setenv("AUDIT_DATA_DIR", str(edition))
    before = _request()
    path = edition / "checklist.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        assert fields is not None
        rows = list(reader)
    selected = before.shortlist[0]
    for row in rows:
        if row["id"] == selected:
            row["question_ru"] = "Synthetic replacement wording"
            row["levels"] = "D3"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    after = _request()
    enum = after.ask.schema["properties"]["records"]["items"]["properties"]["item"]["enum"]
    assert [pick for pick in enum if pick.startswith(selected + ":")] == [selected + ":D3"]
    assert "Synthetic replacement wording" in after.ask.cached_prefix
    assert before.ask.cached_prefix != after.ask.cached_prefix
    assert before.shortlist == after.shortlist
