# Soft Items: Design and Implementation

## Overview

**Soft items** refer to generic, nondescript items that exist in the
game world, and can be picked up and/or used by the player, but that
lack special significance.  Examples: rocks, loose stones, and leaves
in a forest.  They are tracked by their generic names (e.g., `rock`).
They contrast with **hard items** — named entities with plot relevance
(e.g., `rusty_key`, `excalibur_sword`).

The soft items subsystem is intended to give the player access to
items that (i) are mentioned in the narration as incidental detail,
but were *not* explicitly modelled in the adventure corpus, or (ii)
aren't mentioned, but ought to exist based on common sense (e.g., hair
on a dog).  However, the subsystem guards against abuses ("I search
the pile of leaves and pick up a wand of wishing").

During the [turn loop](intro.md), LLM Call 1 may propose taking,
giving, or examining one or more previously-unsurfaced soft items.
This is passed by the engine to LLM Call 2, which adjudicates whether
to accept the proposed interaction.  If accepted, the soft item is
introduced into the game world by the engine's post-validation step.

## Where Soft Items Live

### Corpus guidance

Rooms and entities may contain an optional `soft_item_guidance` field,
containing a freeform string that help the LLM know what kinds of
generic objects are plausible in a scene.

```json
{
  "rooms": {
    "axe_head": {
      "soft_item_guidance": "Loose stones, dust, and cobwebs are common here."
    }
  },
  "entities": {
    "rubbish_pile": {
      "type": "feature",
      "soft_item_guidance": "Corks, loose copper pieces, stale food, and lint are plausible."
    }
  }
}
```

This is advisory, *not* an authoritative whitelist.  Whether a
proposed soft item is actually allowed is decided by LLM Call 2 during
adjudication, as explained below.

### Soft State

The player's carried soft items live in `soft_inventory`:

```json
{
  "soft_inventory": ["rock", "cork"]
}
```

Soft items the player has encountered (examined, taken, given) are
tracked in `surfaced_soft_items` as counts per source:

```json
{
  "surfaced_soft_items": {
    "axe_head": { "loose stone": 1 },
    "rubbish_pile": { "cork": 1 },
    "korbar": { "cork": 1 }
  }
}
```

## Interaction Flow

### Examining a Soft Item

```
Player: "I examine the rock."

LLM Call 1 → ExamineAction(target="rock")
         ↓
Engine resolver → "rock" is not a hard room/entity
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="rock", action="examine",
                                        source_id="<current_room>")
                     ])
         ↓
LLM Call 2 → narrates and adjudicates:
             "You examine the rock. It's a smooth, grey stone, small enough
              to fit in your palm." (accepted)
         ↓
Engine post-validation → records surfaced_soft_items["<current_room>"]["rock"] = 1

Subsequent briefings for this room include soft_items=["rock"].
```

Because `ExamineAction` does not carry an entity source, examine proposals
always use the **current room** as `source_id`.

### Picking Up / Taking a Soft Item

```
Player: "I take the cork."

LLM Call 1 → TransferAction(target="rubbish_pile", taken_items=["cork"])
         ↓
Engine resolver → "cork" is not available as a hard item
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="cork", action="take",
                                        source_id="rubbish_pile", count=1)
                     ])
         ↓
LLM Call 2 → narrates and adjudicates acceptance
         ↓
Engine post-validation → adds "cork" to soft_inventory
                       → records surfaced_soft_items["rubbish_pile"]["cork"] = 1
```

### Giving a Soft Item

```
Player: "I give the cork to Korbar."

LLM Call 1 → TransferAction(target="korbar", given_items=["cork"])
         ↓
Engine resolver → "cork" is in soft_inventory
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="cork", action="give",
                                        source_id="<current_room>",
                                        target_id="korbar", count=1)
                     ])
         ↓
LLM Call 2 → narrates and adjudicates acceptance
         ↓
Engine post-validation → removes "cork" from soft_inventory
                       → records surfaced_soft_items["korbar"]["cork"] = 1
```

## Carried Soft Items

Soft items in the player's inventory are surfaced through
`PlayerStateBriefing.soft_inventory`. This is separate from room/entity
surfacing — the player always sees what they're carrying via the player state
block in the GMBriefing.

## Adjudication Model

`SoftItemProposal` objects carry:

| Field       | Description |
|-------------|-------------|
| `item_name` | The soft item name proposed by the player. |
| `action`    | `"examine"`, `"take"`, or `"give"`. |
| `source_id` | Room or entity ID where the item is proposed to exist. |
| `target_id` | For `"give"`, the recipient entity ID. |
| `count`     | Quantity (default 1). |

LLM Call 2 responds with `SoftItemAdjudication` objects in `NarrationOutput`:

| Field       | Description |
|-------------|-------------|
| `item_name` | Matches the proposal. |
| `action`    | Matches the proposal. |
| `accepted`  | `true` if the narrator agrees the item exists/did the thing. |
| `source_id` | Must match the proposal's `source_id`. |
| `target_id` | For `"give"`, must match the proposal's `target_id`. |
| `count`     | Must match the proposal's `count`. |

The engine's post-validation step:

1. Matches each adjudication to a proposal by `(item_name, action, source_id,
   target_id, count)`.
2. Verifies the proposal source/target is a valid room or entity in the corpus.
3. Ensures `"take"` adjudications do not collide with a hard entity ID.
4. Applies the accepted change: mutates `soft_inventory`, updates
   `surfaced_soft_items` counts, and records rejection reasons for mismatches.

## Key Design Decisions

### 1. No Unique IDs

Soft items are identified by their general name only. Two "rock" entries in
`soft_inventory` are indistinguishable. This is intentional — soft items are
narrative props, not mechanical objects.

### 2. Counts Are Tracked

`surfaced_soft_items` stores counts so repeated takes or gives are reflected
accurately. The Context Assembler formats surfaced items as `name (taken N)`
when building the GMBriefing.

### 3. LLM as Adjudicator

The engine no longer rejects soft-item actions for being "not in the corpus."
Instead, it issues proposals and lets LLM Call 2 decide what exists in the
scene. This prevents the engine from blocking plausible player actions (e.g.,
"I pick up a pebble") while still giving the narrator authority over the world.

### 4. Engine Still Validates Structure

The engine rejects adjudications that:

- Do not match a proposal.
- Reference an unknown room or entity.
- Attempt to "take" an item whose name collides with a hard entity ID.
- Propose state mutations without a matching proposal.

## Files Summary

| File | Role |
|------|------|
| `schema/corpus.md` | Defines `soft_item_guidance` fields on rooms and entities. |
| `schema/soft-state.md` | Documents `soft_inventory` and `surfaced_soft_items` fields. |
| `schema/actions.md` | Documents soft-item proposals and adjudications for `examine`, `transfer`, and narration output. |
| `mgmai/models/corpus.py` | Pydantic models: `Room.soft_item_guidance`, `Entity.soft_item_guidance`. |
| `mgmai/models/briefing.py` | Pydantic models: `BriefingRoom.soft_item_guidance`, `BriefingEntity.soft_item_guidance`. |
| `mgmai/models/soft_state.py` | Pydantic model: `SoftGameState.surfaced_soft_items` as `dict[str, dict[str, int]]`. |
| `mgmai/models/actions.py` | Pydantic models: `SoftItemProposal`, `EngineResult.soft_item_proposals`. |
| `mgmai/models/narration.py` | Pydantic model: `SoftItemAdjudication`, `NarrationOutput.soft_item_adjudications`. |
| `mgmai/engine/resolver.py` | Issues soft-item proposals in `resolve_examine` and `resolve_transfer`. |
| `mgmai/engine/engine.py` | Persists surfaced items; populates `_build_room_after` with surfaced items. |
| `mgmai/engine/post_validate.py` | Validates and applies soft-item adjudications. |
| `mgmai/context/assembler.py` | Populates `BriefingRoom.soft_items` and `BriefingEntity.soft_items` from surfaced items. |
| `mgmai/game/loop.py` | Passes adjudications to post-validation. |
| `doc/soft-items.md` | This document. |


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
