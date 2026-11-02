"""Every workspace has one page title above its filters and columns (D688)."""

import re
from pathlib import Path

from jinja2 import Environment, nodes

PUBLIC = {
    "landing.html",
    "login.html",
    "login_base.html",
    "login_second_step.html",
    "demo/app.html",
    "demo/pick.html",
    "dodois/connect.html",
}
TEMPLATES = Path(__file__).resolve().parents[1] / "src/web/templates"


def _misplaced(node: nodes.Node) -> list[int]:
    if isinstance(node, nodes.Block) and node.name == "page_heading":
        return []
    if isinstance(node, nodes.Output):
        dynamic_h1 = any(c.value == "h1" for c in node.find_all(nodes.Const))
        opening_tag = any(isinstance(c, nodes.TemplateData) and "<" in c.data for c in node.nodes)
        if dynamic_h1 and opening_tag:
            return [node.lineno]
    found = (
        [node.lineno]
        if isinstance(node, nodes.TemplateData) and re.search(r"<h1\b", node.data)
        else []
    )
    for child in node.iter_child_nodes():
        found.extend(_misplaced(child))
    return found


def test_all_workspace_titles_use_the_shared_heading_slot() -> None:
    env = Environment(autoescape=True)
    failures = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        name = path.relative_to(TEMPLATES).as_posix()
        if name in PUBLIC:
            continue
        tree = env.parse(path.read_text())
        for line in _misplaced(tree):
            failures.append(f"{name}:{line}: h1 is below the shared page-heading slot")
    assert not failures, "\n".join(failures)


def test_shared_heading_precedes_notices_and_workspace() -> None:
    base = (TEMPLATES / "base.html").read_text()
    start = base.index('<main class="page')
    assert start < base.index("block page_heading", start) < base.index("if passkey_here", start)
    assert base.index("block page_heading", start) < base.index("block body", start)
