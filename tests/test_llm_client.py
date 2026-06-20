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

"""Tests for llm/client.py — LLM API wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from mgmai.llm.client import LLMClient
from mgmai.llm.model_config import ModelConfig


class TestLLMClient:
    """Tests for LLMClient — API wrapper behaviour."""

    @pytest.mark.parametrize("method_name,temp,expect_key", [
        ("call_ruling", 0.25, "temperature"),
        ("call_prose", 0.75, "temperature"),
        ("call_ruling", None, None),
        ("call_prose", None, None),
    ])
    def test_temperature_forwarding(self, method_name, temp, expect_key):
        """Temperature is forwarded/omitted based on config value."""
        config = ModelConfig(
            name="test-model",
            base_url="https://api.example.com",
            ruling_temperature=temp if method_name == "call_ruling" else 0.5,
            prose_temperature=temp if method_name == "call_prose" else 0.5,
        )
        client = LLMClient(api_key="fake-key", config=config)

        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"x": 1}'))]
            )
            result = getattr(client, method_name)("system", "user")

        assert result == '{"x": 1}'
        kwargs = mock_create.call_args.kwargs
        if expect_key is not None:
            assert kwargs[expect_key] == temp
        else:
            assert "temperature" not in kwargs

    def test_raises_on_empty_content(self):
        """RuntimeError when LLM returns content=None."""
        config = ModelConfig(
            name="test-model",
            base_url="https://api.example.com",
        )
        client = LLMClient(api_key="fake-key", config=config)

        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=None))]
            )
            with pytest.raises(RuntimeError, match="empty content"):
                client.call_ruling("system", "user")
