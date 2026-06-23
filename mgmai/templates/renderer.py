from __future__ import annotations
from pathlib import Path
from typing import Any
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).resolve().parent

_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                   autoescape=False)

def render_ruling(**kwargs: Any) -> str:
    return _env.get_template("ruling.j2").render(**kwargs)

def render_prose(
    *,
    include_combat: bool = False,
    include_dialogue: bool = False,
    **kwargs: Any,
) -> str:
    combat_section = ""
    if include_combat:
        combat_section = _env.get_template("prose_combat.j2").render()

    dialogue_section = ""
    if include_dialogue:
        dialogue_section = _env.get_template("prose_dialogue.j2").render()

    return _env.get_template("prose.j2").render(
        combat_section=combat_section,
        dialogue_section=dialogue_section,
        **kwargs,
    )
