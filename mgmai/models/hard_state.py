from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


class PlayerState(BaseModel):
    location: str
    inventory: list[str] = Field(default_factory=list)
    stats: Optional[Dict[str, int]] = None


class GameOverState(BaseModel):
    type: str  # "win" or "lose"
    trigger: str


class HardGameState(BaseModel):
    player: PlayerState
    flags: Dict[str, bool] = Field(default_factory=dict)
    room_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    entity_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    turn_count: int = 0
    game_over: Optional[GameOverState] = None

    @model_validator(mode="after")
    def check_turn_count_non_negative(self) -> HardGameState:
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")
        return self
