# Design: Soft-Item State Split — Extraction Ledger + Content Tracking

## 1. Preamble: The Issue

The revamped soft-items subsystem (`doc/soft-items.md`) tracks
player-encountered soft items in a single soft-state field,
`surfaced_soft_items: dict[room_or_entity_id, dict[item_name, count]]`.
Review of the implementation shows this one field is currently asked to
carry **three different meanings at once**, and fails to carry a fourth
meaning we actually need:

1. **Extraction counts (the load-bearing use).**  Accepted takes
   increment a count on the source (`post_validate.py`).  The prose
   template (`prose.j2` §Soft Item Adjudication) explicitly instructs
   Call 2 to read these `(taken N)` counts as a *depletion* signal —
   the anti-farming guard promised in `doc/soft-items.md`.  This is the
   only structured, non-evictable record of how many times a soft item
   has been extracted from a source (turn history and notes are capped
   at 5 entries each).

2. **Examine records (semantically muddy).**  Accepted examines write a
   count-0 entry attributed to the *current room* — `ExamineAction`
   carries no source, so "I examine the lint on the rubbish pile"
   surfaces `lint` on the room, not the pile.  These entries are never
   evicted or decremented, so they clutter briefings without bound and
   assert stale presence (examine a quill → room claims a quill forever,
   even after it is taken from the desk).  The information they preserve
   is the weakest possible (a bare name); the *valuable* part of an
   examine — the established description — is discarded, and is anyway
   the job of the `room_note`/`entity_note` channel, which is already
   used when the player examines feature entities and soft room
   features.

3. **Give records (semantically wrong).**  Accepted gives increment the
   *same* counter on the *target* (`post_validate.py`).  Give a cork to
   Korbar and future briefings show Korbar with `"cork (taken 1)"` —
   which Call 2 is instructed to read as *depletion of Korbar*.  The
   depletion signal is actively corrupted by gives, and nothing records
   the true fact ("Korbar now has the cork").

4. **Missing: content tracking.**  There is no representation of where
   placed soft items currently are.  "I put the stone on the table"
   is recorded only as a bogus take-count on the table; "I drop the
   stone" (room target) is structurally *rejected*, because
   `resolve_transfer` builds room-targeted give proposals with
   `target_id=None` (`resolver.py`) and post-validation rejects gives
   without a valid entity target (`post_validate.py`).  The only
   workaround is a `soft_inventory_remove` patch plus a freeform room
   note — unstructured, uncountable, and evicted after 5 notes.

In addition, two further defects survive from the pre-revamp design:

- A **dead code path**: `ResolutionResult.surfaced_soft_items`
  (`resolver.py`) is only ever populated by `_fire_on_examine_events`,
  which accumulates it from nested `_resolve_interaction` results that
  never set the field.  The merge loop in `engine.py` (step 5, "persist
  surfaced items") therefore always iterates an empty dict.
- A **latent multi-take bug**: `resolve_transfer` rejects `count > 1`
  for any item not tagged stackable in the corpus, and `_is_stackable`
  (`engine/utils.py`) treats unknown names as non-stackable — i.e.
  every soft item.  "Take 2 stones" therefore fails outright today,
  before any soft-item handling.  The retrieval design below requires
  multi-count soft takes, so the guard must be relaxed for soft item
  names (§4.5).

**The plan: split the field into two single-purpose structures.**

- `soft_items_taken` — a pure *extraction ledger*: written only on
  accepted takes of ambient items.  `soft_items_taken[source][name] = N`
  means exactly "the player has extracted N of *name* from *source*."
- `soft_contents` — *current placement* of soft items the player has
  given, placed, or dropped: incremented on accepted gives (including
  room targets, which become legal), decremented when placed items are
  retrieved.

Examines no longer write soft-item state at all; durable examine facts
route through the existing note channel.  The dead code path is
deleted.

## 2. Design Rationale

### 2.1 Take-only surfacing

The examine round-trip (proposal → adjudication) is **kept**: it is the
channel that tells Call 2 "the player is examining an unverified item —
decide whether it exists and narrate accordingly."  What is removed is
only the *state write* on acceptance.  Justification:

- Call 1 is already told not to predict presence from surfaced lists
  (`ruling.j2` §Soft Items: "Do not try to predict which items are
  present; propose what the player's input asks for... trust the
  narrator to adjudicate"), so a later take does not mechanically need
  the examine record.
- Call 2 default-accepts mundane, setting-appropriate items, so an
  examine-then-take sequence re-accepts on fresh adjudication.
- Short-term continuity is covered by `turn_history` (5 turns).
  Durable continuity, where it matters, belongs in
  `room_notes`/`entity_notes` — with the description intact, the source
  correctly attributed, and 5-entry eviction.  `ruling.j2` gains a line
  of guidance to this effect (§6.2).
- Rejected examines were never recorded, so no regression there.

With takes as the only writer, every entry has count ≥ 1, the
`(taken N)` display becomes uniform, and the depletion guidance in
`prose.j2` becomes literally true of the data.

### 2.2 Content tracking as a separate structure

Placement is a different kind of fact from extraction: it is *current
state*, requiring increment and decrement, whereas the extraction ledger
is a monotonic history.  Folding both into one counter is what produced
the give-corruption above.  `soft_contents` mirrors the hard-state
containment maps (`room_contains` / `entity_contains`) in shape, but for
name-keyed soft items:

```json
{
  "soft_contents": {
    "table":     { "stone": 1 },
    "korbar":    { "cork": 1 },
    "bag_floor": { "rock": 2 }
  }
}
```

A key property: items in `soft_contents` have **mechanically verified
existence** — they came out of the player's own `soft_inventory` via an
accepted give.  Retrieving them therefore does not need narrative
adjudication of *existence* (though NPC consent still does; see §4.4).

## 3. Schema Changes

### 3.1 `SoftGameState` (`mgmai/models/soft_state.py`)

| Field | Change |
|-------|--------|
| `surfaced_soft_items` | **Renamed** to `soft_items_taken` (`Dict[str, Dict[str, int]]`, default `{}`).  Semantics: accepted ambient takes only. |
| `soft_contents` | **New** (`Dict[str, Dict[str, int]]`, default `{}`).  Keyed by room or entity ID; values map soft item names to current counts.  Counts are always ≥ 1; zero-count entries (and emptied parent entries) are pruned.  Keys are stored verbatim from give adjudications; all lookups normalize via `_normalize_item_name` (§4.4). |

No changes to `SoftItemProposal` / `SoftItemAdjudication` shapes.  The
only behavioural schema change is that a give proposal's `target_id`
may now be a **room ID** (a drop) as well as an entity ID.

### 3.2 Briefing models (`mgmai/models/briefing.py`)

`BriefingRoom.soft_items` and `BriefingEntity.soft_items` are replaced
by two fields each:

| Field | Contents | Format |
|-------|----------|--------|
| `soft_items_taken` | from `soft.soft_items_taken[id]` | `"cork (taken 2)"` |
| `soft_items_present` | from `soft.soft_contents[id]` | `"stone x1"` |

`PlayerStateBriefing.soft_inventory` is unchanged.

### 3.3 `EngineResult` (`mgmai/models/actions.py`)

New field `soft_content_takes: Dict[str, Dict[str, int]]` (default
`{}`) — source → name → count for placed soft items mechanically
retrieved this turn (§4.4).  This is Call 2's *explicit* signal that a
retrieval happened: the `EngineResult` is Call 2's only view of engine
outcomes, and without the field a mechanical retrieval would be
visible only by diffing `room_after` against the pre-turn briefing.

## 4. Flow Changes

### 4.1 Examine (state write removed)

```
Player: "I examine the rock."

Call 1 → ExamineAction(target="rock")
       → may attach a room_note patch if the examine establishes a
         durable fact (see §6.2)
Resolver → soft proposal (examine, source_id=<current room>)   [unchanged]
Call 2 → adjudicates; accepted → narrates the rock              [unchanged]
Post-validation → validates + records the adjudication in
         soft_items_accepted (audit only); NO soft-state mutation
```

The examine branch in `post_validate_soft_items` (`post_validate.py`,
the `elif adj.action == "examine"` block) is deleted.  All other
validation rules (proposal matching, hard-entity collision, etc.)
remain.

### 4.2 Take of an ambient item (unchanged except field name)

```
Player: "I take the cork from the pile."

Resolver → cork not a hard item, not in soft_contents["rubbish_pile"]
         → proposal (take, source_id="rubbish_pile", count=1)
Call 2 → adjudicates (consults soft_items_taken counts for depletion)
Post-validation (accepted) → soft_inventory += "cork"
                           → soft_items_taken["rubbish_pile"]["cork"] += 1
```

### 4.3 Give / place / drop

```
Player: "I put the stone on the table."      (table = feature entity)
Call 1 → TransferAction(target="table", given_items=["stone"])
Resolver → stone in soft_inventory
         → proposal (give, source_id="player", target_id="table")
Call 2 → adjudicates (can the stone rest there? does the NPC accept?)
Post-validation (accepted) → soft_inventory -= "stone"
                           → soft_contents["table"]["stone"] += 1
```

Room drops become legal:

```
Player: "I drop the stone."
Call 1 → TransferAction(target=<room_id>, given_items=["stone"])
Resolver → proposal (give, source_id="player", target_id=<room_id>)
           [resolver.py: pass the room ID instead of None]
Post-validation → valid give targets = corpus entities ∪ corpus rooms
                → soft_contents[<room_id>]["stone"] += 1
```

Gives **no longer touch the extraction ledger.**

### 4.4 Retrieving a placed item

Takes consult `soft_contents` before falling back to an ambient
proposal.  All `soft_contents` lookups — here and in the
post-validation rule below — normalize names with
`_normalize_item_name`: keys are stored verbatim from give
adjudications, and "the Stone" must match "stone".

- **Source is a room or non-NPC entity:** existence is mechanically
  established, so the resolver satisfies the take directly — no Call 2
  adjudication.  The resolver records the retrieval on a new
  `ResolutionResult.soft_content_takes: dict[source_id, dict[name, count]]`;
  engine step 5 applies it (decrement `soft_contents`, prune zeros and
  emptied parents, append to `soft_inventory`), and it is copied onto
  `EngineResult.soft_content_takes` (§3.3) so Call 2 can narrate the
  retrieval.  `_summarize_resolution` gains a line for it so turn
  history keeps a record.  This replaces the dead
  `surfaced_soft_items` plumbing with live plumbing of the same shape.
- **Closed containers gate retrieval.**  A container entity's
  `soft_contents` are subject to the same `_container_is_open` check
  as its hard contents: taking a placed soft item from a closed
  container fails with the same "The X is closed." error a hard item
  would produce.  (Gives need no such gate — they pass through Call 2,
  which sees the container's `open` state.)
- **Source is an NPC:** existence is known but *consent* is not.  The
  resolver emits a normal take proposal; Call 2 adjudicates (it sees
  the item in the NPC's `soft_items_present`).
- **Ambiguous source:** if the take targets the room but the item is
  placed on an entity in the room, the resolver searches the
  `soft_contents` of the room's entities before emitting an ambient
  proposal — mirroring the hard-item path, which checks the available
  pool first, then scans closed containers for the closed error.  An
  item found only inside a closed container yields that error.
  Without this fallback, "take the stone" aimed at the room would miss
  `soft_contents["table"]`, pollute `soft_items_taken[room]` on
  acceptance, and leave a stale table entry.
- **Shortfall:** if the requested count exceeds the placed count, the
  placed portion is satisfied per the rules above and only the
  remainder becomes an ambient-take proposal.

Unified post-validation rule for accepted takes: decrement from
`soft_contents[source]` first (up to `count`); only the remainder
increments `soft_items_taken[source]`.  Retrieving your own stone is
not extraction and must not pollute the depletion signal.

### 4.5 Multi-count soft takes

`resolve_transfer` currently rejects `count > 1` for any item not
tagged stackable in the corpus, and `_is_stackable` treats unknown
names as non-stackable — i.e. every soft item (§1).  Relax the guard
to skip names with no corpus entity, so multi-count soft takes reach
both the retrieval path above and the ordinary ambient-proposal path.

## 5. Dead Code Removal

| Location | Action |
|----------|--------|
| `resolver.py` — `ResolutionResult.surfaced_soft_items` field | Delete (superseded by `soft_content_takes`, §4.4). |
| `resolver.py` — `_fire_on_examine_events` accumulation of `ex_result.surfaced_soft_items` and the `"surfaced"` return key | Delete; update the two call sites in `resolve_examine`. |
| `engine.py` — step-5 merge loop over `resolution.surfaced_soft_items` | Replace with application of `resolution.soft_content_takes`. |

## 6. Template Changes

### 6.1 `ruling.j2`

- Briefing description (line ~17): describe both fields —
  `soft_items_taken` ("what the player has already extracted here, as
  `name (taken N)`") and `soft_items_present` ("soft items currently
  placed here — these verifiably exist").
- §Soft Items / §Containers & Items: note that dropping a soft item
  uses `transfer` with the room ID as `target` (the action reference
  already documents room IDs as transfer targets — drops simply start
  working as documented), and that placed items listed in
  `soft_items_present` can be taken back like ordinary contents.
  Explicitly: to retrieve a placed item, target the room or entity
  whose `soft_items_present` lists it.  Targeting the listing entity
  is preferred; a room-targeted take works too, via the resolver's
  entity fallback (§4.4).
- Clarify division of labour: destruction/consumption of a carried soft
  item → `soft_inventory_remove` patch; putting it somewhere →
  `transfer`.

### 6.2 `ruling.j2` §Soft State Patches — note-ification guidance

Add: *"If an examine establishes a notable ambient object or detail the
player may return to, record it as a `room_note` or `entity_note` —
soft-item examines leave no other persistent record."*

### 6.3 `prose.j2`

- Engine-result table: add a `soft_content_takes` row — "soft items
  the player retrieved from placed contents this turn (source → name →
  count); narrate the retrieval naturally.  These need no adjudication
  — their existence was mechanically verified."
- §Soft Item Adjudication: depletion guidance now references
  `soft_items_taken` and can assert its clean semantics (every count
  is a completed extraction).
- Note that `give` proposals may carry a room ID as `target_id`
  (a drop) and acceptance means the item now rests there.  Extend the
  output example (which currently shows only `"target_id": null`) with
  a room-drop give, so Call 2 reliably echoes room targets —
  post-validation matches proposals on exact `target_id`.
- Note that accepted `examine` adjudications affect narration only.

## 7. Documentation Changes

| File | Change |
|------|--------|
| `doc/soft-items.md` | Rewrite the state section around the two fields; update the examine/take/give flow diagrams and add the retrieval flow (§4.4: mechanical for rooms/features, Call 2 consent for NPCs, closed-container gate, shortfall); fix drift: give proposals use `source_id="player"` (the doc currently says `"<current_room>"`); update Key Design Decisions (#2 becomes "extraction counts are tracked; placement is tracked separately") and the files summary. |
| `schema/soft-state.md` | Replace the `surfaced_soft_items` section with `soft_items_taken` (population: accepted takes only) and a new `soft_contents` section (population: accepted gives/drops; decrement on retrieval; zero-pruning); update the top-level structure block and the initial-state example. |
| `schema/actions.md` | Update references: examine adjudications carry no state effect; give targets may be rooms. |
| `schema/scenario-generation.md` | Rename field in the initial-state template and checklists; add `soft_contents: {}`. |

## 8. Data / Fixture Migration

Rename `surfaced_soft_items` → `soft_items_taken` and add
`soft_contents: {}` in:

- `adventures/bag-of-holding/soft-state.json`
- `tests/fixtures/soft-state.json`
- `tests/fixtures/mini_adventure/soft-state.json`

This is a clean break (pre-release); existing save files are not
migrated.  A stale `surfaced_soft_items` key in a pre-change save
(e.g. the `autosave.json` in the repo root) is ignored by pydantic on
load — no crash, the old data is simply discarded.  If save
compatibility turns out to matter, a one-line validator alias on
`SoftGameState` (accept the old key, discard count-0 entries) can be
added, but it is not planned.

## 9. Implementation Checklist

1. `mgmai/models/soft_state.py` — rename field; add `soft_contents`.
2. `mgmai/models/briefing.py` — split briefing `soft_items` into
   `soft_items_taken` / `soft_items_present`.
3. `mgmai/models/actions.py` — add `EngineResult.soft_content_takes`.
4. `mgmai/engine/post_validate.py` — delete examine state write; give
   targets may be rooms; gives write `soft_contents`; accepted takes
   decrement `soft_contents` first (normalized lookup), remainder to
   `soft_items_taken`.
5. `mgmai/engine/resolver.py` — room-targeted give proposals carry the
   room ID; takes consult `soft_contents` (mechanical retrieval via
   `soft_content_takes`, closed-container gate, room-targeted entity
   fallback, NPC-consent proposals, shortfall rule); relax the
   `_is_stackable` count guard for soft names; delete
   `ResolutionResult.surfaced_soft_items` and `_fire_on_examine_events`
   surfacing.
6. `mgmai/engine/engine.py` — replace the dead step-5 merge loop with
   `soft_content_takes` application; copy it onto `EngineResult`;
   extend `_summarize_resolution`; update `_build_room_after`
   formatting (two fields).
7. `mgmai/engine/utils.py` — `inject_following_npcs` formatting (two
   fields).
8. `mgmai/context/assembler.py` — populate both briefing fields;
   `(taken N)` formatting is now unconditional.
9. Templates — §6.
10. Docs — §7.  Fixtures — §8.

## 10. Test Plan

Updates to existing tests:

- `tests/test_soft_state.py` — rename field; drop count-0 population
  case; add `soft_contents` round-trip.
- `tests/test_engine.py` —
  `test_surfaced_soft_items_persisted_after_examine` inverts: accepted
  examine writes **no** soft-item state; take test asserts
  `soft_items_taken` only.
- `tests/test_assembler.py` — count-0 formatting cases replaced by
  two-field assertions.
- `tests/test_resolver.py` — assert `soft_content_takes` instead of
  `surfaced_soft_items`.

New coverage:

- Accepted give to entity → `soft_contents` incremented,
  `soft_items_taken` untouched, item removed from `soft_inventory`.
- Accepted give to **room** (drop) → accepted by post-validation,
  `soft_contents[room]` incremented.
- Retrieval from room/feature → resolved mechanically (no proposal
  emitted), `soft_contents` decremented and pruned at zero,
  `soft_items_taken` untouched.
- Retrieval from NPC → proposal emitted; on acceptance,
  `soft_contents` decremented, `soft_items_taken` untouched.
- Shortfall: placed 1, take 2 → 1 mechanical + 1 ambient proposal;
  on acceptance the ambient unit increments `soft_items_taken`.
- Depletion integrity: give cork to Korbar, then examine Korbar —
  briefing shows `soft_items_present=["cork x1"]` and no `(taken N)`
  entry.
- Multi-count takes: take 2 of a placed item → fully mechanical,
  `soft_contents` decremented by 2; take 2 ambient → proposal with
  `count=2` (no stackable-guard failure).
- Closed container: placed item inside a closed container entity →
  take fails with the closed error and `soft_contents` is unchanged;
  the same take succeeds once the container is open.
- Ambiguous source: item placed on a table, take with the room as
  target → satisfied from the table's `soft_contents`; no
  `soft_items_taken` entry, no stale table entry.
- Normalization: give "Stone", then take "the stone" → retrieval
  matches the stored key.
- Surfacing: mechanical retrieval populates
  `EngineResult.soft_content_takes` and the turn-history summary.
- Assembler/briefing: room with both extraction history and placed
  items renders both fields correctly.

## 11. Out of Scope

- Hard-item containment (`room_contains`/`entity_contains`) is
  untouched.
- No engine-enforced depletion: depletion remains a Call 2 judgment
  informed by `soft_items_taken`.
- NPCs autonomously using/moving placed soft items (a `soft_contents`
  entry only changes via player actions).
- Corpus changes: `soft_item_guidance` is unchanged.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
