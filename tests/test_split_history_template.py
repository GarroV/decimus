from pathlib import Path
from types import SimpleNamespace

from flask import Flask, render_template

from src.web.texts import t


def test_source_and_children_are_readable_and_escaped_in_history() -> None:
    app = Flask(
        __name__, template_folder=str(Path(__file__).resolve().parents[1] / "src/web/templates")
    )
    event = {
        "at": "2026-10-31T12:00:00+00:00",
        "before": {
            "n": 1,
            "code": "CLN05",
            "level": "D1",
            "zone": "hot_kitchen",
            "text": "source <script>",
            "comment": "",
            "words": "hidden raw words",
            "photos": ["a", "b"],
        },
        "after": [
            {
                "n": 2,
                "code": "CLN05",
                "level": "D1",
                "zone": "hot_kitchen",
                "text": "first child",
                "comment": "",
                "photos": ["a"],
            },
            {
                "n": 3,
                "code": "CLN06",
                "level": "D1",
                "zone": "hot_kitchen",
                "text": "second child",
                "comment": "",
                "photos": ["b"],
            },
        ],
    }
    with app.app_context():
        html = render_template(
            "inspections/_split_history.html",
            head=SimpleNamespace(finding_history=[event]),
            t=lambda key, **args: t(key, "ru", **args),
        )
    assert "История разделений" in html
    assert "source &lt;script&gt;" in html and "<script>" not in html
    assert "first child" in html and "second child" in html
    assert "Фото 1" in html and "Фото 2" in html
    assert "hidden raw words" not in html
