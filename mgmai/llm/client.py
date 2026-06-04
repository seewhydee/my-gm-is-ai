from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


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
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        ruling_temperature: float = 0.9,
        prose_temperature: float = 1.1,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model
        self._ruling_temperature = ruling_temperature
        self._prose_temperature = prose_temperature

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
            temperature=self._ruling_temperature,
        )

    def call_prose(self, system_prompt: str, user_prompt: str) -> str:
        """LLM Call 2: narrate engine outcome → prose + optional blocks.

        Returns the raw JSON string from the model.  Callers must parse
        it with :func:`parse_prose_output`.
        """
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._prose_temperature,
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
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        choice = response.choices[0]
        if choice.message.content is None:
            raise RuntimeError("LLM returned empty content")

        return choice.message.content
