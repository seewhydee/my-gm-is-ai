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
import time
from typing import Any

from openai import OpenAI

from mgmai.llm.model_config import ModelConfig

log = logging.getLogger(__name__)

# Degenerate-response retry: providers under load occasionally answer a
# well-formed request with a 200 carrying ``choices: null`` (or an empty
# message).  This is a transport-level anomaly, distinct from malformed
# *content* (which is the game loop's responsibility, via corrective
# retry prompts); the SDK's own retry only covers HTTP error statuses,
# so we re-ask a few times with a short backoff before giving up.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = (1.0, 2.0)


class LLMClient:
    """Thin wrapper around the OpenAI-compatible client for the two LLM calls.

    Call 1 (ruling) — low-temperature, strict JSON, interprets player input.
    Call 2 (prose)  — moderate-temperature, creative, narrates engine outcomes.

    The client retries only degenerate transport-level responses (no
    choices, empty content).  Retries of malformed *content* are the
    game loop's responsibility.
    """

    def __init__(self, api_key: str, config: ModelConfig) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._config = config

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """The configured model name (for run metadata / logging)."""
        return self._config.name

    def call_ruling(self, system_prompt: str, user_prompt: str) -> str:
        """LLM Call 1: interpret player input → PlayerAction JSON.

        Returns the raw JSON string from the model.  Callers must parse
        it with :func:`parse_player_action`.
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._config.ruling_temperature,
            max_tokens=self._config.ruling_max_tokens)

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        """LLM Call 2: narrate engine outcome → prose + optional blocks.

        Returns the raw JSON string from the model.  Callers must parse
        it with :func:`parse_prose_output`.
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._config.prose_temperature,
            max_tokens=self._config.prose_max_tokens)

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = True,
    ) -> str:
        """Generic single-shot chat completion.

        Used by auxiliary LLM roles (player driver, integration-test
        judge) that don't fit the ruling/prose dichotomy.  Defaults to
        the model's prose temperature and prose max_tokens when not
        specified.

        *json_mode* can be set to ``False`` to suppress
        ``response_format`` even when the model config enables it (e.g.
        for the player driver, which produces plain-text commands).
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else self._config.prose_temperature,
            max_tokens=max_tokens if max_tokens is not None else self._config.prose_max_tokens,
            json_mode=json_mode,
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _call(self, system_prompt: str, user_prompt: str,
              temperature: float | None,
              max_tokens: int,
              json_mode: bool = True) -> str:
        kwargs: dict[str, Any] = {
            "model": self._config.name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_mode and self._config.supports_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._config.extra_body is not None:
            kwargs["extra_body"] = self._config.extra_body

        log.debug(
            "LLM request: model=%s temperature=%s max_tokens=%s json_mode=%s\n"
            "SYSTEM:\n%s\nUSER:\n%s",
            self._config.name, temperature, max_tokens, json_mode,
            system_prompt, user_prompt,
        )
        response = None
        content = None
        for attempt in range(_MAX_ATTEMPTS):
            response = self._client.chat.completions.create(**kwargs)
            choices = getattr(response, "choices", None)
            if choices:
                content = choices[0].message.content
            if content is not None:
                break
            log.warning(
                "LLM returned a degenerate response (attempt %d/%d): %r",
                attempt + 1, _MAX_ATTEMPTS, response,
            )
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_S[attempt])

        if content is None:
            raise RuntimeError("LLM returned empty content")

        log.debug("LLM response:\n%s", content)
        return content
