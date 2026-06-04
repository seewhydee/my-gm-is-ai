# Phase 4: Engine — Detailed Coding Plan

## Overview

Phase 4 implements the deterministic game engine — the core of the system. Per the architecture in `plan.md`, the engine sits between LLM Call 1 (which produces a structured `PlayerAction`) and LLM Call 2 (which narrates the outcome). The engine is the **sole authority** over game mechanics: it validates actions, resolves outcomes, mutates hard state, validates soft-state patches, and produces an `EngineResult` for the narrator.

This is the largest and most complex phase. It depends on all three prior phases:
- **Phase 1 (Models):** `PlayerAction`, `EngineResult`, `HardStateChanges`, `SoftStatePatch`, `ConditionExpression`, corpus models
- **Phase 2 (State Manager):** `StateManager` with direct-mutable state references and `apply_hard_changes`/`apply_soft_patches`
- **Phase 3 (Conditions):** `evaluate()` for condition objects and bare strings against hard/soft state

---

## Architecture: Where the Engine Fits

```
Player Input
     │
     ▼
┌──────────────────────────┐
│ Context Assembler (P5)   │  Reads corpus + state → GMBriefing
└──────────────────────────┘
     │
     ▼
┌──────────────────────────┐
│ LLM Call 1 (P6)          │  GMBriefing + input → PlayerAction
└──────────────────────────┘
     │
     ▼
┌──────────────────────────┐
│ ENGINE (P4) ← WE ARE HERE│  PlayerAction → EngineResult
│  validate → resolve →    │  Reads corpus + state
│  mutate → produce result  │  Writes hard state, validates soft patches
└──────────────────────────┘
     │
     ▼
┌──────────────────────────┐
│ LLM Call 2 (P6)          │  EngineResult → prose narration
└──────────────────────────┘
     │
     ▼
┌──────────────────────────┐
│ Post-validate (P4)       │  knowledge_tags + attitude_changes
└──────────────────────────┘
```

The engine has **no LLM calls** and **no I/O** (beyond random number generation for rolls). It is a pure function: `(PlayerAction, StateManager, ModuleCorpus) → EngineResult`.

---

## Files to Create

| File | Responsibility |
|------|----------------|
| `mgmai/engine/engine.py` | Main entry point: `resolve()` orchestrator |
| `mgmai/engine/resolver.py` | Per-action-type validation and resolution |
| `mgmai/engine/encounters.py` | Encounter/behavior rule evaluation |
| `mgmai/engine/dialogue.py` | Dialogue state lifecycle management |
| `mgmai/engine/post_validate.py` | Step 4.5: validate knowledge_tags + attitude_changes |
| `tests/test_engine.py` | Tests for engine.py orchestrator |
| `tests/test_resolver.py` | Tests for each action resolver |
| `tests/test_encounters.py` | Tests for encounter resolution |
| `tests/test_dialogue.py` | Tests for dialogue lifecycle |
| `tests/test_post_validate.py` | Tests for post-validation |

---

## Step-by-Step Implementation

### Step 1: `engine/resolver.py` — Per-Action-Type Resolution

This is the foundation. Each action type gets a resolver function that validates the action against current state and returns what changes should happen.

#### Design

```python
from dataclasses import dataclass
from mgmai.models.actions import (
    MoveAction, ExamineAction, InteractAction, TalkAction,
    TransferAction, WaitAction, OocDiscussionAction,
    HardStateChanges,
)
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState

@dataclass
class ResolutionResult:
    """Outcome of resolving a single PlayerAction."""
    success: bool
    error: str | None = None
    hard_changes: HardStateChanges | None = None
    triggered_narration: list[str] | None = None
    encounter_outcome: dict | None = None
    on_enter_events: list[dict] | None = None
    warnings: list[str] | None = None
    room_after_id: str | None = None  # room ID after resolution
```

#### Resolver Functions

Each function signature:
```python
def resolve_<action_type>(
    action: <SpecificAction>,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
) -> ResolutionResult:
```

##### `resolve_move`

1. Look up current room from `hard.player.location`
2. Find exit matching `action.target` in room's exits
3. If not found → `success=False, error="Exit '{target}' not found in room '{room}'"`
4. If exit is one-way and player came from target room → reject
5. Evaluate exit `conditions` using `evaluate()` from Phase 3
6. If conditions not met → `success=False, error="Conditions not met for exit"`
7. Build `HardStateChanges`:
   - `player_location = exit.target_room`
   - Apply `on_traverse.set_flag` → `flags_set`
   - Apply `on_traverse.set_flag` clearing → `flags_cleared`
8. Collect `on_traverse.narrative` → `triggered_narration`
9. If `on_traverse.skip_if` evaluates true, skip the traverse effect and use `narrative_skip`
10. If `on_traverse.trigger_encounter` is set, mark for encounter resolution
11. `room_after_id = exit.target_room`
12. Return `success=True`

##### `resolve_examine`

1. Determine target type:
   - If `action.target` matches current room ID → examining the room
   - If `action.target` matches an entity in current room's `entities_present` → examining an entity
   - If `action.target` matches a soft item in room's `soft_items` or entity `soft_items` → examining a soft item
   - Otherwise → `success=False, error="Target '{target}' not found"`
2. For room examination: return room description as narration
3. For entity examination:
   - Check `state.alive != False` for NPCs (dead entities may have different descriptions)
   - Return entity description
   - If `rigorous=True`, evaluate any interactions gated by rigorous search
4. For soft item examination: return a generic description
5. If `using` specified, verify item is in inventory
6. `success=True`, no hard state changes (examine is read-only)

##### `resolve_interact`

1. Find target: entity in room, or soft item in room/entity soft_items
2. Find interaction by `action.interaction_id`:
   - Check entity-level interactions
   - Check room-level interactions
   - Check generic interactions (e.g., `attack`, `take`)
3. If no matching interaction → `success=False`
4. Evaluate interaction `condition` if present
5. Validate `parameter_signature` if present (check `target`/`using` types)
6. If `using` specified, verify item in inventory
7. Resolve interaction:
   - If `check` present: roll random, branch to `success`/`failure` result
   - If `result` present: apply directly
8. Apply result effects:
   - `add_item` → `inventory_added`
   - `remove_item` → `inventory_removed`
   - `set_flag` → `flags_set`/`flags_cleared`
   - `narrative` → `triggered_narration`
   - `reveals` → include in narration hints
9. Check if interaction triggers a behavior encounter (for `attack` on NPCs with behavior)
10. Return `success=True` with changes

**Generic interactions:**
- `attack`: If target is NPC with `behavior`, route to encounter resolution. Otherwise, `success=False` with "Nothing to attack" or similar.
- `take`: If target is an item entity in the room, add to inventory. If target is a soft item from room/entity soft_items, add to soft inventory via soft-state patch.

##### `resolve_talk`

1. Verify `action.target` is an NPC entity present in current room
2. Verify NPC `state.alive != False`
3. If `action.target` differs from current `soft.dialogue_state.active_npc`:
   - Archive current dialogue (if any) via `dialogue.py`
   - Start new dialogue with target NPC
4. Append player utterance (or action detail) to conversation log
5. If `action.ends_dialogue`: mark for dialogue exit after narration
6. Reset stall counter
7. `success=True`, no hard state changes

##### `resolve_transfer`

1. Verify `action.target` exists (entity in room, or room ID)
2. For `given_items`: verify each is in player's hard or soft inventory
3. For `taken_items`: verify each is available from target
   - Hard items: in target entity's available items (defined by corpus)
   - Soft items: in target's `soft_items` or room's `soft_items`
4. Build `HardStateChanges`:
   - Remove given items from inventory → `inventory_removed`
   - Add taken items to inventory → `inventory_added`
5. For soft items: produce `SoftStatePatch` proposals
6. `success=True`

**Note:** The adventure's NPC/container inventory model needs clarification (see `problems.txt`). For now, assume entities have an implicit pool: their own item children (entities present in the same room that are items) plus their `soft_items`.

##### `resolve_wait`

1. Always valid
2. No hard state changes
3. `success=True`

##### `resolve_ooc`

1. Always valid
2. No hard state changes, no turn increment
3. `success=True` with a flag indicating "skip to narration"

---

### Step 2: `engine/encounters.py` — Encounter Resolution

Handles NPC `behavior` blocks and `mechanics` encounter rules.

#### Design

```python
def resolve_encounter(
    encounter_rules: list[EncounterRule],
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    npc_id: str | None = None,
) -> EncounterOutcome:
    """Evaluate encounter rules top-to-bottom. First matching condition wins."""
```

#### Logic

1. Iterate rules top-to-bottom
2. For each rule, evaluate `rule.condition` using `evaluate()` from Phase 3
3. First match determines outcome:
   - `death`: Set `game_over = { type: "lose", trigger: ... }`. Apply `set_flags`. Return narrative.
   - `flee`: Apply NPC `on_flee` effects (set flags, set entity state). Return narrative.
   - `roll`: Generate random number. If `random() < threshold` → success branch, else failure branch. Apply branch effects.
4. If no rules match, return a default "nothing happens" outcome

#### Behavior Trigger Detection

```python
def should_trigger_behavior(
    entity_id: str,
    action_type: str,
    action_target: str | None,
    corpus: ModuleCorpus,
) -> list[EncounterRule] | None:
    """Check if an action triggers an NPC's behavior block."""
```

- Check if action target or traversed exit is in the NPC's `behavior.triggers_on`
- Also trigger on `attack` interactions targeting the NPC
- Return the encounter rules if triggered, None otherwise

#### Flee Effects

When a flee outcome fires:
1. Apply `behavior.on_flee.set_flags` → set flags in hard state
2. Apply `behavior.on_flee.set_entity_state` → update entity states
3. Record `behavior.on_flee.effect` in warnings for LLM Call 2

---

### Step 3: `engine/dialogue.py` — Dialogue State Lifecycle

Manages `soft_state.dialogue_state` transitions.

#### Functions

```python
def enter_dialogue(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    player_utterance: str | None,
    detail: str,
) -> None:
    """Start dialogue with an NPC."""

def append_player_turn(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    utterance: str | None,
    detail: str,
) -> None:
    """Append player's utterance to conversation log."""

def append_npc_response(
    soft: SoftGameState,
    npc_id: str,
    turn: int,
    response: str,
) -> None:
    """Append NPC's response to conversation log (extracted from LLM Call 2)."""

def increment_stall(soft: SoftGameState) -> bool:
    """Increment stall counter. Returns True if dialogue should auto-exit."""

def exit_dialogue(
    soft: SoftGameState,
    corpus: ModuleCorpus,
    hard: HardGameState,
) -> dict | None:
    """Archive conversation, apply on_dialogue_exit effects, clear state."""

def check_room_change_exit(
    soft: SoftGameState,
    old_room: str,
    new_room: str,
    corpus: ModuleCorpus,
    hard: HardGameState,
) -> dict | None:
    """Exit dialogue if player moved rooms away from active NPC."""
```

#### Lifecycle Rules (per schema)

| Trigger | Action |
|---------|--------|
| `talk` to new NPC | Archive old dialogue (if any), start new |
| `talk` to same NPC | Append utterance, reset stall counter |
| `talk` with `ends_dialogue` | Archive + clear |
| Non-`talk` action while in dialogue | Increment stall; auto-exit at 3 |
| `move` leaving NPC's room | Archive + clear + apply `on_dialogue_exit` |
| NPC dies/flees | Archive + clear |
| `ooc_discussion` | No stall increment, no state change |

#### Archival Format

When dialogue exits, append to `entity_notes[npc_id]`:
```
"[Turn N-M] Conversation summary: <summary of topics and key revelations>"
```

The summary is generated from `topics_discussed` and `conversation_log`.

---

### Step 4: `engine/engine.py` — Main Orchestrator

This is the top-level entry point that ties everything together.

#### Design

```python
MAX_CHAIN_LENGTH = 10  # Constant: max follow-up chain depth

def resolve(
    player_action: PlayerAction,
    state_manager: StateManager,
    *,
    chain_depth: int = 0,
    player_input_echo: str | None = None,
) -> EngineResult:
    """Resolve a PlayerAction and produce an EngineResult."""
```

#### Flow

```
1. If action is ooc_discussion:
   - Return minimal EngineResult(success=True, action_type="ooc_discussion")
   - Do NOT increment turn counter
   - Do NOT mutate any state

2. VALIDATE action via resolver:
   - Call appropriate resolve_<type>() function
   - If validation fails: return EngineResult(success=False, error=...)

3. If action has follow_up AND chain_depth >= MAX_CHAIN_LENGTH:
   - Terminate chain: return result with chain_info(termination_reason="max depth")

4. APPLY hard-state changes:
   - state_manager.apply_hard_changes(resolution.hard_changes)

5. APPLY soft-state patches:
   - Validate each proposed_soft_state_patches entry
   - Accepted patches → state_manager.apply_soft_patches()
   - Rejected patches → include in EngineResult with reasons

6. RESOLVE encounters (if triggered by traversal or interaction):
   - Call encounters.resolve_encounter()
   - Apply encounter outcomes to hard state

7. PROCESS on_enter events (if player moved to new room):
   - Evaluate on_enter event conditions
   - Apply set_flag, set_entity_state, trigger_dialogue
   - Collect narratives

8. HANDLE dialogue state transitions:
   - If action is talk: manage dialogue entry/continuation
   - If action is move: check if NPC is in new room
   - If non-talk while in dialogue: increment stall

9. CHECK game-over conditions:
   - Evaluate all mechanics with type="win" or type="lose"
   - If any condition fires: set hard_state.game_over

10. INCREMENT turn counter (except ooc_discussion)

11. BUILD turn_history entry:
    - player_input, ruled_action summary, engine_result_summary, flags_changed, location_after

12. POPULATE EngineResult fields:
    - room_after: build BriefingRoom from corpus + updated state
    - hard_state_changes: the diff
    - soft_state_patches_applied/rejected
    - rolls (any random checks)
    - encounter_outcome
    - triggered_narration
    - on_enter_events
    - game_over
    - dialogue_exited
    - will_reveal_readiness (for NPCs in room)
    - npc_attitude_limits (for NPCs in room)
    - chain_info (if follow_up present)
    - warnings

13. If chain is viable (follow_up present, not terminated):
    - Recurse: resolve() with follow_up as next input, chain_depth + 1
```

#### Soft-State Patch Validation

For each `SoftStatePatch` in `proposed_soft_state_patches`:
- `room_note`: `target_id` must be a valid room
- `entity_note`: `entity_id` must be a valid entity
- `soft_inventory_add`: item name must appear in current room's `soft_items` or a present entity's `soft_items`
- `soft_inventory_remove`: item must be in `soft_state.soft_inventory`
- `reason` must be non-empty
- Notes must not contradict hard state (basic keyword check against entity names + state fields)

#### Building `room_after` (BriefingRoom)

The EngineResult includes a `room_after` field that gives LLM Call 2 the current room state:
- Fetch room from corpus
- Filter `entities_visible`: only entities with `alive != False`
- Include entity state, entity_notes (up to 3), soft_items
- Filter `exits_available`: conditions met, hidden exits omitted
- Include room's `soft_items`, `room_notes`
- Include room's `interactions_available`

#### Building `will_reveal_readiness`

For each NPC in the current room with `dialogue_guidelines.will_reveal`:
- For each topic, evaluate its `conditions` array
- Set `conditions_met: True/False` with the topic's `description`

#### Building `npc_attitude_limits`

For each NPC in the current room:
- Read `corpus.entities[npc_id].dialogue_guidelines.attitude_limits`
- Read current attitude from `soft_state.npc_attitudes[npc_id]` (or `initial`)
- Return `{ min, max, step_per_turn, current }`

---

### Step 5: `engine/post_validate.py` — Step 4.5

Validates LLM Call 2's structured outputs after narration.

#### Functions

```python
def post_validate_knowledge_tags(
    knowledge_tags: dict[str, list[str]],  # { npc_id: [topic_id, ...] }
    state_manager: StateManager,
) -> list[RevelationApplied]:
    """Validate and apply knowledge_tag revelations."""

def post_validate_attitude_changes(
    attitude_changes: dict[str, AttitudeChange],
    state_manager: StateManager,
) -> tuple[dict[str, AttitudeChange], dict[str, dict]]:
    """Validate attitude changes. Returns (applied, rejected)."""

def apply_post_validation(
    knowledge_tags: dict[str, list[str]] | None,
    attitude_changes: dict[str, AttitudeChange] | None,
    state_manager: StateManager,
) -> EngineResult:
    """Run full post-validation and produce updated EngineResult."""
```

#### Knowledge Tag Validation

For each `(npc_id, topic_ids)` pair:
1. Verify NPC exists in corpus and is type `npc`
2. Verify NPC `state.alive == True`
3. For each `topic_id`:
   - Verify topic exists in NPC's `dialogue_guidelines.will_reveal`
   - Evaluate topic's `conditions` against current state
   - If all conditions met:
     - Apply `set_flag` side effects → `state_manager.apply_hard_changes()`
     - Apply `set_entity_state` side effects → `state_manager.apply_hard_changes()`
     - Record in `soft_state.npc_revelations[npc_id]` (avoid duplicates)
     - Add to `revelations_applied` list
   - If conditions not met or topic unknown: silently skip

#### Attitude Change Validation

For each `(npc_id, change)` pair:
1. Verify NPC exists in corpus and is type `npc`
2. Verify NPC `state.alive == True`
3. Read `attitude_limits` from corpus
4. Verify `change.old_value` matches current `npc_attitudes[npc_id]`
5. Verify `abs(change.new_value - change.old_value) <= step_per_turn`
6. Verify `min <= change.new_value <= max`
7. Verify `change.reason` is non-empty
8. If all valid: apply `npc_attitudes[npc_id] = change.new_value`
9. If invalid: add to `attitude_changes_rejected` with reason

---

## Interaction with Existing Code

### Models (Phase 1) — Used Directly

- `PlayerAction` (discriminated union): engine dispatches on `action_type`
- `EngineResult`: engine populates all fields
- `HardStateChanges`: engine builds this, passes to `StateManager.apply_hard_changes()`
- `SoftStatePatch`: engine validates proposed patches
- `ConditionExpression`: engine evaluates via `evaluate()`
- `BriefingRoom`, `BriefingEntity`, etc.: engine builds `room_after`

### State Manager (Phase 2) — Mutation Interface

The engine receives the `StateManager` and calls:
- `state_manager.hard_state` (direct reference, mutable)
- `state_manager.soft_state` (direct reference, mutable)
- `state_manager.corpus` (read-only reference)
- `state_manager.apply_hard_changes(changes)` — validates then applies
- `state_manager.apply_soft_patches(patches)` — validates then applies
- `state_manager.append_turn_history(entry)` — logs turn

Per plan.md Design Decision 1, the engine mutates state directly through these references.

### Conditions (Phase 3) — Evaluation Interface

The engine calls:
- `evaluate(condition, hard_state, soft_state, corpus)` → `bool`
- Used for: exit conditions, interaction conditions, on_enter conditions, encounter rules, game-over mechanics, will_reveal topic conditions

---

## Edge Cases and Error Handling

### Invalid Actions

| Scenario | Engine Response |
|----------|----------------|
| Unknown exit ID | `success=False, error="Exit not found"` |
| Entity not in room | `success=False, error="Entity not present"` |
| NPC dead | `success=False, error="NPC is dead"` |
| Conditions not met | `success=False, error="Conditions not met"` |
| Item not in inventory | `success=False, error="Item not in inventory"` |
| Interaction not found | `success=False, error="Interaction not found"` |
| Wrong parameter types | `success=False, error="Invalid parameter"` |

### Chain Actions

- `follow_up` on PlayerAction indicates more steps to perform
- Engine includes `chain_info` in EngineResult with `follow_up` text
- Game loop (Phase 7) will feed `follow_up` back as next input
- Chain terminates on: validation failure, hard/soft rejection, max depth
- On termination: `chain_info.termination_reason` explains why

### Game-Over Detection

- After all state changes applied, evaluate all `mechanics` with `type` set
- If condition fires: set `hard_state.game_over = { type, trigger }`
- Include `game_over` in EngineResult with mechanic's `narrative`
- LLM Call 2 will narrate the ending

### Random Rolls

- Use `random.random()` for probabilistic checks
- Record roll details in `EngineResult.rolls` for debugging/replay
- Roll format: `{ "check_id": "...", "threshold": 0.5, "result": 0.32, "success": True }`

---

## Testing Strategy

### Test File: `tests/test_resolver.py`

Tests for each action resolver against the sample adventure.

#### `test_resolve_move`
- Valid exit traversal
- Exit not found → error
- Conditions not met → error
- One-way exit blocked → error
- `on_traverse` applies flags
- `on_traverse` with `skip_if`
- Hidden exit not accessible

#### `test_resolve_examine`
- Examine entity in room
- Examine room itself
- Examine soft item
- Target not found → error
- `rigorous=True` triggers deeper search
- `using` item must be in inventory

#### `test_resolve_interact`
- Valid interaction with result
- Interaction with check (mock random)
- Interaction with conditions
- Generic `attack` on NPC with behavior → encounter triggered
- Generic `take` for item entity
- Generic `take` for soft item
- Interaction not found → error

#### `test_resolve_talk`
- Start dialogue with NPC
- Continue dialogue
- NPC not in room → error
- NPC dead → error
- `ends_dialogue=True`

#### `test_resolve_transfer`
- Give items to NPC
- Take items from entity
- Give/take soft items
- Item not in inventory → error

#### `test_resolve_wait`
- Always succeeds, no state changes

#### `test_resolve_ooc`
- No state changes, no turn increment

### Test File: `tests/test_encounters.py`

- Encounter rule matching (top-to-bottom)
- Death outcome sets game_over
- Flee outcome applies on_flee effects
- Roll outcome with success/failure branches
- No matching rules → default outcome
- Behavior triggers on specific exits/interactions

### Test File: `tests/test_dialogue.py`

- Enter dialogue mode
- Append utterances
- Stall counter increment
- Stall auto-exit at 3
- Move exits dialogue
- Switch NPC archives old dialogue
- `ends_dialogue` exits cleanly
- `on_dialogue_exit` effects applied
- `ooc_discussion` doesn't increment stall

### Test File: `tests/test_post_validate.py`

- Valid knowledge tag → applies side effects, records revelation
- Unknown topic → silently rejected
- Conditions not met → silently rejected
- Valid attitude change → applied
- Attitude exceeds bounds → rejected
- Step limit exceeded → rejected
- Dead NPC → rejected
- Empty reason → rejected

### Test File: `tests/test_engine.py`

- Full resolution flow for each action type
- Soft-state patch validation (accepted and rejected)
- Game-over detection
- Chain action handling (depth tracking, termination)
- Turn counter increments (except ooc)
- Turn history entry built correctly
- `room_after` BriefingRoom built correctly
- `will_reveal_readiness` populated correctly
- `npc_attitude_limits` populated correctly

### Test Fixtures (add to `conftest.py`)

- `state_manager`: StateManager with sample adventure loaded
- `sample_engine`: Pre-configured engine test helper

---

## Implementation Order

The recommended implementation sequence, from least to most dependent:

1. **`engine/encounters.py`** — Standalone logic, depends only on conditions + models
2. **`engine/dialogue.py`** — Standalone state management, depends only on models
3. **`engine/resolver.py`** — Core resolvers, depends on conditions + encounters
4. **`engine/post_validate.py`** — Depends on conditions + state manager
5. **`engine/engine.py`** — Orchestrator, depends on all of the above
6. **Tests** — Write tests alongside each file; integration tests last

Within `resolver.py`, implement resolvers in this order:
1. `resolve_wait` (trivial, always succeeds)
2. `resolve_ooc` (trivial, no-op)
3. `resolve_examine` (read-only, no state mutation)
4. `resolve_move` (simple state mutation, on_traverse)
5. `resolve_talk` (dialogue integration)
6. `resolve_transfer` (multi-item movement)
7. `resolve_interact` (most complex: conditions, checks, encounters)

---

## Key Design Decisions

### 1. Engine mutates state directly

The engine receives `StateManager` and calls `apply_hard_changes()` / `apply_soft_patches()` during resolution, rather than collecting all changes and applying at the end. This is safe because:
- The engine is the sole writer
- If validation fails early, no changes are applied (the resolver returns before mutation)
- This matches plan.md Design Decision 1

### 2. Resolver functions are pure-ish

Each resolver takes `(action, hard, soft, corpus)` and returns a `ResolutionResult` with proposed changes, but does NOT mutate state directly. The orchestrator (`engine.py`) applies changes after validation. This keeps resolvers testable in isolation.

Exception: dialogue state is mutated in-place by `resolve_talk` since it's soft state managed by `dialogue.py`.

### 3. Random rolls use `random.random()`

Standard library `random` module. For testing, use `random.seed()` or mock `random.random` to return deterministic values.

### 4. Encounter resolution is separate from resolver

Encounters can fire from exit traversal OR interaction. By keeping encounter logic in `encounters.py`, both `resolve_move` (via `on_traverse.trigger_encounter`) and `resolve_interact` (via `attack` on NPC with behavior) can call it.

### 5. Post-validation produces a delta, not a new EngineResult

`post_validate.py` returns lists of applied/rejected changes. The game loop (Phase 7) will merge these into the existing EngineResult. This keeps post-validation composable and testable.

---

## Dependencies and Imports

```python
# engine/engine.py
from mgmai.models.actions import PlayerAction, EngineResult, HardStateChanges
from mgmai.models.corpus import ModuleCorpus
from mgmai.state.manager import StateManager
from mgmai.engine.resolver import resolve_action, ResolutionResult
from mgmai.engine.encounters import resolve_encounter, should_trigger_behavior
from mgmai.engine.dialogue import (
    enter_dialogue, append_player_turn, increment_stall,
    exit_dialogue, check_room_change_exit,
)
from mgmai.engine.conditions import evaluate

# engine/resolver.py
from mgmai.models.actions import *
from mgmai.models.corpus import ModuleCorpus, Interaction
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate

# engine/encounters.py
from mgmai.models.corpus import EncounterRule, Behavior, ModuleCorpus
from mgmai.models.hard_state import HardGameState
from mgmai.models.soft_state import SoftGameState
from mgmai.engine.conditions import evaluate

# engine/dialogue.py
from mgmai.models.soft_state import SoftGameState, DialogueState
from mgmai.models.corpus import ModuleCorpus
from mgmai.models.hard_state import HardGameState

# engine/post_validate.py
from mgmai.models.actions import EngineResult, RevelationApplied, AttitudeChange
from mgmai.models.narration import AttitudeChange
from mgmai.state.manager import StateManager
from mgmai.engine.conditions import evaluate
```

---

## What This Phase Does NOT Cover

- **Context Assembler** (Phase 5): building GMBriefing from state — the engine produces `room_after` but not the full briefing
- **LLM Integration** (Phase 6): calling the LLM, parsing output — the engine receives already-parsed `PlayerAction`
- **Game Loop** (Phase 7): REPL, turn orchestration, chain handling loop — the engine handles one resolution call; the loop handles chaining
- **Display** (Phase 7): Rich rendering — the engine produces data, not UI

---

## Open Questions from `problems.txt`

These issues were identified during earlier phases and affect engine implementation:

1. **NPC/container inventory**: The `transfer` action's `taken_items` needs a clear source model. Proposed: entities have an implicit available pool of items (entities in the same room that are items, plus their `soft_items`). The engine should document this clearly.

2. **LLM Call 2 chain-continue signal**: The engine's `chain_info` field in `EngineResult` signals chain status. The game loop (Phase 7) decides whether to continue.

3. **Result.reveals field**: This hint text should be included in `triggered_narration` for LLM Call 2 to weave into prose.

4. **step_per_turn: 0**: The post-validation should treat this as "no attitude changes ever allowed" and reject all proposals.

---

## Estimated Scope

| File | Est. Lines | Complexity |
|------|-----------|------------|
| `engine/resolver.py` | 400-500 | High — many action types, validation logic |
| `engine/encounters.py` | 150-200 | Medium — rule evaluation, random rolls |
| `engine/dialogue.py` | 200-250 | Medium — state transitions, archival |
| `engine/post_validate.py` | 150-200 | Medium — validation, side effects |
| `engine/engine.py` | 300-400 | High — orchestration, state assembly |
| Tests (5 files) | 800-1200 | Medium — many cases, fixtures |
| **Total** | **2000-2750** | |
