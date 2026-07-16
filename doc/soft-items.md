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
giving, or examining one or more soft items that are not represented
by hard entities.  The engine passes the proposal to LLM Call 2, which
adjudicates whether to accept the proposed interaction.  Accepted
takes and gives update the player's `soft_inventory` and the tracking
fields described below; accepted examines affect narration only.

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

Two further fields track soft items in the world, each with a single
meaning.  `soft_items_taken` is a pure **extraction ledger**, written
only on accepted takes of ambient soft items:
`soft_items_taken[source_id][item_name] = N` means exactly "the player
has extracted N of `item_name` from `source_id`".  Every count is ≥ 1.

```json
{
  "soft_items_taken": {
    "axe_head": { "loose stone": 1 },
    "rubbish_pile": { "cork": 2 }
  }
}
```

`soft_contents` tracks the **current placement** of soft items the
player has given, placed, or dropped, keyed by the room or entity ID
now holding them.  It is incremented on accepted gives and decremented
when placed items are retrieved; zero-count entries (and emptied
parent entries) are pruned.

```json
{
  "soft_contents": {
    "korbar": { "cork": 1 },
    "bag_floor": { "rock": 2 }
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
Engine post-validation → records the adjudication for audit;
                         NO soft-state mutation
```

Accepted examine adjudications affect narration only — they write no
soft-item state.  If an examine establishes a durable fact the player
may return to, LLM Call 1 should record it via a `room_note` or
`entity_note` patch (see `schema/soft-state.md`).

Because `ExamineAction` does not carry an entity source, examine proposals
always use the **current room** as `source_id`.

### Picking Up / Taking a Soft Item

```
Player: "I take the cork."

LLM Call 1 → TransferAction(target="rubbish_pile", taken_items=["cork"])
         ↓
Engine resolver → "cork" is not available as a hard item, and is not
                  placed in soft_contents["rubbish_pile"]
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="cork", action="take",
                                        source_id="rubbish_pile", count=1)
                     ])
         ↓
LLM Call 2 → narrates and adjudicates acceptance
         ↓
Engine post-validation → adds "cork" to soft_inventory
                       → records soft_items_taken["rubbish_pile"]["cork"] = 1
```

### Giving, Placing, or Dropping a Soft Item

```
Player: "I give the cork to Korbar."

LLM Call 1 → TransferAction(target="korbar", given_items=["cork"])
         ↓
Engine resolver → "cork" is in soft_inventory
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="cork", action="give",
                                        source_id="player",
                                        target_id="korbar", count=1)
                     ])
         ↓
LLM Call 2 → narrates and adjudicates acceptance
         ↓
Engine post-validation → removes "cork" from soft_inventory
                       → records soft_contents["korbar"]["cork"] = 1
```

Give proposals always use `source_id="player"` — the item comes out of
the player's own `soft_inventory`.  The `target_id` may be an entity ID
(a give or placement) or a **room ID**, which is a drop:

```
Player: "I drop the rock."

LLM Call 1 → TransferAction(target="bag_floor", given_items=["rock"])
         ↓
Engine resolver → proposal (give, source_id="player",
                            target_id="bag_floor", count=1)
         ↓
LLM Call 2 → narrates and adjudicates acceptance
         ↓
Engine post-validation → removes "rock" from soft_inventory
                       → records soft_contents["bag_floor"]["rock"] = 1
```

Accepted gives never touch `soft_items_taken` — placing an item is not
extracting one.

### Retrieving a Placed Soft Item

Takes consult `soft_contents` before falling back to an ambient take
proposal.  Items in `soft_contents` came out of the player's own
`soft_inventory` via an accepted give, so their existence is
mechanically verified — no adjudication of *existence* is needed.  All
`soft_contents` lookups normalize names (via `_normalize_item_name`), so
"the Stone" matches a stored "stone".

- **From a room or non-NPC entity, retrieval is mechanical.**  The
  resolver satisfies the take directly, with no Call 2 adjudication.
  It records the retrieval in `ResolutionResult.soft_content_takes`
  (source → name → count); the engine decrements `soft_contents`
  (pruning zero-count and emptied parent entries), appends the items
  to `soft_inventory`, and copies the record onto
  `EngineResult.soft_content_takes` so Call 2 can narrate the
  retrieval.
- **From an NPC, Call 2 adjudicates consent.**  The resolver emits a
  normal take proposal; Call 2 sees the item in the NPC's
  `soft_items_present` and decides whether the NPC parts with it.
- **Closed containers gate retrieval.**  A placed item inside a closed
  container entity cannot be retrieved: the take fails with the same
  "The X is closed." error a hard item would produce.
- **Room-targeted takes search the room's entities.**  If the take
  targets the room but the item rests on an entity, the resolver
  searches the room's entities' `soft_contents` before going ambient;
  an item found only inside a closed container yields the closed error.
- **Shortfall splits the take.**  If the requested count exceeds the
  placed count, the placed portion is satisfied as above and only the
  remainder becomes an ambient take proposal.

A unified post-validation rule keeps the extraction ledger clean:
every accepted take decrements `soft_contents[source]` first; only the
remainder increments `soft_items_taken[source]`.  Retrieving your own
stone is not extraction.

## Carried Soft Items

Soft items in the player's inventory are surfaced through
`PlayerStateBriefing.soft_inventory`. This is separate from the room/entity
`soft_items_taken` and `soft_items_present` fields — the player always sees
what they're carrying via the player state block in the GMBriefing.

## Adjudication Model

`SoftItemProposal` objects carry:

| Field       | Description |
|-------------|-------------|
| `item_name` | The soft item name proposed by the player. |
| `action`    | `"examine"`, `"take"`, or `"give"`. |
| `source_id` | Room or entity ID where the item is proposed to exist; `"player"` for gives. |
| `target_id` | For `"give"`, the recipient entity ID or room ID (a drop). |
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
2. Verifies the proposal source/target is a valid room or entity in the corpus
   (or `"player"` as a give source).
3. Ensures `"take"` adjudications do not collide with a hard entity ID.
4. Applies the accepted change: mutates `soft_inventory`, updates
   `soft_items_taken` and `soft_contents`, and records rejection reasons
   for mismatches.  Accepted examines have no state effect.

## Key Design Decisions

### 1. No Unique IDs

Soft items are identified by their general name only. Two "rock" entries in
`soft_inventory` are indistinguishable. This is intentional — soft items are
narrative props, not mechanical objects.

### 2. Extraction Counts Are Tracked; Placement Is Tracked Separately

`soft_items_taken` records how many times each soft item has been taken from
each source. It is written only by accepted takes, so every count is a
completed extraction — a clean depletion signal for LLM Call 2. Placement is
a different kind of fact — current state, not history — and lives in
`soft_contents`, from which placed items can later be retrieved. The Context
Assembler formats the two as `name (taken N)` and `name xN` respectively
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
| `schema/soft-state.md` | Documents `soft_inventory`, `soft_items_taken`, and `soft_contents` fields. |
| `schema/actions.md` | Documents soft-item proposals and adjudications for `examine`, `transfer`, and narration output. |
| `mgmai/models/corpus.py` | Pydantic models: `Room.soft_item_guidance`, `Entity.soft_item_guidance`. |
| `mgmai/models/briefing.py` | Pydantic models: `BriefingRoom.soft_item_guidance`, `BriefingEntity.soft_item_guidance`, and the `soft_items_taken` / `soft_items_present` briefing fields. |
| `mgmai/models/soft_state.py` | Pydantic model: `SoftGameState.soft_items_taken` and `SoftGameState.soft_contents` as `dict[str, dict[str, int]]`. |
| `mgmai/models/actions.py` | Pydantic models: `SoftItemProposal`, `EngineResult.soft_item_proposals`, `EngineResult.soft_content_takes`. |
| `mgmai/models/narration.py` | Pydantic model: `SoftItemAdjudication`, `NarrationOutput.soft_item_adjudications`. |
| `mgmai/engine/resolver.py` | Issues soft-item proposals in `resolve_examine` and `resolve_transfer`; resolves mechanical retrievals from `soft_contents` into `ResolutionResult.soft_content_takes`. |
| `mgmai/engine/engine.py` | Applies `soft_content_takes` (decrementing `soft_contents`, appending to `soft_inventory`) and copies them onto `EngineResult.soft_content_takes`; populates `_build_room_after` with taken/present items. |
| `mgmai/engine/post_validate.py` | Validates and applies soft-item adjudications. |
| `mgmai/context/assembler.py` | Populates `BriefingRoom`/`BriefingEntity` `soft_items_taken` and `soft_items_present`. |
| `mgmai/game/loop.py` | Passes adjudications to post-validation. |
| `doc/soft-items.md` | This document. |


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
