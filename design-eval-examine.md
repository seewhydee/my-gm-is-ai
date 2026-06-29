# Design Evaluation: `on_examine` vs Unified Reaction System

**Date:** 2026-06-22
**Evaluator:** Subagent (design analysis)
**Context:** "my-gm-is-ai" project — playtesting revealed scenario generator
             produced incorrect examine content, prompting this evaluation.

---

## Summary

**Recommendation: Keep `on_examine` as a separate mechanism, but improve its
documentation and integration with the event bus.**

The two mechanisms serve genuinely different purposes, and unifying them would
introduce complexity without eliminating the class of bugs the scenario generator
produced. The generator bugs stem from **author confusion about whether content
belongs in `on_examine` vs `interaction`** (which is a schema-level design choice,
not an engine architecture problem) and from **insufficient validation rules**
in the generator, not from the separation of `on_examine` from reactions.

That said, there is one concrete improvement worth making: **examine should emit
an event** (e.g. `"examine.room"` / `"examine.entity"`) to the event bus, even
if `on_examine` events continue to fire through the existing direct path. This
would allow reactions to observe examine actions without needing to duplicate
logic.

---

## 1. Current Design Analysis

### 1A. The Two Mechanisms at a Glance

| Aspect | `on_examine` (OnExamineEvent) | Reaction system |
|--------|-------------------------------|-----------------|
| **Model** | `corpus.py` line 225 — 7 fields | `corpus.py` line 268 — 6 fields + `ReactionEffects` (4 fields) |
| **Where defined** | `Room.on_examine` (line 294), `Entity.on_examine` (line 392) | `Room.reactions` (line 296), `Entity.reactions` (line 415), `Mechanic.reactions` |
| **Event trigger** | Player action `examine` on room or entity | Any event string: `"interaction.used"`, `"room.entered"`, `"flag.set"`, etc. |
| **Discovery** | Direct property access (`room.on_examine`, `entity.on_examine`) | `find_matching_reactions()` in `event_bus.py` (line 50) — filtered by event type, scope, alive/fled state, conditions |
| **Dispatch** | `_fire_on_examine_events()` in `resolver.py` (line 1455) — simple iteration loop | `dispatch_reactions()` in `event_bus.py` (line 138) — priority sorting, self-resolution, encounter/dialogue/game-over dispatch, recursion |
| **Execution order** | Definition order in the array | Sorted by `priority` asc, then scope (entity→room→mechanic), then definition index |
| **Result application** | `_resolve_interaction_check()` (for checks) or `_apply_result()` (for results) | Same `_apply_result()` path, but through `_resolve_self()` first (resolves `"self"` references) |

### 1B. What OnExamineEvent Has That Reaction Doesn't

**`rigorous_only: bool` (line 228)**

This is the single unique field. When `true`, the on_examine event only fires
if the examine action has `rigorous: true` (i.e., the player explicitly asked
to "examine carefully"). This enables a two-tier observation system:
- Casual examine → get the base description + obvious on_examine events
- Rigorous examine → additionally get the hidden/obscure on_examine events

The Reactions system has no equivalent. Adding `rigorous_only` to Reaction
would be trivial (it's a single boolean filter), but it would also need to
be plumbed through the event context so that `find_matching_reactions` could
check it — or else reaction conditions would need an `event:rigorous == true`
domain check.

### 1C. What Reaction Has That OnExamineEvent Doesn't

| Field | Description | Relevance to examine |
|-------|-------------|---------------------|
| `once` (line 273) | Fire at most once per adventure load | Useful for "I notice this the first time I look" patterns. Currently, on_examine events rely on flag-gating in `condition` to achieve one-shot behavior. |
| `priority` (line 274) | Numeric sort key for reaction ordering | Not needed for examine — definition order is fine for passive observation. |
| `phase` (line 275) | `"immediate"` or `"deferred"` | Not relevant for examine — there is nothing to be "immediate" about during passive observation. |
| `trigger_encounter` (line 252) | Start an encounter | Would be wrong for examine — you don't start combat by looking at something. (Examine reveals; interaction triggers.) |
| `trigger_dialogue` (line 253) | Start NPC dialogue | Not relevant for examine — dialogue is initiated by `talk`. |
| `game_over` (line 254) | End the game | Could theoretically be used ("examining the artifact kills you") but this is an anti-pattern; game-over should come from mechanics. |

### 1D. Flow Comparison

**Current on_examine flow (`resolve_examine` → `_fire_on_examine_events`):**

```
Player: examine room/entity
  → resolve_examine() sets base_narrative = [room/entity.description]
  → _fire_on_examine_events():
       for each event in room/entity.on_examine:
         if condition holds and (not rigorous_only or action.rigorous):
           if event.check:
             build synthetic Interaction → _resolve_interaction_check()
               _emit_event("check.passed"/"check.failed")  ← IMMEDIATE REACTIONS here
           else:
             _apply_result(event.result)
             if event.result.chain_check:
               _resolve_chained_check()
  → return ResolutionResult with triggered_narration, revealed_hints, rolls
  → NO "examine.room"/"examine.entity" event is emitted to the deferred event bus
```

**Current reaction flow (via engine.py end-of-turn dispatch):**

```
After action resolution:
  → collect action_events (from resolution.events list)
  → _dispatch_events(action_events):
       for each event_type, context:
         find_matching_reactions(event_type, context, ...)
         dispatch_reactions(matches, ...):
           sort by priority, scope, definition order
           for each (reaction, owner_id):
             _resolve_self(effects, owner_id)  # resolve "self" references
             _apply_result(result) | trigger_encounter | trigger_dialogue | game_over
             recurse up to MAX_RECURSION_DEPTH (5)
  → _derive_state_events(merged_changes) → _dispatch_events(state_events)
  → _dispatch_events([("turn.end", ...)])
```

### 1E. The Base Description Narrative

The base description (room description or entity description) is **not part of
`on_examine`**. It is always emitted as the first element of
`triggered_narration` before any on_examine events fire. This is correct and
should remain separate — it's the canonical prose description of the target,
while on_examine events are conditional discoveries layered on top.

If examine were unified into the reaction system, the base description would
still need to be separate (it's not conditional, it's not an event response).
This is the strongest argument against full unification: the base description
is a mandatory narrative emission, not an event reaction.

---

## 2. Unification Analysis

### 2A. What Would "Full Unification" Mean?

```python
# Hypothetical: OnExamineEvent is removed; on_examine fields become Reactions

# Step 1: Add "examine.room" and "examine.entity" to IMMEDIATE_ALLOWED_EVENTS
# or keep them as deferred events

# Step 2: Convert each on_examine event to a Reaction:
{
  "on": "examine.room"  # or "examine.entity"
  "condition": { "require": "flag:already_noticed == false" },
  "effects": {
    "result": { "narrative": "You notice...", "set_flag": {"already_noticed": true} }
  }
}

# Step 3: Add rigorous_only equivalent — either as a new Reaction field
# or as event context:
{
  "on": "examine.room",
  "condition": {
    "all": [
      { "require": "flag:glow_noticed == false" },
      { "require": "event:rigorous == true" }  # hypothetical event context key
    ]
  },
  "effects": {/*...*/}
}
```

### 2B. Migration Changes

| Component | Change Required |
|-----------|-----------------|
| **`corpus.py`** | Add `"examine.room"` and `"examine.entity"` to `IMMEDIATE_ALLOWED_EVENTS` (optional) or leave as deferred. Remove `OnExamineEvent` model. Remove `on_examine` field from `Room` and `Entity`. Add `rigorous_only` field to `Reaction` or document event-context approach. |
| **`resolver.py`** | In `resolve_examine()`, emit `_emit_event("examine.room"/"examine.entity", {"target": target, "rigorous": action.rigorous})` instead of calling `_fire_on_examine_events()`. Remove `_fire_on_examine_events()` entirely. |
| **`event_bus.py`** | No changes needed (already handles any event type string). |
| **`corpus.md` schema** | Remove `on_examine` section. Add `"examine.room"` / `"examine.entity"` to event types table. Update all examples. |
| **`scenario-generation.md`** | Rewrite §2F, §3E decision table, and all on_examine examples as reactions. |
| **`validate_adventure.py`** | Remove on_examine-specific validation (lines collecting addable entities from on_examine results). |
| **All existing adventures** | Migrate every `on_examine` block to a `reactions` block. Every single adventure corpus.json would need changes. |

### 2C. What Would Be Lost

**1. Simplicity of the on_examine model**

`OnExamineEvent` is 7 fields with a straightforward validator: check or result,
mutually exclusive. `Reaction` + `ReactionEffects` is a larger API surface (10+
fields) with more complex semantics (`once`, `priority`, `phase`, `self`
resolution, encounter/dialogue/game-over side effects). For content authors
writing "the player notices X when they look at Y," the smaller surface is
genuinely easier.

**2. The `rigorous_only` distinction**

This would need to be added to Reaction as a new field, or handled via
event-context conditions. Neither is hard, but it's one more thing to
teach authors.

**3. Definition-order execution guarantee**

On-examine events fire in array order. Reactions have a sorting step
(priority → scope → definition order). While the sorting is harmless
(default priority=0 → definition order), it adds a mental model shift:
"examine events are reactions, so they might reorder." This is subtle
but could confuse authors who expect sequential discovery patterns.

**4. The base narrative separation**

The base description is conceptually not an event response — it's the
canonical content of the target. If examine became an event, you could
write a reaction for the base description too, but then the base
description would become conditional and overridable, which breaks the
core design invariant that "examining Y always shows Y's description."

### 2D. What Would Be Gained

**1. Reactions could respond to examine actions**

Currently, if you want "when the player examines the statue, an NPC reacts,"
you can't use a reaction because there's no `"examine.*"` event. You'd have
to either:
- Add an on_examine event that sets a flag, and a reaction on the flag change
- Or duplicate the logic in both systems

This gap would be closed by simply **emitting an `"examine.room"` / `"examine.entity"`
event** from `resolve_examine()`, regardless of whether on_examine events
continue to fire through their own path.

**2. Single pattern for all event-driven behavior**

New contributors learn one mechanism instead of two. The schema documentation
shrinks.

**3. Use `once` instead of flag-gating**

On-examine events that should only fire once currently need a `condition` with
`"require": "flag:already_noticed == false"` and a `set_flag` in the result.
Reactions with `once: true` achieve this with one field instead of two. But
this is a minor convenience, not a dealbreaker.

---

## 3. Trade-offs

### 3A. Impact on Content Authors

| Criterion | Separate `on_examine` | Unified |
|-----------|----------------------|---------|
| **API surface to learn** | 7-field model (OnExamineEvent) + decision table ("notice"→on_examine, "do"→interaction) | 10+ field model (Reaction + effects) + larger event type table + decision table is still needed for "examine vs interaction" distinction |
| **Schema documentation** | ~40 lines in corpus.md for on_examine + ~80 lines for reactions | Reactions doc grows ~30 lines (add examine.* events, rigorous_only guidance); on_examine doc is removed. Net reduction: ~50 lines. |
| **Existing adventures** | No migration needed | Every adventure needs corpus.json changes; schema-version bump required |
| **Validation burden** | Validated as a separate model (simpler per-model rules) | Validated through reaction validation (more complex, but single path) |

### 3B. Impact on Scenario Generator

The bugs the scenario generator produced were traced to **incorrect placement**
of content — putting examine discoveries in `interactions` instead of
`on_examine`, or putting entity-specific on_examine events on the room. These
are **schema-level authorship errors**, not engine-mechanism errors.

Unifying `on_examine` into reactions would not eliminate this class of bug.
The scenario generator would still need to decide: "is this a reaction to
`examine.room`, or an `interaction`?" The decision boundary is the same:
passive observation vs active manipulation. If the generator makes the wrong
choice today, it will make the wrong choice under unification too.

**The fix** is better generator rules and validation, not architectural
unification. Specifically:
- The "When to use interaction vs on_examine" decision table in
  `scenario-generation.md` (line 745) is good — the generator needs a
  coded version of the same table.
- The generator should validate: every "notice" / "see" / "recognize"
  scenario clause must produce an on_examine event, not an interaction.
- The generator should verify: entity-specific on_examine events are on
  the entity, not the room.

### 3C. Engine Complexity

| Metric | Separate | Unified |
|--------|----------|---------|
| **Code paths in resolver.py** | 2 (resolve_examine + _fire_on_examine_events) | 1 (resolve_examine emits event, reactions handle the rest) |
| **Code paths in event_bus.py** | 0 (no examine events) | ~15 lines for find_matching_reactions to match examine events (trivial) |
| **Branches in event_bus.py** | 0 | examine events need to check rigorous_only (1 branch) |
| **Risk of regression** | Low (existing code unchanged) | Medium (all adventure content must be migrated) |

### 3D. The Missing Event Gap

The clearest deficiency in the current design is that **examine does not emit
any event**. This means:

- You cannot write a room-level or entity-level `reaction` that fires
  `on: "examine.room"` — the event doesn't exist.
- To make something happen in response to an examine action, you must use
  `on_examine` events, or set a flag in on_examine and react to the flag
  change at end of turn.
- The flag-change approach works (flag.set is a state-change event), but it's
  two-hop and defers the response to end-of-turn dispatch.

This gap is **the single concrete argument for change**. But it can be fixed
without full unification: simply emit `_emit_event("examine.room", ...)` /
`_emit_event("examine.entity", ...)` from `resolve_examine()`, while keeping
`_fire_on_examine_events()` as the primary pipeline for on_examine content.

---

## 4. Recommendation

### Keep `on_examine` separate, but bridge the gap.

**Rationale:**

1. **Different semantic intent.** On-examine events describe **what you notice
   when you look**. Reactions describe **what happens in response to something
   occurring**. These are different authorial intents, and the 7-field
   OnExamineEvent model is a better fit for "notice" patterns (smaller surface,
   no irrelevant fields like `trigger_encounter`).

2. **The base description is not an event response.** The invariant "examining
   Y always shows Y's description" is fundamental. Unification would either
   break it (if reactions could override) or require special-casing it anyway.

3. **`rigorous_only` is genuinely useful** and would need to be re-added
   to Reaction or handled awkwardly via `event:rigorous == true` conditions.
   A dedicated field is cleaner.

4. **Migration cost is high, benefit is low.** Every existing adventure would
   need corpus.json changes. The scenario generator bugs are not architecture
   bugs — they're logic bugs in content placement rules.

### Concrete improvement: Emit examine events to the event bus.

Add two lines to `resolve_examine()`:

```python
# After building the ResolutionResult (before returning):
if target == room_id:
    _emit_event("examine.room", {"target": target, "rigorous": action.rigorous},
                hard, soft, corpus, state_manager, result)
else:
    _emit_event("examine.entity", {"target": target, "rigorous": action.rigorous},
                hard, soft, corpus, state_manager, result)
```

This adds "examine.room" and "examine.entity" to the event list without changing
how on_examine events fire. Authors can now write reactions that observe examine
actions, while on_examine continues to be the recommended path for "things you
notice when examining."

No schema changes are needed for this improvement — the event types just need
to be documented in `events.md`. The `on_examine` mechanism remains the
primary pipeline for examine-specific authored content.

### Additional improvements (as follow-ups):

1. **Add `on_examine` to `IMMEDIATE_ALLOWED_EVENTS`?** No — examine is
   observational and deferred is appropriate for any reactions that observe it.
   There is no scenario where a reaction needs to fire "before the examine
   description is shown."

2. **Better scenario generator rules.** The decision table at
   `scenario-generation.md:745` should be coded as generator logic:
   - Scenario clauses with "notice" / "see" / "recognize" / "spot" /
     "reveal" / "discover" (passive discovery) → `on_examine`
   - Scenario clauses with "pull" / "force" / "search" / "rummage" /
     "pick" / "hauls" (active manipulation) → `interaction`
   - Validate: entity-specific content goes on entity, not room.

3. **Add `once`-like behavior to OnExamineEvent?** No — flag-gating is
   idiomatic and consistent with the rest of the system. Adding `once` to
   OnExamineEvent would create a second `once` mechanism with different
   semantics (global vs per-event-scope) and increase the surface.

---

## Appendix: Line References

| Component | File | Lines |
|-----------|------|-------|
| `OnExamineEvent` model | `mgmai/models/corpus.py` | 225–240 |
| `ReactionEffects` model | `mgmai/models/corpus.py` | 250–264 |
| `Reaction` model | `mgmai/models/corpus.py` | 268–282 |
| `Room.on_examine` | `mgmai/models/corpus.py` | 294 |
| `Entity.on_examine` | `mgmai/models/corpus.py` | 392 |
| `Room.reactions` | `mgmai/models/corpus.py` | 296 |
| `Entity.reactions` | `mgmai/models/corpus.py` | 415 |
| `IMMEDIATE_ALLOWED_EVENTS` | `mgmai/models/corpus.py` | 9–13 |
| `Interaction` model (field comparison) | `mgmai/models/corpus.py` | 184–208 |
| `resolve_examine()` | `mgmai/engine/resolver.py` | 164–253 |
| `_fire_on_examine_events()` | `mgmai/engine/resolver.py` | 1455–1525 |
| `_emit_event()` | `mgmai/engine/resolver.py` | 64–107 |
| `_resolve_interaction_check()` (used for on_examine checks) | `mgmai/engine/resolver.py` | 1078–1138 |
| `find_matching_reactions()` | `mgmai/engine/event_bus.py` | 50–106 |
| `dispatch_reactions()` | `mgmai/engine/event_bus.py` | 138–304 |
| `_resolve_self()` | `mgmai/engine/event_bus.py` | 323–364 |
| `_dispatch_events()` (engine-level) | `mgmai/engine/engine.py` | 1038–1080 |
| State-change event derivation | `mgmai/engine/engine.py` | ~479–499 |
| Schema docs: on_examine | `schema/corpus.md` | OnExamineEvent section (~40 lines) |
| Schema docs: reactions | `schema/corpus.md` | Reaction section (~80 lines) |
| Scenario gen: decision table | `schema/scenario-generation.md` | 745–770 |
| Scenario gen: entity vs room placement | `schema/scenario-generation.md` | 405–425, 1221–1225 |
| Scenario gen: multiple on_examine | `schema/scenario-generation.md` | 1227–1232 |
| Scenario gen: validation checklist | `schema/scenario-generation.md` | 1258–1259 |
| Validate: on_examine references | `scripts/validate_adventure.py` | 65–68 (addable entity collection) |
