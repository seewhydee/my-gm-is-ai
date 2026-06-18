# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

- **Character sheet improvements**: LLM-aided prompt for character sheet generation; save character sheets in .config/mgmai.

---

## Unified Event-Reaction System (Trigger Architecture Rework)

### 1. Problem Statement

The current trigger system is fragmented across multiple model types, each with
a different (and incomplete) set of permissible effects:

| Trigger location | set_flag | alter_stat | trigger_encounter | trigger_dialogue | chain_check | combat |
|---|---|---|---|---|---|---|
| `OnEnterEvent` | yes | no | **no** | yes | no | no |
| `TraversalEffect` (success) | yes | yes | yes | no | no | no |
| `TraversalCheck` (failure) | no | no | **no** | no | no | no |
| `Interaction.success` | yes | yes | no | no | yes | no |
| `Interaction.failure` | yes | yes | no | no | yes | no |
| `BranchOutcome` | yes | yes | no | no | **no** | by outcome |
| `Behavior.triggers_on` | via enc. | via enc. | via enc. | no | no | by outcome |
| `will_reveal` side effects | yes | no | no | no | no | no |
| `DialoguePath` result | yes | yes | no | no | no | no |
| `on_dialogue_exit` | yes | no | no | no | no | no |

State-based triggers (on flag change, attitude threshold, stat change) do not
exist at all.  Every new adventure surfaces more "X doesn't support Y" gaps,
and each fix adds an ad-hoc field with its own engine code path.

### 2. Design Overview

Define a **canonical set of game events** that the engine emits after every
meaningful state transition or action.  Any object (room, entity, mechanic)
can register **reactions** — `(on_event, condition, effects)` tuples — that
fire when matching events occur.

This replaces six separate trigger mechanisms with one.  Every combination of
`<event> × <effect>` works automatically.  State-based triggers become trivial.

### 3. Event Model

#### 3.1 Canonical event types

Each event has a **type** (string identifier) and a **context** (flat
`dict[str, str | int | bool]` of details about the specific occurrence).

**Action-level events (emitted during resolution):**

| Event | Context keys | Emitted when |
|---|---|---|
| `room.entered` | `room_id` | Player arrives in a room (including game start) |
| `room.exited` | `room_id` | Player leaves a room |
| `traversal.attempted` | `exit_id`, `from_room`, `to_room` | Player attempts to traverse an exit (before the traversal check) |
| `traversal.succeeded` | `exit_id`, `from_room`, `to_room` | Exit traversal succeeds |
| `traversal.failed` | `exit_id`, `from_room`, `fail_reason` | TraversalCheck fails |
| `check.passed` | `check_type` (`stat_check`\|`roll`), `stat?`, `dc?`, `threshold?`, `source_id`, `source_type` (`interaction`\|`examine`\|`traversal`\|`dialogue_path`\|`reaction`) | Any check succeeds |
| `check.failed` | same as `check.passed` | Any check fails |
| `interaction.used` | `interaction_id`, `target_id`, `using_item?` | An interaction is attempted (before check) |
| `dialogue.started` | `npc_id` | enter_dialogue() called |
| `dialogue.ended` | `npc_id`, `reason` (`player_left`\|`ends_dialogue`\|`switched_npc`\|`stall`\|`room_change`\|`combat`) | exit_dialogue() called |
| `combat.started` | `combatant_ids` (list) | Combat phase begins |
| `combat.ended` | `reason` (`victory`\|`defeat`\|`fled`) | Combat phase ends |
| `item.acquired` | `item_id`, `source` (`transfer`\|`interaction`\|`examine`\|`equip`) | Item enters inventory |
| `item.lost` | `item_id`, `reason` (`transfer`\|`interaction`\|`destroyed`\|`unequip`) | Item leaves inventory |

**State-change events (emitted after applying HardStateChanges):**

| Event | Context keys | Emitted when |
|---|---|---|
| `flag.set` | `flag_name` | A flag transitions to `true` |
| `flag.cleared` | `flag_name` | A flag transitions to `false` |
| `entity_state.changed` | `entity_id`, `field`, `new_value` | Any entity state field changes |
| `attitude.changed` | `npc_id`, `old_value`, `new_value`, `delta` | NPC attitude changes |
| `stat.changed` | `stat_name`, `old_value`, `new_value`, `delta` | Player stat changes |
| `equipment.changed` | `added?`, `removed?` | Equipped gear changes |
| `player.damaged` | `amount`, `new_hp` | Player HP decreases |
| `player.healed` | `amount`, `new_hp` | Player HP increases |

**Lifecycle events:**

| Event | Context | Emitted when |
|---|---|---|
| `adventure.start` | `{}` | First turn of the adventure (fires once) |
| `turn.start` | `turn_number` | Beginning of each engine.resolve() call (after action validation) |
| `turn.end` | `turn_number` | End of engine.resolve(), before building EngineResult |

**Notes on not-yet-fully-implemented events:** `adventure.start` is defined in
the event model but is not currently emitted. `combat.started` is emitted when
a reaction-triggered encounter resolves to combat, but not yet from the main
encounter path or direct combat entry. `combat.ended` is not yet emitted.

#### 3.2 Context availability in conditions

During reaction dispatch, event context is available via a new condition domain:

```
event:<key> <op> <value>
```

Examples:
- `event:interaction_id == attack`
- `event:flag_name == spider_fled`
- `event:field == alive`
- `event:new_value == false`
- `event:check_type == stat_check`
- `event:stat == STR`

The `event:` domain is only valid during reaction dispatch.  Outside dispatch
(e.g., in interaction conditions or game-over mechanics), it evaluates to `false`.

Reactions are added to three existing models as optional lists:

```
Room.reactions:     list[Reaction]   # scoped to when player is in this room
Entity.reactions:   list[Reaction]   # scoped to when entity is present in current room
Mechanic.reactions: list[Reaction]   # globally scoped (mechanics are adventure-wide)
```

`Mechanic` also gains a backward-compatible `reactions` field alongside the
existing `type`/`condition`/`trigger_id` and `rules` fields.  A mechanic may be:
- A game-over condition (`type` + `condition` + `trigger_id`)
- An encounter (`rules`)
- Reaction-only (`reactions` — no `type` or `rules` required)

At least one of these must be present.  When `reactions` is non-empty, the
engine dispatches them like any other reaction.  The mechanic's `condition`
field is only used for game-over and encounter mechanics; reaction-only
mechanics use per-reaction `condition` fields instead.

Entity-scoped reactions are active when the entity is alive and has not fled.
The engine checks `entity_state.get("alive") is not False and
entity_state.get("fled") is not True`.  The `fled` field is standardized as a
reserved state field alongside `alive` — adventures that don't declare it in
`state_fields` simply never have it set, so the check passes naturally.
Document this in `schema/corpus.md`.

### 4. Migration Plan (6 Phases)

#### Phase 1: Add models (no behavior change)
**Files:** `models/corpus.py`
- Add `has_any_effect()` method to `Result` (returns `True` if any non-`None`
  field is set)
- Add `GameOverTrigger`, `ReactionEffects`, `Reaction` models
- `ReactionEffects` wraps `Result` plus `trigger_encounter`, `trigger_dialogue`,
  `game_over`
- `Reaction` includes a Pydantic validator that rejects `phase="immediate"`
  for events not in the immediate allow-list
- Add `reactions: list[Reaction] = []` to `Room`, `Entity`, `Mechanic`
- All new fields are optional with empty defaults — zero impact on existing
  adventures, zero impact on existing engine code

#### Phase 2: Add event: domain to conditions
**Files:** `engine/conditions.py`
- Add `event` to `DOMAINS` regex
- Add `event_ctx: dict | None = None` parameter to `evaluate_condition_string()`,
  `evaluate()`, `evaluate_require()`, `get_condition_detail()`
- Implement `event:` domain handler — lookup key in `event_ctx`, compare
- All existing call sites pass no `event_ctx` — backward compatible

#### Phase 3: Implement event bus (complete)
**Files:** `engine/event_bus.py` (new), `engine/resolver.py`, `engine/engine.py`
- ✅ `find_matching_reactions()` and `dispatch_reactions()` implemented
- ✅ `events` and `immediate_changes` fields on `ResolutionResult`
- ✅ `"self"` resolution in `dispatch_reactions()`
- ✅ `check.passed`/`check.failed` events with `source_id`/`source_type` from
  `_resolve_interaction_check` (interaction/examine) and `_resolve_traversal_check`
  (traversal).  Chain-check events from reactions use `source_type: "reaction"`.
- ✅ Encounter triggering from reactions: immediate via `encounter_trigger_ref`,
  deferred inline via `_resolve_reaction_encounter`.  Encounter-once-per-turn
  guard via shared `encounter_fired_ref`.
- ✅ All resolver functions instrumented with action-level events
- ✅ `_derive_state_events()` and `_dispatch_events()` in engine.py
- ✅ `turn.start` / `turn.end` lifecycle events
- ✅ Reaction narrative/reveals propagation via `triggered_narration`/`revealed_hints`
  output parameters on `dispatch_reactions()` and `_dispatch_events()`
- ✅ Reaction-only mechanics allowed (`Mechanic.check_shape()` accepts non-empty
  `reactions` without `type` or `rules`)

At this point, the event bus is fully operational but **no adventure uses
reactions yet** — all existing triggers still work through legacy code paths.
Phase 4 documents reactions for scenario authors; Phase 5 converts adventures
one trigger type at a time, removing each legacy code path as it becomes unused.

#### Phase 4: Update scenario-generation pipeline
**Files:** `schema/corpus.md`, `schema/scenario-generation.md`
- Document the `Reaction` model and `reactions` field
- Document `check.passed`/`check.failed` events and their `source_type`/
  `source_id` context keys.  Note that `source_type` can be `"interaction"`,
  `"examine"`, `"traversal"`, `"dialogue_path"`, or `"reaction"` (for
  chain-check events from reactions).
- Document reaction-only mechanics: a `Mechanic` with `reactions` but no `type`
  or `rules` is valid.  Use for adventure-wide state-based reactions that don't
  need encounter rules.
- Document that reaction narrative and reveals propagate to the `EngineResult`:
  narrative from reaction `result` effects and encounter triggers appears in
  `triggered_narration`; hint reveals appear in `revealed_hints`.
- Document the encounter-once-per-turn guard: only one encounter can fire per
  turn (from either the resolver or deferred reactions).  Subsequent
  `trigger_encounter` effects are silently ignored with a warning log.
- Add examples: state-based triggers, chained encounters, room-entry encounters,
  failed-check triggers
- Update the "Common Pitfalls" section — remove workarounds that reactions
  obsolete
- Keep old trigger field documentation (marked as "legacy, prefer reactions")
- Add guidance on nested encounters: a reaction that fires during an encounter
  can trigger another encounter via `trigger_encounter`.  The depth-5 recursion
  limit prevents infinite loops, but scenario authors should be aware that
  nested encounters are possible and design reaction conditions carefully to
  avoid unintended chains.

#### Phase 5: Convert adventures, remove legacy code paths
**Files:** adventures (JSON), `engine/engine.py`, `engine/resolver.py`,
`engine/dialogue.py`

Convert adventures to use reactions and remove legacy code paths as
they become unused.

Conversion order (one trigger type at a time, playtesting each):

1. **`OnEnterEvent` → `Room.reactions`**
   - Convert each room's `on_enter` list to equivalent `on="room.entered"`
     reactions
   - One-shot unconditional events use `once: true`; conditional events
     preserve their `condition`; `trigger_dialogue` maps to
     `effects.trigger_dialogue`
   - Once no room uses `on_enter`, delete `_fire_on_enter_events()` from
     `engine.py` and its call site

2. **`TraversalEffect` → exit-scoped reactions**
   - Convert each exit's `on_traverse` to `on="traversal.succeeded"` reactions
     with `condition={require: "event:exit_id == <exit_id>"}`
   - `set_flag`/`alter_stat`/`narrative` map to `effects.result`;
     `trigger_encounter` maps to `effects.trigger_encounter`
   - Once no exit uses `on_traverse`, remove the inline traversal-effect
     processing from `resolve_move()` in `resolver.py`

3. **`Behavior.triggers_on` → entity-scoped reactions**
   - Convert NPC behavior triggers to `on="interaction.used"` reactions on
     the entity, with `condition={require: "event:interaction_id == <id>"}`
   - `effects.trigger_encounter = "self"` (resolved to entity ID at dispatch)
   - Once no entity uses `behavior.triggers_on`, remove the inline check
     from `resolve_interact()` in `resolver.py` and
     `check_behavior_trigger()` in `encounters.py`

4. **`on_dialogue_exit` → entity-scoped reactions**
   - Convert NPC `on_dialogue_exit` to `on="dialogue.ended"` reactions on
     the entity, with `condition={require: "event:npc_id == <npc_id>"}`
   - `set_entity_state`/`set_flag`/`narrative` map to `effects.result`
   - Once no entity uses `on_dialogue_exit`, remove the inline effect
     processing from `_archive_and_exit()` in `dialogue.py`

5. **`OnExamineEvent` → reactions** (if applicable)
   - Evaluate whether `on_examine` should become reactions or remain as-is;
     may be better left alone since examine events are interaction-driven

**Not migrated:**
- `will_reveal` — LLM-triggered, stays outside the reaction system
- Game-over mechanics (`Mechanic.type`/`condition`/`trigger_id`) — work fine
  as-is, semantically distinct from reactions.  The `game_over` effect on
  `ReactionEffects` is for new reaction-based patterns, not a replacement.

After each conversion step, run the full test suite and playtest.  Delete the
legacy code path only when no adventure uses it anymore.

#### Phase 6: Remove old model fields
**Files:** `models/corpus.py`, adventures (JSON)

Once all adventures are converted and all legacy code paths removed:
- Delete `OnEnterEvent`, `TraversalEffect`, `OnExamineEvent` (if migrated),
  `DialogueExit` models from `corpus.py`
- Remove `on_enter`, `on_traverse`, `on_examine`, `on_dialogue_exit` fields
  from `Room`, `Exit`, `Entity` etc.
- Remove `Behavior.triggers_on` field (keep `Behavior.encounter_rules` —
  encounters are still used, just triggered via reactions now)

### 5. Events Not Emitted During Reaction Dispatch

A critical rule: **reaction effects that mutate state do NOT emit state-change
events during dispatch.**  State-change events (`flag.set`, `stat.changed`,
`entity_state.changed`, etc.) are derived once at the end of the turn from the
merged `HardStateChanges` diff (see §14.2).  This means reaction state mutations
DO eventually produce state-change events — but only after all reactions have
finished dispatching, preventing cascading chains where reaction A sets a flag,
which triggers reaction B, which sets another flag...

Reaction effects *can* emit action-level events (`check.passed`/`check.failed`
from `chain_check`, `dialogue.started`/`ended`, `combat.started`/`ended`).
These are dispatched at the next recursion level (within the depth-5 limit).
This enables patterns like "on dialogue ended, trigger an encounter" without
enabling infinite regress.

---

### Known Gaps / Remaining Work

1. **Legacy code paths still active**: `_fire_on_enter_events()`,
   inline traversal effects in `resolve_move()`, inline `behavior.triggers_on`
   in `resolve_interact()`, and inline `on_dialogue_exit` in
   `_archive_and_exit()` are all still active.  These will be removed one at
   a time as adventures are converted.

2. **`context/assembler.py` not updated**: With the Option B accumulator model,
   reaction effects are applied through the normal `apply_hard_changes()` path
   and the assembler reads the final state — no structural change is needed.
   This may become relevant when on-enter events are fully migrated
   to reactions.

3. **Encounter stat check event emission**: `check.passed`/`check.failed` events
   are not yet emitted from `_resolve_encounter_stat_check` in `encounters.py`.
   Encounter checks have their own outcome tracking; this can be added in a
   future phase if reaction-based encounter check triggers become important.

4. **`adventure.start` not emitted**: Defined in the event model but not
   currently emitted.

5. **`combat.started` / `combat.ended` partially implemented**: `combat.started`
   is emitted only when a reaction-triggered encounter resolves to combat.
   `combat.ended` is not yet emitted.

6. **Transfer take_checks don't emit events**: `resolve_transfer` calls
   `_resolve_interaction_check` without `state_manager` or `resolution`, so
   `check.passed`/`check.failed` events and immediate reactions don't fire for
   transfer take_checks.  Fix by threading `state_manager`/`resolution` through
   the transfer path at `engine/resolver.py:667-668`.
