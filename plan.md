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
| `check.passed` | `check_type` (`stat_check`\|`roll`), `stat?`, `dc?`, `threshold?`, `source_id`, `source_type` (`interaction`\|`examine`\|`traversal`\|`dialogue_path`) | Any check succeeds |
| `check.failed` | same as `check.passed` | Any check fails |
| `interaction.used` | `interaction_id`, `target_id`, `using_item?` | An interaction is attempted (before check) |
| `dialogue.started` | `npc_id` | enter_dialogue() called |
| `dialogue.ended` | `npc_id`, `reason` (`player_left`\|`ends_dialogue`\|`stall`\|`room_change`\|`combat`) | exit_dialogue() called |
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

### 4. Reaction Model

#### 4.1 Pydantic models (new additions to `models/corpus.py`)

```python
class GameOverTrigger(BaseModel):
    """Lightweight game-over descriptor for reaction effects."""
    type: Literal["win", "lose"]
    trigger_id: str


class ReactionEffects(BaseModel):
    """Effects a reaction can produce.

    Wraps the existing ``Result`` model for shared state-mutation fields
    (narrative, set_flag, alter_stat, etc.) and adds reaction-specific
    fields (trigger_encounter, trigger_dialogue, game_over).

    At least one of ``result`` or the reaction-specific fields must be set.
    """
    result: Optional[Result] = None                     # reuses existing Result model
    trigger_encounter: Optional[str] = None             # mechanic ID or entity ID
    trigger_dialogue: Optional[str] = None              # NPC entity ID
    game_over: Optional[GameOverTrigger] = None

    @model_validator(mode="after")
    def check_non_empty(self):
        has_result = self.result is not None and self.result.has_any_effect()
        has_reaction = any(
            f is not None
            for f in (self.trigger_encounter, self.trigger_dialogue, self.game_over)
        )
        if not has_result and not has_reaction:
            raise ValueError("ReactionEffects must have at least one effect set")
        return self


class Reaction(BaseModel):
    """A single reaction: on event X, if condition Y holds, do Z."""
    id: str                                           # corpus-unique ID (for debugging / once tracking)
    on: str                                           # event type (see §3.1)
    condition: Optional[ConditionExpression] = None   # event-context + state filter
    effects: ReactionEffects
    once: bool = False                                # fire at most once, then self-disable (in-memory only)
    priority: int = 0                                 # lower = fires earlier
    phase: Literal["immediate", "deferred"] = "deferred"  # when to fire (see §6.5)

    @model_validator(mode="after")
    def validate_phase(self) -> Reaction:
        IMMEDIATE_ALLOWED = {"interaction.used", "traversal.attempted", "room.entered"}
        if self.phase == "immediate" and self.on not in IMMEDIATE_ALLOWED:
            raise ValueError(
                f"phase='immediate' is only allowed for events: "
                f"{IMMEDIATE_ALLOWED}. Got: {self.on!r}"
            )
        return self
```

Note: the existing `Result` model needs a `has_any_effect()` convenience method
that returns `True` if any non-`None` field is set.  This is a small addition
to `models/corpus.py`.

Note: applying a reaction's `result` effects reuses the existing `_apply_result()`
function from `engine/resolver.py`.  The reaction-specific fields
(`trigger_encounter`, `trigger_dialogue`, `game_over`) are handled by the event
bus's `dispatch_reactions()` function.

#### 4.2 Where reactions live

Reactions are added to three existing models as optional lists (empty by default,
zero impact on existing adventures):

```
Room.reactions:     list[Reaction]   # scoped to when player is in this room
Entity.reactions:   list[Reaction]   # scoped to when entity is present in current room
Mechanic.reactions: list[Reaction]   # globally scoped (mechanics are adventure-wide)
```

`Mechanic` also gains a backward-compatible `reactions` field alongside the
existing `type`/`condition`/`trigger_id` and `rules` fields.  When `reactions`
is present and non-empty, the engine uses reactions.  When absent, the existing
mechanic logic applies unchanged.

Entity-scoped reactions are active when the entity is alive and has not fled.
The engine checks `entity_state.get("alive") is not False and
entity_state.get("fled") is not True`.  The `fled` field is standardized as a
reserved state field alongside `alive` — adventures that don't declare it in
`state_fields` simply never have it set, so the check passes naturally.
Document this in `schema/corpus.md`.

### 5. Condition System Extension

#### 5.1 New domain: `event:`

Add `event` to the `DOMAINS` regex in `conditions.py:27`:

```python
DOMAINS = "flag|inventory|tag|entity|room|attitude|topic|item|stat|equipped|event"
```

`evaluate_condition_string()` gains an `event_ctx: dict | None = None` parameter.
When domain is `event`, it looks up the key in `event_ctx` and compares:

```python
if domain == "event":
    if event_ctx is None:
        return False  # outside dispatch, event context doesn't exist
    if op is None or value is None:
        raise ValueError(f"event condition requires operator and value: {raw!r}")
    ctx_val = event_ctx.get(key)
    if ctx_val is None:
        return False
    return _compare(ctx_val, op, value)
```

The `evaluate()`, `evaluate_require()`, and `get_condition_detail()` functions
all gain `event_ctx: dict | None = None` as an optional trailing parameter.
This is backward-compatible — all existing call sites pass no `event_ctx`.

#### 5.2 Self-reference for entity-scoped reactions

When a reaction is defined on an entity and its effects reference that entity,
the special string `"self"` is resolved to the entity's own ID.  This makes
entity-scoped reactions portable — copying a reaction to a different entity
doesn't require editing the effect references.

Resolution happens in a single pass inside `dispatch_reactions()` before any
effects are applied.  The event bus replaces `"self"` with the owning entity's
ID in all relevant effect fields, then applies the resolved effects normally.

| Effect field | `"self"` resolves to |
|---|---|
| `trigger_encounter` | The entity's ID (for entity.behavior lookup) |
| `trigger_dialogue` | The entity's ID (must be type `npc`) |
| `result.set_entity_state` key | The entity's ID |
| `result.adjust_attitude` key | The entity's ID |

### 6. Event Bus Architecture

#### 6.1 Core components (`engine/event_bus.py` — new file)

```
emit(event_type, context, hard, soft, corpus, state_manager) -> list[Reaction]
    Collects all matching reactions from rooms/entities/mechanics,
    dispatches them in priority order, applies effects via state_manager,
    collects any new events triggered by reaction effects (recursive, max depth 5).

dispatch_reactions(reactions, hard, soft, corpus, state_manager) -> list[dict]
    Applies ReactionEffects, returns list of events emitted by effects
    for recursive dispatch.

find_matching_reactions(event_type, context, hard, soft, corpus) -> list[Reaction]
    Scans current room, entities present, and all mechanics.
    Filters by event_type, evaluates condition against state + event_ctx.
    Skips disabled once-reactions.
```

#### 6.2 Scoping rules

| Reaction on... | Active when... |
|---|---|
| `Room` | Player is currently in that room |
| `Entity` | Entity is in `entities_present` of the current room AND is alive/not-fled |
| `Mechanic` | Always (mechanics are global) |

For events that aren't room-specific (`adventure.start`, `turn.start`,
`turn.end`), room-scoped reactions fire if the player is in that room at
the time of the event.

#### 6.3 Ordering guarantees

1. Sort by `priority` ascending (lower = earlier).
2. Within same priority, entity reactions fire before room reactions before
   mechanic reactions.  This ensures NPCs react before their environment.
3. Within same priority and scope, reactions fire in definition order (list index).
4. `once: true` reactions disable themselves after firing.  The disabled flag
   is tracked in memory only (not persisted to JSON — once-reactions reset
   on adventure reload).  This is acceptable for room-entry reactions where
   the `visited` room-state flag already prevents re-triggering.  For other
   use cases, adventure authors should use flag-gated conditions instead of
   `once: true`, which provides explicit persistence through `hard-state.json`.
5. When multiple reactions mutate the same state field (e.g., two reactions
   set the same flag), the last writer wins.  Reactions are processed in
   priority/definition order, so the later reaction's value persists.

#### 6.4 Loop prevention

- Reactions that emit new events are dispatched recursively.
- Maximum recursion depth: **5**.  Exceeding this logs a warning and stops.
- `once: true` is the primary mechanism for preventing repeated firing
  (e.g., a room entry reaction fires once, sets `once` to true internally).
- State-change events (`flag.set`, `stat.changed`, `entity_state.changed`, etc.)
  are NOT emitted during reaction dispatch.  They are derived once at the end
  of the turn from the merged `HardStateChanges` diff (see §14.2).  This
  prevents reaction→state change→reaction cascades during dispatch.

#### 6.5 Immediate vs deferred reactions

Reactions have a `phase` field that controls when they fire relative to the
current action:

- **`deferred`** (default): the reaction is queued when the event is emitted and
  dispatched after the current action/turn has finished resolving.  This is the
  behavior described in §6.1–§6.4 and covers most state-based and side-effect
  triggers.
- **`immediate`**: the reaction runs synchronously when the event is emitted,
  before the resolver continues with the current action.  This is needed when a
  reaction must alter or interrupt the action in progress.

`phase: "immediate"` is validated at corpus load time — it is only allowed for
the following event types:

- `interaction.used` — before the interaction's check/result is evaluated
- `traversal.attempted` — before the traversal check is evaluated
- `room.entered` — before room-entry narration and other post-entry logic

Using `phase: "immediate"` with any other event type raises a `ValidationError`.

Immediate reactions:

- Receive the same event context as deferred reactions.
- Apply effects through a `HardStateChanges` accumulator passed into the
  resolver, so their state changes are merged into `ResolutionResult.hard_changes`
  and applied once by the engine at the end of the turn.  This keeps
  `EngineResult.hard_state_changes` authoritative.
- May set `resolution.encounter_trigger` to start an encounter, but do not
  resolve encounters themselves.  The outer `engine.resolve()` processes the
  encounter through the normal path.
- Do not emit state-change events from their own state mutations (same rule as
  deferred reactions in §6.4).
- Are subject to the same recursion depth limit as deferred reactions.

Deferred reactions are collected and dispatched in a single batch after action
resolution.  If a deferred reaction produces new events, those events are handled
recursively as deferred (not immediate), up to the depth limit.

### 7. Engine Integration

#### 7.1 Where events are emitted

Events must be emitted at specific points in the resolution pipeline.  The
following locations are instrumented:

**In `engine/resolver.py` (individual action resolvers):**

| Resolver function | Events emitted |
|---|---|
| `resolve_move()` | `traversal.attempted` (before check), `traversal.succeeded` (on success), `traversal.failed` (on TraversalCheck failure) |
| `resolve_interact()` | `interaction.used` (before check), `check.passed` / `check.failed` (after check) |
| `resolve_examine()` | `check.passed` / `check.failed` (after on_examine checks) |
| `resolve_talk()` | `dialogue.started` (on enter_dialogue), `dialogue.ended` (on exit/ends_dialogue) |
| `resolve_transfer()` | `item.acquired` / `item.lost` (after item movement) |
| `resolve_equip()` / `resolve_unequip()` | `equipment.changed` |
| `resolve_combat()` | (none — mid-combat events deferred to a future phase; see §14.10) |

**In `engine/engine.py` (`resolve()`):**

| Point in resolve() | Events emitted |
|---|---|
| After validation, before `resolve_action()` | `turn.start` |
| After applying `hard_changes` via `state_manager.apply_hard_changes()` | `flag.set` / `flag.cleared`, `entity_state.changed`, `stat.changed`, `attitude.changed`, `player.damaged` / `player.healed`, `item.acquired` / `item.lost`, `equipment.changed` |
| After room change detection (`new_room != old_room`) | `room.exited` (old room), `room.entered` (new room) |
| After dialogue exit | `dialogue.ended` |
| After combat start/end | `combat.started`, `combat.ended` |
| Before building `EngineResult` (game-over mechanics check) | `turn.end` |

**In `engine/encounters.py` (`resolve_encounter()`):**

| Point | Events emitted |
|---|---|
| After branch outcome (stat_check/roll) | `check.passed` / `check.failed` |

#### 7.2 Event collection approach

Rather than threading an event list through every resolver function signature,
use a **context-managed event accumulator** on the `ResolutionResult` or a
thread-local list:

```python
# In ResolutionResult dataclass, add:
events: list[tuple[str, dict]] = field(default_factory=list)
immediate_changes: HardStateChanges = field(default_factory=HardStateChanges)
```

Each resolver appends `(event_type, context)` tuples to `resolution.events`.
When an immediate reaction is dispatched, its effects are merged into
`resolution.immediate_changes`.  The engine reads `resolution.events` after
`resolve_action()` returns, adds its own engine-level events (state changes,
room transition, turn end), then calls `emit()` for the combined event list.

This avoids threading `event_ctx` through every function in the call stack.
Immediate reactions are dispatched at the emit point inside the resolver; all
other reactions are dispatched in one batch at the end.

#### 7.3 Integration point in `engine.resolve()`

```python
def resolve(player_action, state_manager, *, chain_depth=0, player_input_echo=None):
    # ... existing setup ...

    # 1. Emit turn.start (before resolve_action so immediate reactions on
    #    turn.start can influence the action).
    _emit_event("turn.start", {"turn_number": hard.turn_count}, resolution)

    # 2. Resolve the action (collects events into resolution.events).
    #    Immediate reactions are dispatched inside resolve_action via the event
    #    bus; their effects are accumulated into resolution.immediate_changes.
    resolution = resolve_action(player_action, hard, soft, corpus)

    # 3. Process encounter triggers (existing logic, unchanged)
    # ...

    # 4. Apply hard state changes (action + immediate reaction changes)
    hard_changes.merge(resolution.immediate_changes)
    old_flags = dict(hard.flags)
    old_stats = dict(hard.player.stats or {})
    state_manager.apply_hard_changes(hard_changes)

    # 5. Derive state-change events from HardStateChanges diff
    state_events = _derive_state_events(hard_changes, old_flags, old_stats, hard)

    # 6. Collect all events and dispatch deferred reactions
    all_events = (
        resolution.events
        + state_events
        + _derive_transition_events(old_room, new_room, ...)
    )
    _dispatch_events(all_events, hard, soft, corpus, state_manager, resolution)

    # 7. on_enter is now handled entirely by room.reactions; legacy
    #    _fire_on_enter_events() is disabled in Phase 4.

    # 8. Fire turn.end event and check game-over mechanics
    turn_end_events = [("turn.end", {"turn_number": hard.turn_count})]
    _dispatch_events(turn_end_events, hard, soft, corpus, state_manager, resolution)

    # ... rest of existing logic ...
```

### 8. Migration Plan (6 Phases)

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

#### Phase 3: Implement event bus
**Files:** `engine/event_bus.py` (new), `engine/resolver.py`, `engine/engine.py`,
`context/assembler.py`
- Implement `find_matching_reactions()`, `dispatch_reactions()`, `emit()`
- Add `events: list[tuple[str, dict]]` and `immediate_changes: HardStateChanges`
  to `ResolutionResult`
- Implement `"self"` resolution: a single pass in `dispatch_reactions()` that
  replaces `"self"` in effect fields with the owning entity's ID before applying
  effects.  This keeps `"self"` awareness in one place.
- Implement `source_id` / `source_type` wiring for check events: update
  `_resolve_interaction_check`, `_resolve_stat_check`, `_resolve_roll_check`,
  `_resolve_traversal_check`, `_resolve_stat_check_chain`,
  `_resolve_roll_check_chain`, `_fire_on_examine_events`, and
  `_resolve_encounter_stat_check` to populate check event context with source
  metadata.  Each returns or appends structured check results including
  `source_id` and `source_type`.
- Implement encounter triggering from reactions:
  - If `trigger_encounter` is an entity ID, use `entity.behavior.encounter_rules`
  - If it is a mechanic ID, use `mechanic.rules` with mechanic-level condition
  - Immediate reactions set `resolution.encounter_trigger` (processed by the
    existing pipeline after `resolve_action()` returns)
  - Deferred reactions: encounter is processed after deferred reaction dispatch,
    using the same pipeline
  - If an encounter already fired this turn, ignore subsequent
    `trigger_encounter` from reactions (log a warning)
- Implement `chain_check` event emission: when a reaction's `chain_check`
  resolves, emit `check.passed` or `check.failed` events with
  `source_type: "reaction"`, `source_id: reaction.id`
- Instrument resolver functions to emit action-level events:
  - `resolve_move()`: `traversal.attempted`, `traversal.succeeded`, `traversal.failed`
  - `resolve_interact()`: `interaction.used`, `check.passed`, `check.failed`
  - `resolve_examine()`: `check.passed` / `check.failed` (after on_examine checks)
  - `resolve_talk()`: `dialogue.started`, `dialogue.ended`
  - `resolve_transfer()`: `item.acquired`, `item.lost`
  - `resolve_equip()` / `resolve_unequip()`: `equipment.changed`
- Add `_derive_state_events()` helper to engine.py
- Add `_dispatch_events()` call in engine.resolve() after state application
- Add `turn.start` event (emitted before `resolve_action()`) and `turn.end` event
- Update `context/assembler.py` to include reaction-produced state changes in
  the GMBriefing (on_enter_events now come from reactions)
- Implement both immediate and deferred dispatch (both are Phase 3 features)

At this point, the event bus is fully operational but **no adventure uses
reactions yet** — all existing triggers still work through legacy code paths.
New adventures can opt into reactions by adding `reactions` lists.

#### Phase 4: Legacy trigger adapter
**Files:** `engine/legacy_adapter.py` (new), `state/manager.py`
- Implement `adapt_legacy_triggers(corpus: ModuleCorpus) -> ModuleCorpus`:
  - Reads all old trigger fields and appends equivalent `Reaction` objects
  - Does NOT remove old fields (backward compat)
- Called automatically in `StateManager.load_corpus()` after validation — all
  adventures are adapted transparently.  No opt-in flag needed; the existing
  test suite against `bag-of-holding` catches adapter bugs.
- Mapping rules:

| Old trigger | Generated Reaction |
|---|---|
| `OnEnterEvent` (unconditional, one-shot) | `on="room.entered"`, `once=true`, `effects={result: {narrative/set_flag/...}}` |
| `OnEnterEvent` (conditional) | `on="room.entered"`, `condition` preserved, `effects={result: {narrative/set_flag/...}}` |
| `OnEnterEvent` with `trigger_dialogue` | `on="room.entered"`, `effects={trigger_dialogue: <npc_id>}` |
| `TraversalEffect.trigger_encounter` | `on="traversal.succeeded"`, `condition={require: "event:exit_id == <exit_id>"}`, `effects={trigger_encounter: <mech_id>}` |
| `TraversalEffect.set_flag` / `alter_stat` | same event + condition, `effects={result: {set_flag/alter_stat}}` |
| `Behavior.triggers_on: ["attack"]` | `on="interaction.used"`, `condition={require: "event:interaction_id == attack"}`, `entity_state: alive, not fled`, `effects={trigger_encounter: "self"}` |
| `on_dialogue_exit` | `on="dialogue.ended"`, `condition={require: "event:npc_id == <npc_id>"}`, effects from `DialogueExit` wrapped in `result` |
| `will_reveal` side effects | NOT migrated — `will_reveal` is LLM-triggered and stays outside the reaction system |
| Game-over mechanic | `on="turn.end"`, existing `condition`, `effects={game_over: {type, trigger_id}}` |

On-enter events are fully migrated to `Room.reactions` by the adapter.  The
legacy `_fire_on_enter_events()` path in `engine.resolve()` is disabled in this
phase; on-enter behavior is now implemented entirely through reactions.  Unit
tests should catch any ordering or double-firing regressions.

#### Phase 5: Update scenario-generation pipeline
**Files:** `schema/corpus.md`, `schema/scenario-generation.md`
- Document the `Reaction` model and `reactions` field
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

#### Phase 6: Deprecation and cleanup (future, after stabilization)
- Mark old trigger fields as deprecated in Pydantic models (add
  `DeprecationWarning` on validation)
- Remove `LegacyTriggerAdapter`
- Remove old trigger field processing from resolver and engine
- Remove old fields from Pydantic models (breaking change for old adventures —
  provide a migration script)

### 9. All Known Gaps Addressed

Each issue from `scenario-report.md` and `combat-plan-report.md` maps to
a reaction-based solution:

| Gap | Reaction-based solution |
|---|---|
| **2.1: Spider attacks on ANY web-forcing attempt** | Deferred reaction on spider entity: `on="traversal.failed"`, `condition={require: "event:exit_id == exit_through_webs_down"}`, `effects={trigger_encounter: "self"}`.  Alternatively, an immediate reaction on `traversal.attempted` triggers the encounter before the traversal check. |
| **2.2: Fall damage stat penalties** | Already fixed in models (`alter_stat` on `TraversalEffect`); already works |
| **2.3: Per-exit traversal check duplication** | Not fully solved — global traversal checks need a separate mechanism (lightweight, not reaction-based).  Reactions don't help here because TRAVERSAL_CHECKS gate movement, and reactions fire after movement.  Keep the existing workaround for now; a `global_traversal_checks: list[TraversalCheck]` field on `ModuleCorpus` or `Room` can be added orthogonally. |
| **2.4: Weapon-dependent DC for traversal** | Same as 2.3 — traversal check gating is pre-move, reactions are post-move.  Add `using_results` to `TraversalCheck` as a separate, small model fix. |
| **2.5: Korbar attacks at attitude -10** | Deferred reaction on korbar entity: `on="attitude.changed"`, `condition={require: "event:new_value <= -10"}`, `effects={trigger_encounter: "self"}` |
| **2.6: Korbar helps with padlock (skip check)** | Immediate reaction on `interaction.used` for the padlock interaction can set a `korbar_helped` flag if Korbar is present and attitude >= 0; the interaction check is then skipped when that flag is set.  Alternatively, add `skip_check_if` to `Interaction` as a small orthogonal fix. |
| **2.7: Dropping items through the rip** | Immediate reaction on `interaction.used` with `condition={require: "event:interaction_id == drop_through_rip"}` and `effects={remove_item: "self"}` (where `"self"` resolves from the item entity or `event:using_item` provides the item ID).  Alternatively, add `remove_item_void: str` to `Result` as an orthogonal small fix. |
| **Nested encounter checks** | Reaction with `chain_check` in effects: a failed check triggers a reaction that runs the follow-up check.  Or simply use chained reactions: reaction A fires on `check.failed`, its effects include a `chain_check` or it emits `check.passed`/`check.failed` events. |
| **No `trigger_encounter` on `OnEnterEvent`** | Reaction on room: `on="room.entered"`, `effects={trigger_encounter: "spider_ambush"}` |
| **State-based behavior triggers** | Reaction on entity with any condition referencing entity state, flags, attitude, etc. |

### 10. Events Not Emitted During Reaction Dispatch

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

### 11. Performance Considerations

- **Reaction lookup**: on each event, scan `current_room.reactions` +
  `entities_present[*].reactions` + `mechanics[*].reactions`.  For a typical
  5-room adventure with 10 entities and 4 mechanics, this is at most ~20
  reactions to filter.  Trivial.
- **Condition evaluation**: reactions that don't match `on` event type are
  skipped before condition evaluation.  Only matching reactions evaluate
  conditions (which involves the existing, fast condition evaluator).
- **Large adventures**: if reaction count becomes a concern (>100), add an
  index `{event_type: [reaction_ids]}` built at load time.  Not needed now.

### 12. Testing Strategy

| What to test | File |
|---|---|
| Reaction model validation (required fields, mutual exclusion, phase values) | `tests/test_reactions.py` |
| Event context condition evaluation (`event:` domain) | `tests/test_conditions.py` (extend) |
| Reaction matching (scoping, priority ordering, once-flag) | `tests/test_event_bus.py` |
| Immediate vs deferred reaction dispatch and ordering | `tests/test_event_bus.py` |
| Legacy adapter correctness (all old trigger types → reactions) | `tests/test_legacy_adapter.py` |
| End-to-end: adventure with reactions behaves correctly | `tests/test_engine.py` (extend) |
| Existing adventures work unchanged after migration | Run full test suite on `bag-of-holding` |
