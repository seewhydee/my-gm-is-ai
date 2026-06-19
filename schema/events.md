# Event Model

The engine emits **canonical events** after every meaningful state transition or
player action. Any object (room, entity, or mechanic) can register **reactions**
— `(on_event, condition, effects)` tuples — that fire when a matching event
occurs.

This document is the authoritative reference for:

- Which events the engine emits
- What context keys each event carries
- When each event is emitted
- Which events support `phase: "immediate"` reactions
- Known gaps in event emission

For how to write reactions, see [`corpus.md`](corpus.md) § Reaction object and
[`scenario-generation.md`](scenario-generation.md). For the original design
rationale, see [`plan.md`](../plan.md).

---

## Event structure

Each event has:

- **`type`** — a dot-separated string identifier such as `room.entered` or
  `flag.set`.
- **`context`** — a flat dict of details about the specific occurrence. Context
  values are strings, integers, or booleans.

During reaction dispatch, context values are available via the `event:`
condition domain:

```json
{ "require": "event:exit_id == exit_climb_down" }
{ "require": "event:interaction_id == attack" }
{ "require": "event:flag_name == spider_fled" }
```

The `event:` domain is **only valid during reaction dispatch**.
Outside dispatch (e.g., in interaction conditions, exit conditions, or
game-over mechanic conditions), it always evaluates to `false`.


---

## Action-level events

These events are emitted while the engine resolves a player action or an
encounter.

| Event | Context keys | Emitted when |
|---|---|---|
| `room.entered` | `room_id` | Player arrives in a room, including at game start. |
| `room.exited` | `room_id` | Player leaves a room. |
| `traversal.attempted` | `exit_id`, `from_room`, `to_room` | Player attempts to traverse an exit **before** the traversal check is rolled. |
| `traversal.succeeded` | `exit_id`, `from_room`, `to_room` | Exit traversal succeeds. |
| `traversal.failed` | `exit_id`, `from_room`, `fail_reason` | A `traversal_check` fails and the player stays in the current room. |
| `check.passed` | `check_type`, `stat?`, `dc?`, `threshold?`, `source_id`, `source_type` | Any roll or stat_check succeeds. |
| `check.failed` | same as `check.passed` | Any roll or stat_check fails. |
| `interaction.used` | `interaction_id`, `target_id`, `using_item?` | An interaction is attempted **before** its check is rolled. |
| `dialogue.started` | `npc_id` | Dialogue mode begins with an NPC. |
| `dialogue.ended` | `npc_id`, `reason` | Dialogue mode ends. `reason` is one of `player_left`, `ends_dialogue`, `switched_npc`, `stall`, `room_change`, `combat`, or `triggered`. |
| `combat.started` | `combatant_ids` | Combat begins. |
| `combat.ended` | `reason` (`victory`\|`defeat`\|`fled`) | Combat ends. |
| `item.acquired` | `item_id`, `source` (`transfer`\|`interaction`\|`examine`\|`unequip`) | An item enters the player's inventory. |
| `item.lost` | `item_id`, `reason` (`transfer`\|`interaction`\|`destroyed`\|`equip`) | An item leaves the player's inventory. |

### `check.passed` / `check.failed` context keys

| Key | Type | Description |
|---|---|---|
| `check_type` | string | `"stat_check"` or `"roll"`. |
| `stat` | string\|absent | The stat key for `stat_check` checks. |
| `dc` | int\|absent | The difficulty class for `stat_check` checks. |
| `threshold` | float\|absent | The probability threshold for `roll` checks. |
| `source_id` | string | The interaction, exit, dialogue path, or reaction ID that originated the check. |
| `source_type` | string | `"interaction"`, `"examine"`, `"traversal"`, `"dialogue_path"`, or `"reaction"`. |

`source_type: "reaction"` is used when a `chain_check` inside a reaction result
produces the event.

### `dialogue.ended` reasons

| Reason | Meaning |
|---|---|
| `player_left` | The player moved to another room while in dialogue. |
| `ends_dialogue` | The player explicitly ended dialogue (e.g., via a `talk` action with `ends_dialogue: true`). |
| `switched_npc` | Dialogue switched to a different NPC. |
| `stall` | The conversation stalled and the engine timed it out. |
| `room_change` | The NPC could not follow the player into a new room. |
| `combat` | Dialogue ended because combat started. |
| `triggered` | A reaction triggered dialogue with a different NPC. |

---

## State-change events

These events are **derived once at the end of the turn** from the merged
`HardStateChanges` diff, after all action and reaction effects have been
applied. They are dispatched in a single final pass.

| Event | Context keys | Emitted when |
|---|---|---|
| `flag.set` | `flag_name` | A flag transitions to `true`. |
| `flag.cleared` | `flag_name` | A flag transitions to `false`. |
| `entity_state.changed` | `entity_id`, `field`, `new_value` | Any entity state field changes. |
| `attitude.changed` | `npc_id`, `old_value`, `new_value`, `delta` | An NPC's attitude changes. |
| `stat.changed` | `stat_name`, `old_value`, `new_value`, `delta` | A player stat changes. |
| `equipment.changed` | `added?`, `removed?` | Equipped gear changes. |
| `player.damaged` | `amount`, `new_hp` | Player HP decreases. |
| `player.healed` | `amount`, `new_hp` | Player HP increases. |

### No cascading state-change events

However, reaction effects that mutate state do not emit state-change
events *during* dispatch.  State-change events are derived once at the
end of the turn.  Reaction state mutations do eventually produce
state-change events, but only after all reactions have finished
dispatching.  This prevents cascading chains where reaction A sets a
flag, which triggers reaction B, which sets another flag...

Reaction effects *can* emit events (`check.passed`/`check.failed` from
`chain_check`, `dialogue.started`/`ended`, `combat.started`/`ended`).
These are dispatched at the next recursion level, enabling patterns
like "on dialogue ended, trigger an encounter".

---

## Lifecycle events

| Event | Context | Emitted when |
|---|---|---|
| `adventure.start` | `{}` | First turn of the adventure. Fires once. |
| `turn.start` | `turn_number` | Beginning of each `engine.resolve()` call, after action validation. |
| `turn.end` | `turn_number` | End of `engine.resolve()`, before building `EngineResult`. |

---

## Immediate vs deferred reactions

Reactions default to `phase: "deferred"`, meaning they fire at the end of the
turn during the event-dispatch pass. `phase: "immediate"` reactions fire
synchronously as soon as the matching event is emitted, before the current
action continues.

Immediate reactions are only allowed for these events:

- `interaction.used`
- `traversal.attempted`
- `traversal.succeeded`
- `room.entered`

For all other events, `phase: "immediate"` is rejected by the model validator.

---

## Known gaps and partial implementation

The following events are defined in the model but not yet fully emitted:

- **`combat.started`** — emitted when a reaction-triggered encounter resolves to
  combat, but not yet from the main encounter path or direct combat entry.
- **`combat.ended`** — not yet emitted.
- **Encounter stat checks** — `check.passed`/`check.failed` events are not yet
  emitted from `_resolve_encounter_stat_check`.
- **Transfer take_checks** — `check.passed`/`check.failed` events and immediate
  reactions do not fire for `transfer` take_checks because `resolve_transfer`
  does not thread `state_manager`/`resolution` through the check path.

Scenario authors should not rely on reactions to these events until the gaps are
closed.

---

## Where reactions are defined

Reactions can be attached to three existing models:

- **`Room.reactions`** — scoped to when the player is in that room.
- **`Entity.reactions`** — scoped to when the entity is present in the current
  room and `alive` is not `false` and `fled` is not `true`.
- **`Mechanic.reactions`** — globally scoped; use for adventure-wide triggers.

See [`corpus.md`](corpus.md) for the full `Reaction` schema, effect fields, and
examples.

---

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
