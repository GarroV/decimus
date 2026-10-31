"""Edit history remains readable when a new photo was absent from the original."""

from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


def test_generic_history_includes_manual_before_after_and_new_photo():
    templates = Path(__file__).resolve().parents[1] / "src/web/templates"
    env = Environment(loader=FileSystemLoader(templates), autoescape=select_autoescape())
    before = dict(
        n=1,
        code="SYN01",
        level="D1",
        zone="z",
        text="<before>",
        comment="Old comment",
        photos=["old"],
        reading_c=0,
        repeat=False,
    )
    after = before | dict(
        text="<after>", comment="New comment", photos=["new"], reading_c=4, repeat=True
    )
    html = env.get_template("inspections/_split_history.html").render(
        head=SimpleNamespace(
            finding_history=[dict(kind="edit", before=before, after=[after], at="synthetic")]
        ),
        t=lambda key, **kw: key,
    )
    assert "walk.edit.before" in html and "walk.edit.after" in html
    assert "&lt;before&gt;" in html and "&lt;after&gt;" in html
    assert "Old comment" in html and "New comment" in html
    assert "0 °C" in html and "4 °C" in html
    assert "walk.rec.repeat" in html


def test_clarification_history_needs_no_before_and_escapes_questions_answers():
    templates = Path(__file__).resolve().parents[1] / "src/web/templates"
    env = Environment(loader=FileSystemLoader(templates), autoescape=select_autoescape())
    event = dict(
        kind="clarification",
        n=7,
        at="synthetic",
        clarifications=[dict(question="<system>", answer="<human>")],
        after=[],
    )
    html = env.get_template("inspections/_split_history.html").render(
        head=SimpleNamespace(finding_history=[event]), t=lambda key, **kw: key
    )
    assert "walk.edit.clarification" in html
    assert "walk.edit.question" in html and "walk.edit.answer" in html
    assert "&lt;system&gt;" in html and "&lt;human&gt;" in html
