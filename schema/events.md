# Event Model

This document is the authoritative reference for:

- Which events the engine emits
- What context keys each event carries, and their meanings
- When events are emitted and reactions are triggered

For how to write reactions, see the [Corpus schema](corpus.md).

---

## Event structure

Each event has:

- **`type`** — a dot-separated string identifier, e.g. `room.entered`
- **`context`** — a flat dict of details about the specific event

During reaction dispatch, context values are available via the `event:`
condition domain:

```json
{ "require": "event:exit_id == exit_climb_down" }
{ "require": "event:interaction_id == attack" }
{ "require": "event:flag_id == daytime" }
```

The `event:` domain is **only valid during reaction dispatch**.
Outside dispatch (e.g., in interaction conditions, exit conditions, or
game-over condition predicates), it always evaluates to `false`.

---

## Action-Induced Events

These events are emitted when the engine resolves a player action or
an encounter:

### Passing/failing checks

- `check.passed` – passed a Check
- `check.failed` – failed a Check

For both these events, the context keys are:

| Key           | Type   | Value                                  |
|---------------|--------|----------------------------------------|
| `check_type`  | string | `"stat_check"` or `"roll"`             |
| `stat`¹       | string | Stat key for `stat_check` checks       |
| `target`¹     | int    | Target number / DC for stat check      |
| `threshold`¹  | float  | Probability threshold for `roll` check |
| `source_type` | string | Source of the check (see below)        |
| `source_id`   | string | ID of the source (see below)           |
> ¹ optional

`source_type` should specify the action/event leading to the check –
one of `"interaction"`, `"examine"`, `"traversal"`, `"dialogue_path"`,
`"take"`, or `"reaction"`.  For example, a `then_check` inside a
reaction result emits `source_type: "reaction"`.  The `source_id`
field holds the corresponding interaction, exit, dialogue path, or
reaction ID.

### Entering/Exiting Rooms, and Traversing Exits

- `room.entered` – Player arrives in a room
- `room.exited`  – Player leaves a room

For these events, the context key is `room_id`, whose value is the
Room ID for the room in question.

- `traversal.attempted` – tried using an exit (before any traversal check)
- `traversal.succeeded` – succeeded in an exit traversal check

For these events, the context keys are `exit_id` (the exit ID),
`from_room` (origin room ID), and `to_room` (destination room ID).

- `traversal.failed` – failed in an exit traversal check.  The context
  keys are `exit_id` (the exit ID) and `from_room` (origin room ID).

### Interactions

- `interaction.used` – player tries an interaction with a room/entity.
  The event fires *before* any check is rolled.  The context keys are
  `interaction_id` (the interaction ID), `target_id` (the target room
  or entity ID), and `using_item` (the item ID used, if any).

### Dialogue

- `dialogue.started` – player beings dialogue with an NPC.  The
  context key is `npc_id` (the NPC's entity ID).
  
- `dialogue.ended` – dialogue mode ends.  The context keys are
  `npc_id` (the dialogue NPC's entity ID), and `reason`, which is one
  of the following:

| Reason          | Meaning                                        |
|-----------------|------------------------------------------------|
| `player_left`   | Player moved to another room                   |
| `ends_dialogue` | Player explicitly ended dialogue               |
| `switched_npc`  | Dialogue switched to a different NPC           |
| `stall`         | Conversation stalled and timed out             |
| `room_change`   | NPC could not follow the player into new room  |
| `combat`        | Dialogue ended by start of combat              |
| `triggered`     | A reaction triggered dialogue with another NPC |

### Combat and Encounters

- `combat.started` – Combat begins.  No context keys.

- `combat.ended` – Combat ends.  Context key is `reason`, which should
  be one of the following: `"victory"`, `"defeat"`, or `"fled"`.

- `encounter.branched` – An Encounter Rule selects a success or
  failure branch (not emitted for `result`-only rules).  The context
  keys are `branch` (`"success"` or `"failure"`), and `encounter_id`
  (the source ID of the encounter: the NPC's entity ID for `aggro`
  encounters, or the mechanic ID for encounter mechanics).

### Inventory

- `item.acquired` – An item enters the player's inventory
- `item.lost` – An item leaves the player's inventory

The context keys are `item_id` (the item's entity ID), `count` (item
counts), `source` (for `item.acquired` only; one of `"transfer"`,
`"interaction"`, `"examine"`, or `"unequip"`), and `reason` (for
`item.lost` only; one of `"transfer"`, `"interaction"`, `"destroyed"`,
or `"equip"`).

---

## State-change Events

| Event              | Context keys         | Emitted when             |
|--------------------|----------------------|--------------------------|
| `flag.set`         | `flag_id`            | A flag becomes `true`    |
| `flag.cleared`     | `flag_id`            | A flag becomes `false`   |
| `entity_state.changed`| `entity_id`, `field`, `new_value` | An entity state field changes    |
| `room_state.changed`  | `room_id`, `field`, `new_value`   | A room state field changes       |
| `attitude.changed`    | `npc_id`, `old_value`, `new_value`, `delta` | An NPC's attitude changes |
| `stat.changed`     | `stat_name`, `old_value`, `new_value`, `delta` | A player stat changes  |
| `equipment.changed`| `added?`, `removed?` | Equipped gear changes    |
| `player.damaged`   | `amount`, `new_hp`   | Player HP decreases      |
| `player.healed`    | `amount`, `new_hp`   | Player HP increases      |

These events are **derived once at the end of the turn**, after all
action and reaction effects have been applied. They are dispatched in
a single pass.

As an exception, reaction effects that mutate state do not emit
state-change events *during* dispatch.  They do eventually produce
state-change events, but only after all reactions have finished
dispatching.  This enables patterns like "on dialogue ended, trigger
an encounter".

---

## Player death

| Event         | Context keys | Emitted when                          |
|---------------|--------------|---------------------------------------|
| `player.died` | `new_hp`     | Player HP drops to 0 or below         |

`player.died` fires once per turn pipeline, after all other reactions
have settled (including `turn.end` reactions), whenever the player's HP
is 0 or lower — regardless of the damage source (combat, traps, falls,
or any other `player_damage`).  It is the player's "death moment".

Reactions on `player.died` are **rescue hooks**: after the dispatch
settles, the engine re-checks the player's HP.  If any reaction has
restored HP above 0 (e.g., via `player_heal` in a [Result](corpus.md#result)),
the death is averted and play continues, alongside whatever other
effects the reaction applied (teleporting the player away, setting
flags, etc.).  If the player is still at 0 HP or below, the game ends
with `{ "type": "lose", "trigger": "player_death" }`.

Notes:

- When the player drops to 0 HP in combat, combat ends immediately
  (no further hostile actions that round); `player.died` fires
  afterward.  A rescue therefore also leaves the player out of combat.
- `player.died` does not fire for scripted deaths: an inline
  `game_over` in a [Result](corpus.md#result) is absolute and cannot be
  averted.
- If HP is not tracked (`current_hp` unset, e.g. a statless
  adventure), the check is skipped entirely.

---

## Lifecycle events

| Event | Context | Emitted when |
|---|---|---|
| `adventure.start` | `{}` | First turn of the adventure. Fires once. |
| `turn.start` | `turn_number` | Beginning of each `engine.resolve()` call, after action validation. |
| `turn.end` | `turn_number` | End of `engine.resolve()`, before building `EngineResult`. |

---

## Reaction timing

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

Ordering and loop prevention:

1. Reactions are sorted by `priority` (lower first), then by scope (entity before room before mechanic), then by definition order.
2. State-change events are derived once at the end of the turn from the complete state diff, after all action and reaction effects have been applied. They are dispatched in a single final pass; reactions triggered by that pass may mutate state, but no further state-change events are derived from those mutations.
3. Maximum reaction dispatch recursion depth is 5. Exceeding this stops dispatch with a warning.
4. Only one encounter can fire per turn (from the resolver or from reactions). Subsequent `trigger_encounter` effects are silently ignored.

---

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
