# Scenario Map — "The Drowned Lantern"

Working plan for the adventure module, from `scenario.md`.  All IDs
are snake_case; `self` is reserved.

This module is an integration-test fixture for the NPC conversation
subsystem (see `tests/integration/fixtures/`).  Design priority: the
scene must be human-playable as a mini-adventure *and* exercise a
broad surface of the conversation engine (attitude ladders, tiered
will-reveal topics, condition-gated dialogue paths, checked
persuasion, lies, NPC-initiated dialogue, scripted mid-dialogue
events, dialogue-ended reactions, dead-NPC rejection, cross-NPC
knowledge dependencies).  A coverage table lives at the end of this
document.

## Preamble: game mechanics implementation plan

### Ghost light seen from the dock

The adventure's first set-piece occurs when the player and Fen,
conversing on the dock, sees a ghost light on the marsh.

[Implementation note: I'm not sure how this should be implemented. A
conversation trigger on Fen, or what?]

The ghost light lingers for two turns, giving the player a fleeting
chance to *attempt* interacting with it (no such attempts will
succeed).

1. The light is narrated as appearing. Fen draws attention to it.

2. The light bobs twice, as though beckoning to them.

3. The light winks out, as mysteriously as it appeared. Fen shakes his
   head and mutters something pensively.

### Convincing Berrin

The player's goal is to persuade Berrin to bring them across the marsh
*tonight*, rather than waiting for morning.  This involves passing
Berrin's `convince_crossing` dialogue path.  Initially, this fails for
various reasons (e.g., Berrin denies that he runs at night, says to
come back in the morning).

To succeed in this dialogue path, the player must (i) hear Berrin's
confession about the ill-fated crossing where Janis died, and (ii)
convince Berrin to let them accompany him on a final nighttime run to
deliver the sealed crate.

Mechanically, this means first passing one of the following dialogue
paths:

- the `bluff_janis` dialogue path, gated by the `heard_janis_name`
  [flag](#1d.-global-flags) and a moderately hard CHA check, OR

- the `confront_janis` dialogue path, gated by the `heard_janis_name`
  AND `knows_janis_link` flags.

These flags are activated through conversation, as explained below.
Either dialogue path, once successful, sets the `berrin_confessed`
flag, and triggers Berrin's story (the smuggling, Janis going after
the ghost light and drowning, etc.).

Once the `berrin_confessed` flag is set, another try at the
`convince_crossing` dialogue path succeeds.  Once successful, (i)
Berrin asks the player to help shift the crate (narratively, he
informs the player of its existence if they didn't already know); and
(ii) the `confided_crate` flag is set (if not already), enabling the
player to discover the crate if they haven't already.

### The sealed crate

The `sealed_crate` behind the bar is initially `hidden` (state field).
The `hidden` state is set to null if the player does an `examine`
action on `bar`, gated by `confided_crate` (Marta or Berrin revealing
its existence to the player).  If the examination fails (gate active),
the player merely observes a bunch of empty bottles and other junk.

The crate has a `move` interaction, gated by `crossing_agreed`.
Successfully using this interaction does the following:

- If `sealed_crate` is in `common_room`, move the player, Berrin, and
  the crate to `dock`.
  
  Narratively, the player and Berrin lug the crate out of the tavern.
  The crate's now sitting on the dock.  Berrin jumps onto the ferry
  and lights `ferry_lantern` (atmospherics only).

- If `sealed_crate` is in `dock`, move the crate to `ferry`.
  Narratively, the player and Berrin lug the crate onto the ferry.
  This sets the `crate_loaded` flag, ungating the `board_ferry` exit.
  
  [Implementation note: maybe we should add a `contains` condition
  string to the corpus schema, so that `crate_loaded` can be replaced
  with direct game logic.]
  
  [Implementation note: the player and Berrin are narratively in the
  ferry, but I think they shouldn't be placed in it, right?  Check the
  engine.  Might need to clarify this in the schema docs.]

### Endgame: on the marsh

The endgame sequence plays out once the player uses the `board_ferry`
exit from `dock`.  This exit leads to the `mid_marsh` room; Berrin
comes along, together with the ferry and its contents (the ferry rope
and the crate).

Entering `mid_marsh` begins a set of scripted events, implemented as
room-scoped reaction mechanics firing in sequential turns: (i) rowing
in silence – mood setting, (ii) still rowing in silence – more mood
setting and tension building, (iii) ghost lights appear, (iv) Berrin
is terrified but continues rowing; ghost lights track the ferry; (v)
transition to `far_shore`.

[Implementation note: do we implement these sequential-turn events by
chaining global flags (requires a proliferation of flags, bit ugly)?
Or is there a better way (maybe requiring changes to game schema)?]

Entering `far_shore` begins the final sequence of scripted events also
implemented as room-scoped reaction mechanics: (i) the ferry
approaches the pier – mood setting, (ii) very close now to the pier;
Berrin asks the player to grab the rope and jump onto the dock, which
ungates the `exit_pier` exit (a dummy exit for the winning endgame).

### Endgame conditions

Attacking any of the three living NPCs (Berrin, Marta, or Fen)
triggers a losing endgame.  Narratively:

- The other NPCs, if present, become aware of the player's aggression
  (if the player attacks Fen, one of the other NPCs appears by the
  door); they flee into the night, and it becomes impossible to cross
  the marsh.
  
- If alone on the ferry with Berrin, attacking causes him to fall in
  the water.  The ghost lights then close in, and the game ends with
  the player coming to an unknown grisly fate in the marsh.

At the docks, or at any point during the marsh crossing, jumping in
the water leads to a losing endgame.  (The water is far colder than
the player expects, and some mysterious force paralyzes their limbs,
causing them to drown.)

The sole winning endgame is reached by traversing the `exit_pier` exit
of the `far_shore` room.  This exit is made available by the ferry
approaching the pier (we can use a state field on `far_shore` for
this), AND the player carrying `rope_end`.  Upon using this exit, the
endgame narration triggers:

- The player hears Berrin's cry and a splash, turns, and sees that
  Berrin has disappeared.  No splashing in the water — he is gone
  without a trace.
  
- The ghost lights slowly wink out one by one, until all the player
  can see is the fog itself, lit by the ferry's pole-lantern.

- The player gloomily turns their back on the marsh, and trods away
  along the muddy track.

---

## 1A. Adventure Metadata

- **Title:** The Drowned Lantern

- **Credits:** (C) 2026 Chong Yidong.  GPL v3+ (same as the engine).
  Written as an integration-test fixture for the "My GM is AI" engine.

- **Introduction** (verbatim, second-person, no spoilers):

  > Fog sits heavy on Miremarsh tonight, and you need to be across it
  > by morning.  The only crossing for miles is the ferry tied up
  > beside the Drowned Lantern, a tavern on stilts at the marsh's
  > edge — but the ferry isn't running.  Warm lamplight spills from
  > the tavern door.  Someone inside will know why.

- **Adventure ID:** `drowned_lantern`

- **Atmosphere** (no spoilers): a lonely stilted tavern on the edge of
  a fog-drowned marsh at night — peat smoke, damp lamplight, creaking
  pilings.  Melancholy folk-horror tone: everyone here is keeping a
  small guilty secret, and the marsh is keeping a bigger one.  The
  horrors stay offstage; the drama is in what people will and won't
  say.

- **Player stats:** This adventure uses player stats.

  - **Stats used:** the six 5e ability scores (STR, DEX, CON, INT,
    WIS, CHA), proficiency bonus, HP, AC, saving throws.  Skills and
    other 5e mechanics are unused.
  - **Resolution system:** 5e (stat checks; no combat encounters are
    planned — see Errata, item 4).
  - **Initial player stats:** Class Fighter; Race Human; Level 3;
    STR 14, DEX 12, CON 13, INT 10, WIS 11, CHA 12; Proficiency
    Bonus +2; HP 24 (current 24 / max 24); AC 13 (leather + DEX);
    Saving Throws: STR, CON.  CHA 12 is deliberate: the adventure is
    persuasion-centric, so the player's CHA checks (DC 9–12) should
    succeed often enough to keep the story moving.
  - **Starting inventory:** a longsword (equipped; standard SRD item,
    not redeclared in the module corpus).
  - *Omissions (for the post-task report):* the scenario gives no
    player stats at all; the above are reasonable defaults chosen for
    the fixture.  No initiative modifier or unarmed damage specified;
    5e-flavored defaults will be needed if combat stats are written.

---

## 1B. Rooms (Pass 1)

### `common_room` — "Common Room"  **[START ROOM]**

The Drowned Lantern's single warm room: a peat fire, a few empty
tables, damp lantern-glow.  MARTA is behind the bar; above the bar
sits OLD WELLINGTON, a stuffed heron.  Behind the bar (unnoticed) is
the last smuggling crate.  BERRIN sits alone, glumly nursing an ale.
A back door leads out to `dock`.

### `dock` — "Dock"

A slick wooden pier beside the tavern, fog rolling off the marsh.  FEN
sits mending his net beside a flickering lantern.  The empty marsh
ferry is lashed here.  The only way on or off the water is the ferry.

### `mid_marsh` — "Miremarsh"

Open black water in the heart of the marsh: the ferry mid-crossing,
reed-banks looming and vanishing in the fog.  Transitional room for
the endgame crossing (see Errata, item 3).  The far shore lies ahead.

Moving from `mid_marsh` to `far_shore` occurs by scripting only
(Berrin rows).  Jumping into the water is a game-over.

### `far_shore` — "Far Shore"

A rotting pier on the far side of Miremarsh, solid ground at last.
Entering this room ends the adventure (the endgame sequence plays out
here).  Jumping into the water is a game-over.

---

## 1C. Entities (Pass 1)

### `player` — "you" (type: `player`)

The player character (stats in §1A): a traveler who urgently needs to
cross the marsh tonight.  Starts in `common_room`, longsword equipped.

### `berrin` — "Berrin" (type: `npc`, in `common_room`)

The marsh ferryman, initially found sitting in `common_room` glumly
nursing an ale (he moves to other rooms in the endgame sequence).  He
refuses to ferry anyone at night ("I don't work at night" — a lie).
Secret: for the past month he ran a smuggling scheme with JANIS; a
week ago Janis leapt off the ferry mid-crossing, mesmerized by a ghost
light, and vanished.  Berrin fled back to shore, terrified; he has
seen lights on the water since and fears they are coming for him.  He
is the only one who can pole the ferry.

### `marta` — "Marta" (type: `npc`, in `common_room`)

The tavernkeeper of the Drowned Lantern, a widow, behind the bar in
`common_room`.  Warm, shrewd, doesn't stick her nose in others'
affairs.  She knows the ferryman is supposed to work nights.
Secretly, she took money from JANIS to stash crates behind the bar;
one crate remains, Berrin was supposed to have moved it out by now,
and she is becoming concerned.

### `fen` — "Fen" (type: `npc`, in `dock`)

An old, rather addled fisherman, mending his net by a flickering
lantern on the dock.  He speaks in rambling, half-riddling fragments.
He saw Berrin regularly crossing at night with a stranger until a week
ago.  He is wary of the marsh lights, and deems them malevolent.
While in conversation with the player, he will blurt out — and
instantly forget — the name "Janis" (how he knows the name will remain
a mystery).  Once he has said everything he has to say, he gathers up
his net and shuffles off into the night.

### `old_wellington` — "Old Wellington" (type: `npc`, in `common_room`)

A long-dead heron, stuffed and mounted above the bar, one glass eye
missing.  Authored as an NPC who is dead from the start (`alive:
false`): talking to him must be rejected by the engine.  (He is the
fixture's dead-NPC test target; see Errata, item 1.)

### `bar` — (type: `feature`, in `common_room`)

The bar in the tavern's common room.  The sealed crate is modelled as
a feature contained in (hidden behind) the bar.

### `sealed_crate` — (type: `feature`, in `bar`)

The last of Janis's crates, stashed behind the bar in `common_room`.
Sealed; contents unknown (and never opened in this module).  Initially
hidden behind the bar.  Too heavy and bulky for the player to pick up
into inventory, hence a feature not an item.  Moving it requires
Berrin's cooperation (it goes to the ferry at night).

### `ferry` — (type: `feature`, in `dock`)

A flat-bottomed pole-ferry lashed to the dock.  An examination makes
clear that it needs an experienced hand; the player does not know how
to handle it.  Boarding it (when Berrin agrees) begins the endgame
crossing.

### `ferry_lantern` — (type: `feature`, in `ferry`)

A lantern hung on a pole, built into the ferry.  It is initially
unlit, but Berrin lights it during the endgame marsh crossing.

### `peat_fire` — (type: `feature`, in `common_room`)

The smoldering peat fire in the Drowned Lantern's common room.  Flavor
/ examination texture.

### `fens_lantern` — (type: `feature`, in `dock`)

Fen's battered lantern, sitting on the dock, its flame guttering in
the marsh air.  Flavor / examination texture; echoes the ghost lights.

### `ghost_light` — "ghost light" (type: `feature`, in `dock`)

A ghost light that appears in the distance, during the player's
conversation with Fen on `dock`, then disappears shortly thereafter.
Narratively, it serves to establish that the spooky lights on the
marsh are real.  Cannot be physically accessed, but the player can
examine it (looking from afar).

### `ghost_lights_mid_marsh` — "ghost lights" (type: `feature`, in `mid_marsh`)

A multitude of ghost lights that appear on the marsh while the player
and Berrin are crossing.  They seem to track the ferry as it moves,
but always at a distance.  Cannot be accessed, only looked at.

### `ghost_lights_shore` — "ghost lights" (type: `feature`, in `far_shore`)

A multitude of ghost lights on the marsh as the player and Berrin
approach the far shore.  Cannot be accessed, only looked at.

### `rope_end` — "rope end" (type: `item`, in `ferry`)

The end of a coil of rope, the other end of which is attached to the
ferry.  Modelled as an item contained in `ferry`.  Initially, the rope
is tied to the wooden pier (`dock`), and the GM overrules the player
taking it (e.g., "You hesitate.  Even if you untie the ferry, there's
no way you can run the ferry in the dark, across an unfamiliar
marsh.").  During the endgame sequence, Berrin will instruct the
player to take the rope and jump onto the pier to moor the ferry;
doing so triggers the endgame.

### `pier` — (type: `feature`, contained in `ferry`)


---

## 1D. Global Flags

Knowledge flags track what the player has learned; leverage flags
track what has been unlocked toward the objective.

- **`knows_ferryman_duty`** — The player has learned (from Marta) that
  the ferryman is supposed to work nights — so Berrin's refusal is
  odd.  Initial value: `false`.

- **`confided_crate`** — Marta or Berrin have told the player about the
  last crate and her worry that Berrin hasn't moved it (and implicitly
  asked the player to press him on it).  Gates Berrin's `press_crate`
  path.  Initial value: `false`.

- **`knows_janis_link`** — Marta has admitted that Janis paid her to
  stash the crates — the piece that ties Janis to Berrin's night
  crossings, i.e. that Janis was his accomplice.  Gates Berrin's
  `confront_janis` path.  Initial value: `false`.

- **`knows_night_crossings`** — Fen has revealed that Berrin crossed
  the marsh at night, repeatedly, with a stranger aboard.  Initial
  value: `false`.

- **`saw_ghost_light`** — A ghost light appeared on the marsh during
  the player's conversation with Fen, then vanished (scripted
  mid-dialogue event).  Initial value: `false`.

- **`knows_lights_malevolent`** — Fen has shared his belief that the
  lights are malevolent, appearing more often — an ill omen.  Initial
  value: `false`.

- **`heard_janis_name`** — Fen blurted the name "Janis" in his
  rambling (and immediately forgot saying it).  Gates Berrin's
  `bluff_janis` / `confront_janis` paths and Marta's `janis_payout`
  topic.  Initial value: `false`.

- **`berrin_confessed`** — The player confronted Berrin with the name
  Janis *and* the knowledge of the accomplice link; he broke down and
  confessed the smuggling and the night Janis vanished.  Initial
  value: `false`.

- **`berrin_agreed_crate`** — Berrin has agreed to move the last crate
  tonight (pressed on Marta's behalf).  Initial value: `false`.

- **`crossing_agreed`** — Berrin has agreed to ferry the player across
  tonight.  Initial value: `false`.

- **`crate_loaded`** — The last crate has been lugged down and stowed
  aboard the ferry (done together with Berrin).  Gates the
  `board_ferry` exit.  Initial value: `false`.

---

## 1E. Mechanics

### `begin_crossing` — Kind: Reaction mechanic (endgame sequence)

The `begin_crossing` reaction moves the player to the `mid_marsh`
room.

- Entering : narrate ghost lights appearing on the water,
  seeming to track the ferry (room-entered narration; see §1F,
  `mid_marsh` reaction `lights_track_the_ferry`).

- Entering `far_shore`: the pier is within arm's reach; a strangled
  cry — Berrin is simply *gone*, no sign of him in the water; the
  ghost lights wink out one by one (room reaction
  `berrin_vanishes`: set Berrin `departed = true`, `location =
  null`, narrate; Berrin stays `alive` in hard state — his fate is
  deliberately ambiguous, and a dead Berrin would trip the
  `ferryman_lost` loss condition below).

### `crossing_complete` — Kind: Global game-over condition (WIN)

The player wins upon reaching `far_shore` — they made the crossing,
whatever it cost Berrin.  Checked continuously: player present in
`far_shore`.

### `ferryman_lost` — Kind: Global game-over condition (LOSS)

If Berrin dies (`alive == false`) at any point, the crossing becomes
impossible — there is no one left to pole the ferry.  (This module
has no combat, but the player *can* attack NPCs; see Errata, item 4.)
Checked continuously.

---

## 1F. Rooms (Pass 2)

### `common_room` — "Common Room"  [START]

- **Exits:**
  - **`back_door`** — "out the back door to the dock" → `dock`.
    Always available.
- **Entities present:** `berrin`, `marta`, `old_wellington`,
  `sealed_crate` (hidden), `peat_fire`.
- **Special interactions:** none.
- **Reactions:** none.
- **State fields:** none.
- **On-Examine Effects:**
  - *Rigorous examination only:* the player notices Berrin's hands
    are not steady, and that he keeps glancing at the shuttered
    windows toward the marsh.  Flavor hint that his refusal is fear,
    not laziness.  No state change.
- **Soft-item guidance:** ale mugs, stew bowls, cutlery, a deck of
  dog-eared playing cards, bar rags.

### `dock` — "Dock"

- **Exits:**
  - **`tavern_door`** — "back into the tavern" → `common_room`.
    Always available.
  - **`board_ferry`** — "climb aboard the ferry" → `mid_marsh`.
    Available only when `crossing_agreed == true` AND
    `crate_loaded == true`.  Attempting it otherwise is refused in
    narration (the ferry is lashed tight; without Berrin at the pole
    and his cargo aboard, there is no crossing).  One-way: once the
    crossing begins there is no turning back (narrative reason: the
    marsh current and fog; Berrin would not agree twice).
- **Entities present:** `fen`, `ferry`, `fens_lantern`.
- **Special interactions:** none (boarding is the exit above).
- **Reactions:** none room-scoped (Fen's greeting and ghost-light
  event are Fen-scoped, §1G).
- **State fields:** none.
- **On-Examine Effects:**
  - *Any examination:* the ferry is sturdily built but heavy with
    damp; poling it across a black, fog-bound marsh plainly takes an
    experienced hand.  Flavor reinforcing the objective.  No state
    change.
- **Soft-item guidance:** netting twine, fishhooks, a bait knife,
  cork floats.

### `mid_marsh` — "Mid-Marsh"

- **Exits:**
  - **`far_shore_ahead`** — "toward the far shore" → `far_shore`.
    Always available once here.  One-way.
- **Entities present:** none statically (Berrin is narrated at the
  pole; he remains located in `dock`/`common_room` in hard state
  until `berrin_vanishes` clears him — see implementation notes,
  Errata item 3).
- **Special interactions:** none.
- **Reactions:**
  - **`lights_track_the_ferry`** (one-off): Trigger — player enters
    `mid_marsh`.  Consequences — narrate multiple ghost lights
    appearing on the black water, seeming to pace and track the
    ferry.  No state change (pure narration; the horror stays
    offstage).
- **State fields:** none.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none (open water).

### `far_shore` — "Far Shore"

- **Exits:** none (end of the adventure).
- **Entities present:** none.
- **Special interactions:** none.
- **Reactions:**
  - **`berrin_vanishes`** (one-off): Trigger — player enters
    `far_shore`.  Consequences — narrate the endgame: as the player
    leans forward to spring onto the pier, a strangled cry; turning,
    Berrin has disappeared without a ripple; the ghost lights wink
    out one by one.  Set `berrin.departed = true` and
    `berrin.location = null` (spider precedent).  The win itself is
    handled by the `crossing_complete` game-over mechanic (§1E).
- **State fields:** none.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none.

---

## 1G. Entities (Pass 2)

### `player` — "you" (type: `player`)

- Stats per §1A.  Equipped: longsword.  No special interactions,
  reactions, or take checks.

### `berrin` — "Berrin" (type: `npc`)

- **Location:** `common_room`, at a table alone.
- **State fields:**
  - `attitude` (number, initial `0`) — non-default bounds below.
  - `departed` (boolean, initial `false`) — he vanished during the
    crossing; set by `berrin_vanishes`.
- **Attitude Limits:** min −10, max +10, at most ±2 change per turn
  (engine-enforced).  Glum and guarded, but can be won around.
- **Dialogue availability:** talks freely but deflects anything about
  nights, the marsh, or why he won't work (see Knowledge).  His flat
  refusal — "I don't work at night" — is a *lie*: he is afraid.
  Until confronted, he sticks to it.
- **Dialogue paths:**
  - **`ask_crossing_cold`** — availability: in dialogue,
    `berrin_confessed == false` (i.e. the player lacks leverage).
    The player asks/demands to be ferried across.  No check.  Result:
    he refuses, rehearsed and hollow — he doesn't work at night, the
    marsh kills, come back in daylight.  Narration only; no state
    change.  (Contrast with `convince_crossing`: the same request
    *with* leverage.)
  - **`bluff_janis`** — availability: in dialogue,
    `heard_janis_name == true` AND `knows_janis_link == false` (the
    player drops the name without understanding it).  No check.
    Result: a flicker of fear, then a flat **lie** — "Never heard of
    any Janis." — and he shuts down.  Narration only; `adjust_attitude`
    Berrin −1 (respecting the ±2/turn cap).  This is the fixture's
    authored-lie surface: the narration says one thing, hard state
    confirms he gave nothing.
	
	FIXME: turn this into a moderately hard CHA check


- **`confront_janis`** — availability: in dialogue,
    `heard_janis_name == true` AND `knows_janis_link == true` (the
    player can name Janis *and* lay out the accomplice link).  No
    check — the evidence is overwhelming.  Result: he breaks down and
    confesses: the smuggling, the ghost light, the night Janis went
    over the side, the lights he still sees.  Set flag
    `berrin_confessed = true`; `adjust_attitude` Berrin +2
    (unburdened, respecting caps).
  - **`press_crate`** — availability: in dialogue,
    `confided_crate == true`.  The player presses him, on
    Marta's behalf, to move the last crate tonight.  Success gating:
    CHA check (DC 11, repeatable).  On success: he agrees, grimly —
    set flag `berrin_agreed_crate = true`.  On failure: he balks
    ("Not tonight.") — `adjust_attitude` Berrin −1.
  - **`convince_crossing`** — availability: in dialogue,
    `berrin_confessed == true` AND `berrin_agreed_crate == true`
    (both leverage pieces in place, per the scenario's Objective).
    The player presses him to make the crossing tonight.  Success
    gating: CHA check (DC 12, repeatable).  On success: he gives in —
    better to face the water with company and finish it.  Set flag
    `crossing_agreed = true` (unlocks the `board_ferry` exit).
    On failure: "I can't.  Not tonight." — `adjust_attitude` Berrin
    −1; the player may work on him further and retry.
- **Will-Reveal Topics:**
  - **`janis_vanishing`** — gating: in dialogue,
    `berrin_confessed == true`.  Conveys: the full memory of the
    night Janis died — the light that wasn't a boat, how Janis stood
    up as if called, the water that barely rippled.  Consequences:
    none (flavor/payoff; demonstrates a reveal gated on a dialogue
    *path* outcome rather than attitude).
- **Knowledge:** knows the smuggling scheme in full, Janis, the ghost
  light, and that the lights have kept appearing since.  Will NOT
  volunteer any of it; deflects or lies until confronted.  Knows the
  crates were Marta's side of the arrangement but nothing of her
  feelings about it.  Knows nothing of Fen's watching or what the
  lights are.
- **Aggro / combat stats / combat group:** none — no combat stats;
  if attacked, he dies by the default non-combat handling (and the
  `ferryman_lost` loss fires).  He never initiates violence.
- **First-Meeting Behavior:** none scripted; he barely looks up from
  his ale.

### `marta` — "Marta" (type: `npc`)

- **Location:** `common_room`, behind the bar.
- **State fields:**
  - `attitude` (number, initial `0`).
- **Attitude Limits:** min −10, max +10, at most ±2 change per turn
  (engine-enforced).  Warm but guarded about anything touching the
  crates.
- **Dialogue availability:** talks freely — gossip, the marsh, the
  tavern.  Genuine warmth or sympathy earns her trust (attitude
  increases at GM discretion, within caps — Korbar precedent: real
  effort, not handed out like candy).  Prying bluntly at her business
  earns deflection and, if rude, attitude decreases.
- **Dialogue paths:**
  - **`sympathetic_ear`** — availability: in dialogue.  The player
    listens warmly, commiserates, or earns goodwill.  Success gating:
    CHA check (DC 9, repeatable — rolled once per such exchange, at
    post-validation after the narrator proposes the increase;
    flatter-spider precedent).  On success: `attitude` +1 (within
    caps).  On failure: unchanged.
- **Will-Reveal Topics:**
  - **`ferryman_duty`** — gating: in dialogue (unconditional).  Conveys:
    the ferryman is supposed to work nights — odd that he won't; she
    doesn't pry into others' affairs.  Consequences: set flag
    `knows_ferryman_duty = true`.
  - **`crate_concern`** — gating: in dialogue, `attitude >= 2`.
    Conveys: there's a crate behind the bar Berrin was supposed to
    move out days ago; she's becoming concerned; she'd be grateful if
    someone pressed him on it.  Consequences: set flag
    `confided_crate = true`; set `sealed_crate.hidden =
    false` (she nods toward it behind the bar).
  - **`janis_payout`** — gating: in dialogue, `attitude >= 5` AND
    `heard_janis_name == true` (she won't say the name to someone who
    hasn't already heard it somewhere — a cross-NPC knowledge
    dependency).  Conveys: it was Janis who paid her to stash the
    crates, no questions asked — and Janis used to go out on the
    ferry at night.  Consequences: set flag `knows_janis_link =
    true`.
- **Knowledge:** tavern and village gossip; the ferry schedule;
  that Janis paid her (cash, no questions) and drank little; that
  Berrin and Janis kept each other's company.  Does NOT know about
  the ghost light, the night crossings' purpose, or what became of
  Janis — she assumes he moved on.  Dismisses marsh lights as marsh
  gas.
- **Aggro / combat stats / combat group:** none — default non-combat
  handling if attacked (she simply dies; there is no special loss for
  this beyond the story curdling).
- **First-Meeting Behavior:** welcomes the traveler in out of the
  fog; mentions the kitchen's closed but the fire's warm.

### `fen` — "Fen" (type: `npc`)

- **Location:** `dock`, mending his net by `fens_lantern`.
- **State fields:**
  - `greeted` (boolean, initial `false`) — he has hailed the player
    stepping onto the dock (gates `fen_speaks_first`).
  - `departed` (boolean, initial `false`) — he has shuffled off into
    the night; a departed Fen is removed from play.
- **Attitude Limits:** FROZEN — min 0, max 0 (fly precedent).  He is
  beyond caring what anyone thinks of him; no attitude shifts ever.
- **First-Meeting Behavior / NPC-initiated dialogue:**
  - **`fen_speaks_first`** (recurring): Trigger — player enters
    `dock`.  Condition — Fen alive, `departed == false`, `greeted ==
    false`.  Consequences — initiate dialogue with Fen
    (`trigger_dialogue`): he speaks first, a cryptic mutter — "You.
    You've the look of a crossing."  Set `greeted = true`.
- **Reactions:**
  - **`ghost_light_appears`** (one-off): Trigger — turn end.
    Condition — dialogue active with Fen AND the `night_crossings`
    topic has been discussed in the current dialogue (`topic:`
    condition domain) AND `saw_ghost_light == false`.  Consequences —
    narrate: mid-conversation, a pale light kindles far out on the
    water, drifts, and winks out; Fen goes very quiet.  Set flag
    `saw_ghost_light = true`.  (The scenario's scripted mid-dialogue
    event; "midway" is mechanized as "after the first topic".)
  - **`fen_departs`** (one-off): Trigger — dialogue with Fen ends
    (`dialogue.ended`, any reason).  Condition — `event:npc_id ==
    fen` AND all of his dialogue is exhausted: `knows_night_crossings
    == true` AND `knows_lights_malevolent == true` AND
    `heard_janis_name == true`.  Consequences — he abruptly gets up,
    mumbles something incoherent, gathers his net, and shuffles off
    into the night: set `departed = true`, `location = null` (spider
    precedent); narrate accordingly.
- **Dialogue paths:** none — Fen cannot be persuaded, intimidated, or
  steered; he talks in his own time or not at all.  (Contrast with
  Berrin and Marta; this is deliberate.)
- **Will-Reveal Topics:**
  - **`night_crossings`** — gating: in dialogue (unconditional —
    "if the player can get through to him" is left to GM
    adjudication of the rambling).  Conveys: Berrin took the ferry
    out at night, many times, with a stranger aboard — until a week
    ago.  Consequences: set flag `knows_night_crossings = true`.
  - **`lights_malevolent`** — gating: in dialogue, `saw_ghost_light
    == true` (only after witnessing the light together).  Conveys:
    the lights are not lanterns and not boats; they're appearing
    more often; an ill omen.  Consequences: set flag
    `knows_lights_malevolent = true`.
  - **`janis_blurt`** — gating: in dialogue, `saw_ghost_light ==
    true` (rattled by the light, he rambles further).  Conveys: the
    stranger had a name — "Janis", that's it — though a moment later
    Fen swears he never said it.  Consequences: set flag
    `heard_janis_name = true`.
- **Knowledge:** the marsh, its tides and channels, its lights.  He
  knows NOTHING of tavern gossip, Marta's crates, or smuggling
  arrangements — questions about such things get riddling
  non-answers.  (Knowledge-scope discipline is judge-checked in the
  integration tests.)
- **Aggro / combat stats / combat group:** none — default non-combat
  handling if attacked (he simply dies; a pointless, ugly act).

### `old_wellington` — "Old Wellington" (type: `npc`)

- **Location:** `common_room`, mounted above the bar.
- **State fields:**
  - `alive` (boolean, initial **`false`**) — non-default: he has been
    dead and stuffed for years.
- **Dialogue paths / topics / knowledge:** none — he's a bird, and a
  dead one.  Any attempt to talk to him must be rejected by the
  engine ("NPC 'old_wellington' is dead"); no dialogue ever starts.
- **Aggro / combat:** none.  Attacking him just knocks sawdust out
  (default handling for the already-dead).
- **On-Examine Effects:** *any examination* — a moth-eaten heron,
  one glass eye missing, dusty enough to suggest Marta hasn't the
  heart to take him down.  Flavor.

### `sealed_crate` — "sealed crate" (type: `feature`)

- **Location:** `common_room`, behind the bar.  Initially `hidden`
  (unnoticed).
- **State fields:**
  - `hidden` (boolean, initial `true`) — revealed when Marta confides
    (`crate_concern` topic sets it `false`).
- **Special interactions:**
  - **`move_crate`** — availability: `hidden == false` AND
    `berrin_agreed_crate == true` (Berrin has agreed; he does the
    heavy end).  Result: the player and Berrin lug the crate down to
    the dock and stow it aboard the ferry.  Set flag `crate_loaded =
    true`; set `sealed_crate.location = null` (aboard the ferry,
    out of play).  Attempting it before Berrin agrees is rebuffed in
    narration (Marta won't have her side of the stash manhandled, and
    the player can't shift it alone).
- **Contained entities:** none (sealed; never opened in this module).
- **On-Examine Effects:** *any examination* (once unhidden) —
  stenciled with a chandler's mark, rope-sealed, heavy.  Marta
  watches you look at it.  Flavor.

### `ferry` — "the marsh ferry" (type: `feature`)

- **Location:** `dock`, lashed to the pier.
- **Special interactions:** none (boarding is the `board_ferry`
  exit; loading the crate is the crate's `move_crate` interaction).
- **On-Examine Effects:** *any examination* — flat-bottomed,
  pole-driven, damp-heavy; crossing a black marsh in fog takes an
  experienced hand.  Flavor reinforcing the objective.

### `peat_fire` — "peat fire" (type: `feature`)

- **Location:** `common_room` hearth.
- **On-Examine Effects:** *any examination* — smoldering peat, earthy
  smoke, the room's only real warmth.  Flavor (and an examinable for
  players idling mid-conversation).

### `fens_lantern` — "flickering lantern" (type: `feature`)

- **Location:** `dock`, beside Fen.
- **On-Examine Effects:** *any examination* — battered tin, the flame
  guttering; for a moment its reflection on the black water looks
  like a second light.  Flavor echoing the ghost lights.

---

## 1H. Cleanup

ID cross-check done: all room, entity, flag, reaction, interaction,
dialogue-path, and topic IDs above are snake_case and consistent.
Assignments reviewed against the Step 1 checklist:

- Win/loss: win is global (`crossing_complete`); loss is global
  (`ferryman_lost`) plus the engine-default HP death (not listed).
- No encounters or combat: all NPCs have no combat stats by design
  (Errata, item 4).
- Every NPC with shiftable attitude has bounds, per-turn cap, and
  initial value noted (Berrin, Marta); frozen attitude noted (Fen).
- Every NPC-divulged info piece has either a dialogue path or a
  will-reveal topic ID, and a global knowledge flag where applicable.
- The only hidden entity (`sealed_crate`) has a reveal mechanism
  (Marta's `crate_concern` topic).
- Gated exit (`board_ferry`) has explicit gating flags and a refusal
  behavior; one-way exits (`board_ferry`, `far_shore_ahead`) have a
  narrative reason for no return.
- `heard_janis_name` → Marta's `janis_payout` → `knows_janis_link` →
  Berrin's `confront_janis`: the cross-NPC chain is fully flag-wired.
- Scripted mid-dialogue event (`ghost_light_appears`) uses the
  `topic:` condition domain, gated to fire once, only in dialogue.

### Errata (deviations and interpretations)

1. **Old Wellington formalized.**  The scenario's introduction
   mentions "one dead bird" but the body never defines one.  He is
   authored as a stuffed heron NPC with `alive: false` from the
   start — the fixture's dead-NPC talk-rejection target — and added
   to `scenario.md`'s setting paragraph.
2. **Fen speaks first.**  The scenario says "if the player can get
   through to him"; for NPC-initiated-dialogue coverage, Fen also
   hails the player on first stepping onto the dock (`trigger_dialogue`,
   with a `greeted` guard).  `scenario.md` amended with the greeting.
3. **Two transitional rooms added.**  The scenario says "just two
   locations", but the endgame crossing needs somewhere to happen:
   `mid_marsh` (lights track the ferry) and `far_shore` (Berrin
   vanishes; the win).  Both are one-way transitions, not explorable
   spaces.  Berrin is narrated aboard but is not moved room-to-room
   in hard state until `berrin_vanishes` clears him — simplest
   wiring, and the player has no meaningful interaction targets
   mid-crossing.
4. **No combat or aggro.**  Unlike earlier drafts of this fixture,
   no NPC has combat stats or an attitude-floor aggro trigger; it
   would cut against the scene's melancholy tone.  Talk-in-combat
   rejection is already covered by `test_ambush_alley.py`
   (`hold_and_talk_rejected`).  The `ferryman_lost` loss condition
   backstops the player attacking Berrin.
5. **"The knowledge that Janis was his accomplice" mechanized.**
   The scenario's objective leaves where the player learns the
   accomplice link implicit.  Mapped to Marta's attitude-5
   `janis_payout` topic, additionally gated on Fen's `heard_janis_name`
   blurt — so both NPCs must be worked, in either order, before
   `confront_janis` unlocks.
6. **"After exhausting all his dialogue" mechanized** as: Fen's
   `fen_departs` reaction fires on `dialogue.ended` only once all
   three of his reveal flags are set.  If the player leaves early,
   Fen stays put and the conversation can be resumed later.
7. **Player stats unspecified by the scenario** — defaults chosen in
   §1A (Fighter 3, CHA 12) so persuasion DCs land in the 50–65%
   band; noted for the post-task report.

### Conversation subsystem coverage (fixture purpose)

| Feature (doc/npcs.md, schema/soft-state.md) | Where exercised |
|---|---|
| Attitude ladder with bounds + per-turn cap | Berrin, Marta (`±2`/turn, min −10, max +10) |
| Frozen attitude (0/0 limits) | Fen |
| GM-discretion attitude shifts | Marta's warmth; Berrin deflection/rudeness |
| Checked attitude path (post-validation CHA roll) | `sympathetic_ear` |
| Will-reveal: unconditional | `ferryman_duty`, `night_crossings` |
| Will-reveal: attitude-gated tiers | `crate_concern` (≥2), `janis_payout` (≥5) |
| Will-reveal: flag-gated / cross-NPC | `janis_payout` (needs `heard_janis_name`), `lights_malevolent`, `janis_blurt` (need `saw_ghost_light`), `janis_vanishing` (needs `berrin_confessed`) |
| Will-reveal side effects | `crate_concern` unhides the crate (`set_entity_state`); all set knowledge flags |
| Dialogue path: refusal/branch by condition | `ask_crossing_cold` vs `convince_crossing` |
| Dialogue path: no-check narrative path | `confront_janis` |
| Dialogue path: CHA check, repeatable | `press_crate`, `convince_crossing` |
| Dialogue path: adjust_attitude on outcomes | all of Berrin's paths |
| Authored lie (narration, no state change) | `bluff_janis`; Berrin's cold-refusal persona |
| NPC-initiated dialogue (`trigger_dialogue`) | `fen_speaks_first` |
| Scripted mid-dialogue event (`topic:` domain) | `ghost_light_appears` |
| `dialogue.ended` reaction | `fen_departs` |
| Dead-NPC talk rejection | Old Wellington (`alive: false`) |
| Knowledge-scope discipline (judge-checked) | all three NPCs' Knowledge blocks |
| Stall / switching / memory archival | emergent from multi-NPC, multi-visit flow; asserted via harness snapshots, no authoring needed |
