# Human Validation Plan

## 1. Overview

Human validation is the process of reviewing real LLM-driven game sessions (automated or manual) to catch quality issues that unit tests and static analysis cannot detect. These include:

- **Narrative coherence**: Does LLM Call 2's prose respect the engine result and world state?
- **Ruling correctness**: Does LLM Call 1 correctly parse player intent into a valid PlayerAction?
- **Hallucination resistance**: Does the system avoid inventing items, NPCs, or mechanics?
- **Constraint violation**: Does narration leak hidden information, contradict triggered narration, or ignore game-over?
- **Prompt quality**: Are GMBriefing and prompt templates producing the desired behaviour?

This plan describes how to use the existing validation tools (`scripts/validate.py`, `scripts/validate_adventure.py`) systematically to achieve coverage of the game's capabilities, and how to review the resulting logs.

## 2. Tool Overview

### 2.1 Static validation (`scripts/validate_adventure.py`)

Checks adventure corpus files for structural integrity — missing fields, broken cross-references, unreachable rooms, orphaned entities. No LLM required.

**Usage:**
```
python scripts/validate_adventure.py adventures/<adventure-dir>
```

Runs before any play-testing. Catches data-entry errors, schema violations, and connectivity issues. Should pass cleanly for every adventure before runtime validation begins.

**Exit code:** 0 if all checks pass; 1 if errors found (printed to stderr).

### 2.2 Runtime validation (`scripts/validate.py`)

Runs the full game loop (GMBriefing → LLM Call 1 → Engine → LLM Call 2 → post-validate) with verbose logging of every intermediate artifact. Does not display a pretty console UI — it dumps raw JSON for each stage so a human can inspect.

**Three modes:**

| Mode | Flag | Purpose |
|------|------|---------|
| Manual interactive | (no flags) | Exploratory testing — type inputs ad hoc |
| Automated sequence | `--sequence <file>` | Repeatable, scripted test scenarios |
| Turn-limited | `--turns <N>` | Cap total turns (with or without a sequence) |

**Output artifacts:**

| Artifact | What it shows |
|----------|--------------|
| Raw LLM Call 1 output | The exact JSON the LLM produced for the ruling |
| Parsed PlayerAction | The validated Pydantic model (or parse error) |
| Engine Result | Structured outcome: success/failure, state diffs, triggered narrations, rolls, attitude limits |
| State after turn | Player location, inventory, flags, NPC attitudes after resolution |
| Raw LLM Call 2 output | The exact JSON the LLM produced for the prose narration |
| Parsed NarrationOutput | Structured narration with knowledge_tags and attitude_changes |
| Post-validation result | Any corrections from engine post-validation of Call 2 output |

**Usage examples:**
```bash
# Static validation first
python scripts/validate_adventure.py adventures/bag-of-holding

# Automated run with sequence file
python scripts/validate.py adventures/bag-of-holding \
    --sequence tests/validation_sequences/basic_movement.json

# Manual interactive session, max 10 turns
python scripts/validate.py adventures/bag-of-holding --turns 10

# With delay for rate limiting
python scripts/validate.py adventures/bag-of-holding \
    --sequence tests/validation_sequences/basic_movement.json \
    --delay 1.0

# Custom log directory
python scripts/validate.py adventures/bag-of-holding \
    --sequence tests/validation_sequences/basic_movement.json \
    --log-dir tests/validation_logs
```

## 3. Validation Sequence Files

### 3.1 Format

Sequence files live in `tests/validation_sequences/` as JSON:

```json
[
  {
    "input": "I look around the room",
    "expectations": "Should describe the current room with entities and exits listed"
  },
  {
    "input": "I talk to Korbar",
    "expectations": "Should enter dialogue mode with NPC korbar"
  }
]
```

Each entry has:
- `input` (required): The verbatim player input line.
- `expectations` (optional): A human-readable note of what *should* happen. Not parsed by the script, but critical for the reviewer.

### 3.2 Writing sequence files

Each sequence file should test a specific capability or scenario. Name them descriptively:

| Filename | Covers |
|----------|--------|
| `basic_movement.json` | Moving between rooms, examining rooms/entities |
| `dialogue_basic.json` | Starting/exiting dialogue, simple conversational exchange |
| `dialogue_attitude.json` | NPC attitude shifts through conversation |
| `dialogue_knowledge.json` | NPC revealing knowledge topics via will_reveal |
| `interactions_simple.json` | Using basic interactions (take, attack, use) |
| `interactions_checks.json` | Interactions with roll checks (success and failure) |
| `interactions_stat_checks.json` | Interactions with stat checks (requires stat extension) |
| `chain_simple.json` | Simple two-step chained action |
| `chain_fail.json` | Chain action where one step fails (should terminate) |
| `malformed_input.json` | Ambiguous or impossible actions (error handling) |
| `game_over.json` | Sequence that triggers a game-over condition |
| `full_scenario.json` | A complete play-through from start to end of an adventure |

### 3.3 Coverage criteria

Every adventure should have sequence files that collectively cover:

1. **Movement**: Navigate through all accessible rooms.
2. **Basic interactions**: Examine, take, attack, use on available entities.
3. **Dialogue**: Start conversation, exchange multiple turns, exit.
4. **Checks**: Interact with entities that require roll checks (both success and failure paths).
5. **Chain actions**: At least one multi-step chained action.
6. **Error recovery**: An input that should produce `success: false` (e.g., using a non-existent item).
7. **Soft state**: Proposing and having soft-state patches accepted/rejected.
8. **Edge cases**: `ooc_discussion`, `wait`, `/exit`.

For the bag-of-holding adventure specifically, the recommended sequence files are listed in §7.

## 4. Validation Logs

### 4.1 Log format

Every `validate.py` run produces a timestamped JSON log file in `tests/validation_logs/`. The filename encodes:
```
<sequence_name_or_manual>_<YYYY-MM-DD_HH-MM-SS>.json
```

Top-level structure:
```json
{
  "adventure": "adventures/bag-of-holding",
  "turns": [ ... ],
  "sequence": "tests/validation_sequences/basic_movement.json"
}
```

Each turn in the `turns` array contains:
```json
{
  "turn": 1,
  "player_input": "look around",
  "chain_steps": [ ... ]
}
```

Each `chain_steps` entry contains a full record of one engine cycle (may be multiple for chained actions):
- `briefing`: The GMBriefing as assembled by the context assembler.
- `raw_ruling`: Raw LLM output from Call 1.
- `parsed_action` or `parse_error_ruling`: Parsed PlayerAction or error.
- `engine_result`: Structured EngineResult from the deterministic engine.
- `raw_prose`: Raw LLM output from Call 2.
- `parsed_prose` or `parse_error_prose`: Parsed NarrationOutput or error.
- `post_validated`: Engine result after post-validation (if applicable).
- `narration`: Final prose text delivered to the player.

### 4.2 Log review procedure

For each log, the reviewer works through turns in order. The review has three layers:

**Layer 1: Mechanical correctness** (engine constraints)

Check that:
- LLM Call 1 output produced a valid, parsable PlayerAction (no parse error).
- EngineResult matches expectations: if the action should succeed, `success: true`;
  if impossible, `success: false` with a reason.
- Hard-state changes are appropriate: player moved to the right room, inventory
  updated correctly, flags set/cleared as expected.
- Soft-state patches were applied or rejected for valid reasons.
- Post-validation applied (or rejected) knowledge_tags and attitude_changes correctly.
- Chained actions terminated if any step failed.

**Layer 2: Narrative quality** (LLM Call 2)

Check that:
- Narration does not contradict the engine result.
- Narration does not invent entities, items, or state changes not reported by the engine.
- Narration incorporates triggered narrations (not replacing them).
- Hidden information is not revealed (secret exits, gated knowledge topics).
- Game-over is respected if set by the engine.
- Tone and style are appropriate for the adventure's specified tone.
- If attitude_changes are proposed, they align with the EngineResult's attitude limits.

**Layer 3: System behaviour** (overall flow)

Check that:
- The `expectations` note from the sequence file were met.
- GMBriefing correctly reflects state (entities hidden when they should be,
  dialogue_context present when in dialogue mode, etc.).
- Any retries (LLM output parse errors) behaved correctly.
- No unexpected behaviour like infinite loops, blank outputs, or repeated errors.

### 4.3 Grading

Each turn is graded:

| Grade | Meaning | Action |
|-------|---------|--------|
| ✅ PASS | All three layers pass | Proceed |
| ⚠️ MINOR | Small narrative quirk, no mechanical error | Note in issues list, continue |
| ❌ FAIL | Mechanical error, hallucination, constraint violation | Stop, file bug report |
| 🔄 RETRY | LLM parse error recovered gracefully | Note but pass if corrected |

A session is:
- **PASS** if every turn is ✅ or ⚠️(minor only).
- **FAIL** if any turn is ❌.

### 4.4 Defect reporting

When a ❌ is found, create a bug report entry in `problems.txt` with:

```
## [YYYY-MM-DD] <brief title>

- Severity: (critical/major/minor)
- Affected: (what capability or module)
- Turn: N (or chain step N)
- Log: <log_filename>
- Sequence: <sequence_file> (if applicable)
- LLM model: <model_name>
- Observation:
  <what went wrong, with verbatim quotes from the log>
- Expected:
  <what should have happened>
- Root cause guess:
  <prompt issue, code bug, model limitation, etc.>
```

If the same issue occurs across multiple logs, link them: tag the root cause with an ID and reference it in each log's bug entry.

## 5. Validation Session Workflow

### 5.1 Session types

**A. Smoke test** (5 min)

After any code change. Run `validate_adventure.py` on all adventures, then run `validate.py` with the first sequence file. Quick check that nothing is broken.

**B. Coverage sweep** (30-60 min)

A planned session covering a specific capability or adventure. The reviewer picks one or more sequence files, runs them, and reviews the logs systematically. This is the core validation activity.

**C. Regression sweep** (30 min)

After fixing a bug. Re-run the sequence file that exposed it. Also run related sequence files to check no new issues were introduced.

**D. Exploratory session** (unstructured)

Manual interactive mode. The reviewer types inputs freely to probe edge cases not covered by sequence files. Good for discovery.

### 5.2 Before any session

1. Ensure `MGMAI_API_KEY` and `MGMAI_MODEL` are set in the environment.
2. `git pull` to ensure the code matches the adventure files.
3. Run `validate_adventure.py` on the target adventure. Fix any structural errors first.
4. Confirm the sequence file exists and is valid JSON.

### 5.3 During a session

- Run the validate script with appropriate flags.
- For manual sessions, type inputs clearly — avoid ambiguous phrasing.
- For automated sessions, review as the output streams by (especially the raw LLM outputs).
- Take notes on anything that looks off, even if not a hard failure.

### 5.4 After a session

1. The log is saved automatically to `tests/validation_logs/`.
2. Perform a structured log review (§4.2).
3. Fill in the validation tracking table (§6).
4. If defects found, update `problems.txt` (§4.4).

## 6. Validation Tracking

### 6.1 Session log

Maintain a running record at the top of this file or in a companion `validation-log.md`:

| Date | Session type | Adventure | Seq file | Turns | Result | Issues |
|------|-------------|-----------|----------|-------|--------|--------|
| 2026-06-06 | Smoke test | bag-of-holding | basic_movement | 4 | PASS | None |
| 2026-06-07 | Coverage | bag-of-holding | dialogue_basic | 8 | FAIL (#1) | Dialogue mode not entered when expected |
| 2026-06-07 | Regression | bag-of-holding | dialogue_basic | 8 | PASS | Fix applied |

### 6.2 Known issues

Keep a list in `problems.txt` (already exists) that accumulates all known defects. Tag each with an ID (`#1`, `#2`, …) and reference them in the session log.

## 7. Recommended Sequence Files for Bag-of-Holding

> **Note:** These are the sequence files to write and then run for the bag-of-holding adventure. Begin by writing the ones marked **P0** (core functionality), then expand.

### P0 — Core (test first)

| Seq file | Inputs | What it tests |
|----------|--------|--------------|
| `basic_movement.json` | ✓ | Move through all rooms. Exists (4 inputs). |
| `basic_interactions.json` | Examine the padlock, try to take the key, examine stuck_fly, inspect webs | Basic examine/take on entities. |
| `dialogue_korbar.json` | Talk to Korbar, ask about exit, ask about axe, end dialogue | Dialogue entry/exit, basic Q&A, engine-post-validation of knowledge_tags. |
| `error_cases.json` | `/exit`, nonsensical action like "fly to the moon", trying to attack dead NPC | Error handling, `ooc_discussion`, impossible actions. |

### P1 — Important

| Seq file | Inputs | What it tests |
|----------|--------|--------------|
| `chain_movement.json` | "Climb down the handle carefully and examine the webs" | Chained action: move + examine in one input. |
| `spider_encounter.json` | Enter spider room, attack spider, examine aftermath | Encounter resolution, combat flow, entity state changes. |
| `check_success_fail.json` | Interact with something that requires a roll. Run twice or include both outcome branches (may need multiple sequences). | Roll check resolution, success and failure branches. |
| `soft_state_examine.json` | Pick up a loose stone, note the room, then examine the room | Soft inventory, room notes, soft state patches. |

### P2 — Nice to have

| Seq file | Inputs | What it tests |
|----------|--------|--------------|
| `ooc_discussion.json` | Ask the GM questions OOC, get clarification | ooc_discussion action type. |
| `game_over.json` | Perform actions leading to a game-over condition | Game-over detection and narration. |

### 7.1 Writing the P0 sequences

Below are drafts for the remaining P0 sequences (basic_movement already exists).

**`tests/validation_sequences/basic_interactions.json`:**
```json
[
  { "input": "I reach up and try to touch the padlock",
    "expectations": "Should examine the padlock feature. Describes it as firmly locked." },
  { "input": "I look closely at the stuck fly",
    "expectations": "Should examine the stuck_fly entity. Should describe the fly." },
  { "input": "I tear a piece of canvas from the wall",
    "expectations": "Should reject or allow as soft state (add 'canvas scrap' to soft_inventory). OK either way but note the outcome." },
  { "input": "I climb down the axe handle",
    "expectations": "Move to axe_handle_upper." },
  { "input": "I examine the webs above",
    "expectations": "Should describe the webs_upper feature." }
]
```

**`tests/validation_sequences/dialogue_korbar.json`:**
```json
[
  { "input": "I climb carefully down the axe handle",
    "expectations": "Move to axe_handle_upper." },
  { "input": "I walk down to the lower handle",
    "expectations": "Move to axe_handle_lower. Korbar should be present." },
  { "input": "I talk to Korbar",
    "expectations": "Enter dialogue mode with NPC korbar. GMBriefing should include dialogue_context block." },
  { "input": "Hello there! What brings you to this bag?",
    "expectations": "Dialogue exchange. Korbar should respond in character." },
  { "input": "Do you know a way out?",
    "expectations": "NPC should provide information. May trigger will_reveal if conditions met." },
  { "input": "Thanks for the help. I'll be on my way.",
    "expectations": "Exit dialogue (ends_dialogue or move triggers exit)." }
]
```

**`tests/validation_sequences/error_cases.json`:**
```json
[
  { "input": "/exit",
    "expectations": "Should exit the game cleanly." },
  { "input": "I flap my arms and fly to the moon",
    "expectations": "Engine should return success: false or LLM should produce a wait action explaining impossibility." },
  { "input": "I take the magical flaming sword",
    "expectations": "No such item exists. Should reject or produce a wait action." }
]
```

## 8. Validation Checklist (Quick Reference)

Before each session, run:

- [ ] `git status` — working tree clean? Adventure files committed?
- [ ] `python scripts/validate_adventure.py adventures/<name>` — passes?
- [ ] `echo $MGMAI_API_KEY` — set?
- [ ] `echo $MGMAI_MODEL` — set? Known working model?
- [ ] Sequence file valid JSON? (`python3 -m json.tool <file>`)

For each turn in the log, check:

**Engine layer:**
- [ ] PlayerAction parsed without error (or retry succeeded)
- [ ] Action type matches intent (move → move, examine → examine, etc.)
- [ ] Target entity/room exists and is valid
- [ ] `success` flag matches expectation
- [ ] State changes are correct: room changed, inventory +/- reasonable, flags set
- [ ] For checks: roll details logged, outcome correct
- [ ] Soft-state patches: expected ones applied, invalid ones rejected with reason
- [ ] Chained action continued/terminated correctly
- [ ] Game-over (if expected) triggered

**Narration layer:**
- [ ] Narration does not contradict engine result
- [ ] No invented entities, items, or state
- [ ] Triggered narrations incorporated (not replaced)
- [ ] Hidden information not revealed
- [ ] Tone/style consistent with adventure setting
- [ ] Game-over respected (game ends, no more actions)
- [ ] attitude_changes respect engine's attitude limits

**System layer:**
- [ ] GMBriefing correctly reflects current state
- [ ] Dialogue context present when in dialogue; absent when not
- [ ] No infinite loops, repeated errors, or blank outputs
- [ ] `/exit` terminates cleanly
