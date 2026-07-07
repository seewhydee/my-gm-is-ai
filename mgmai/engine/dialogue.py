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

from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import ConversationLogEntry, SoftGameState
from mgmai.engine.utils import get_following_npc_ids

DIALOGUE_MAX_LOG_ENTRIES = 10
DIALOGUE_STALL_LIMIT = 3


def enter_dialogue(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    player_utterance: str | None,
    detail: str,
) -> None:
    soft.dialogue_state.active_npc = npc_id
    soft.dialogue_state.conversation_log = []
    soft.dialogue_state.topics_discussed = []
    soft.dialogue_state.entered_turn = turn
    soft.dialogue_state.stall_counter = 0

    if player_utterance:
        _append_log(soft, turn, "player", player_utterance)
    elif detail:
        _append_log(soft, turn, "player", f"[{detail}]")


def append_player_turn(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    utterance: str | None,
    detail: str,
) -> None:
    if soft.dialogue_state.active_npc != npc_id:
        return
    soft.dialogue_state.stall_counter = 0
    text = utterance if utterance else f"[{detail}]"
    _append_log(soft, turn, "player", text)


def append_npc_response(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    response: str,
) -> None:
    if soft.dialogue_state.active_npc != npc_id:
        return
    _append_log(soft, turn, "npc", response)


def _append_log(
    soft: SoftGameState,
    turn: int,
    speaker: str,
    text: str,
) -> None:
    soft.dialogue_state.conversation_log.append(
        ConversationLogEntry(turn=turn, speaker=speaker, text=text)
    )
    if len(soft.dialogue_state.conversation_log) > DIALOGUE_MAX_LOG_ENTRIES:
        soft.dialogue_state.conversation_log = (
            soft.dialogue_state.conversation_log[-DIALOGUE_MAX_LOG_ENTRIES:]
        )


def increment_stall(soft: SoftGameState) -> bool:
    """Increment stall counter. Returns True if dialogue should auto-exit."""
    if soft.dialogue_state.active_npc is None:
        return False
    soft.dialogue_state.stall_counter += 1
    return soft.dialogue_state.stall_counter >= DIALOGUE_STALL_LIMIT


def exit_dialogue(
    soft: SoftGameState,
    corpus: ModuleCorpus,
    hard: HardGameState,
) -> dict | None:
    """Archive conversation and clear dialogue state.

    Returns a dict with optional exit_narrative and side effects or None.
    """
    npc_id = soft.dialogue_state.active_npc
    if npc_id is None:
        return None

    result = _archive_and_exit(soft, npc_id, corpus, hard)
    return result


def check_room_change_exit(
    soft: SoftGameState,
    old_room: str,
    new_room: str,
    corpus: ModuleCorpus,
    hard: HardGameState,
) -> dict | None:
    """Exit dialogue if player moved rooms away from active NPC."""
    npc_id = soft.dialogue_state.active_npc
    if npc_id is None:
        return None

    if old_room == new_room:
        return None

    new_room_data = corpus.rooms.get(new_room)
    if new_room_data and npc_id in hard.room_contains.get(new_room, {}):
        return None

    # Following NPCs travel with the player; don't exit dialogue.
    follower_ids = get_following_npc_ids(hard, corpus)
    if npc_id in follower_ids:
        return None

    return _archive_and_exit(soft, npc_id, corpus, hard)


def _archive_and_exit(
    soft: SoftGameState,
    npc_id: str,
    corpus: ModuleCorpus,
    hard: HardGameState,
) -> dict:
    # Build fallback summary for use when the LLM doesn't provide
    # a better conversation_note (archived after LLM Call 2).
    summary = _build_conversation_summary(soft)
    archival_fallback = (
        f"[Turn {soft.dialogue_state.entered_turn}-"
        f"{hard.turn_count}] "
        f"Conversation summary: {summary}"
    )

    npc_entity = corpus.entities.get(npc_id)
    exit_narrative = None

    soft.dialogue_state.active_npc = None
    soft.dialogue_state.conversation_log = []
    soft.dialogue_state.topics_discussed = []
    soft.dialogue_state.entered_turn = 0
    soft.dialogue_state.stall_counter = 0

    # Note: entity_notes are NOT written here. The archival is deferred to
    # _execute_turn() after LLM Call 2, which may provide a richer
    # conversation_note. The fallback is passed through for that step.
    return {
        "npc_id": npc_id,
        "exit_narrative": exit_narrative,
        "archival_fallback": archival_fallback,
    }


def _build_conversation_summary(soft: SoftGameState) -> str:
    topics = soft.dialogue_state.topics_discussed
    log = soft.dialogue_state.conversation_log
    if not topics and not log:
        return "Brief conversation with no significant topics discussed."
    topic_str = ", ".join(topics) if topics else "various topics"
    return (
        f"Discussed {topic_str} over {len(log)} exchanges."
    )


def track_topic(soft: SoftGameState, topic: str) -> None:
    """Add a topic to the set of discussed topics in dialogue."""
    if soft.dialogue_state.active_npc is None:
        return
    if topic not in soft.dialogue_state.topics_discussed:
        soft.dialogue_state.topics_discussed.append(topic)
