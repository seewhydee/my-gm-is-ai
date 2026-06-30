# Plan: Unify Interaction, DialoguePath, and OnExamineEvent under `Resolvable`

## Rationale

Three types in the schema share identical resolution semantics — an
optional availability `condition`, an optional `skip_check_if` bypass,
and either a deterministic `result` or a probabilistic `check` with
`success`/`failure` branches:

| Trait | `Interaction` | `DialoguePath` | `OnExamineEvent` |
|---|---|---|---|
| identity | `id` (field) | dict key | `id` (field) |
| `description` | yes (required) | yes (required) | — |
| `condition` | optional | optional | optional |
| `skip_check_if` | optional | optional | optional |
| `check` | optional | optional | optional |
| `success` | optional | optional | optional |
| `failure` | optional | optional | optional |
| `result` | optional | optional | optional |
| `using_results` | optional | **—** | **—** |
| extra fields | — | — | `rigorous_only` |
| validator | `check` XOR `result`; if `check` → need `success` | **identical** | `check` XOR `result`; if `check` → need `success` |

`DialoguePath` is a **strict subset** of `Interaction`, and
`OnExamineEvent` is `Interaction` minus `description`/`using_results`
plus `rigorous_only`.  The three differ only in their trigger context
and in which identifying fields are required — not in their resolution
logic.

The engine proves the equivalence: it **already constructs synthetic
`Interaction` objects** to route dialogue paths and examine events
through the same `_resolve_interaction_check()` code path — in three
separate locations:

| Location | Lines | What it does |
|---|---|---|
| `resolve_talk()` | 552–564 | Builds synthetic `Interaction` from `DialoguePath` fields |
| `_fire_on_examine_events()` | 1512–1520 | Builds synthetic `Interaction` from `OnExamineEvent` fields |
| `_resolve_using_override()` | 1130–1138 | Builds synthetic `Interaction` from `UsingResultOverride` fields |

This is a code smell indicating that the resolution shape is already a
shared primitive; the subtypes differ only in trigger context.

## Design decision: `Resolvable` primitive + strict `Interaction`

Rather than overloading the name `Interaction` to cover all three
contexts (which would mislabel dialogue paths and on-examine events as
"interactions" when they are really sibling resolvables), we introduce
a new primitive **`Resolvable`** that carries the shared shape, and
keep **`Interaction`** as its strict subclass for the room/entity
context (where `id` and `description` are genuinely required).

This mirrors the existing `Checkable` family: `Checkable` is the
abstract base; `CheckResolution`, `GatedCheck` are concrete
specializations.  Similarly, `Resolvable` is the abstract base for
"an id-bearing, condition-gated node that resolves to a `Result` via
either a deterministic `result` or a probabilistic `check`," and
`Interaction` / `OnExamineEvent` are concrete specializations tied to
specific trigger contexts.

### Why `Resolvable`?

- Parallels `Checkable` (both `-able` adjectives: "can be checked" /
  "can be resolved").
- Accurately describes all three use sites (they all *resolve* to
  outcomes), unlike `Interactable` (on-examine fires automatically, not
  "interacted with").
- Fits the existing `ResolutionResult` / `_resolve_*` vocabulary.

### Optional-vs-required via subclass tightening

`Resolvable.id` and `Resolvable.description` are `Optional` (so
dialogue-path JSON, which has no `id`/`description`-as-required, loads
cleanly).  `Interaction` redeclares them as required — the same pattern
`CheckResolution(Checkable)` already uses to tighten `check`/`success`
from `Optional` to required (corpus.py:179–196).  This is proven to
work in this codebase's Pydantic version.

## End-state primitives

After this plan, the `Checkable` hierarchy becomes:

| Primitive | Identity | Gate | `using_results`? | Extra | Where used |
|---|---|---|---|---|---|
| **Checkable** (base) | — | — | — | `skip_check_if`, `check`, `success`, `failure` | base class |
| **GatedCheck** | — | `gating` | optional | — | Item `take_check`, Exit `traversal_check` |
| **CheckResolution** | — | — | — | `check` required, `success` required | Result `then_check` |
| **Resolvable** (new) | `id` optional | `condition` | optional | `description` optional, `result` | base for Interaction / OnExamineEvent / dialogue_paths |
| **Interaction** | `id` required | `condition` | optional | `description` required, `result` | Room/Entity `interactions` |
| **OnExamineEvent** | `id` optional | `condition` | optional (unused) | `description` optional (unused), `result`, `rigorous_only` | Room/Entity `on_examine` |

`DialoguePath` is **removed**.  `dialogue_paths` becomes
`Dict[str, Resolvable]`; a `DialogueGuidelines` validator populates
each entry's `id` from the dict key.

### `using_results` scope

`using_results` is carried by `Resolvable` and therefore inherited by
all three subtypes.  In practice it is only meaningful for room/entity
`Interaction`s (e.g. "show the guard your badge").  For dialogue paths
and on-examine events it is **documented as unused** — no validator
rejects it, to keep the primitive uniform and the hierarchy shallow.
The schema doc notes this.

## Schema changes (`schema/corpus.md`)

### 1. Add `Resolvable` to the primitives section

Add a new subsection in the primitives area (near `Checkable` /
`GatedCheck` / `CheckResolution`) describing the unified primitive:

```
## Resolvable

A `Resolvable` is the shared primitive for any id-bearing,
condition-gated node that resolves to a `Result`.  It is the base type
for `Interaction` (room/entity interactions), `OnExamineEvent`
(on-examine events), and the entries of an NPC's `dialogue_paths`.

Each `Resolvable` has:
- an optional `id` (populated from the dict key for `dialogue_paths`
  entries; required and always present for room/entity `Interaction`s),
- an optional `description` (required for room/entity `Interaction`s;
  surfaced to the LLM for dialogue paths; unused for on-examine
  events),
- an optional availability `condition`,
- an optional `skip_check_if` bypass,
- either a deterministic `result` or a probabilistic `check` with
  `success`/`failure` branches (mutually exclusive; if `check` is
  present, `success` must be),
- an optional `using_results` map (item-based alternative resolutions;
  meaningful only for room/entity `Interaction`s — documented as unused
  for dialogue paths and on-examine events).
```

### 2. Update `Interaction` section (lines 475–481)

Keep the section describing `Interaction` as the room/entity-scoped
type with required `id` and `description`.  Add a sentence noting it is
a strict subclass of `Resolvable`:

```
## Interaction

Interactions describe discrete, non-generic operations performed on (or
with) entities or rooms, triggered by the `interact` action.  An
`Interaction` is a `Resolvable` whose `id` and `description` are
required (they identify and label the interaction for the LLM).  All
other fields (`condition`, `skip_check_if`, `check`, `success`,
`failure`, `result`, `using_results`) inherit their semantics from
`Resolvable`.
```

### 3. Update `dialogue_paths` subsection (lines 1084–1120)

Replace the standalone `DialoguePath` field table with a
cross-reference to `Resolvable`:

```
#### `dialogue_paths` object

Each entry is a [Resolvable](#resolvable).  The dict key is the path ID
used in the `talk` action (`dialogue_path` field); the `Resolvable.id`
field is populated from the dict key automatically during model
validation (and need not be supplied in the JSON).

The `description` field (required) is surfaced to LLM Call 1 in
`entities_visible` as `{path_id: description}` so it can match player
intent to the right path.  The `using_results` field is inherited from
`Resolvable` but is documented as unused for dialogue paths.

(The existing JSON example at lines 1086–1107 remains correct — all
field names are identical.)
```

Remove the standalone `DialoguePath` field table (lines 1110–1118) and
the "Path results support the same fields..." note (line 1120), since
they duplicate the `Resolvable` section.

### 4. Update `On-Examine` subsection (lines 546–607)

Replace the `OnExamineEvent` field descriptions with a reference:

```
Each On-Examine event is a [Resolvable](#resolvable) with one extra
field, `rigorous_only` (boolean, default `false`), which restricts the
event to rigorous (turn-costing) examination.  `id` is supplied in the
JSON (used as the source identifier in roll dicts and repeatability
tracking).  `description` is inherited from `Resolvable` but is unused
for on-examine events (not surfaced to the LLM).  `using_results` is
inherited but documented as unused.
```

Keep the JSON example and the notes about cursory vs rigorous
behavior.  The field table is replaced with the cross-reference above.

## Model changes (`mgmai/models/corpus.py`)

### 5. Rename current `Interaction` → `Resolvable`; make `id`/`description` optional

Replace the current `Interaction` class (lines 224–241) with:

```python
class Resolvable(Checkable):
    """The shared primitive for id-bearing, condition-gated resolution nodes.

    Base for Interaction (room/entity), OnExamineEvent, and the entries
    of an NPC's dialogue_paths.  Subclasses tighten optionality per
    their context (e.g. Interaction requires id and description).
    """
    id: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[ConditionExpression] = None
    result: Optional[Result] = None
    using_results: Optional[Dict[str, UsingResultOverride]] = None

    @model_validator(mode="after")
    def check_mutually_exclusive(self) -> "Resolvable":
        has_check = self.check is not None
        has_result = self.result is not None
        if not has_check and not has_result:
            raise ValueError(
                "Resolvable must have at least one of 'check' or 'result'")
        if has_check and has_result:
            raise ValueError(
                "Resolvable must have either check or result, not both")
        if has_check and self.success is None:
            raise ValueError(
                "Resolvable with 'check' must also have 'success'")
        return self
```

Note the validator is slightly tightened from the current
`OnExamineEvent`/`DialoguePath` validators (which permitted
neither-check-nor-result): the unified primitive requires at least one
of `check` or `result`.  This matches the current `Interaction`
validator.  Audit existing dialogue-path and on-examine JSON to confirm
every entry has at least one (the bag-of-holding corpus does).

### 6. Add strict `Interaction(Resolvable)` subclass

Immediately after `Resolvable`, add:

```python
class Interaction(Resolvable):
    """A room/entity-scoped Resolvable with required id and description."""
    id: str = Field(...)
    description: str = Field(...)
```

`Interaction` inherits `check_mutually_exclusive` and all other fields
from `Resolvable`.  It tightens `id` and `description` to required —
the same pattern `CheckResolution(Checkable)` uses to tighten
`check`/`success`.

### 7. Remove `DialoguePath` class (lines 344–358)

Delete the entire `DialoguePath` class and its `check_mutually_exclusive`
validator.  Its semantics are subsumed by `Resolvable`.

### 8. Convert `OnExamineEvent` to a `Resolvable` subclass (lines 253–267)

Replace the current `OnExamineEvent(Checkable)` class and its validator
with:

```python
class OnExamineEvent(Resolvable):
    rigorous_only: bool = False
```

`OnExamineEvent` is now a **sibling** of `Interaction` (both extend
`Resolvable`), not a subclass of `Interaction`.  It inherits
`check_mutually_exclusive` and all `Resolvable` fields.  `id` stays
optional at the type level (on-examine JSON supplies it); `description`
is inherited as optional (on-examine JSON does not supply it, and it is
unused).  Delete the now-redundant `check_mutually_exclusive` validator
on `OnExamineEvent`.

### 9. Update `DialogueGuidelines.dialogue_paths` type (line 369)

```python
# Before:
dialogue_paths: Dict[str, DialoguePath] = Field(default_factory=dict)
# After:
dialogue_paths: Dict[str, Resolvable] = Field(default_factory=dict)
```

### 10. Add `id` auto-population validator on `DialogueGuidelines`

Because `Resolvable.id` is now `Optional`, dialogue-path JSON (which
has no `id` field — the id is the dict key) loads cleanly, and a
parent-level `model_validator(mode="after")` can populate `id` from
the key after construction:

```python
class DialogueGuidelines(BaseModel):
    personality: str
    on_encounter: str = ""
    can: List[str] = Field(default_factory=list)
    cannot: List[str] = Field(default_factory=list)
    knows: List[str] = Field(default_factory=list)
    attitude_limits: AttitudeLimits
    will_reveal: Dict[str, WillRevealEntry] = Field(default_factory=dict)
    dialogue_paths: Dict[str, Resolvable] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_dialogue_path_ids(self) -> "DialogueGuidelines":
        for path_id, resolvable in self.dialogue_paths.items():
            resolvable.id = path_id
        return self
```

This validator runs after each `Resolvable` is constructed (which now
succeeds because `id` is optional), so `id` is always populated before
any downstream code reads it.

### 11. Update `Checkable` docstring (line 168)

Replace "DialoguePath, OnExamineEvent" with "Resolvable, Interaction,
OnExamineEvent".  The docstring already lists `GatedCheck` per the
prior plan.

### 12. Imports in `corpus.py`

`Interaction` and `OnExamineEvent` remain exported.  `DialoguePath` is
removed.  `Resolvable` is newly exported.  `Room.interactions` and
`Entity.interactions` keep type `List[Interaction]` (unchanged name —
`Interaction` is now the strict subclass, which is exactly what those
fields hold).

## Engine changes

### 13. `resolve_talk()` — eliminate synthetic `Interaction` (lines 552–564)

The dialogue path is now a `Resolvable`, and the resolution helpers
accept `Resolvable`, so the synthetic wrapper is removed.  The
recommended approach is to extract a shared `_resolve_interaction()`
helper (step 15) and call it directly:

```python
# After (replacing lines 534–578):
if path is not None:
    path_result = _resolve_interaction(
        path, hard, soft, corpus, room_id,
        state_manager=state_manager,
        resolution=result,
        source_type="dialogue_path",
    )
    result.hard_changes = path_result.hard_changes or HardStateChanges()
    result.triggered_narration.extend(path_result.triggered_narration or [])
    result.revealed_hints.extend(path_result.revealed_hints or [])
    result.rolls.extend(path_result.rolls or [])
    result.events.extend(path_result.events or [])
```

The early `path.condition` check at line 485 stays — it gates dialogue
*entry* (before any turn is appended), which is a different concern
from the per-branch `condition` semantics inside `_resolve_interaction`.
(See step 15 for the double-condition note.)

### 14. `_fire_on_examine_events()` — eliminate synthetic `Interaction` (lines 1512–1520)

Since `OnExamineEvent` is now a `Resolvable`, the `event` object can be
passed directly to `_resolve_interaction()`:

```python
# After (replacing lines 1497–1531):
if event.check:
    if event.skip_check_if and evaluate(event.skip_check_if, hard, soft, corpus):
        if event.success:
            _apply_result_with_check(event.success, ..., source_id=f"_on_examine_{event.id}", source_type="examine", ...)
        continue
    ex_result = _resolve_interaction(
        event, hard, soft, corpus, room_id,
        state_manager=state_manager,
        resolution=resolution,
        source_type="examine",
    )
    if ex_result.hard_changes: changes.merge(ex_result.hard_changes)
    if ex_result.triggered_narration: narrative.extend(ex_result.triggered_narration)
    if ex_result.revealed_hints: revealed_hints.extend(ex_result.revealed_hints)
    if ex_result.surfaced_soft_items:
        for k, v in ex_result.surfaced_soft_items.items():
            surfaced.setdefault(k, []).extend(v)
    if ex_result.rolls: rolls.extend(ex_result.rolls)
elif event.result:
    _apply_result_with_check(event.result, ..., source_id=f"_on_examine_{event.id}", source_type="examine", ...)
```

The `rigorous_only` and `condition` filters at lines 1492–1495 stay
unchanged.

### 15. Extract `_resolve_interaction()` helper from `resolve_interact()`

Extract the body of `resolve_interact()` lines 912–973 (the
condition/skip_check_if/using_results/result/check dispatch) into a
shared helper that takes a `Resolvable`:

```python
def _resolve_interaction(
    inter: Resolvable,
    *,
    hard: HardGameState,
    soft: SoftGameState,
    corpus: ModuleCorpus,
    room_id: str,
    action_using: str | None = None,
    state_manager: Any | None = None,
    resolution: ResolutionResult | None = None,
    source_type: str = "interaction",
) -> ResolutionResult:
    """Resolve a single Resolvable (shared by interact, talk, examine).

    Handles skip_check_if bypass, using_results override, result-only,
    and check-bearing branches.  Does NOT evaluate the availability
    `condition` (callers gate entry themselves) and does NOT emit
    `interaction.used` (callers emit context-appropriate events).
    """
    # (body of resolve_interact lines 912–973, generalized; uses inter.id
    #  as source_id, inter.check/success/failure/result/using_results)
    ...
```

Then `resolve_interact()` becomes a thin wrapper that finds the
`Interaction` by `(target, interaction_id)`, emits
`interaction.used`, evaluates `inter.condition` (returning
"Conditions not met" on failure, as today), and delegates to
`_resolve_interaction(inter, ..., source_type="interaction")`.

**Two contracts the helper must preserve** (flagged in evaluation):

- **No `interaction.used` emission inside the helper.** `resolve_interact`
  emits `interaction.used` at line 897 *before* resolution;
  `resolve_talk` and `_fire_on_examine_events` do not emit it.  The
  helper must not emit it, or dialogue paths / on-examine events would
  gain a new event.  Callers remain responsible for emitting
  context-appropriate events.
- **No `condition` evaluation inside the helper.** `resolve_interact`
  evaluates `inter.condition` at line 912 (returning an error);
  `resolve_talk` evaluates `path.condition` early at line 485 (before
  dialogue entry); `_fire_on_examine_events` evaluates `event.condition`
  at line 1492 (skipping the event).  Each caller keeps its own
  condition gate; the helper assumes the caller has already gated.

### 16. `_resolve_interaction_check()` — annotate against `Resolvable`

Change the `inter` parameter type from `Interaction` to `Resolvable`
(line 1056).  No logic change — the function only reads `inter.check`,
`inter.success`, `inter.failure`, and `inter.id`, all present on
`Resolvable`.

### 17. `_resolve_using_override()` — no change (lines 1130–1138)

`UsingResultOverride` is a standalone intermediate type.  The synthetic
`Interaction` it constructs is internal to the resolution path and not
surfaced in the schema or public API.  Leave as-is.  (The synthetic
`Interaction` still validates because `id` and `description` are
supplied.)

### 18. `_resolve_checkable()` type annotation (line 1309)

```python
# Before:
chk: CheckResolution | Interaction | OnExamineEvent | GatedCheck,
# After:
chk: CheckResolution | Resolvable | GatedCheck,
```

`Interaction` and `OnExamineEvent` are both `Resolvable` subtypes, so
the union simplifies to `Resolvable`.

### 19. Update imports in `resolver.py`

```python
# Before:
from mgmai.models.corpus import (
    ...
    Interaction,
    ...
    OnExamineEvent,
    ...
)
# After:
from mgmai.models.corpus import (
    ...
    Interaction,
    Resolvable,
    ...
    OnExamineEvent,
    ...
)
```

`OnExamineEvent` is still imported (used for the
`_fire_on_examine_events` parameter type and the `rigorous_only`
attribute access).  `Interaction` is still imported (used by
`resolve_interact`'s `matches: list[tuple[Interaction, str]]` and by
`_resolve_using_override`'s synthetic construction).

## Assembler / engine changes (briefing)

### 20. `assembler.py` — dialogue path description extraction (lines 100–105)

```python
# Before:
path_descriptions = {
    path_id: path.description
    for path_id, path in entity.dialogue_guidelines.dialogue_paths.items()
}
# After (no logic change; rename variable):
path_descriptions = {
    path_id: resolvable.description
    for path_id, resolvable in entity.dialogue_guidelines.dialogue_paths.items()
}
```

`resolvable.description` works because `Resolvable` carries
`description` (optional, but always supplied for dialogue paths).

### 21. `engine.py` `_build_room_after()` — same pattern (lines 718–723)

No logic change; rename loop variable `path` → `resolvable`.

### 22. `utils.py` `inject_following_npcs()` — same pattern (lines 80–85)

No logic change; rename loop variable `path` → `resolvable`.

## Test changes

### 23. `tests/test_assembler.py` — update DialoguePath references (line 200)

```python
# Before:
from mgmai.models.corpus import DialoguePath, Result
# After:
from mgmai.models.corpus import Resolvable, Result

# Before (lines 202–209):
dialogue_paths["test_path"] = DialoguePath(
    description="Test path",
    result=Result(narrative="Test result"),
)
# After:
dialogue_paths["test_path"] = Resolvable(
    description="Test path",
    result=Result(narrative="Test result"),
)
```

No `id=` needed (the `DialogueGuidelines` validator populates it).

### 24. `tests/test_resolver.py` — update DialoguePath references (line 821)

```python
# Before:
from mgmai.models.corpus import DialoguePath, ConditionExpression
# After:
from mgmai.models.corpus import Resolvable, ConditionExpression

# Before (lines 823–827):
path = DialoguePath(description="...", condition=..., result=...)
# After:
path = Resolvable(description="...", condition=..., result=...)
```

Update all `DialoguePath(...)` constructor calls (lines 823, 846).  No
`id=` needed.

### 25. `tests/test_event_bus.py` — update DialoguePath references (line 701)

```python
# Before:
from mgmai.models.corpus import DialoguePath, RollCheck
# After:
from mgmai.models.corpus import Resolvable, RollCheck

# Before (line 705):
korbar.dialogue_guidelines.dialogue_paths["ask_secret"] = DialoguePath(...)
# After:
korbar.dialogue_guidelines.dialogue_paths["ask_secret"] = Resolvable(...)
```

Same for `"rummage"` at line 975.

### 26. Room/entity interaction test fixtures — verify `Interaction` still works

Tests that construct `Interaction(id=..., description=...)` for
`room.interactions` / `entity.interactions` continue to work unchanged:
`Interaction` is still the field type, and its required fields are
unchanged.  No edit needed unless a test constructed `Interaction`
*without* `id`/`description` (none do — they were always required).

### 27. Add test for `id` auto-population

```python
def test_dialogue_path_resolvable_id_populated():
    guidelines = DialogueGuidelines(
        personality="test",
        attitude_limits=AttitudeLimits(min=-5, max=5),
        dialogue_paths={
            "flatter": Resolvable(
                description="Flatter the spider",
                result=Result(narrative="The spider preens."),
            ),
        },
    )
    assert guidelines.dialogue_paths["flatter"].id == "flatter"
```

### 28. Add test for `Interaction` required fields

```python
import pytest
from mgmai.models.corpus import Interaction

def test_interaction_requires_id_and_description():
    with pytest.raises(ValidationError):
        Interaction(result=Result(narrative="x"))  # missing id, description
    with pytest.raises(ValidationError):
        Interaction(id="x", result=Result(narrative="x"))  # missing description
```

### 29. Add migration test for existing corpus JSON

Verify that `adventures/bag-of-holding/corpus.json` loads correctly
after the model changes.  All existing dialogue paths use field names
identical to `Resolvable` (`description`, `condition`, `check`,
`success`, `failure`, `result`) and omit `id` (now optional, populated
from the dict key).  All on-examine events supply `id` and omit
`description` (now optional).  No JSON file changes.

### 30. Grep for remaining references

After changes, run:

```
rg 'DialoguePath' tests/ mgmai/ schema/ --type py --type md
```

Expected: zero matches (the type is fully removed).

```
rg 'OnExamineEvent' tests/ mgmai/ schema/ --type py --type md
```

Expected surviving references:
- `OnExamineEvent` class definition in `corpus.py` (now a subclass of
  `Resolvable`).
- `from mgmai.models.corpus import ... OnExamineEvent ...` in
  `resolver.py` (for `_fire_on_examine_events()` typing and
  `rigorous_only` access).
- Schema docs cross-references.

## What does NOT change

- **`Checkable` base class** — unchanged.
- **`GatedCheck`** — unchanged.
- **`CheckResolution` / FollowUpCheck** — unchanged.
- **`UsingResultOverride`** — unchanged (and its synthetic
  `Interaction` in `_resolve_using_override` stays).
- **`WillRevealEntry`** — unrelated to this unification.
- **`Room.interactions` / `Entity.interactions` field types** — still
  `List[Interaction]`.  The name `Interaction` is preserved as the
  strict room/entity type.
- **The adventure corpus JSON files** — no migration needed.  All
  existing dialogue paths use field names identical to `Resolvable`
  and omit `id` (now optional, auto-populated).  All on-examine events
  supply `id` and omit `description` (now optional).  No JSON changes.
- **`BriefingEntity.dialogue_paths`** — still `Dict[str, str]`
  (path_id → description).  The assembler still extracts descriptions
  from `Resolvable.description`.
- **The resolution *semantics*** of dialogue paths and on-examine
  events — unchanged.  The code is simplified, but runtime behavior is
  identical: `condition` gates availability, `skip_check_if` bypasses
  the check, `check`/`result` resolve as before.
- **`source_type` differentiation** — `"interaction"`, `"dialogue_path"`,
  and `"examine"` remain distinct in roll dicts and event emission.
  The extracted `_resolve_interaction()` helper accepts a `source_type`
  parameter exactly as the current code does.
- **`interaction.used` event emission** — emitted only by
  `resolve_interact` (for room/entity interactions), not by
  `resolve_talk` or `_fire_on_examine_events`.  Preserved by keeping
  the emit outside the shared helper (step 15).

## File-change inventory

| File | Change |
|---|---|
| `schema/corpus.md` | Add `Resolvable` primitive subsection; update `Interaction` section to note it is a strict `Resolvable` subclass; replace `DialoguePath` field table with cross-reference to `Resolvable`; update `On-Examine` section to reference `Resolvable` |
| `mgmai/models/corpus.py` | Rename current `Interaction` → `Resolvable` (optional `id`/`description`, carries `check_mutually_exclusive`); add strict `Interaction(Resolvable)` with required `id`/`description`; delete `DialoguePath` class + validator; convert `OnExamineEvent` to `Resolvable` subclass with `rigorous_only` (delete its validator); update `DialogueGuidelines.dialogue_paths` type to `Dict[str, Resolvable]`; add `id` auto-population validator on `DialogueGuidelines`; update `Checkable` docstring |
| `mgmai/engine/resolver.py` | Extract `_resolve_interaction()` helper from `resolve_interact()` (takes `Resolvable`; no `interaction.used` emit, no `condition` eval inside); refactor `resolve_talk()` to call it directly (eliminate synthetic `Interaction`); simplify `_fire_on_examine_events()` (no synthetic `Interaction`); annotate `_resolve_interaction_check()` and `_resolve_checkable()` against `Resolvable`; update imports |
| `mgmai/context/assembler.py` | Rename loop variable `path` → `resolvable` (cosmetic); no logic change |
| `mgmai/engine/engine.py` | Rename loop variable `path` → `resolvable` in `_build_room_after()` (cosmetic); no logic change |
| `mgmai/engine/utils.py` | Rename loop variable `path` → `resolvable` in `inject_following_npcs()` (cosmetic); no logic change |
| `tests/test_assembler.py` | `DialoguePath` → `Resolvable` import and constructor calls |
| `tests/test_resolver.py` | `DialoguePath` → `Resolvable` import and constructor calls |
| `tests/test_event_bus.py` | `DialoguePath` → `Resolvable` import and constructor calls |
| `tests/test_corpus.py` or new test | Add test for `id` auto-population from dict key; add test for `Interaction` required fields |

## Task ordering

1. **Model** — `mgmai/models/corpus.py`:
   - Rename `Interaction` → `Resolvable`; make `id`/`description`
     `Optional`; keep `check_mutually_exclusive` (tightened to require
     at least one of check/result)
   - Add strict `Interaction(Resolvable)` with required `id`/`description`
   - Delete `DialoguePath` class + validator
   - Convert `OnExamineEvent` to `Resolvable` subclass with
     `rigorous_only`; delete its validator
   - Update `DialogueGuidelines.dialogue_paths` type to
     `Dict[str, Resolvable]`; add `id` auto-population validator
   - Update `Checkable` docstring
2. **Engine** — `mgmai/engine/resolver.py`:
   - Extract `_resolve_interaction()` helper from `resolve_interact()`
     body (takes `Resolvable`; no `interaction.used` emit, no
     `condition` eval inside)
   - Refactor `resolve_interact()` to delegate to the helper
   - Refactor `resolve_talk()` to call `_resolve_interaction()` directly
     (eliminate synthetic `Interaction`)
   - Simplify `_fire_on_examine_events()` — remove synthetic
     `Interaction`, call `_resolve_interaction()` directly
   - Annotate `_resolve_interaction_check()` and `_resolve_checkable()`
     against `Resolvable`; update imports
3. **Assembler/engine briefing** — cosmetic variable renames (3 files)
4. **Tests** — update all `DialoguePath` → `Resolvable` references;
   add `id` auto-population test; add `Interaction` required-fields test;
   add corpus-JSON migration test
5. **Schema** — `schema/corpus.md`: add `Resolvable` primitive
   subsection; update `Interaction`, `dialogue_paths`, and On-Examine
   sections
6. `pytest` green
7. `rg 'DialoguePath' tests/ mgmai/ schema/ --type py --type md` clean
