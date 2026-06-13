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

from mgmai.llm.client import LLMClient
from mgmai.llm.model_config import ModelConfig


def _make_client(
    *,
    ruling_temperature: float | None = 0.5,
    prose_temperature: float | None = 0.6,
) -> LLMClient:
    config = ModelConfig(
        name="test-model",
        base_url="https://api.example.com",
        ruling_temperature=ruling_temperature,
        prose_temperature=prose_temperature,
    )
    return LLMClient(api_key="fake-key", config=config)


class TestTemperatureHandling:
    """Temperature is omitted from API calls when the model config leaves it null."""

    def test_ruling_passes_temperature_when_set(self):
        client = _make_client(ruling_temperature=0.25)
        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"x": 1}'))]
            )
            client.call_ruling("system", "user")

        kwargs = mock_create.call_args.kwargs
        assert kwargs["temperature"] == 0.25

    def test_prose_passes_temperature_when_set(self):
        client = _make_client(prose_temperature=0.75)
        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"x": 1}'))]
            )
            client.call_prose("system", "user")

        kwargs = mock_create.call_args.kwargs
        assert kwargs["temperature"] == 0.75

    def test_ruling_omits_temperature_when_none(self):
        client = _make_client(ruling_temperature=None)
        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"x": 1}'))]
            )
            client.call_ruling("system", "user")

        kwargs = mock_create.call_args.kwargs
        assert "temperature" not in kwargs

    def test_prose_omits_temperature_when_none(self):
        client = _make_client(prose_temperature=None)
        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"x": 1}'))]
            )
            client.call_prose("system", "user")

        kwargs = mock_create.call_args.kwargs
        assert "temperature" not in kwargs
