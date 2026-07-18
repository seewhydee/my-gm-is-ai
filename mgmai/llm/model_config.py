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

import json
import logging
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MODELS_FILENAME = "models.json"


@dataclass(frozen=True)
class ModelConfig:
    """Model-specific settings for an OpenAI-compatible LLM.

    Each field captures a quirk or requirement of a particular model so
    that the rest of the codebase can remain model-agnostic.
    """

    name: str
    base_url: str
    ruling_temperature: float | None = None
    prose_temperature: float | None = None
    label: str | None = None
    extra_body: dict[str, Any] | None = None
    supports_json_mode: bool = True
    request_timeout: float = 300.0
    ruling_max_tokens: int = 800
    prose_max_tokens: int = 2000


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

_MODEL_REGISTRY: dict[str, ModelConfig] = {
    # -- Fast / non-reasoning models --
    "deepseek-v4-flash": ModelConfig(
        name="deepseek-v4-flash",
        label="Deepseek v4 Flash (Deepseek API)",
        base_url="https://api.deepseek.com",
        ruling_temperature=1.0,
        prose_temperature=1.1,
        extra_body={"thinking": {"type": "disabled"}},
    ),
    "kimi-k2.6": ModelConfig(
        name="kimi-k2.6",
        label="Kimi K2.6 (Moonshot API)",
        base_url="https://api.moonshot.ai/v1",
        ruling_temperature=None,
        prose_temperature=None,
    ),
    "mimo-v2.5": ModelConfig(
        name="mimo-v2.5",
        label="Mimo 2.5 (Xiaomi API)",
        base_url="https://api.xiaomimimo.com/v1",
        ruling_temperature=0.6,
        prose_temperature=0.7,
    ),
    "mistral-small-2603": ModelConfig(
        name="mistral-small-2603",
        label="Mistral Small 4 (Mistral API)",
        base_url="https://api.mistral.ai/v1",
        ruling_temperature=0.65,
        prose_temperature=0.75,
    ),
    # -- Reasoning models --
    #
    # NOTE: These are placeholders.  You MUST fill in the correct
    # model *name* (the identifier the provider's API expects) for each
    # entry.  The ``base_url`` should point to the provider's
    # OpenAI-compatible endpoint.  Adjust ``max_tokens`` upwards (some
    # reasoning models need ≥4096 to fit chain-of-thought).
    #
    # Reasoning models often expose a separate "thinking budget".
    # Use ``extra_body`` to pass provider-specific parameters:
    #
    #   DeepSeek:  {"thinking": {"type": "enabled"}}
    #   OpenAI:    {"reasoning_effort": "medium"}  (o1/o3 series)
    #   Groq:      {} (enabled by default on reasoning models)
    #
    # Set ``supports_json_mode=False`` if the model doesn't support
    # structured JSON output (e.g. early Anthropic reasoning models).

    "deepseek-reasoner": ModelConfig(
        name="deepseek-reasoner",          # FIXME: verify correct model name
        label="Deepseek Reasoner (Deepseek API)",
        base_url="https://api.deepseek.com",
        ruling_temperature=None,           # reasoning models often require None
        prose_temperature=None,
        extra_body={"thinking": {"type": "enabled"}},
        supports_json_mode=True,
        prose_max_tokens=4096,             # reasoning needs headroom for CoT
    ),
    # Add more reasoning models here following the same pattern:
    #
    # "groq-reasoning": ModelConfig(
    #     name="FIXME-model-name",
    #     label="Groq Reasoning Model (Groq API)",
    #     base_url="FIXME",
    #     ruling_temperature=None,
    #     prose_temperature=None,
    #     extra_body=None,
    #     supports_json_mode=True,
    #     prose_max_tokens=4096,
    # ),
    #
    # "openai-o3-mini": ModelConfig(
    #     name="FIXME-model-name",
    #     label="OpenAI o3-mini (OpenAI API)",
    #     base_url="FIXME",
    #     ruling_temperature=None,
    #     prose_temperature=None,
    #     extra_body={"reasoning_effort": "medium"},
    #     supports_json_mode=True,
    #     prose_max_tokens=4096,
    # ),
}

# ------------------------------------------------------------------
# Custom model loading (models.json)
# ------------------------------------------------------------------

_VALID_CONFIG_FIELDS = {f.name for f in fields(ModelConfig)}


def load_custom_models(config_dir: str | Path) -> dict[str, ModelConfig]:
    """Load user-defined model configurations from *config_dir*/models.json.

    Returns an empty dict if the file does not exist.  Invalid entries
    are logged as warnings and skipped.
    """
    path = Path(config_dir) / MODELS_FILENAME
    if not path.is_file():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return {}

    if not isinstance(data, dict):
        log.warning("%s must contain a JSON object, got %s", path, type(data).__name__)
        return {}

    result: dict[str, ModelConfig] = {}
    for model_name, entry in data.items():
        if not isinstance(entry, dict):
            log.warning("%s: entry '%s' is not a JSON object — skipping", path, model_name)
            continue

        unknown = set(entry) - _VALID_CONFIG_FIELDS - {"name"}
        if unknown:
            log.warning(
                "%s: entry '%s' has unknown fields: %s — ignoring",
                path, model_name, ", ".join(sorted(unknown)),
            )

        if "base_url" not in entry:
            log.warning(
                "%s: entry '%s' missing required 'base_url' — skipping",
                path, model_name,
            )
            continue

        kwargs: dict[str, Any] = {"name": entry.get("name", model_name)}
        for key in ("base_url", "ruling_temperature", "prose_temperature",
                     "label", "extra_body", "supports_json_mode",
                     "request_timeout", "ruling_max_tokens", "prose_max_tokens"):
            if key in entry:
                kwargs[key] = entry[key]

        try:
            result[model_name] = ModelConfig(**kwargs)
        except TypeError as exc:
            log.warning(
                "%s: entry '%s' has invalid field types: %s — skipping",
                path, model_name, exc,
            )

    return result


def _resolve_model_config(
    model_name: str,
    base_url: str | None,
    custom_models: dict[str, ModelConfig] | None,
) -> ModelConfig:
    """Resolve a ModelConfig from custom models, registry, or generic defaults.

    Lookup order: custom_models > registry > generic (requires base_url).
    """
    if custom_models and model_name in custom_models:
        config = custom_models[model_name]
    elif model_name in _MODEL_REGISTRY:
        config = _MODEL_REGISTRY[model_name]
    else:
        if base_url is None:
            raise ValueError(
                f"Unknown model '{model_name}' and no base_url provided. "
                "Pass --base-url, set it in models.json, or register the model."
            )
        config = ModelConfig(
            name=model_name,
            base_url=base_url,
            extra_body=None,
            supports_json_mode=False,
        )

    if base_url is not None:
        config = replace(config, base_url=base_url)

    return config


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def get_model_config(
    model_name: str,
    base_url: str | None = None,
    custom_models: dict[str, ModelConfig] | None = None,
) -> ModelConfig:
    """Return the configuration for *model_name*.

    Lookup order: custom_models > built-in registry > generic fallback.
    For unknown models a generic safe default is returned only when a
    *base_url* is provided; otherwise an error is raised.

    An optional *base_url* overrides the value stored in the registry
    or custom models.
    """
    return _resolve_model_config(model_name, base_url, custom_models)


def list_known_models(
    custom_models: dict[str, ModelConfig] | None = None,
) -> list[str]:
    """Return the names of all registered models (built-in + custom)."""
    names = set(_MODEL_REGISTRY)
    if custom_models:
        names.update(custom_models)
    return sorted(names)


def get_known_model_labels(
    custom_models: dict[str, ModelConfig] | None = None,
) -> dict[str, str]:
    """Return a mapping of model name to human-readable label."""
    all_models = dict(_MODEL_REGISTRY)
    if custom_models:
        all_models.update(custom_models)
    return {
        name: (config.label or name)
        for name, config in all_models.items()
    }


def register_model(config: ModelConfig) -> None:
    """Register (or overwrite) a model configuration at runtime."""
    _MODEL_REGISTRY[config.name] = config
