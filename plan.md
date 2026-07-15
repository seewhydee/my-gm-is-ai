# Design: Narrative-Adjudicated Soft Items

## 1. Problem

The soft-items subsystem (`doc/soft-items.md`) requires module authors
to exhaustively pre-list every plausible ambient object on each room
and entity in the corpus.  A cave room needs `"rock"`, `"pebble"`,
`"sharp stone"`, `"dust"`, `"cobweb"`, `"bone fragment"`, `"loose
gravel"`, etc. enumerated in its `soft_items` field, or the engine
rejects any player attempt to interact with objects not on the list.

This is fragile: if the corpus author overlooks soft items and leaves
a cave room with `soft_items: []`, a player who says "I pick up a
pebble" gets *"You search but find no such thing"* —
immersion-breaking in a room the prose describes as littered with
rubble.

The fundamental tension is that the LLM's common sense *can* judge
whether a rock exists in a cave, but the engine's corpus whitelist is
the sole authority.  An exhaustive whitelist is the wrong shape for
the safety problem.

## 2. Core Insight: Call 2 Already Adjudicates Narrative Plausibility

LLM Call 2 (Prose) already produces structured, non-narrative output
that the engine post-validates after Call 2 returns.  The validation
lives in `mgmai/engine/post_validate.py` and is orchestrated by
`apply_post_validation()`, which is invoked from the game loop
(`mgmai/game/loop.py`) after Call 2 completes — *not* from inside the
engine's `resolve()` step.  The established pattern is:

- **`knowledge_tags`** — which `will_reveal` topics the NPC disclosed
  this turn.  The engine validates against corpus conditions
  (`will_reveal.conditions`) and applies side effects (`set_flag`,
  `set_entity_state`).  Implemented by `post_validate_knowledge_tags`.
- **`attitude_changes`** — proposed shifts in NPC disposition.  The
  engine validates against `attitude_limits` (step per turn, min/max
  bounds) and the requirement of a non-empty `reason`.  Implemented by
  `post_validate_attitude_changes`.
- **`conversation_note`** — a narrative summary of a concluded
  dialogue, written entirely by Call 2, stored by the engine as an
  `entity_note`.
- **`npc_response`** — extracted spoken text, used by the engine to
  populate `conversation_log`.

In all four cases, Call 2 is not merely a narrator but also doubles as
the *narrative authority* — it decides what the NPC said, how their
attitude shifted, what was revealed, and how the conversation should
be remembered.  The engine provides a safety fence (gating conditions,
bounds checks) but does *not* attempt to predict or whitelist the
LLM's output.  In every case the engine's post-validation *mutates the
`EngineResult` in place* (e.g. `revelations_applied`,
`attitude_changes_applied`) — so adding post-Call-2 soft-item results
to `EngineResult` follows an established flow.

Soft items are the same category of problem: we want *narrative
plausibility*, not mechanical truth.  A rock belongs in a cave because
the fiction says so, not because a corpus entry says so.  The engine
should gate the mechanical consequences (inventory placement,
surfacing), not the ontological question of whether the rock exists.

**The proposal: extend Call 2's structured output to include
soft-item adjudication, route those adjudications through a new
`post_validate_soft_items()` in `post_validate.py`, and stop checking
corpus `soft_items` lists in the resolver.**

## 3. Current Mechanics (what changes)

The reader needs the precise current flow, since several details
matter for the design.

### 3.1 Where corpus `soft_items` is consulted today

Corpus `soft_items` (`Room.soft_items`, `Entity.soft_items` — both
`List[str]`) are consulted in exactly three places:

1. **`resolve_examine`** (`resolver.py`): builds
   `all_soft = set(room.soft_items) ∪ {ent.soft_items for ent in
   room contents}`.  If the examine target is not a hard room/entity,
   it is matched against `all_soft`; on match, the item is surfaced on
   its source (room first, else the owning entity).  This is a
   *fallback* path — hard room/entity examines are handled earlier and
   fire `on_examine` events.  **Soft-item examines never fire
   `on_examine` events**, so soft items carry no `on_examine`-gated
   mechanical consequence today.

2. **`resolve_transfer`** (`resolver.py`): builds
   `available_pool: dict[str, int]` — a *quantity map* aggregating
   hard world-items *and* soft items (each soft name counted as `+1`).
   `taken_items` are validated against `available_pool`; `given_items`
   are validated against `soft.soft_inventory`.  Note `available_pool`
   is broader than `all_soft` (it includes hard items with counts);
   the two must not be conflated.

3. **`_validate_soft_patches`** (`engine.py`, inside engine step 5,
   *pre*-Call-2): a `soft_inventory_add` patch is validated against
   `all_soft` for the current room + contained entities.  So
   `soft_inventory_add` *is* already gated by the corpus today.  The
   gap is one of *scope* (current room only) and that
   engine-internal resolver patches bypass this check entirely.

### 3.2 Where corpus `soft_items` is *not* consulted

Crucially, corpus `soft_items` is **never briefed to either LLM**.
The Context Assembler populates `BriefingRoom.soft_items` and
`BriefingEntity.soft_items` from `soft.surfaced_soft_items` (discovered
items only), never from the corpus lists (`assembler.py`).  So today,
Call 1 and Call 2 only ever see soft items the player has already
touched.  This is central to the design: there is currently *no
channel* by which the corpus `soft_items` list reaches Call 2 as a
"hint."  Any hint mechanism must be built fresh.

### 3.3 What `surfaced_soft_items` tracks (and doesn't)

`surfaced_soft_items: dict[room_or_entity_id, list[str]]` records
names the player has examined/taken/given.  It deduplicates by string
name.  It does **not** track counts, depletion, or how many times a
name was taken.  A cave with "rock" surfaced once is indistinguishable
from a desk with one "quill."  Depletion is therefore not an
engine-knowable fact; it can only be inferred by Call 2 from narrative
context.

### 3.4 Current soft-item stacking (or lack thereof)

Hard items in the corpus may declare quantities (e.g.,
`contains: [{"rock": 3}]`), which the resolver tracks via
`available_pool: dict[str, int]`.  Each take decrements the count.
Soft items have no such mechanism: `surfaced_soft_items` is a set
(names only), and each soft name is added to `available_pool` with
count 1 regardless of how many might plausibly exist.  There is no
way for the engine or Call 2 to distinguish "the player took one rock"
from "the player took fifteen rocks."

## 4. Design

### 4.1 Changed flow

```
Player: "I pick up the rock and examine it."

Call 1 → TransferAction(target="bag_floor", taken_items=["rock"])
          (LLM proposes freely — no corpus soft_items lookup)

Resolver → does NOT check bag_floor.soft_items for "rock".
         → records "rock" as a pending SoftItemProposal on the
           ResolutionResult (source_id="bag_floor", action="take").

Engine  → step 5: _validate_soft_patches no longer accepts
           soft_inventory_add patches from Call 1 (deprecated path —
           see §4.5).  The proposal is carried on EngineResult.
         → EngineResult.soft_item_proposals = [
             { item_name: "rock", action: "take",
               source_id: "bag_floor", target_id: null,
               proposed_by: "call_1" }
           ]

Call 2  → receives the EngineResult (including soft_item_proposals)
         → sees surfaced_soft_items["bag_floor"] = {"rock": 1} from
           a previous take
         → decides: rock on a cave floor?  Still plausible (count is
           low, source is far from exhausted).
         → narrates: "You stoop and pick up a smooth grey stone from
           the rubble."
         → NarrationOutput.soft_item_adjudications = [
             { item_name: "rock", action: "take", accepted: true,
               source_id: "bag_floor", target_id: null,
               justification: "The bag floor is covered in debris
               and loose stones." }
           ]

Loop    → apply_post_validation() calls post_validate_soft_items():
         → validates adjudication shape and mechanical consistency
         → for accepted "take": appends "rock" to soft_inventory,
           increments surfaced_soft_items["bag_floor"]["rock"] → 2
         → mutates EngineResult: soft_items_accepted / soft_items_rejected
```

### 4.2 Schemas

```python
class SoftItemProposal(BaseModel):
    item_name: str
    action: Literal["take", "give", "examine"]
    source_id: str            # room or entity the item comes from
    target_id: Optional[str]  # entity receiving a "give"
    proposed_by: Literal["call_1"] = "call_1"

class SoftItemAdjudication(BaseModel):
    item_name: str
    action: Literal["take", "give", "examine"]
    accepted: bool
    source_id: str            # echoed from the proposal
    target_id: Optional[str]
    justification: Optional[str]   # required when accepted=False

class NarrationOutput(BaseModel):
    narration: str
    npc_response: Optional[str] = None
    knowledge_tags: Optional[KnowledgeTags] = None
    attitude_changes: Optional[Dict[str, AttitudeChange]] = None
    conversation_note: Optional[str] = None
    terminate_chain: bool = False
    soft_item_adjudications: List[SoftItemAdjudication] = Field(default_factory=list)
```

`SoftItemProposal` is added to `EngineResult` (produced by the engine,
pre-Call-2, mirroring how the engine already populates
`EngineResult`).  `SoftItemAdjudication` is added to `NarrationOutput`
(produced by Call 2).  The two are joined inside
`post_validate_soft_items()`.

**`source_id` is required on both proposals and adjudications.**  The
engine needs a surfacing target, and cannot derive the source from
item name alone (a name can belong to multiple sources).  Call 1
already specifies the source via `TransferAction.target` /
`ExamineAction.target`, and has access to the room ID and all present
entity IDs via the GM Briefing.  Call 2 echoes the proposal's
`source_id`; see §4.4 for the rule that makes this always possible.

### 4.3 `justification` is required only on rejection

On `accepted: true`, `justification` is optional — every accepted
pebble should not cost a justification token.  On `accepted: false`,
`justification` must be a non-empty string; Call 2's narration already
explains the rejection to the player, and the justification is an
engine-side audit record.  (This matches the asymmetry of
`attitude_changes`, where `reason` is always required because every
attitude change is consequential — but soft-item acceptance is
consequence-light.)

### 4.4 Call 2 may only adjudicate items Call 1 proposed

Call 2 receives `EngineResult.soft_item_proposals` and adjudicates
each.  Call 2 **may not invent new soft items** in its
`soft_item_adjudications`.  Rationale:

- **Inventory traceability.** `soft_inventory` changes must be
  traceable to a Call-1-ruled `TransferAction` recorded in
  `turn_history`.  Spontaneous Call-2 takes would break that
  invariant.
- **Source bookkeeping.** Without a Call-1 proposal, there is no
  `source_id` to surface on, and the engine cannot derive one.

If the player's input implies an item Call 1 missed ("I smash the
bottle"), the correct behaviour is for Call 1 to propose it.  The Call
1 prompt (§6.1) instructs Call 1 to propose soft items generously when
the player's input implies them.  The engine's post-validation
**rejects** any adjudication whose `item_name`+`action` does not match
a pending proposal (see §4.6 rule 6).

**Single point of failure.**  This constraint means the system's
coverage of player intent is only as good as Call 1's proposal
generation.  If Call 1 is conservative or misses implied items, the
player gets the same failure mode as today ("you find no such thing"),
just with a different root cause.  The mitigation is prompt
engineering (§6.1) — Call 1 must be instructed to propose generously
and to infer implied items from context.  This is an acceptable
trade-off: the alternative (allowing Call 2 to invent items) breaks
inventory traceability.

### 4.5 Split of the soft-state patch space

Under the new design:

- **`soft_inventory_add`** — **deprecated as a Call-1 patch.**  Soft
  additions flow exclusively through `TransferAction`/`ExamineAction`
  → proposal → Call-2 adjudication → `post_validate_soft_items`.  The
  engine rejects `soft_inventory_add` patches from
  `proposed_soft_state_patches` (they appear in
  `soft_state_patches_rejected`).  This removes the current
  current-room-scoped corpus check in `_validate_soft_patches`
  (`engine.py`), which is now redundant: Call 2 owns existence.

- **`soft_inventory_remove`** — **retained.**  Call 1 may still remove
  items from `soft_inventory` for mechanical reasons (consuming an
  item as part of an interaction).  The engine validates the item
  exists in `soft_inventory` (unchanged).

- **Other patches** (`room_note`, `entity_note`, `appearance_note_add`,
  `set_improvised_weapon`) — unchanged.

This cleanly splits the soft-state patch space:

| Concern | Authority |
|---------|-----------|
| Narrative existence / acquisition | Call 2 adjudicates |
| Mechanical consumption / removal | Call 1 proposes, engine validates |
| Narrative notes / appearance | Call 1 proposes, engine validates |

### 4.6 Engine post-validation rules

`post_validate_soft_items(adjudications, proposals, soft, hard, corpus,
result)` follows the shape of `post_validate_knowledge_tags` /
`post_validate_attitude_changes`.  For each adjudication:

| Rule | Failure action |
|------|----------------|
| 1. `item_name` non-empty | Reject |
| 2. `action` ∈ {take, give, examine} | Reject |
| 3. `accepted` is boolean | Reject |
| 4. If `accepted == false`: `justification` non-empty | Reject |
| 5. `source_id` present and is a valid room or entity ID; `target_id` required and valid for `give` actions | Reject |
| 6. `item_name` + `action` matches a pending `SoftItemProposal` (case-insensitive after normalization) | Reject |
| 7. Hard-entity collision: normalized `item_name` does not match a corpus entity ID or display name | Reject |
| 8. For `take` (accepted): engine does *not* re-check a corpus list. Duplicate-take is permitted — stacking identical names (two "rock") is allowed. `surfaced_soft_items` tracks the count | Apply: append to `soft_inventory`, increment count on `source_id` |
| 9. For `give` (accepted): `item_name` must be present in `soft.soft_inventory` | Apply: remove from `soft_inventory`, increment count on `target_id` |
| 10. For `examine` (accepted): surface on `source_id` only; no inventory change | Apply: mark as surfaced on `source_id` (count 0 if not already present) |
| 11. Rejected adjudications | Log; no state change. Call 2's narration already explains the rejection, so there is no separate player-visible error. |

**Default for missing/empty adjudications.**  If
`soft_item_adjudications` is absent or empty while proposals exist,
the engine treats every proposal as **rejected** (no state change).
Rejection is the safe default for inventory correctness: a missing
adjudication is treated as "Call 2 declined to confirm existence,"
which must not silently add items to the player's inventory.

### 4.7 Stacking and depletion

Soft items are **stackable by name**.  The engine permits taking
multiple items of the same name (e.g., two "rock" entries in
`soft_inventory`).  `surfaced_soft_items` tracks how many times each
name has been taken from each source, giving Call 2 the information it
needs to judge depletion.

**Schema change.**  `surfaced_soft_items` changes from
`dict[str, list[str]]` to `dict[str, dict[str, int]]`:

```json
{
  "bag_floor": { "rock": 3, "pebble": 1 },
  "rubbish_pile": { "cork": 1, "lint clump": 2 }
}
```

The integer counts how many times the player has taken that item from
that source.  An examine sets the count to 0 (surfaced but not taken)
if the name is not already present, or leaves the count unchanged if
it is.

**Briefing format.**  The Context Assembler briefs counts to Call 2.
The briefing surface includes both the item name and its take count,
so Call 2 can judge whether the source is plausibly exhausted.  For
example:

```
Soft items on bag_floor: rock (taken 3), pebble (taken 1)
```

Call 2 is prompted to use this count as a depletion signal: a cave
with "rock" taken 3 times likely still has more, but a desk with
"quill" taken once may not.  The engine does **not** enforce depletion
— that remains Call 2's judgment — but it provides the data to make
that judgment informed.

**`soft_inventory` remains a flat list.**  The player's carried items
are still `List[str]` (e.g., `["rock", "rock", "pebble"]`).  Duplicate
entries are allowed, matching existing semantics
(`schema/soft-state.md`: "Duplicate entries are allowed").  The
inventory is not count-deduplicated — each take appends a string.

**Failure mode.**  The worst case is a player accumulating a
narratively silly number of identical items (47 rocks from one cave)
because Call 2 fails to judge depletion.  This is mechanically
harmless (see §5, Layer 5) and unlikely in practice, since Call 2 sees
the rising count in its briefing and is prompted to refuse when a
source is plausibly exhausted.

### 4.8 Hard-entity collision check (Layer 4)

This check is a backstop, not the primary gate.  It matches the
adjudication `item_name` against corpus entity IDs and display names
**after normalization** (lowercase, strip articles, collapse
whitespace, map spaces↔underscores).  This catches "rusty key" vs
`rusty_key` but cannot catch semantic collisions ("the old key" vs
`rusty_key`).

Call 1's prompt (§6.1) is the primary defence: it is instructed to
check whether a proposed item matches a hard entity in the room before
proposing it as a soft item.  The engine's collision check catches
cases where Call 1 misses this.  A miss is not catastrophic because
soft items have no mechanical leverage — the player would end up with
a soft "rusty key" that doesn't unlock anything, while the hard
`rusty_key` entity remains uncollected.  This is confusing but not
game-breaking, and the engine's entity-ID check prevents the most
common collisions.

## 5. Safety Model

The safety model shifts from "engine whitelist" to "LLM prompt
constraints + engine post-validation of adjudication shape."  The
layers are:

### Layer 1: Call 1 prompt guardrails
Call 1 is instructed not to propose magical, valuable, or
game-breaking items, and to check for hard-entity collisions before
proposing a soft item.  This catches the most obvious failure modes
before they reach Call 2.

### Layer 2: Call 2's narrative judgment
Call 2, with full narrative context (room description, recent history,
the verbatim chat log, the player's `soft_inventory`, and
`soft_item_guidance` from the corpus), is the primary plausibility
gate.  It rejects items contradicted by established fiction, depleted
sources, or setting inappropriateness.  It receives take counts from
`surfaced_soft_items` to judge depletion.

### Layer 3: Engine post-validation of adjudication shape
`post_validate_soft_items` validates well-formedness and mechanical
consistency (no giving items not held, source/target validity,
proposal matching).  This prevents corrupted outputs from producing
corrupted state.

### Layer 4: Hard-entity ID collision check
See §4.8.  Prevents soft-item-ifying a hard item.

### Layer 5: No mechanical leverage
Soft items carry no mechanical effect — they don't deal damage, unlock
doors, or satisfy conditions.  They do not fire `on_examine` events
(only hard room/entity examines do).  The worst-case hallucination is
a narratively silly soft inventory, which is mechanically harmless.
The improvised-weapon path (`set_improvised_weapon`) is the *separate,
mechanically consequential* route for using a soft item as a weapon,
and remains Call-1-validated.

### Adversarial players
A player who says "I pick up the Wand of Wishing" routes through both
LLMs.  Call 1 should refuse to propose it (guardrails); if Call 1
proposes it, Call 2 should reject it (guardrails); if both fail, the
engine's entity-ID check catches it if it is a corpus entity; if it is
not a corpus entity and both LLMs accept, the player receives a soft
item named "Wand of Wishing" with no mechanical meaning.  The narrator
can describe it as "a gnarled twig you optimistically call a wand."
This is an acceptable failure mode: the system prevents absurd things
from *having mechanical consequences*, not from being *said*.

## 6. Prompt Changes

### 6.1 Call 1 (Ruling)

Add to the Call 1 system prompt:

```
You may propose interactions with any mundane object that could plausibly
exist in the current environment — rocks, dust, loose coins, scraps of
cloth, bone fragments, water droplets, and similar ambient items.  These
are "soft items" — they carry no mechanical stats and are identified by
their common name.

The prose narrator (Call 2) will judge whether each soft item you propose
actually exists in the scene.  Do not try to predict which items are
present; propose what the player's input asks for (including items the
player's action implies, such as "broken glass" when the player smashes a
bottle), and trust the narrator to adjudicate.

Do NOT propose soft items that are:
- Obviously magical (wands, scrolls, potions, enchanted objects)
- Extremely valuable (gems, jewellery, gold bars)
- Dedicated weapons or armour (swords, shields, helmets)
- Plot-critical items that would short-circuit the adventure
- Anachronistic or setting-inappropriate objects

Before proposing a soft item, check whether the item name matches a hard
entity (by ID or display name) currently present in the room.  If it does,
target that entity directly — do not propose it as a soft item.  Soft items
are for ambient objects that have no corpus entity.

When the player's input implies interacting with a soft item, use the normal
action types: TransferAction for taking/giving, ExamineAction for examining.
Set source_id to the room ID if the item comes from the room environment, or
to the entity ID if the player specifies a source (e.g., "take a cork from
the rubbish pile").

If the player grabs a non-standard object to use as a weapon, that is NOT a
soft-item take: propose a set_improvised_weapon patch instead, with the
object's mechanical parameters.  Soft items are narrative props; improvised
weapons are mechanical.
```

### 6.2 Call 2 (Prose)

Add to the Call 2 system prompt:

```
SOFT ITEM ADJUDICATION
---------------------
The EngineResult may contain "soft_item_proposals" — items the ruling LLM
believes the player is trying to take, give, or examine, but whose existence
in the scene has not been mechanically verified.

For each proposal, you must decide whether the item plausibly exists in the
current scene and produce a "soft_item_adjudications" entry.  Echo the
proposal's source_id and target_id.  Your decision should be reflected in
your narration: accept → narrate finding/using the item; reject → narrate
not finding it.

Guidelines for acceptance:
- Default to ACCEPTING mundane items that fit the environment (rocks in a
  cave, dust in an attic, coins in a purse).
- Consult soft_item_guidance (if present on the room or source entity) as
  a hint about what the environment contains.  You may accept items not
  mentioned and reject items mentioned — the guidance is advisory.
- REJECT items that are magical, legendary, extremely valuable, anachronistic,
  or would break the adventure's balance.
- REJECT items that contradict recent narrative (e.g., accepting "a torch"
  in a room just described as pitch-black with no light sources).
- REJECT items the player has already taken excessively, if the source is
  now depleted.  The surfaced-soft-items briefing shows take counts per
  item per source — use this to judge depletion.  A cave has many rocks
  (low count is fine), but a desk has only one quill (count ≥ 1 means
  depleted).

You may ONLY adjudicate items that appear in soft_item_proposals.  Do not
invent new soft items.

When rejecting, provide a brief "justification" (one sentence).  When
accepting, justification is optional.
```

## 7. Corpus Changes

### 7.1 `soft_items` removed

The `soft_items` field is removed from `Room` and `Entity`.  There is
no backward compatibility shim: this project is pre-alpha, and a
shim would only preserve a validation gate the design explicitly
removes.  Existing modules must drop their `soft_items` lists (or
convert any authorially-significant ones to `soft_item_guidance`, §7.2).

### 7.2 `soft_item_guidance` (optional)

Because corpus `soft_items` is never briefed today (§3.2), removing it
loses nothing the LLMs currently see.  But authors may want to *seed*
Call 2's judgment with hints (e.g., "this room is barren; reject all
soft items," or "the desk has a quill and inkwell").  An optional
freeform string is added:

```json
{
  "rooms": {
    "void_chamber": { "soft_item_guidance": "Barren. No ambient items." },
    "sages_desk":   { "soft_item_guidance": "Quill, inkwell, scattered parchment." }
  }
}
```

`soft_item_guidance` is surfaced to Call 2 (via `BriefingRoom` /
`BriefingEntity`) as a hint.  It is **not** a validation list — Call 2
may accept items not mentioned, and reject items mentioned.  This is
the *only* new corpus/briefing field; it is the channel that did not
exist before.

### 7.3 Authorial control for puzzle rooms

Some rooms have puzzle-significant item availability (e.g., "the only
takeable thing here is the silver lever").  Narrative adjudication
cannot enforce this strictly.  Authors who need rigid control should
model the item as a **hard entity** (which the engine still gates
strictly), not a soft item.  The `strict` policy mode (§9.1) is future
work for cases where hard-entity modelling is too heavy; it is
intended as an escape hatch for puzzle rooms, not a general
alternative to narrative adjudication.

## 8. EngineResult and NarrationOutput changes

- Add `soft_item_proposals: List[SoftItemProposal]` to `EngineResult`
  (`mgmai/models/actions.py`).  Populated by the resolver/engine
  pre-Call-2.
- Add `soft_item_adjudications: List[SoftItemAdjudication]` to
  `NarrationOutput` (`mgmai/models/narration.py`).  Populated by Call
  2.
- Add `soft_items_accepted: List[SoftItemAdjudication]` and
  `soft_items_rejected: List[SoftItemAdjudication]` to `EngineResult`,
  populated by `post_validate_soft_items` (post-Call-2 mutation,
  mirroring `revelations_applied` / `attitude_changes_applied`).

`NarrationOutput` now carries 7 structured fields (4 optional objects
alongside the prose).  This increases the compliance risk — LLMs are
more likely to omit or malform fields as the number grows.  Phase F
testing must measure Call 2's compliance rate with `soft_item_adjudications`
and simplify the prompt if compliance is poor.

## 9. Extensibility

### 9.1 `soft_item_policy` modes (future)

```json
{
  "rooms": {
    "throne_room": {
      "soft_item_policy": "strict",
      "soft_item_guidance": "dust, loose thread"
    }
  }
}
```

- `"narrative"` (default): Call 2 adjudicates; `soft_item_guidance` is
  a hint.
- `"strict"`: engine enforces that accepted items appear in a corpus
  list (restoring a whitelist for puzzle rooms).  Intended as an
  escape hatch for rooms where hard-entity modelling is too heavy.
  Future work — requires keeping an explicit list, so deferred.
- `"barren"`: Call 2 is instructed to reject all soft-item proposals.

### 9.2 Narrative notes via Call 2 (future)

`room_note` / `entity_note` currently proposed by Call 1 could follow
the same Call-2-adjudication pattern.  Future work.

### 9.3 Improvised weapons (future)

`set_improvised_weapon` straddles narrative and mechanics.  Call 1
could propose the mechanical parameters while Call 2 adjudicates the
object's existence.  The current design keeps this in Call 1 for
simplicity; the split is natural but deferred.

## 10. Trade-offs

### Advantages
- **No exhaustive pre-listing.**  Module authors describe rooms
  narratively; the LLM handles ambient objects.
- **True narrative flexibility.**  Players improvise with the
  environment and the system adapts.
- **Leverages existing architecture.**  `post_validate.py` already
  hosts two Call-2-output validators; a third fits the pattern
  cleanly, including in-place `EngineResult` mutation.
- **Call 1 stays focused on mechanics.**  Soft-item existence becomes
  Call 2's domain, alongside NPC dialogue, attitude, and revelations.
- **Graceful degradation.**  Missing adjudications default to
  rejection (safe for inventory correctness); if both LLMs
  hallucinate, the worst outcome is a silly soft inventory entry.
- **Depletion-aware.**  `surfaced_soft_items` tracks take counts,
  giving Call 2 the data to judge depletion without engine-level
  enforcement.

### Disadvantages
- **Less deterministic.**  The same input at the same state may
  produce different soft-item outcomes across runs.  Arguably correct
  for a narrative system, but makes testing harder.
- **Token cost.**  `soft_item_proposals` on `EngineResult` and
  `soft_item_adjudications` on `NarrationOutput` add tokens.  The
  proposals are small (a few item names per turn) and Call 2 already
  reads the room description, so marginal cost is low.
- **Call 2 prompt complexity.**  Adjudication instructions lengthen
  the Call 2 prompt; keep them terse and test for compliance.  With 7
  structured fields on `NarrationOutput`, compliance monitoring is
  essential.
- **Module author loss of strict control.**  Authors who need rigid
  item availability must use hard entities (§7.3) or wait for
  `strict` mode (§9.1).
- **Single point of failure on Call 1.**  The "Call 2 may not invent
  new soft items" constraint (§4.4) means coverage of player intent
  depends entirely on Call 1 proposing generously.  Mitigated by
  prompt engineering.

## 11. Implementation Outline

### Phase A: Schema and models
- Add `SoftItemProposal` to `mgmai/models/actions.py` (or a new
  `soft_items.py`); add the field to `EngineResult`.
- Add `SoftItemAdjudication` and the `soft_item_adjudications` field
  to `mgmai/models/narration.py` (`NarrationOutput`).
- Add `soft_items_accepted` / `soft_items_rejected` to `EngineResult`.
- Remove `soft_items` from `Room` and `Entity` in
  `mgmai/models/corpus.py`.  Add `soft_item_guidance: Optional[str]`.
- Add `soft_item_guidance` to `BriefingRoom` / `BriefingEntity` in
  `mgmai/models/briefing.py`.
- Change `surfaced_soft_items` from `Dict[str, List[str]]` to
  `Dict[str, Dict[str, int]]` in `mgmai/models/soft_state.py`.
- Remove `soft_inventory_add` from the `SoftStatePatch.field` Literal
  in `mgmai/models/soft_state.py`.

### Phase B: Resolver changes
- In `resolve_transfer`: for `taken_items` / `given_items` that are
  soft-item names, stop checking `available_pool` for the soft portion
  and stop checking `ent.soft_items` / `room.soft_items`.  Instead
  record a `SoftItemProposal` on the `ResolutionResult` (and thence
  `EngineResult`).  Hard-item transfer validation is unchanged.
- In `resolve_examine`: for targets that don't match a hard room/entity,
  record a `SoftItemProposal` instead of matching `all_soft`.  (The
  `on_examine` path for hard targets is unchanged.)
- Remove the `soft_inventory_add` branch from `_validate_soft_patches`
  in `engine.py`; emit a rejection for any such patch.
- `soft_inventory_remove` handling is unchanged.

### Phase C: Post-validation
- Add `post_validate_soft_items()` in `mgmai/engine/post_validate.py`,
  following `post_validate_knowledge_tags` / `post_validate_attitude_changes`.
- Rules per §4.6.
- Hook into `apply_post_validation()`; populate
  `soft_items_accepted` / `soft_items_rejected` on `EngineResult`.
- Invoked from the game loop (`loop.py`) after Call 2, alongside the
  existing knowledge-tag and attitude-change post-validation.

### Phase D: Context assembler
- Populate `BriefingRoom.soft_item_guidance` /
  `BriefingEntity.soft_item_guidance` from the new corpus field.
- Update `BriefingRoom.soft_items` / `BriefingEntity.soft_items` to
  surface take counts from the new `surfaced_soft_items` schema.
  Format: include item names and counts so Call 2 can judge depletion.
- Confirm `soft_inventory` is briefed to Call 2 (it already is, via the
  player-state block — `assembler.py`).

### Phase E: Prompts
- Update the Call 1 system prompt per §6.1.
- Update the Call 2 system prompt per §6.2.

### Phase F: Tests
- Adjudication shape validation: missing fields, empty `item_name`,
  unknown action, missing `justification` on rejection.
- Hard-entity ID collision: "rusty key" rejected when `rusty_key` is a
  corpus entity (with normalization).
- Proposal-matching: adjudication without a matching proposal rejected.
- `take` (accepted): appended to `soft_inventory`, count incremented
  on `source_id`.  Duplicate `take` of the same name permitted.
- `give` (accepted) of a non-held item: rejected.
- `examine` (accepted): surfaced on `source_id`, no inventory change.
- Rejected adjudications produce no state change.
- Missing/empty `soft_item_adjudications` with pending proposals → all
  rejected, no state change.
- `soft_inventory_add` patch from Call 1 → rejected.
- `soft_item_guidance` surfaced to Call 2.
- Source ID validation: proposal with missing `source_id` → rejected;
  proposal with invalid `source_id` (non-existent room/entity) →
  rejected; adjudication `source_id` that doesn't match the proposal's
  `source_id` → rejected.
- Depletion counts: `surfaced_soft_items` increments correctly on
  repeated takes; counts are surfaced in briefing to Call 2.
- **Fixture migration:** all existing test fixtures and the adventure
  corpus must be updated to remove `soft_items` and adopt the new
  `surfaced_soft_items` schema.  74 soft-item references across 8 test
  files, plus 2 corpus JSONs and 2 soft-state JSONs.

### Phase G: Documentation
- Update `doc/soft-items.md` to reflect the adjudication model and
  count-based depletion.
- Update `schema/actions.md` (EngineResult fields, Call 2 output).
- Update `schema/soft-state.md`: remove `soft_inventory_add` from the
  patch table; document new `surfaced_soft_items` schema
  (`dict[str, dict[str, int]]`).
- Update `schema/corpus.md`: remove `soft_items`, document
  `soft_item_guidance`.
