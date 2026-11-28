"""The actual walk client selects Russian/English count forms from its catalogue."""

import json
import subprocess
from pathlib import Path

from src.web.texts_walk import WALK_TEXTS


def test_walk_item_count_forms():
    script = """
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const document = {documentElement: {lang: 'ru'}, getElementById: () => ({getAttribute: () => ''})};
const window = {};
vm.runInNewContext(input.code, {window, document, Intl});
const W = window.DecimusWalk;
let result = {};
for (const lang of ['ru','en']) {
  document.documentElement.lang = lang;
  const texts = Object.entries(input.texts).map(([k,v]) => [k,v[lang]]);
  W.state.data = {texts: Object.fromEntries(texts)};
  result[lang] = [1,2,5,11,21,22].map(n => W.txCount('walk.cl.count', n));
}
process.stdout.write(JSON.stringify(result));
"""
    code = Path("src/web/static/walk-core.js").read_text()
    result = subprocess.run(  # noqa: S603 — trusted repository JS and fixed harness
        ["node", "-e", script],  # noqa: S607 — Node is the project JS test runtime
        input=json.dumps({"code": code, "texts": WALK_TEXTS}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "ru": ["1 пункт", "2 пункта", "5 пунктов", "11 пунктов", "21 пункт", "22 пункта"],
        "en": ["1 item", "2 items", "5 items", "11 items", "21 items", "22 items"],
    }
