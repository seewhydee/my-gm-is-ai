# Soft Items: Design and Implementation

## Overview

Soft items are generic, nondescript objects that exist in the game world without
unique identifiers or mechanical significance. Examples: rocks, loose stones,
dust, cobwebs, cork, lint. They contrast with **hard items** — named entities
with IDs, hard-state tracking, and plot relevance (e.g., `rusty_key`,
`toenail_sword`).

## Why "Soft"?

The term reflects the relationship to the **hard/soft state** split:

- **Hard items** are tracked in `HardGameState.player.inventory` as entity IDs.
  Moving them requires `HardStateChanges`. The engine is the sole authority.
- **Soft items** are tracked in `SoftGameState.soft_inventory` as plain strings.
  The LLM proposes additions/removals via `SoftStatePatch`, and the engine
  validates them.

This split serves two purposes:

1. **Context efficiency.** The corpus may define dozens of plausible soft items
   per room (dust, pebbles, etc.). Surfacing all of them in the GMBriefing
   wastes tokens without benefit.
2. **Narrative flexibility.** The LLM can reference soft items naturally ("I
   pick up a rock") without requiring the author to pre-define every possible
   interaction. The engine validates against the corpus; the LLM's common sense
   fills the gap.

## Where Soft Items Live

### Corpus

Rooms and entities declare soft items in the corpus (`schema/corpus.md`):

```json
{
  "rooms": {
    "axe_head": {
      "soft_items": ["loose stone", "dust"]
    }
  },
  "entities": {
    "rubbish_pile": {
      "type": "feature",
      "soft_items": ["cork", "loose copper", "stale sandwich", "lint"]
    }
  }
}
```

These lists are the **authoritative source of truth** for what exists. The
engine validates every soft-item action against them.

### Soft State

The player's carried soft items live in `soft_inventory`:

```json
{
  "soft_inventory": ["rock", "cork"]
}
```

Soft items that the player has encountered (examined, taken, given) are tracked
in `surfaced_soft_items`:

```json
{
  "surfaced_soft_items": {
    "axe_head": ["loose stone"],
    "rubbish_pile": ["cork"],
    "korbar": ["cork"]
  }
}
```

See `schema/soft-state.md` for the full schema.

## Design Evolution

### Phase 1 (Initial): Full Enumeration

The initial design surfaced all corpus `soft_items` in the GMBriefing. Every
room and entity carried its full list. This caused:

- **Context pollution.** The LLM read "loose stone, dust, rock, dense webbing,
  sticky webbing" in every briefing, most of which were never relevant.
- **Token waste.** A typical room might have 2-5 soft items, but across
  entities the total could reach 10+ irrelevant strings per briefing.

### Phase 2 (Current): Surface-on-Interaction

Soft items are omitted from the GMBriefing by default. Only items the player
has interacted with (through `examine`, `transfer`, or `interact` actions)
appear in subsequent briefings.

The algorithm:

1. Player submits an action targeting a soft item (e.g., "examine rock").
2. The engine's resolver validates the action against the corpus `soft_items` list.
3. On success, the resolver returns a `surfaced_soft_items` map in the
   `ResolutionResult`.
4. The engine persists these entries into `SoftGameState.surfaced_soft_items`.
5. The Context Assembler reads `surfaced_soft_items` when building the
   GMBriefing, populating `BriefingRoom.soft_items` and
   `BriefingEntity.soft_items`.

This ensures:

- **Zero context waste** for untouched items.
- **Informed LLM decisions** for items the player has seen.
- **Deterministic engine validation** against the full corpus list regardless
  of what's surfaced.

## Interaction Flow

### Examining a Soft Item

```
Player: "I examine the rock."

LLM Call 1 → ExamineAction(target="rock")
         ↓
Engine resolver → validates "rock" ∈ all_soft for current room
                → on success: surfaces "rock" on the room/entity it belongs to
                → returns ResolutionResult(success=True, surfaced_soft_items={...})
         ↓
LLM Call 2 → narrates: "You examine the rock. It's a smooth, grey stone,
              small enough to fit in your palm."

Subsequent briefings for this room include soft_items=["rock"].
```

### Picking Up / Taking a Soft Item

```
Player: "I take the cork."

LLM Call 1 → TransferAction(target="rubbish_pile", taken_items=["cork"])
         ↓
Engine resolver → validates "cork" ∈ available_pool (rubbish_pile.soft_items)
                → adds "cork" to hard_changes.inventory_added
                → surfaces "cork" on rubbish_pile
                → surfaces "cork" on target if given
         ↓
Engine (post-resolution) → applies inventory changes
                         → persists surfaced items
         ↓
LLM Call 2 → narrates: "You pick up a cork from the pile."
```

### Giving a Soft Item

```
Player: "I give the cork to Korbar."

LLM Call 1 → TransferAction(target="korbar", given_items=["cork"])
         ↓
Engine resolver → validates "cork" ∈ soft.soft_inventory
                → creates soft_patch: soft_inventory_remove("cork")
                → surfaces "cork" on "korbar"
         ↓
Subsequent briefings → korbar.soft_items=["cork"]
```

## Carried Soft Items

Soft items in the player's inventory are surfaced through
`PlayerStateBriefing.soft_inventory`. This is separate from room/entity
surfacing — the player always sees what they're carrying via the player state
block in the GMBriefing.

## Key Design Decisions

### 1. No Unique IDs

Soft items are identified by their general name only. Two "rock" entries in
`soft_inventory` are indistinguishable. This is intentional — soft items are
narrative props, not mechanical objects.

### 2. No Garbage Collection (Yet)

Surfaced items accumulate but are never removed by the engine. If the player
examines "dust" in a room, it stays surfaced for the rest of the game. Future
work might add pruning (e.g., clearing surfaced items when the player leaves a
room for good), but the current design prioritises simplicity.

### 3. Engine as Gatekeeper

The corpus `soft_items` list remains the authoritative truth for validation,
regardless of what is surfaced. The LLM cannot conjure "Wand of Wishing" even
if all soft items are omitted from the briefing. The engine rejects invalid
items, and LLM Call 2 narrates the failure naturally ("You search but find no
such thing").

### 4. LLM Common Sense

The LLM does not need the full soft-items list to propose plausible actions.
If the player says "I pick up a rock in this cave," the LLM can construct
`TransferAction(target="<cave_room>", taken_items=["rock"])` using world
knowledge. The engine then validates against the corpus — if the cave has
"rock" in its `soft_items`, it succeeds; if not, the narrator explains why.

## Files Summary

| File | Role |
|------|------|
| `schema/corpus.md` | Defines `soft_items` fields on rooms and entities. |
| `schema/soft-state.md` | Documents `soft_inventory` and `surfaced_soft_items` fields. |
| `schema/actions.md` | Documents soft-item validation for `examine`, `interact`, `transfer`. |
| `mgmai/models/corpus.py` | Pydantic models: `Room.soft_items`, `Entity.soft_items`. |
| `mgmai/models/briefing.py` | Pydantic models: `BriefingRoom.soft_items`, `BriefingEntity.soft_items`. |
| `mgmai/models/soft_state.py` | Pydantic models: `SoftGameState.surfaced_soft_items`. |
| `mgmai/engine/resolver.py` | Soft-item validation and surfacing in `resolve_examine`, `resolve_transfer`. |
| `mgmai/engine/engine.py` | Persists surfaced items; populates `_build_room_after` with surfaced items. |
| `mgmai/context/assembler.py` | Populates `BriefingRoom.soft_items` and `BriefingEntity.soft_items` from surfaced items. |
| `doc/soft-items.md` | This document. |


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
