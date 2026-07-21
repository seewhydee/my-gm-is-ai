# Design Exploration: Inline Mechanical Indicators

## Problem Statement

Currently, all mechanical indicators (stat check results, HP changes, stat changes, combat log summaries) are **prepended as prefixes** to the AI-generated narration by `GameLoop._execute_turn()`. This produces output like:

```
**[STR check: failed]**

You try to lift the statue. It's too heavy to budge.
```

The desired behavior is to **interleave** these indicators at narratively appropriate points *within* the prose:

```
You try to lift the statue.

**[STR check: failed]**

It's too heavy to budge.
```

There may be multiple indicators per turn, and the placement should be contextually appropriate.

## Current Architecture (simplified)

```
Player Input → Call 1 (ruling) → PlayerAction
PlayerAction → Engine Resolve → EngineResult (rolls, combat_log, hard_state_changes, triggered_narration)
EngineResult → Call 2 (prose) → NarrationOutput (narration string)
GameLoop → prefixes prepended → Display
```

The prefix formatting happens in `GameLoop._execute_turn()` (~lines 281-370 in `loop.py`):
- `format_stat_check_prefix(result.rolls)` — stat check outcomes
- `format_hp_change_prefix(...)` — HP loss/gain  
- `format_stat_change_prefix(...)` — stat modifiers
- `format_combat_prefix(...)` — combat round summaries

These are all concatenated **before** `prose.narration`.

## Design Constraint: Separation of Concerns

The engine knows *what* happened mechanically. The LLM narrator knows *how* to tell the story. The engine should not dictate narrative structure. The LLM should decide where indicators belong — but it must use the engine's canonical formatting, not paraphrase.

This means the engine must **give the narrator the means to place indicators**, and the narrator must **signal where they go**.

---

## Approach 1: Marker-Based Placement (Recommended)

### Idea

The engine assigns each indicator a unique, unlikely-to-collide marker string (e.g. `[MECH:check:0]`, `[MECH:hp]`, `[MECH:combat:2]`). These markers are passed to Call 2 in the prompt. The LLM is instructed to place each marker in its narration at the narratively appropriate point. After Call 2 returns, the GameLoop replaces markers with the corresponding formatted indicator strings. Unplaced markers fall back to being prepended.

### Data Flow

```
EngineResult → build_indicators() → list[Indicator]

Indicator:
  marker_id: str        # e.g. "[MECH:check:0]"
  formatted: str        # e.g. "**[STR check: failed]**"
  category: str         # "check" | "hp" | "stat" | "combat"

Prompt (injected into user_data JSON or system prompt):
  ## Mechanical Indicators
  The following events occurred this turn. Place each marker in your
  narration at the appropriate point. Use each marker exactly once.
  
  - `[MECH:check:0]` — STR check: failed
  - `[MECH:hp]` — Took 9 damage (HP 18/27)
  
  Place markers on their own line, surrounded by blank lines.

LLM Output:
  "You try to lift the statue.\n\n[MECH:check:0]\n\nIt's too heavy to budge."

Post-processing:
  replace_markers(narration, indicators) → final narration
  unplaced = collect_unplaced(indicators, narration)
  prepend(unplaced)  # graceful fallback
```

### Pros
- LLM has full creative control over placement
- Minimal engine complexity — just build indicators and post-process
- Backward compatible: unplaced markers fall back to current behavior
- Works for any number of indicators
- Exact formatting preserved (engine controls the text, LLM controls the position)

### Cons
- Requires prompt engineering to ensure LLM compliance
- One extra post-processing step
- Markers could theoretically collide with legitimate narration (mitigated by choosing a distinctive prefix like `[MECH:`)

### Files to touch
- `mgmai/engine/narrative_indicators.py` — new module
- `mgmai/templates/prose.j2` — add "Mechanical Indicators" section
- `mgmai/game/loop.py` — replace prefix prepending with marker injection + post-processing
- `mgmai/models/narration.py` — possibly add `indicators` field to user_data (or just pass via JSON)

---

## Approach 2: Verbatim Inclusion Instruction

### Idea

Pass the already-formatted indicator strings to the LLM and instruct it to include them verbatim in its narration. Post-process to ensure they are bolded consistently.

### Prompt Addition

```
The following mechanical indicators must appear verbatim in your narration.
Place each at the narratively appropriate point:

**[STR check: failed]**
**[Took 9 damage (HP 18/27)]**
```

### Pros
- No markers needed — simpler prompt
- LLM sees the final formatted text

### Cons
- LLM may paraphrase, omit, or split the indicator across sentences
- Hard to validate: did the LLM include the exact string?
- Fragile — formatting consistency relies on LLM obedience
- If LLM omits an indicator, we still need fallback logic

### Verdict
Too fragile. The LLM will sometimes rephrase `[STR check: failed]` as "your strength check failed" or omit it entirely. We'd need marker-style validation anyway, so markers are strictly better.

---

## Approach 3: Structured Segment Output

### Idea

Change the LLM output format so narration is an array of segments, each optionally tagged with a mechanical event:

```json
{
  "narration_segments": [
    {"text": "You try to lift the statue.", "event": null},
    {"text": "", "event": "roll:0"},
    {"text": "It's too heavy to budge.", "event": null}
  ]
}
```

### Pros
- Very structured, easy to validate and test
- No risk of marker collision

### Cons
- Major schema change to `NarrationOutput`
- LLM may struggle with segment-based generation (more cognitive load)
- Restricts narrative flow — segments break natural paragraph boundaries
- Would require retraining/prompt-tuning the prose template significantly

### Verdict
Over-engineered for this problem. The marker approach achieves the same goal with less disruption.

---

## Approach 4: Post-Hoc NLP Insertion (No LLM Cooperation)

### Idea

Generate narration normally. Then use heuristics or a lightweight model to insert indicators at "appropriate" points:
- HP change after damage-describing sentences
- Stat check after attempt-describing sentences
- Combat entries interleaved between action descriptions

### Pros
- No prompt changes needed
- Works with any LLM output

### Cons
- Heavily heuristic-dependent
- Will frequently misplace indicators
- English language understanding required (or an LLM call for placement, which is wasteful)
- Hard to maintain and extend

### Verdict
Too brittle. The whole point is to let the narrator decide placement based on its own narrative structure.

---

## Approach 5: Streaming / Multi-Pass Generation

### Idea

Instead of one Call 2, stream or multi-pass:
1. Generate narration up to first mechanical event
2. Insert indicator
3. Generate next segment
4. Repeat

### Pros
- Perfect placement by construction
- No markers needed

### Cons
- Requires streaming or multiple LLM calls per turn
- Massive complexity increase
- Chained actions already complicate the flow
- Latency would suffer significantly

### Verdict
Not worth the complexity. Single-call marker approach is equivalent in outcome at a fraction of the cost.

---

## Comparison Summary

| Approach | LLM Cooperation | Engine Complexity | Prompt Complexity | Robustness | Latency |
|----------|----------------|-------------------|-------------------|------------|---------|
| **1. Markers** | Yes (places markers) | Low | Medium | High (fallback) | Same |
| 2. Verbatim | Yes (includes text) | Low | Low | Low | Same |
| 3. Segments | Yes (structured output) | Medium | High | High | Same |
| 4. Post-hoc NLP | No | High | None | Low | Same |
| 5. Multi-pass | Yes (incremental) | Very High | Medium | High | Worse |

---

## Recommended Design: Approach 1 (Markers)

### New Module: `mgmai/engine/narrative_indicators.py`

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class NarrativeIndicator:
    marker: str          # e.g. "[MECH:check:0]"
    formatted: str       # e.g. "**[STR check: failed]**"
    category: str        # "check" | "hp" | "stat" | "combat"

def build_indicators(result: EngineResult, hard_state: HardGameState) -> list[NarrativeIndicator]:
    """Build ordered list of indicators from an EngineResult."""
    indicators: list[NarrativeIndicator] = []
    
    # Stat checks: one per roll
    check_idx = 0
    for roll in result.rolls or []:
        check_type = roll.get("check_type") or roll.get("type")
        if check_type == "stat_check":
            stat = roll.get("stat")
            success = roll.get("success")
            if stat is not None and success is not None:
                outcome = "success" if success else "failed"
                indicators.append(NarrativeIndicator(
                    marker=f"[MECH:check:{check_idx}]",
                    formatted=f"**[{stat} check: {outcome}]**",
                    category="check",
                ))
                check_idx += 1
    
    # HP change
    hc = result.hard_state_changes
    if hc and hc.player_hp_delta:
        current_hp = hard_state.player.current_hp or 0
        max_hp = hard_state.player.max_hp or 0
        if hc.player_hp_delta < 0:
            formatted = f"**[Took {abs(hc.player_hp_delta)} damage (HP {current_hp}/{max_hp})]**"
        else:
            formatted = f"**[Healed {hc.player_hp_delta} HP (HP {current_hp}/{max_hp})]**"
        indicators.append(NarrativeIndicator(
            marker="[MECH:hp]",
            formatted=formatted,
            category="hp",
        ))
    
    # Stat modifiers
    if hc and hc.stat_modifiers:
        parts: list[str] = []
        for stat_key, mod in hc.stat_modifiers.items():
            old_val = hc.old_stat_values.get(stat_key)
            if mod.mode == "set":
                parts.append(f"{stat_key} set to {mod.value}")
            elif old_val is not None:
                new_val = old_val + mod.value
                sign = "+" if mod.value >= 0 else ""
                parts.append(f"{stat_key} {sign}{mod.value} (now {new_val})")
        if parts:
            formatted = "**[" + "]**\n\n**[".join(parts) + "]**"
            indicators.append(NarrativeIndicator(
                marker="[MECH:stat]",
                formatted=formatted,
                category="stat",
            ))
    
    # Combat log entries
    for i, entry in enumerate(result.combat_log or []):
        formatted = _format_combat_entry(entry)  # extract from format_combat_prefix logic
        if formatted:
            indicators.append(NarrativeIndicator(
                marker=f"[MECH:combat:{i}]",
                formatted=formatted,
                category="combat",
            ))
    
    return indicators


def process_narration(narration: str, indicators: list[NarrativeIndicator]) -> str:
    """Replace markers in narration with formatted indicators.
    
    Any indicators whose markers are not found in the narration are
    prepended in order as a fallback.
    """
    placed = set()
    result = narration
    
    for ind in indicators:
        if ind.marker in result:
            result = result.replace(ind.marker, ind.formatted, 1)
            placed.add(ind.marker)
    
    # Prepend unplaced indicators
    unplaced = [ind for ind in indicators if ind.marker not in placed]
    if unplaced:
        prefix = "\n\n".join(ind.formatted for ind in unplaced) + "\n\n"
        result = prefix + result
    
    return result
```

### Prose Template Addition

Add a new Jinja2 include or section in `prose.j2`:

```markdown
{% if indicators %}
---

## Mechanical Indicators

The following mechanical events occurred this turn. You MUST place each
marker in your narration at the narratively appropriate point — typically
immediately before describing the consequence of that event.

Place each marker on its own line, surrounded by blank lines (`\n\n`),
like this:

```
You try to lift the statue.

[MECH:check:0]

It's too heavy to budge.
```

{% for ind in indicators %}
- `{{ ind.marker }}` — {{ ind.formatted_plain }}
{% endfor %}

If you do not use a marker, the engine will prepend it to your narration
automatically. Use each marker exactly once.
{% endif %}
```

Note: `ind.formatted_plain` strips the markdown bolding so the LLM sees
`STR check: failed` rather than `**[STR check: failed]**` — we don't want
the LLM to emit the bolding itself, just the marker.

### Changes to `GameLoop._execute_turn()`

```python
# Before Call 2:
indicators = build_indicators(result, hard)

# In user_data for the prompt:
user_data = {
    # ... existing fields ...
    "indicators": [
        {"marker": ind.marker, "description": ind.formatted_plain}
        for ind in indicators
    ],
}

# After Call 2 returns:
narration = process_narration(prose.narration, indicators)
```

The existing prefix logic (lines 352-370) is replaced by the single
`process_narration()` call.

### Fallback Path (LLM Call 2 Failure)

When `LLMOutputError` is caught and we fall back to `triggered_narration[0]`,
we keep the old prefix behavior — there's no LLM-generated narration to
weave markers into, so prepending is the only option.

---

## Open Questions

1. **Should this be opt-in per adventure?** Some adventures may prefer the
top-of-turn summary style. A corpus-level flag like `inline_indicators: true`
would allow per-adventure control.

2. **Combat log granularity:** `format_combat_prefix()` currently produces
a single block of combat summaries. Should each combat log entry get its
own marker, or should combat stay as a single block? Per-entry markers
would allow the narrator to weave combat events throughout the narration
(e.g. "The goblin lunges. [combat:0] You parry and strike back. [combat:1]").

3. **Triggered narration interaction:** `triggered_narration` is canonical
engine text that the LLM weaves in. If triggered narration contains a
description of a check result, should we suppress the corresponding
indicator to avoid duplication? Or trust the LLM to handle it?

4. **Ordering of unplaced indicators:** If the LLM places some but not all
markers, the fallback prepends unplaced ones in engine order. Is this
always correct? Should we allow the LLM to explicitly say "skip this
indicator"?

5. **Marker distinctiveness:** `[MECH:...]` is unlikely to appear in
fantasy narration, but we should verify. Alternatives: `[[MECH:...]]`,
`<MECH:...>`, `{{{MECH:...}}}`. The more distinctive, the safer.

---

## Minimal Viable Implementation

If you want to test this without touching the schema or templates:

1. Add `mgmai/engine/narrative_indicators.py` with `build_indicators()` and `process_narration()`.
2. In `GameLoop._call_prose()`, append indicator instructions to the user_prompt JSON.
3. In `GameLoop._execute_turn()`, call `process_narration()` after Call 2.
4. Keep the fallback path unchanged.

This is a pure add-on with no breaking changes. If it works well, we can
migrate the template-based instructions into `prose.j2` for cleaner
separation.
