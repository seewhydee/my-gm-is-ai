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

from dataclasses import replace

import pytest

from mgmai.llm.model_config import (
    ModelConfig,
    _MODEL_REGISTRY,
    get_known_model_labels,
    get_model_config,
    list_known_models,
    register_model,
)


class TestGetModelConfig:
    def test_returns_registry_entry_for_known_model(self):
        config = get_model_config("deepseek-v4-flash")
        assert config.name == "deepseek-v4-flash"
        assert config.label == "Deepseek v4 Flash (Deepseek API)"
        assert config.base_url == "https://api.deepseek.com"
        assert config.ruling_temperature == 1.0
        assert config.prose_temperature == 1.1
        assert config.extra_body == {"thinking": {"type": "disabled"}}

    def test_unknown_model_without_base_url_raises(self):
        with pytest.raises(ValueError, match="Unknown model 'gpt-4o'"):
            get_model_config("gpt-4o")

    def test_kimi_omits_temperatures(self):
        config = get_model_config("kimi-k2.6")
        assert config.ruling_temperature is None
        assert config.prose_temperature is None

    def test_unknown_model_with_base_url_returns_generic_default(self):
        config = get_model_config("gpt-4o", base_url="https://api.openai.com/v1")
        assert config.name == "gpt-4o"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.ruling_temperature is None
        assert config.prose_temperature is None
        assert config.extra_body is None

    def test_base_url_override_for_known_model(self):
        config = get_model_config("deepseek-v4-flash", base_url="https://proxy.example.com")
        assert config.base_url == "https://proxy.example.com"
        assert config.name == "deepseek-v4-flash"

    def test_base_url_override_for_unknown_model(self):
        config = get_model_config("some-model", base_url="https://custom.example.com")
        assert config.base_url == "https://custom.example.com"
        assert config.name == "some-model"

    def test_unknown_model_uses_provided_base_url_instead_of_openai_default(self):
        config = get_model_config("custom-model", base_url="http://localhost:8000")
        assert config.base_url == "http://localhost:8000"


class TestListKnownModels:
    def test_includes_deepseek_v4_flash(self):
        models = list_known_models()
        assert "deepseek-v4-flash" in models

    def test_returns_names_not_labels(self):
        models = list_known_models()
        assert "Deepseek v4 Flash" not in models
        assert all(isinstance(m, str) for m in models)


class TestGetKnownModelLabels:
    def test_maps_names_to_labels(self):
        labels = get_known_model_labels()
        assert labels["deepseek-v4-flash"] == "Deepseek v4 Flash (Deepseek API)"
        assert "kimi-k2.6" in labels

    def test_falls_back_to_name_when_label_missing(self):
        register_model(ModelConfig(
            name="unlabeled-model",
            base_url="https://example.com",
            ruling_temperature=0.5,
            prose_temperature=0.6,
        ))
        try:
            labels = get_known_model_labels()
            assert labels["unlabeled-model"] == "unlabeled-model"
        finally:
            _MODEL_REGISTRY.pop("unlabeled-model", None)


class TestRegisterModel:
    def test_adds_new_model_to_registry(self):
        config = ModelConfig(
            name="test-model",
            base_url="https://test.example.com",
            ruling_temperature=0.5,
            prose_temperature=0.6,
        )
        register_model(config)
        try:
            retrieved = get_model_config("test-model")
            assert retrieved == config
        finally:
            _MODEL_REGISTRY.pop("test-model", None)

    def test_overwrites_existing_model(self):
        original = get_model_config("deepseek-v4-flash")
        new_config = replace(original, ruling_temperature=0.99)
        register_model(new_config)

        retrieved = get_model_config("deepseek-v4-flash")
        assert retrieved.ruling_temperature == 0.99

        # Restore original to avoid polluting global state for other tests
        register_model(original)
