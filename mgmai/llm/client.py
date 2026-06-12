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

import logging
from typing import Any

from openai import OpenAI

from mgmai.llm.model_config import ModelConfig

log = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around the OpenAI-compatible client for the two LLM calls.

    Call 1 (ruling) — low-temperature, strict JSON, interprets player input.
    Call 2 (prose)  — moderate-temperature, creative, narrates engine outcomes.

    The client does **not** handle retries — that is the game loop's
    responsibility.
    """

    def __init__(
        self,
        api_key: str,
        config: ModelConfig,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
        )
        self._config = config

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def call_ruling(self, system_prompt: str, user_prompt: str) -> str:
        """LLM Call 1: interpret player input → PlayerAction JSON.

        Returns the raw JSON string from the model.  Callers must parse
        it with :func:`parse_player_action`.
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._config.ruling_temperature,
        )

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        """LLM Call 2: narrate engine outcome → prose + optional blocks.

        Returns the raw JSON string from the model.  Callers must parse
        it with :func:`parse_prose_output`.
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._config.prose_temperature,
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._config.name,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._config.supports_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._config.extra_body is not None:
            kwargs["extra_body"] = self._config.extra_body

        response = self._client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        if choice.message.content is None:
            raise RuntimeError("LLM returned empty content")

        return choice.message.content
