# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    """Model-specific settings for an OpenAI-compatible LLM.

    Each field captures a quirk or requirement of a particular model so
    that the rest of the codebase can remain model-agnostic.
    """

    name: str
    base_url: str
    ruling_temperature: float
    prose_temperature: float
    extra_body: dict[str, Any] | None = None
    supports_json_mode: bool = True


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

_MODEL_REGISTRY: dict[str, ModelConfig] = {
    "deepseek-v4-flash": ModelConfig(
        name="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        ruling_temperature=0.9,
        prose_temperature=1.1,
        extra_body={"thinking": {"type": "disabled"}},
    ),
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def get_model_config(model_name: str, base_url: str | None = None) -> ModelConfig:
    """Return the configuration for *model_name*.

    If the model is present in the registry its stored settings are used.
    For unknown models a generic safe default is returned only when a
    *base_url* is provided; otherwise an error is raised so that the
    system does not silently default to a vendor URL.

    An optional *base_url* overrides the value stored in the registry.
    """
    if model_name in _MODEL_REGISTRY:
        config = _MODEL_REGISTRY[model_name]
    else:
        if base_url is None:
            raise ValueError(
                f"Unknown model '{model_name}' and no base_url provided. "
                "Pass --base-url or register the model."
            )
        config = ModelConfig(
            name=model_name,
            base_url=base_url,
            ruling_temperature=0.7,
            prose_temperature=0.9,
            extra_body=None,
        )

    if base_url is not None:
        config = replace(config, base_url=base_url)

    return config


def list_known_models() -> list[str]:
    """Return the names of all models in the registry."""
    return list(_MODEL_REGISTRY.keys())


def register_model(config: ModelConfig) -> None:
    """Register (or overwrite) a model configuration at runtime."""
    _MODEL_REGISTRY[config.name] = config
