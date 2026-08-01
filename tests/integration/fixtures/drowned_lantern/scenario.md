# The Drowned Lantern

An LLM-driven integration-test fixture for the NPC conversation
system.  It consists of a small but complete scenario: two rooms,
three talking NPCs with interlocking secrets, and one dead bird.

## Setting

The Drowned Lantern is a tavern built on stilts over the reed-choked
edge of Miremarsh.  It is night; a storm is threatening.  The player
is a traveler needing to cross the marsh, but the ferry isn't running:
the ferryman, BERRIN, vanished a tenday ago.  His widow MARTA keeps
the tavern.  A toll-man, Sergeant DOVIC, has set up at the ferry pier
gate and lets no one through.  Old FEN, a half-mad fisherman, mends
nets on the dock and talks to the marsh.

The truth (known in full to no one): Berrin followed a lantern-light
out on the marsh — a corpse-light, not a boat — and never came back.
Dovic saw the light that night, argued with Berrin on the pier, and
let him row out alone; he is sick with guilt and covers it with
bluster.  Marta still lights the signal lantern every night, and last
night something out on the marsh lit a light in answer.  Fen knows the
lights are not lanterns and has stopped trying to make anyone believe
him.

## RPG Mechanics

Standard 5e-like checks as used throughout the engine, with CHA checks
for persuasion attempts.  The player character is a capable but
unremarkable traveler armed with a longsword.

## Rooms

### Common Room (START)

The tavern's single warm room: peat fire, a few empty tables, damp
lantern-glow.  MARTA is behind the bar.  On a shelf above the bar sits
OLD WELLINGTON, a stuffed heron (implemented as a dead NPC).

A cellar door behind the bar is locked (Marta has the key).

A back door leads to the DOCK.

The front door leads out to the main road and thence back to town, but
the traveler is gently turned away if they try to return that way --
the GM notes that they really need to get across the marsh.  (This is
a strictly impassable exit.)

### Dock

A set of dilapidated wooden docks behind the tavern.  A door leads
back into the tavern.  There is a single pier, blocked by a chained
gate; beyond, the empty ferry is moored to the pier.  A dense fog is
rolling in off the marsh, lit by a single dim lantern above the gate.

Beside the gate slouches Sergeant DOVIC, looking bored.  He holds the
key to the locked gate.

Old FEN sits on the dock, mending a fishing net. His crickety rowboat
is lashed to the dock.




## Purpose — what is under test

Engine-enforced behaviors (hard assertions in the tests):

- **Attitude tracking**: per-NPC `attitude_limits` (min/max/step_per_turn/
  initial); engine post-validation of LLM-proposed attitude changes;
  frozen attitudes (0/0 limits); attitudes persisting across dialogue
  exit/re-entry and across NPC switches.
- **Knowledge gating**: `will_reveal` topics with tiered `conditions`
  (unconditional, attitude-gated, flag-gated); side effects `set_flag`
  and `set_entity_state` (revealing a hidden object); recording into
  `player_knowledge`; dedup across repeated conversation.
- **Dialogue paths**: stat-checked persuasion with `repeatable` and
  non-repeatable checks, `condition` gating, success/failure branches
  with `set_flag`/`set_entity_state`/`adjust_attitude`; a failure
  branch that is an authored *lie* (narration with no state change).
- **Dialogue lifecycle**: entry on `talk`; exit via `ends_dialogue`,
  room change, and stall (3 consecutive non-talk turns); conversation
  note archival into `entity_notes` on exit; `dialogue.ended` events
  firing reactions.
- **NPC switching**: talking to NPC B while in dialogue with NPC A
  archives A's conversation (`switched_npc`); each NPC's attitude and
  memory are independent.
- **NPC-initiated dialogue**: a `room.entered` reaction with
  `trigger_dialogue` makes an NPC speak first.
- **Talk gating**: `talk` rejected during combat ("Cannot hold a
  conversation during combat"); `talk` rejected targeting a dead NPC.
- **Attitude-threshold reaction**: an NPC aggros into combat when his
  attitude hits the floor, via an `attitude.changed` reaction.

LLM-discretion behaviors (advisory judge rubric, never hard-gated):

- Persona/voice consistency per NPC (`dialogue.guidelines`).
- Knowledge scope: NPCs must not leak information outside their
  authored scope (the fisherman knows nothing of tavern gossip, etc.).
- Lie consistency: an NPC who lies must narrate the lie without the
  hard state changing, and must not "come clean" unprompted.
- Memory: after a conversation is archived, re-engaging the NPC should
  feel continuous (the GM sees the archived `entity_notes`).



## NPCs

### Marta (barkeep, common room)

Warm, shrewd, tired; a good listener who gives gossip freely but
guards family matters.  Attitude: initial 0, min -10, max 10,
step_per_turn 2.

Knowledge scope: the tavern, marsh gossip, the comings and goings of
locals.  She knows nothing about what actually lives in the marsh.

`will_reveal` topics (tiered):

- `ferryman_missing` — conditions: [] (unconditional).
  Her husband Berrin, the ferryman, vanished on the marsh a
  tenday ago; the ferry hasn't run since.  Sets flag
  `heard_ferryman_missing`.
- `dovic_distrust` — conditions: attitude >= 3.  She saw Dovic arguing
  with Berrin on the pier the night he vanished, and doesn't trust the
  man, though she can't say why it sits wrong.  Sets flag
  `suspects_dovic`.
- `signal_light_secret` — conditions: attitude >= 6.  The thing she has
  told no one: she still lights the signal lantern each night, and last
  night a light answered from deep in the marsh.  Sets flag
  `knows_signal_secret` AND `set_entity_state` revealing BERRIN'S
  LOGBOOK (`logbook.hidden: false`), which she pulls from beneath the
  bar — he wrote about the lights before he vanished.

Positive conversation (respect, sympathy, actual effort) can raise her
attitude at the GM's discretion — not handed out like candy.
Mockery lowers it.

`dialogue_paths`:

- `persuade_cellar_key` — "Convince Marta to trust you with the brass
  cellar key (spare lamp oil is down there)."  Condition: attitude >= 1.
  CHA check, DC 12, non-repeatable.  Success: she hands it over —
  `set_flag marta_gave_cellar_key`, and `adjust_attitude` marta +1 (the
  trust itself warms her).  Failure: she politely declines; no state
  change.

### Old Fen (fisherman, dock)

Half-mad, speaks in riddles and half-rhymes about the marsh and its
lights.  Beyond caring what anyone thinks of him: attitude FROZEN at 0
(limits min 0, max 0).

NPC-initiated dialogue: a `room.entered` reaction on the dock fires
`trigger_dialogue: fen` (condition: fen present and not yet departed).
He speaks first: "You.  You've the look of a crossing."

Knowledge scope: the marsh, the tides, the lights.  He knows NOTHING of
tavern gossip, Marta's marriage, or Dovic's arrangements — and his
answers to such questions should be riddling non-answers (judge-checked).

`will_reveal` topics:

- `fen_warning` — conditions: [] (unconditional).  The marsh lights are
  not lanterns, and no boat answers them; do not follow a light on the
  water.  Sets flag `heard_fen_warning`.

Reactions:

- `fen_departs_after_dialogue` — on `dialogue.ended`, condition
  `event:npc_id == fen` and `entity:fen.delivered_warning == true`.
  He pushes his rowboat off into the fog and is gone:
  `set_entity_state` fen `departed: true`, `location: null`.
  `fen_warning`'s reveal sets `delivered_warning: true`
  via `set_entity_state`.

### Sergeant Dovic (toll-man, dock)

Surly, officious, suspicious; secretly rattled by guilt about Berrin
and covering it with bluster.  Attitude: initial -2, min -10, max 0,
step_per_turn 1 — he can never be brought to actually like the player.

Knowledge scope: tolls, the gate, town business.  He volunteers
NOTHING about Berrin — no `will_reveal` at all; his knowledge comes
out only through dialogue paths, or not at all.

`dialogue_paths`:

- `persuade_gate_passage` — "Convince Dovic to unchain the ferry pier
  gate and let you through without paying."  Condition: attitude >= -2.
  CHA check, DC 12, repeatable.  Success: he actually unchains the gate
  — `set_flag gate_open`, `set_entity_state` gate `locked: false`.
  Failure: **he lies** — in an oily, reasonable voice he agrees to open
  it "in just a moment", and does not move (narration only, NO state
  change).  The lie is the point of the test:
  hard state must stay closed while the narration says he agreed.
- `press_about_berrin` — "Press Dovic about his argument with Berrin
  the night the ferryman vanished."  Condition: flag `suspects_dovic`
  (the player must have heard Marta's distrust first — a cross-NPC
  knowledge dependency).  CHA check, DC 15, repeatable.  Success: he
  cracks — admits he saw the lantern-light on the water that night and
  said nothing; `set_flag dovic_confessed`, `adjust_attitude` dovic +2
  (unburdened, capped at his max of 0).  Failure: he lies flatly — he
  barely knew the man, never spoke to him (narration only) — and
  `adjust_attitude` dovic -1.

Aggro: an `attitude.changed` reaction (`dovic_aggro`, condition
`event:entity_id == dovic` and `entity:dovic.attitude <= -10`)
triggers combat (he is a competent but beatable veteran — tough enough
that fleeing back into the tavern is the sane option).  Insults and
threats drop his attitude without any check.

### Old Wellington (stuffed heron, common room)

A long-dead heron, stuffed and mounted above the bar, one glass eye
missing.  Authored as an `npc` entity with `alive: false` from the
start — the dead-NPC test target.  Talking to him must be rejected by
the engine ("NPC 'old_wellington' is dead"); no dialogue ever starts
with him.

## Cross-NPC dependencies (why this is one scene, not three)

- Dovic's `press_about_berrin` path is gated on Marta's `suspects_dovic`
  flag — the player must work the tavern before working the dock.
- Marta's tiered reveals reward a long, warm conversation (attitude 3,
  then 6), while Dovic punishes a hostile one (aggro at -10) — both
  directions of the attitude system in one scene.
- Fen's frozen attitude and unconditional reveal contrast with Marta's
  merit-based ladder, and his departure-on-dialogue-end exercises the
  `dialogue.ended` reaction path.

## Test scenarios (tests/integration/test_drowned_lantern.py)

All scenarios run the standard harness (`run_scenario`, LLM driver,
advisory judge) with generous `max_turns` (up to 100 — turn limits are
deliberately long for conversation) and `stop_when` predicates where a
natural end state exists.  Hard assertions use per-turn
`status.dialogue` (active_npc, topics_discussed, stall_counter, active
NPC attitude), `status.active_flags`, and the soft-state augmentation
in `final_status` (`entity_notes`, `player_knowledge`,
`dialogue_state`).

1. **marta_rapport_unlocks_secrets** (~60 turns).  Directive: be warm
   and genuinely interested; ask about the ferryman, the marsh, Dovic.
   Hard: attitude rose and stayed within bounds; per-turn attitude
   steps respected step_per_turn; `heard_ferryman_missing` set;
   `suspects_dovic` set; `player_knowledge` contains the revealed
   topics with source `marta`.  Conditional (warn, not fail):
   `knows_signal_secret` + logbook unhidden (requires attitude 6).
2. **marta_cellar_key_persuasion** (~40 turns).  Directive: earn some
   goodwill, then persuade her to lend the cellar key.  Success branch:
   `marta_gave_cellar_key` set.  RNG-gated — conditional assert +
   `warnings.warn` per venom_pit convention.
3. **fen_speaks_first_and_departs** (~30 turns).  Directive: go to the
   dock, hear Fen out, talk with him, then say goodbye (or go back
   inside).  Hard: dialogue active with `fen` immediately on room entry
   (trigger_dialogue); `heard_fen_warning` set; after dialogue ends,
   fen `departed` and gone; a conversation note archived for fen.
4. **stall_exit_and_memory** (~40 turns).  Directive: start talking to
   Marta, then get distracted — examine the heron, the fire, the cellar
   door — for several turns, then re-engage her and refer back to the
   earlier chat.  Hard: stall_counter climbed to 3 and dialogue exited;
   `entity_notes["marta"]` non-empty after exit; second conversation
   opens fresh (entered_turn advanced).  Judge: the GM's re-engagement
   shows continuity with the archived note.
5. **dovic_lies_about_passage** (~50 turns).  Directive: try to talk
   Dovic into opening the gate, without hostility.  Hard: gate state is
   consistent — either `gate_open` + unlocked (check passed) or still
   locked with NO flag despite any narrated agreement (the lie).
   Judge: on failure branches, Dovic's agreement was narrated as
   insincere and he never "comes clean" unprompted.
6. **dovic_press_and_aggro** (~60 turns).  Directive: after learning
   Marta's suspicion, press Dovic about Berrin; be increasingly hostile
   when he stonewalls.  Hard: `press_about_berrin` only available after
   `suspects_dovic` (condition gating — indirect: no `dovic_confessed`
   without `suspects_dovic`); attitude floored at -10; combat started
   via the aggro reaction; `talk` during combat rejected (dialogue
   never active while `in_combat`); combat concluded by win or flee.
7. **old_wellington_is_dead** (~15 turns).  Directive: attempt to talk
   to the stuffed heron, persist once or twice, then give up and chat
   with Marta.  Hard: dialogue never active with `old_wellington`;
   engine rejection surfaced in narration/errors; talking to Marta
   afterward works normally (no corrupted dialogue state).

## Harness dependencies

This fixture relies on two harness additions (see
`tests/integration/README.md` once landed):

- `StatusSnapshot.dialogue`: per-turn `{active_npc, topics_discussed,
  stall_counter, entered_turn, log_length, attitude}` from soft state.
- `ScenarioResult.final_status` soft augmentation: `entity_notes`,
  `player_knowledge`, final `dialogue_state`.
- The driver situation line announces the active conversation partner
  so the LLM player behaves sanely in multi-topic dialogues.
