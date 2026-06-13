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
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class AttitudeChange(BaseModel):
    old_value: int
    new_value: int
    reason: str

class KnowledgeTags(BaseModel):
    npc_revealed: Optional[Dict[str, List[str]]] = None

class NarrationOutput(BaseModel):
    narration: str
    npc_response: Optional[str] = None
    knowledge_tags: Optional[KnowledgeTags] = None
    attitude_changes: Optional[Dict[str, AttitudeChange]] = None
    conversation_note: Optional[str] = None
    terminate_chain: bool = False
