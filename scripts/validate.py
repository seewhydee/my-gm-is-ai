#!/usr/bin/env python3
"""Validation playground for Phase 6 LLM integration.

Runs the game loop in validation mode, displaying raw LLM outputs,
parsed structured data, engine state changes, and final narration
for each turn.

Usage:
    python scripts/validate.py adventures/bag-of-holding
    python scripts/validate.py adventures/bag-of-holding --turns 5
    python scripts/validate.py adventures/bag-of-holding --sequence tests/validation_sequences/puzzle_solve.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

parent = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent))

from mgmai.state.manager import StateManager
from mgmai.llm.client import LLMClient
from mgmai.llm.parser import LLMOutputError, parse_player_action, parse_prose_output
from mgmai.context.assembler import assemble
from mgmai.engine.engine import resolve, MAX_CHAIN_LENGTH
from mgmai.engine.post_validate import apply_post_validation


def divider(label: str = "", char: str = "=") -> str:
    line = char * 60
    if label:
        return f"{line}\n  {label}\n{line}"
    return line


def print_section(title: str, content: str) -> None:
    print(f"\n{divider(title, '-')}")
    print(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate LLM integration for MGMAI"
    )
    parser.add_argument("adventure", help="Path to adventure directory")
    parser.add_argument("--turns", type=int, default=0, help="Max turns (0 = unlimited)")
    parser.add_argument(
        "--sequence",
        default=None,
        help="Path to a JSON sequence file of player inputs",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between turns (for rate limiting)",
    )
    parser.add_argument(
        "--log-dir",
        default="tests/validation_logs",
        help="Directory for validation logs",
    )
    args = parser.parse_args()

    api_key = os.environ.get("MGMAI_API_KEY")
    if not api_key:
        print("Error: MGMAI_API_KEY is not set")
        sys.exit(1)

    base_url = os.environ.get("MGMAI_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("MGMAI_MODEL", "deepseek-v4-flash")

    state_manager = StateManager()
    try:
        state_manager.load_all(args.adventure)
    except Exception as e:
        print(f"Error loading adventure: {e}")
        sys.exit(1)

    llm_client = LLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    run_validation(state_manager, llm_client, args)


def run_validation(
    state_manager: StateManager,
    llm_client: LLMClient,
    args: Any,
) -> None:
    sequence = None
    if args.sequence:
        seq_path = Path(args.sequence)
        if not seq_path.is_file():
            print(f"Error: sequence file not found: {args.sequence}")
            sys.exit(1)
        sequence = json.loads(seq_path.read_text())

    chat_log: list[dict[str, str]] = []
    turn_log: list[dict[str, Any]] = []
    turn_num = 0

    display_intro(state_manager)

    while True:
        if args.turns > 0 and turn_num >= args.turns:
            print(f"\nReached turn limit ({args.turns})")
            break

        if sequence and turn_num < len(sequence):
            entry = sequence[turn_num]
            player_input = entry["input"]
            expectations = entry.get("expectations", "")
            print(f"\n{divider(f'TURN {turn_num + 1}')}")
            print(f"\n[Player Input] {player_input}")
            if expectations:
                print(f"[Expectations] {expectations}")
        else:
            if sequence:
                print("\nEnd of sequence.")
                break
            try:
                player_input = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not player_input.strip():
                continue
            print(f"\n{divider(f'TURN {turn_num + 1}')}")

        chat_log.append({"role": "player", "content": player_input})

        if player_input.strip() == "/exit":
            break

        chain_depth = 0
        current_input = player_input
        turn_data: dict[str, Any] = {
            "turn": turn_num + 1,
            "player_input": player_input,
            "chain_steps": [],
        }

        while chain_depth < MAX_CHAIN_LENGTH:
            step_data = execute_turn(
                state_manager,
                llm_client,
                current_input,
                player_input,
                chain_depth,
                chat_log,
            )
            turn_data["chain_steps"].append(step_data)

            if step_data.get("error"):
                chat_log.append({"role": "gm", "content": step_data["error"]})
                print(f"\n[ERROR] {step_data['error']}")
                break

            result = step_data.get("engine_result", {})
            narration = step_data.get("narration", "")

            chain_info = result.get("chain_info") if isinstance(result, dict) else getattr(result, "chain_info", None)
            if chain_info:
                follow_up = chain_info.get("follow_up") if isinstance(chain_info, dict) else getattr(chain_info, "follow_up", None)
                termination = chain_info.get("termination_reason") if isinstance(chain_info, dict) else getattr(chain_info, "termination_reason", None)
                if follow_up and not termination:
                    current_input = follow_up
                    chain_depth += 1
                    print(f"\n[CHAIN {chain_depth}] Continuing: {follow_up[:80]}...")
                    continue

            chat_log.append({"role": "gm", "content": narration})
            if narration:
                print(f"\n[GM] {narration}")
            break

        turn_log.append(turn_data)
        turn_num += 1

        if args.delay > 0:
            import time
            time.sleep(args.delay)

        game_over = check_game_over(turn_data)
        if game_over:
            print(f"\n[GAME OVER] {game_over}")
            break

    save_log(turn_log, args)


def execute_turn(
    state_manager: StateManager,
    llm_client: LLMClient,
    current_input: str,
    original_input: str,
    chain_depth: int,
    chat_log: list[dict[str, str]],
) -> dict[str, Any]:
    from mgmai.templates.renderer import render_ruling, render_prose

    corpus = state_manager.corpus
    hard = state_manager.hard_state
    soft = state_manager.soft_state

    if corpus is None or hard is None or soft is None:
        return {"error": "State not loaded"}

    step: dict[str, Any] = {}

    # 1. GMBriefing
    briefing = assemble(corpus, hard, soft, current_input)
    step["briefing"] = json.loads(briefing.model_dump_json())

    print_section("GMBriefing", briefing.model_dump_json(indent=2))

    # 2. LLM Call 1
    system_prompt = render_ruling()
    user_prompt = briefing.model_dump_json(indent=2)

    raw_ruling = llm_client.call_ruling(system_prompt, user_prompt)
    step["raw_ruling"] = raw_ruling

    print_section("LLM Call 1 (Ruling) Raw Output", raw_ruling)

    try:
        action = parse_player_action(raw_ruling)
        step["parsed_action"] = json.loads(action.model_dump_json())
        print_section("Parsed Action", action.model_dump_json(indent=2))
    except LLMOutputError as e:
        step["parse_error_ruling"] = str(e)
        retry_prompt = user_prompt + f"\n\n[ERROR: {e}]"
        raw_ruling = llm_client.call_ruling(system_prompt, retry_prompt)
        try:
            action = parse_player_action(raw_ruling)
            step["parsed_action"] = json.loads(action.model_dump_json())
        except LLMOutputError as e2:
            step["parse_error_ruling_retry"] = str(e2)
            return {"error": f"LLM Call 1 failed after retry: {e2}"}

    # 3. Engine
    result = resolve(
        action,
        state_manager,
        chain_depth=chain_depth,
        player_input_echo=original_input,
    )
    step["engine_result"] = json.loads(result.model_dump_json())

    print_section("Engine Result", result.model_dump_json(indent=2))
    print_section("State After Turn", format_state(state_manager))

    # 4. LLM Call 2
    system_prompt_prose = render_prose()
    user_data = {
        "setting": briefing.setting,
        "tone": briefing.tone,
        "briefing": json.loads(briefing.model_dump_json()),
        "player_action": json.loads(action.model_dump_json()),
        "engine_result": json.loads(result.model_dump_json()),
        "chat_log": chat_log[-10:],
    }
    user_prompt_prose = json.dumps(user_data, indent=2)

    raw_prose = llm_client.call_prose(system_prompt_prose, user_prompt_prose)
    step["raw_prose"] = raw_prose

    print_section("LLM Call 2 (Prose) Raw Output", raw_prose)

    try:
        prose = parse_prose_output(raw_prose)
        step["parsed_prose"] = json.loads(prose.model_dump_json())
        print_section("Parsed Narration", prose.model_dump_json(indent=2))
    except LLMOutputError as e:
        step["parse_error_prose"] = str(e)
        return {"narration": f"[Error narrating: {e}]", "engine_result": step["engine_result"]}

    # 5. Post-validate
    kt = prose.knowledge_tags.npc_revealed if prose.knowledge_tags else None
    ac = dict(prose.attitude_changes) if prose.attitude_changes else None
    if kt or ac:
        result = apply_post_validation(kt, ac, state_manager, result)
        step["post_validated"] = json.loads(result.model_dump_json())
        print_section("Post-Validated Result", result.model_dump_json(indent=2))

    step["narration"] = prose.narration
    return step


def format_state(state_manager: StateManager) -> str:
    hard = state_manager.hard_state
    soft = state_manager.soft_state
    if hard is None or soft is None:
        return "State not loaded"

    return json.dumps({
        "player_location": hard.player.location,
        "hard_inventory": hard.player.inventory,
        "soft_inventory": soft.soft_inventory,
        "flags": hard.flags,
        "turn_count": hard.turn_count,
        "npc_attitudes": dict(soft.npc_attitudes),
    }, indent=2)


def check_game_over(turn_data: dict[str, Any]) -> str | None:
    for step in turn_data.get("chain_steps", []):
        er = step.get("engine_result", {})
        if isinstance(er, dict):
            go = er.get("game_over")
            if go:
                return f"{go.get('type')} - {go.get('trigger')}"
    return None


def display_intro(state_manager: StateManager) -> None:
    corpus = state_manager.corpus
    if corpus is None:
        return
    adv = corpus.adventure
    print(divider(adv.title))
    print(f"\n{adv.introduction}")
    print(f"\nSetting: {adv.atmosphere.setting if adv.atmosphere else 'N/A'}")
    print(f"Tone: {adv.atmosphere.tone if adv.atmosphere else 'N/A'}")
    if adv.credits:
        c = adv.credits
        parts = [f"Author: {c.author}" if c.author else "",
                 f"Source: {c.source}" if c.source else ""]
        print(" | ".join(p for p in parts if p))
    print(divider())


def save_log(turn_log: list[dict[str, Any]], args: Any) -> None:
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    scenario = "manual"
    if args.sequence:
        scenario = Path(args.sequence).stem

    filename = log_dir / f"{scenario}_{ts}.json"
    filename.write_text(json.dumps({
        "adventure": args.adventure,
        "turns": turn_log,
        "sequence": args.sequence,
    }, indent=2))

    print(f"\n{divider()}")
    print(f"Validation log saved to: {filename}")


if __name__ == "__main__":
    main()
