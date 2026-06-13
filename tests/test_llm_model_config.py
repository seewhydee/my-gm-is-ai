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
    get_model_config,
    list_known_models,
    register_model,
)


class TestGetModelConfig:
    def test_returns_registry_entry_for_known_model(self):
        config = get_model_config("deepseek-v4-flash")
        assert config.name == "deepseek-v4-flash"
        assert config.base_url == "https://api.deepseek.com"
        assert config.ruling_temperature == 0.9
        assert config.prose_temperature == 1.1
        assert config.extra_body == {"thinking": {"type": "disabled"}}

    def test_unknown_model_without_base_url_raises(self):
        with pytest.raises(ValueError, match="Unknown model 'gpt-4o'"):
            get_model_config("gpt-4o")

    def test_unknown_model_with_base_url_returns_generic_default(self):
        config = get_model_config("gpt-4o", base_url="https://api.openai.com/v1")
        assert config.name == "gpt-4o"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.ruling_temperature == 0.7
        assert config.prose_temperature == 0.9
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


class TestRegisterModel:
    def test_adds_new_model_to_registry(self):
        config = ModelConfig(
            name="test-model",
            base_url="https://test.example.com",
            ruling_temperature=0.5,
            prose_temperature=0.6,
        )
        register_model(config)

        retrieved = get_model_config("test-model")
        assert retrieved == config

    def test_overwrites_existing_model(self):
        original = get_model_config("deepseek-v4-flash")
        new_config = replace(original, ruling_temperature=0.99)
        register_model(new_config)

        retrieved = get_model_config("deepseek-v4-flash")
        assert retrieved.ruling_temperature == 0.99

        # Restore original to avoid polluting global state for other tests
        register_model(original)
