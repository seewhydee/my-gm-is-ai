from __future__ import annotations

import json
from typing import Any, Optional

from mgmai.context.assembler import assemble
from mgmai.engine.engine import resolve, MAX_CHAIN_LENGTH
from mgmai.engine.post_validate import apply_post_validation
from mgmai.llm.client import LLMClient
from mgmai.llm.parser import LLMOutputError, parse_player_action, parse_prose_output
from mgmai.game.commands import Commands
from mgmai.game.display import Display
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
    ):
        self._state = state_manager
        self._llm = llm_client
        self._display = display if display is not None else Display()
        self._running = False
        self._chat_log: list[dict[str, str]] = []
        self._commands = Commands(
            state_loader=state_manager,
            render=self._display.print,
            exit_fn=self._do_exit,
            debug=debug,
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
        while self._running:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                self._display.print()
                self._do_exit()
                return

            if not line.strip():
                continue

            if self._commands.handle(line):
                continue

            self._run_turn(line)

    # --- turn running ---

    def _run_turn(self, player_input: str) -> None:
        self._chat_log.append({"role": "player", "content": player_input})

        chain_depth = 0
        current_input = player_input

        while chain_depth < MAX_CHAIN_LENGTH:
            narration = self._execute_turn(current_input, player_input, chain_depth)
            if narration is None:
                return

            result = self._last_result

            if (
                result
                and result.chain_info
                and result.chain_info.follow_up
                and not result.chain_info.termination_reason
            ):
                current_input = result.chain_info.follow_up
                chain_depth += 1
                continue

            self._chat_log.append({"role": "gm", "content": narration})
            self._display.render_narration(narration)
            return

        self._display.render_narration(TURN_ERROR_NARRATION)

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

        if self._commands.debug:
            self._display.print(
                "\n[dim]--- GMBriefing ---[/dim]\n"
                + briefing.model_dump_json(indent=2)
            )

        # 2. LLM Call 1 → PlayerAction (with retry on malformed output)
        try:
            action = self._call_ruling(briefing)
        except LLMOutputError:
            self._display.render_narration(FALLBACK_NARRATION)
            return None

        if self._commands.debug:
            self._display.print(
                "\n[dim]--- PlayerAction ---[/dim]\n"
                + action.model_dump_json(indent=2)
            )

        # 3. Engine → EngineResult
        result = resolve(
            action,
            self._state,
            chain_depth=chain_depth,
            player_input_echo=original_input,
        )
        self._last_result = result

        if self._commands.debug:
            self._display.print(
                "\n[dim]--- EngineResult ---[/dim]\n"
                + result.model_dump_json(indent=2)
            )

        # 4. LLM Call 2 → ProseOutput
        try:
            prose = self._call_prose(briefing, action, result)
        except LLMOutputError:
            narration = result.triggered_narration[0] if result.triggered_narration else TURN_ERROR_NARRATION
            return narration

        if self._commands.debug:
            self._display.print(
                "\n[dim]--- ProseOutput ---[/dim]\n"
                + prose.model_dump_json(indent=2)
            )

        # 5. Post-validate knowledge_tags + attitude_changes
        kt = prose.knowledge_tags.npc_revealed if prose.knowledge_tags else None
        ac = dict(prose.attitude_changes) if prose.attitude_changes else None
        if kt or ac:
            result = apply_post_validation(kt, ac, self._state, result)
            self._last_result = result

        return prose.narration

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _call_ruling(self, briefing):
        from mgmai.templates.renderer import render_ruling

        system_prompt = render_ruling()
        user_prompt = briefing.model_dump_json(indent=2)

        raw = self._llm.call_ruling(system_prompt, user_prompt)

        if self._commands.debug:
            self._display.print(f"\n[dim]--- LLM Call 1 raw ---[/dim]\n{raw}")

        try:
            return parse_player_action(raw)
        except LLMOutputError:
            if self._commands.debug:
                self._display.print("[yellow]LLM Call 1 retry after parse error[/yellow]")
            retry_prompt = (
                user_prompt
                + "\n\n[ERROR FROM PREVIOUS ATTEMPT: Your JSON was invalid. "
                + "Please ensure valid JSON with a correct 'action_type' discriminator.]"
            )
            raw = self._llm.call_ruling(system_prompt, retry_prompt)
            if self._commands.debug:
                self._display.print(f"\n[dim]--- LLM Call 1 retry raw ---[/dim]\n{raw}")
            return parse_player_action(raw)

    def _call_prose(self, briefing, action, result):
        from mgmai.templates.renderer import render_prose

        system_prompt = render_prose()

        user_data = {
            "setting": briefing.setting,
            "tone": briefing.tone,
            "briefing": json.loads(briefing.model_dump_json()),
            "player_action": json.loads(action.model_dump_json()),
            "engine_result": json.loads(result.model_dump_json()),
            "chat_log": self._chat_log[-10:],
        }

        if result.chain_info and result.chain_info.follow_up:
            user_data["chained_action"] = True

        user_prompt = json.dumps(user_data, indent=2)

        raw = self._llm.call_prose(system_prompt, user_prompt)

        if self._commands.debug:
            self._display.print(f"\n[dim]--- LLM Call 2 raw ---[/dim]\n{raw}")

        return parse_prose_output(raw)

    # --- internal ---

    _last_result: Any = None

    def _do_exit(self) -> None:
        self._running = False
        self._display.render_goodbye()
