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

import atexit
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    import readline

    _HISTORY_FILE = os.path.expanduser("~/.config/mgmai/history")
    _HISTORY_LENGTH = 1000
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

log = logging.getLogger(__name__)


def _setup_readline() -> None:
    if not _HAS_READLINE:
        return
    readline.parse_and_bind("set editing-mode emacs")
    readline.parse_and_bind("Control-d: delete-char")
    readline.parse_and_bind('"\\e[3~": delete-char')
    readline.parse_and_bind("Control-h: backward-delete-char")


def _load_history() -> None:
    if not _HAS_READLINE:
        return
    _setup_readline()
    try:
        readline.read_history_file(_HISTORY_FILE)
    except (FileNotFoundError, PermissionError):
        pass
    readline.set_history_length(_HISTORY_LENGTH)


def _save_history() -> None:
    if not _HAS_READLINE:
        return
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        readline.write_history_file(_HISTORY_FILE)
    except (OSError, PermissionError):
        pass


atexit.register(_save_history)

from mgmai.context.assembler import assemble
from mgmai.engine.engine import resolve, MAX_CHAIN_LENGTH
from mgmai.engine.post_validate import apply_post_validation
from mgmai.engine.stat_checks import (
    format_stat_check_prefix,
    format_stat_change_prefix,
    format_combat_prefix,
    format_hp_change_prefix,
)
from mgmai.llm.client import LLMClient
from mgmai.llm.parser import LLMOutputError, parse_player_action, parse_prose_output
from mgmai.logging import format_state_snapshot
from mgmai.game.commands import Commands
from mgmai.game.display import Display
from mgmai.game.input_normalizer import normalize_player_input
from mgmai.state.manager import StateManager


FALLBACK_NARRATION = (
    "You try, but something about the situation confuses you. "
    "Perhaps try a different approach?"
)

TURN_ERROR_NARRATION = (
    "Your senses blur for a moment. You can't quite make sense of what "
    "you were trying to do. Perhaps try again?"
)


class GameLoop:
    def __init__(
        self,
        state_manager: StateManager,
        llm_client: LLMClient,
        *,
        debug: bool = False,
        display: Optional[Display] = None,
        config_dir: Optional[str | Path] = None,
    ):
        self._state = state_manager
        self._llm = llm_client
        self._display = display if display is not None else Display()
        self._running = False
        self._chat_log: list[dict[str, str]] = []
        self._config_dir = Path(config_dir) if config_dir else None
        self._commands = Commands(
            state_loader=state_manager,
            render=self._display.print,
            exit_fn=self._do_exit,
            debug=debug,
            on_load=self._on_game_loaded,
            config_dir=config_dir,
            model_config=getattr(llm_client, "_config", None),
            on_model_change=self._on_model_change,
        )

    @property
    def debug(self) -> bool:
        return self._commands.debug

    def start(self) -> None:
        self._display.render_intro(self._state)
        self._running = True
        self._repl()

    # --- REPL ---

    def _repl(self) -> None:
        _load_history()
        while self._running:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                self._display.print("")
                self._do_exit()
                return

            if not line.strip():
                continue

            if _HAS_READLINE:
                readline.add_history(line)

            if self._commands.handle(line):
                continue

            self._run_turn(line)

    # --- turn running ---

    def _run_turn(self, player_input: str) -> None:
        self._chat_log.append({"role": "player", "content": player_input})

        chain_depth = 0
        current_input = normalize_player_input(player_input)
        room_changed = False
        examined_room = False

        while chain_depth < MAX_CHAIN_LENGTH:
            narration = self._execute_turn(current_input, player_input, chain_depth)
            if narration is None:
                return

            result = self._last_result
            action = self._last_action

            if result and result.success:
                if action and action.action_type == "move" and \
                   result.hard_state_changes and \
                   result.hard_state_changes.player_location is not None:
                    room_changed = True
                elif action and action.action_type == "examine" and \
                     result.room_after and action.target == result.room_after.id:
                    examined_room = True

            if (
                result
                and result.chain_info
                and result.chain_info.follow_up
                and not result.chain_info.termination_reason
            ):
                current_input = result.chain_info.follow_up
                chain_depth += 1
                continue

            if result and result.room_after and (room_changed or examined_room):
                exits_text = self._display.format_exits(result.room_after)
                if exits_text:
                    narration = narration + exits_text

            self._chat_log.append({"role": "gm", "content": narration})
            self._display.render_narration(narration)

            # Check for game over and handle end-of-turn bookkeeping
            self._finalize_turn(narration)
            return

        if narration:
            if result and result.room_after and (room_changed or examined_room):
                exits_text = self._display.format_exits(result.room_after)
                if exits_text:
                    narration = narration + exits_text
            self._chat_log.append({"role": "gm", "content": narration})
            self._display.render_narration(narration)
            self._finalize_turn(narration)

    # ------------------------------------------------------------------
    # single-turn execution
    # ------------------------------------------------------------------

    def _execute_turn(
        self,
        current_input: str,
        original_input: str,
        chain_depth: int,
    ) -> Optional[str]:
        corpus = self._state.corpus
        hard = self._state.hard_state
        soft = self._state.soft_state

        if corpus is None or hard is None or soft is None:
            self._display.render_error("Game state is not loaded.")
            return None

        # 1. Context Assembler → GMBriefing
        briefing = assemble(corpus, hard, soft, current_input)

        log.debug("--- GMBriefing ---\n%s", briefing.model_dump_json(indent=2))

        # 2. LLM Call 1 → PlayerAction (with retry on malformed output)
        try:
            action = self._call_ruling(briefing)
        except LLMOutputError:
            self._display.render_narration(FALLBACK_NARRATION)
            return None

        log.debug("--- PlayerAction ---\n%s", action.model_dump_json(indent=2))

        # 3. Engine → EngineResult
        result = resolve(
            action,
            self._state,
            chain_depth=chain_depth,
            player_input_echo=original_input,
        )
        self._last_result = result
        self._last_action = action

        log.debug("--- EngineResult ---\n%s", result.model_dump_json(indent=2))

        log.debug(
            "--- State After Turn ---\n%s",
            json.dumps(format_state_snapshot(hard, soft), indent=2),
        )

        # 4. LLM Call 2 → ProseOutput
        try:
            prose = self._call_prose(briefing, action, result)
        except LLMOutputError:
            narration = result.triggered_narration[0] if result.triggered_narration else TURN_ERROR_NARRATION
            check_prefix = format_stat_check_prefix(result.rolls)
            if check_prefix:
                narration = check_prefix + narration
            hc = result.hard_state_changes
            if hc and hc.player_hp_delta:
                hp_prefix = format_hp_change_prefix(
                    hc.player_hp_delta,
                    hard.player.current_hp or 0,
                    hard.player.max_hp or 0,
                )
                if hp_prefix:
                    narration = hp_prefix + narration
            if hc and hc.stat_modifiers:
                stat_prefix = format_stat_change_prefix(hc.stat_modifiers, hc.old_stat_values)
                if stat_prefix:
                    narration = stat_prefix + narration
            return narration

        log.debug("--- ProseOutput ---\n%s", prose.model_dump_json(indent=2))

        # 4.5 Feed dialogue state from prose output
        if action.action_type != "ooc_discussion":
            from mgmai.engine.dialogue import append_npc_response, track_topic

            if prose.npc_response and soft.dialogue_state.active_npc is not None:
                append_npc_response(
                    soft,
                    soft.dialogue_state.active_npc,
                    hard.turn_count,
                    prose.npc_response,
                )

            if prose.knowledge_tags and prose.knowledge_tags.npc_revealed:
                for npc_id, topics in prose.knowledge_tags.npc_revealed.items():
                    for topic in topics:
                        track_topic(soft, topic)

        # 4.6 Archive conversation note if dialogue just ended
        if result.dialogue_exited is not None:
            npc_id = result.dialogue_exited.npc_id
            note = prose.conversation_note or result.dialogue_exited.archival_fallback
            if note:
                soft.entity_notes.setdefault(npc_id, []).append(note)

        # 5. Post-validate knowledge_tags + attitude_changes
        kt = prose.knowledge_tags.npc_revealed if prose.knowledge_tags else None
        ac = dict(prose.attitude_changes) if prose.attitude_changes else None
        if kt or ac:
            result = apply_post_validation(kt, ac, self._state, result)
            self._last_result = result

        # LLM Call 2 may narratively terminate an ongoing chained action
        if prose.terminate_chain:
            result = self._last_result
            if result and result.chain_info and not result.chain_info.termination_reason:
                from mgmai.models.actions import ChainInfo
                result.chain_info = ChainInfo(
                    follow_up=result.chain_info.follow_up,
                    termination_reason="narrative termination by LLM Call 2",
                )
                self._last_result = result

        narration = prose.narration
        ## To consider: If the narrator forgot to include the NPC
        ## dialogue in the narration, append it as a fallback?
        # if prose.npc_response and prose.npc_response not in narration:
        #     narration = narration + "\n\n\"" + prose.npc_response + "\""
        check_prefix = format_stat_check_prefix(result.rolls)
        if check_prefix:
            narration = check_prefix + narration
        hc = result.hard_state_changes
        if hc and hc.player_hp_delta:
            hp_prefix = format_hp_change_prefix(
                hc.player_hp_delta,
                hard.player.current_hp or 0,
                hard.player.max_hp or 0,
            )
            if hp_prefix:
                narration = hp_prefix + narration
        if hc and hc.stat_modifiers:
            stat_prefix = format_stat_change_prefix(hc.stat_modifiers, hc.old_stat_values)
            if stat_prefix:
                narration = stat_prefix + narration
        # Prepend combat summary prefix
        if result.combat_log:
            combat_prefix = format_combat_prefix(
                [e if isinstance(e, dict) else e.model_dump() for e in result.combat_log],
                corpus,
            )
            if combat_prefix:
                narration = combat_prefix + narration
        return narration

    # ------------------------------------------------------------------
    # turn finalization
    # ------------------------------------------------------------------

    def _finalize_turn(self, narration: str) -> None:
        hard = self._state.hard_state
        if hard is None:
            return

        if hard.game_over is not None:
            # Build a lightweight result object for the display
            from mgmai.models.actions import GameOverResult

            go = GameOverResult(
                type=hard.game_over.type,
                trigger=hard.game_over.trigger,
            )
            self._display.render_game_over(go)
            self._do_exit()
            return

        self._display.render_status(self._state)
        self._auto_save(narration)

    def _auto_save(self, narration: str) -> None:
        try:
            save_path = self._get_autosave_path()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            self._state.save_state(
                save_path.parent, save_path.name, latest_narration=narration
            )
        except Exception:
            # Auto-save failure is non-fatal; don't interrupt the player
            pass

    def _get_autosave_path(self) -> Path:
        from mgmai.config import get_autosave_path

        adv_name = self._adventure_name()
        if self._config_dir:
            return get_autosave_path(adv_name, self._config_dir)
        return Path("autosave.json")

    def _adventure_name(self) -> str:
        if self._state._adventure_dir:
            return self._state._adventure_dir.name
        return "game"

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _call_ruling(self, briefing):
        from mgmai.templates.renderer import render_ruling

        system_prompt = render_ruling()
        user_prompt = briefing.model_dump_json(indent=2)

        raw = self._llm.call_ruling(system_prompt, user_prompt)
        log.debug("--- LLM Call 1 raw ---\n%s", raw)

        try:
            return parse_player_action(raw)
        except LLMOutputError:
            log.debug("LLM Call 1 retry after parse error")
            retry_prompt = (
                user_prompt
                + "\n\n[ERROR FROM PREVIOUS ATTEMPT: Your JSON was invalid. "
                + "Please ensure valid JSON with a correct 'action_type' discriminator.]"
            )
            raw = self._llm.call_ruling(system_prompt, retry_prompt)
            log.debug("--- LLM Call 1 retry raw ---\n%s", raw)
            return parse_player_action(raw)

    def _call_prose(self, briefing, action, result):
        from mgmai.templates.renderer import render_prose

        system_prompt = render_prose()

        user_data = {
            "setting": briefing.setting,
            "tone": briefing.tone,
            "briefing": briefing.model_dump(mode="json"),
            "player_action": action.model_dump(mode="json"),
            "engine_result": result.model_dump(mode="json"),
            "chat_log": self._chat_log[-10:],
        }

        if result.will_reveal_readiness:
            user_data["will_reveal_readiness"] = {
                npc: {
                    tid: entry.model_dump(mode="json")
                    for tid, entry in topics.items()
                }
                for npc, topics in result.will_reveal_readiness.items()
            }

        if result.chain_info and result.chain_info.follow_up:
            user_data["chained_action"] = True

        user_prompt = json.dumps(user_data, indent=2)

        raw = self._llm.call_prose(system_prompt, user_prompt)
        log.debug("--- LLM Call 2 raw ---\n%s", raw)

        return parse_prose_output(raw)

    # --- internal ---

    _last_result: Any = None
    _last_action: Any = None

    def _on_game_loaded(self) -> None:
        self._chat_log.clear()
        self._last_result = None

    def _on_model_change(self, api_key: str, config: object) -> None:
        self._llm = LLMClient(api_key=api_key, config=config)

    def _do_exit(self) -> None:
        self._running = False
        self._display.render_goodbye()
