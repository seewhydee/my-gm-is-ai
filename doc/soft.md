# The Soft State System

The **soft state system** lets the AI GM track aspects of game state
that are not strictly mechanical, such as tweaks to the environment,
or moving/using generic items found in the game world.  Unlike hard
state, which is managed rigorously by the engine only, soft state is
co-managed by the LLM and the engine.

We let the LLM co-manage soft state for flexibility.  For instance,
the player may interact with items that were narrated as incidental
detail but weren't modelled in the adventure corpus, or items that
simply ought to exist based on common sense (e.g., hair on a dog).  At
the same time, we place safeguards against abuse ("I search the leaves
and pick up a wand of wishing").

The system has two parts: **soft state notes**, and **soft items**.

- **Soft State Notes** – During the [turn loop](intro.md), LLM Call 2
  checks if the turn's outcome warrants recording a note about a room
  or corpus-defined entity (feature, item, or NPC).  If so, it writes
  a `SoftStateNote` object, which goes in the `NarrationOutput`'s
  `soft_state_notes` array (see [Action schema](../schema/actions.md)).

  Each `SoftStateNote` attaches to the present room, or an entity in
  that room (or the player entity, for global notes).  The engine
  validates it during post-validation, applying a simple schema (e.g.,
  can't attach notes to entities not in the present room); after
  passing, the note is included in future GM briefings.

- **Soft Items** – These are nondescript items that can be picked up,
  dropped, and/or used by the player.  Examples: rocks, loose stones,
  and leaves in a forest.  They lack distinguishing features (tags,
  state fields, etc.), and are identified by generic names (e.g.,
  `rock`, `dog hair`), unlike corpus-defined **hard items** (which
  have snake_case IDs like `old_key`, `excalibur_sword`).

  In each turn, LLM Call 1 may interpret the player's actions as
  taking, giving, or examining one or more soft items.  If so, the
  engine passes the proposal to LLM Call 2, which adjudicates whether
  to accept the proposed interaction.  If accepted, the soft item can
  be instantiated.  Soft items can be put in the player's "soft
  inventory", or in corpus-defined rooms or entities.

Relatedly, we also use LLM Call 2 to track and manage what NPCs
remember of their conversations with the player, and any plot-relevant
bits of information gleaned during conversation.  These mechanisms are
described separately, in the [NPC docs](npcs.md).

## Soft State Notes

The game tracks soft state notes as arrays of freeform strings, keyed
to each room or entity (feature, item, or NPC) ID:

```json
{
  "manor_courtyard": [
    "Player swept the leaves into a pile in the center",
    "Player counted the trees: there are exactly 12"
  ]
}
```

These notes come from the optional `soft_state_notes` array in the
`NarrationOutput` emitted by LLM Call 2.  Here is an example of a
room-note (which carries no room identifier — the engine attaches it
automatically to the current room):

```json
{
  "field": "room_note",
  "new_value": "Player counted the trees: there are exactly 12",
  "reason": "Player looked around the courtyard and specifically counted the number of trees"
}
```

Multiple notes can be generated each turn, at the LLM's discretion.
Notes may target only:

- the **current room** (via `room_note`), or
- an **entity present in the current room**, including entities nested
  inside containers, and following NPCs (via `entity_note`), or
- the **player entity** (`entity_id: "player"`), for global
  observations that should follow the player across rooms.

Any proposed note not following this rule is rejected by the engine.
For the patch format and validation rules,see the
[Soft State schema](../schema/soft-state.md).

## Soft Items

Each soft item is identified by its generic name, which can optionally
have spaces (e.g., "rock", "dog hair").  Identically-named soft items
(e.g. two "rock"s) are indistinguishable.

### Corpus guidance

In the game's corpus, rooms and entities may contain an optional
`soft_item_guidance` field, containing a freeform string that suggests
what kinds of generic contents are plausible.  This is advisory, *not*
an authoritative whitelist.

```json
{
  "rooms": {
    "outer_courtyard": {
	  "soft_item_guidance": "leaf, pebble, stick"
    }
  }
}
```

### Tracking soft items

Soft items are tracked in three data structures:

- `soft_inventory` lists the soft items carried by the player.

- `soft_items_taken` is an extraction ledger specifying the number of
  soft items taken from each source (rooms and entities).

- `soft_contents` tracks the current placement of soft items the
  player has put in each room or entity.  These lists are incremented
  on accepted gives, decremented on retrieval, and pruned at zero.

The Context Assembler includes these in the GMBriefing; for details,
see the [Soft State schema](../schema/soft-state.md).

## Surfacing a Soft Item

When the engine receives an `examine` or `transfer` (retrieval) action
involving an uninstantiated soft item (one that does not match any
entity ID, nor any existing soft item), it generates a **soft item
proposal** and passes it to LLM Call 2 for adjudication.  If this
proposal is accepted by LLM Call 2,

- For `examine`, LLM Call 2 proceeds to incorporate the soft item into
  the narration, *without* instantiating it in soft state.  If the
  examination establishes a durable fact the player may return to, LLM
  Call 2 should record it via a soft state note.

- For `transfer` (retrieval of a non-preexisting soft item), LLM Call
  2 proceeds to narrate the player taking the soft item.  During the
  [post-validation step](../schema/actions.md), the engine
  instantiates the soft item by mutating the trackers
  `soft_inventory`, `soft_items_taken`, and `soft_contents`.

For `transfer` actions involving an existing soft item, see the next
section.

### Examples

Examining a soft item:

```
Player: "I examine the rock."

LLM Call 1 → ExamineAction(target="rock")
         ↓
Engine resolver → "rock" is not a hard room/entity
                → returns ResolutionResult(success=True,
                     soft_item_proposals=[
                       SoftItemProposal(item_name="rock",
						   action="examine",
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

Taking a soft item from a feature:

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

## Moving Soft Items

Once instantiated, soft items can be transferred mechanically to
different locations.  Each `examine` or `transfer` action consults the
relevant inventories of soft items (e.g., `soft_inventory` for soft
items carried by the player); if the specified soft item is found, the
action is proceeds mechanically without the instantiation procedure
described in the preceding section.

Note that `transfer` actions can still be gated by the usual game
mechanisms.  For example, an item inside a closed container entity
cannot be retrieved, and transfers involving a living NPC are deferred
to LLM Call 2, which adjudicates whether the NPC consents.

### Examples

Giving a soft item to an NPC:

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

Placing a soft item on the floor of the room:

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

## Files Summary

| File | Role |
|------|------|
| `schema/corpus.md` | Defines `soft_item_guidance` fields on rooms and entities. |
| `schema/soft-state.md` | Documents the full soft-state schema: `soft_inventory`, `room_notes`, `entity_notes`, `soft_items_taken`, `soft_contents`, and the `SoftStatePatch` / `SoftStateNote` references. |
| `schema/actions.md` | Documents soft-item proposals and adjudications for `examine`, `transfer`, and narration output. |
| `mgmai/models/corpus.py` | Pydantic models: `Room.soft_item_guidance`, `Entity.soft_item_guidance`. |
| `mgmai/models/briefing.py` | Pydantic models: `BriefingRoom.soft_item_guidance`, `BriefingEntity.soft_item_guidance`, and the `soft_items_taken` / `soft_items_present` briefing fields. |
| `mgmai/models/soft_state.py` | Pydantic models: `SoftGameState` (incl. `soft_items_taken`, `soft_contents`, `room_notes`, `entity_notes`), `SoftStatePatch`, and `SoftStateNote`. |
| `mgmai/models/actions.py` | Pydantic models: `SoftItemProposal`, `EngineResult.soft_item_proposals`, `EngineResult.soft_content_takes`; `PlayerAction.soft_state_patches`. |
| `mgmai/models/narration.py` | Pydantic model: `SoftItemAdjudication`, `NarrationOutput.soft_item_adjudications`, `NarrationOutput.soft_state_notes`. |
| `mgmai/engine/utils.py` | `present_entity_ids(hard, corpus)` — the shared helper for "entities present in the current room" (direct, nested, and following NPCs); used by the note validator. |
| `mgmai/engine/resolver.py` | Issues soft-item proposals in `resolve_examine` and `resolve_transfer`; resolves mechanical retrievals from `soft_contents` into `ResolutionResult.soft_content_takes`. |
| `mgmai/engine/engine.py` | Applies `soft_content_takes` (decrementing `soft_contents`, appending to `soft_inventory`) and copies them onto `EngineResult.soft_content_takes`; validates and applies `soft_state_patches` via `_validate_soft_patches`; populates `_build_room_after` with taken/present items. |
| `mgmai/engine/post_validate.py` | Validates and applies soft-item adjudications; validates `soft_state_notes` via `post_validate_notes`. |
| `mgmai/context/assembler.py` | Populates `BriefingRoom`/`BriefingEntity` `soft_items_taken` and `soft_items_present`, plus `room_notes`/`entity_notes` and player entity notes. |
| `mgmai/game/loop.py` | Passes adjudications and notes to post-validation. |
| `doc/soft.md` | This document. |


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
