from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)


def render_ruling(**kwargs: Any) -> str:
    return _env.get_template("ruling.j2").render(**kwargs)


def render_prose(**kwargs: Any) -> str:
    return _env.get_template("prose.j2").render(**kwargs)
