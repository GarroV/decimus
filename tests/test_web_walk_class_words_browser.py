"""Class pills show the class in words, never the code (D1/D2/D3) — the code lives in data only.

Real `walk-core.js` in Chromium, no server. A pill reading «D1» is a silent regression: the
screen still works, the auditor just sees a code that PRODUCT.md forbids.
"""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_walk_ux_browser import page  # noqa: F401

from src.web.texts_walk import WALK_TEXTS

WORDS = {
    "ru": {"D1": "отклонение", "D2": "значительное", "D3": "критическое"},
    "en": {"D1": "deviation", "D2": "significant", "D3": "critical"},
}


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_class_pill_is_a_word_and_keeps_the_code_in_data(page, lang):
    texts = {key: entry[lang] for key, entry in WALK_TEXTS.items()}
    got = page.evaluate(
        """texts=>{const W=DecimusWalk; W.tx=key=>texts[key]||key;
          return ['D1','D2','D3'].map(c=>{const n=W.level(c);
            return {text:n.textContent, level:n.dataset.level, word:W.levelWord(c)};});}""",
        texts,
    )
    for row in got:
        assert row["text"] == WORDS[lang][row["level"]], row
        assert row["word"] == row["text"]
        assert row["level"] not in row["text"], "the code must not be on screen"
