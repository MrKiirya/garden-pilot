"""Button content is centred by LVGL, never by hand-computed x/y (rule in CLAUDE.md, gotchas).

A single child (label / image / switch) uses `align: CENTER` with no x/y; two or more children (icon + label) need the
button to be a centred flex container (row, or column for the nav) and carry no x/y/align themselves. Buttons have
`pad_all: 0`. The check walks every `button` widget of every file under packages/ (included fragments such as the nav
bar, the schedule toggle and the cards are files of their own); `${...}` is replaced by a dummy so the files load.
"""

from __future__ import annotations

import re

import pytest
import yaml

from conftest import REPO_ROOT, _EsphomeLoader

pytestmark = pytest.mark.unit

# Left-aligned cards by design (title + value + chevron), not centred content: the only allowed hand-placed children.
CARD_TILES = {"setup_tile_network", "setup_tile_display", "setup_tile_service"}
CHILD_TYPES = ("label", "image", "switch")
HAND_PLACED = ("x", "y")


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _buttons() -> list[tuple[str, dict]]:
    found = []
    for path in sorted((REPO_ROOT / "packages").rglob("*.yaml")):
        text = re.sub(r"\$\{[^}]*\}", "X", path.read_text(encoding="utf-8"))
        data = yaml.load(text, Loader=_EsphomeLoader)  # noqa: S506 - SafeLoader subclass
        rel = path.relative_to(REPO_ROOT).as_posix()
        for d in _walk(data):
            props = d.get("button")
            if isinstance(props, dict) and "widgets" in props and isinstance(props["widgets"], list):
                found.append((f"{rel}:{props.get('id', '?')}", props))
    return found


def _children(button: dict) -> list[tuple[str, dict]]:
    out = []
    for item in button["widgets"]:
        for wtype, props in item.items():
            if wtype in CHILD_TYPES and isinstance(props, dict):
                out.append((wtype, props))
    return out


def _is_centred_flex(button: dict) -> bool:
    layout = button.get("layout")
    return (
        isinstance(layout, dict)
        and str(layout.get("type")).lower() == "flex"
        and str(layout.get("flex_flow")).upper() in ("ROW", "COLUMN")
        and all(str(layout.get(k)).upper() == "CENTER" for k in ("flex_align_main", "flex_align_cross", "flex_align_track"))
    )


BUTTONS = _buttons()


def test_buttons_found() -> None:
    names = {name.split(":")[1] for name, _ in BUTTONS}
    assert len(BUTTONS) >= 40
    assert {"gh_hist_btn_back", "gh_hist_btn_newer", "gh_sed_btn_save", "gp_confirm_cancel", "sched_btn_history"} <= names
    assert any("nav_btn_" in n for n in names)


@pytest.mark.parametrize("name,button", BUTTONS, ids=[n for n, _ in BUTTONS])
def test_button_content_is_centred_by_lvgl(name: str, button: dict) -> None:
    ident = name.split(":")[1]
    if ident in CARD_TILES:
        return
    assert button.get("pad_all") == 0, f"{name}: buttons have pad_all: 0"
    children = _children(button)
    assert children, name
    for wtype, props in children:
        assert not any(k in props for k in HAND_PLACED), f"{name}: {wtype} has hand-placed x/y"
        if wtype == "label" and "width" in props:
            assert props.get("text_align") == "CENTER", f"{name}: a fixed label width shifts the text"
    if len(children) == 1:
        wtype, props = children[0]
        assert props.get("align") == "CENTER", f"{name}: a single {wtype} needs `align: CENTER`"
    else:
        assert _is_centred_flex(button), f"{name}: several children need a centred flex layout (all three aligns CENTER)"
        for wtype, props in children:
            assert "align" not in props, f"{name}: a flex child ({wtype}) must not set align"


def test_nav_buttons_are_centred_columns() -> None:
    navs = [b for n, b in BUTTONS if "nav_btn_" in n and "nav_bar.yaml" in n]
    assert len(navs) == 4
    for b in navs:
        assert str(b["layout"]["flex_flow"]).upper() == "COLUMN"
