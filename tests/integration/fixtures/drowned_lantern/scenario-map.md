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
conversing on the dock, see a ghost light on the marsh.

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
The `hidden` state is cleared if the player does an `examine`
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
  With the crate physically aboard (`entity:sealed_crate.location ==
  entity:ferry`), the `board_ferry` exit is ungated.

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
of the `far_shore` room.  This exit is made available once the ferry
has closed with the pier (`far_shore.approach_stage >= 2`, set by the
approach sequence) AND the player is carrying `rope_end`.  Upon using
this exit, the endgame narration triggers:

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
  - *The scenario gives no player stats; the above are reasonable
    defaults chosen for the fixture (see Errata, item 7).*

---

## 1B. Rooms (Pass 1)

### `common_room` — "Common Room"  **[START ROOM]**

The Drowned Lantern's single warm room: a peat fire, a few empty
tables, damp lantern-glow.  MARTA is behind the bar; above the bar
sits OLD WELLINGTON, a stuffed heron.  Behind the bar (unnoticed) is
the last smuggling crate.  BERRIN sits alone, glumly nursing an ale.
A back door leads out to `dock`.

### `dock` — "Dock"

A slick wooden pier beside the tavern, fog rolling off the marsh.
FEN sits mending his net beside a flickering lantern.  The marsh ferry
is lashed here.  The only way on or off the water is the ferry.

### `mid_marsh` — "Miremarsh"

Open black water in the heart of the marsh: the ferry mid-crossing,
reed-banks looming and vanishing in the fog.  Transitional room for
the endgame crossing (see Errata, item 3).

Moving from `mid_marsh` to `far_shore` occurs by scripting only
(Berrin rows).  Jumping into the water is a game-over.

### `far_shore` — "Far Shore"

A rotting pier on the far side of Miremarsh, solid ground at last.
The final scripted sequence plays out here (the ferry approaches the
pier; the player moors it), ending with the `exit_pier` exit to
`muddy_track`.  Jumping into the water is a game-over.

### `muddy_track` — "Muddy Track"

A muddy track leading away from the marsh, up toward the road.
Terminal epilogue room: entering it plays the endgame narration and
wins the adventure (see Errata, item 3).  There is no going back.

### `in_the_water` — "The Black Water"

Freezing, peat-black marsh water, entered from any waterside room
via the `enter_water` exit.  Terminal: entering the room drowns the
player (a room-entered reaction with an inline game-over loss).

---

## 1C. Entities (Pass 1)

### `player` — "you" (type: `player`)

The player character (stats in §1A): a traveler who urgently needs to
cross the marsh tonight.  Starts in `common_room`, longsword equipped.

### `berrin` — "Berrin" (type: `npc`, in `common_room`)

The marsh ferryman, initially found sitting in `common_room` glumly
nursing an ale (he travels with the player as a follower during the
endgame crossing).  He refuses to ferry anyone at night ("I don't
work at night" — a lie).  Secret: for the past month he ran a
smuggling scheme with JANIS; a week ago Janis leapt off the ferry
mid-crossing, mesmerized by a ghost light, and vanished.  Berrin fled
back to shore, terrified; he has seen lights on the water since and
fears they are coming for him.  He is the only one who can pole the
ferry.

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

### `bar` — "the bar" (type: `feature`, in `common_room`)

The bar in the tavern's common room, Marta's station.  The sealed
crate is stashed behind it (modelled as contained in `bar` and
hidden); examining the bar only spots it once the player knows to
look.  Otherwise: bottles, jars, and tavern junk.

### `sealed_crate` — "sealed crate" (type: `feature`, in `bar`)

The last of Janis's crates, stashed behind the bar in `common_room`.
Sealed; contents unknown (and never opened in this module).  Initially
hidden.  Too heavy and bulky for the player to pick up into inventory,
hence a feature not an item.  Moving it requires Berrin's cooperation:
first out to `dock`, then aboard the `ferry` (it goes out at night).

### `ferry` — "the marsh ferry" (type: `feature`, spans `dock`, `mid_marsh`, `far_shore`)

A flat-bottomed pole-ferry, initially lashed to `dock`.  An
examination makes clear that it needs an experienced hand; the player
does not know how to handle it.  As a multi-room feature it is present
throughout the endgame crossing, so its contents (the rope, its
lantern, and eventually the crate) travel with it.  Boarding it (when
Berrin agrees and the crate is loaded) begins the endgame crossing.

### `ferry_lantern` — "pole lantern" (type: `feature`, in `ferry`)

A lantern hung on a pole, built into the ferry.  Initially unlit;
Berrin lights it when the crate is carried out to the dock.

### `peat_fire` — "peat fire" (type: `feature`, in `common_room`)

The smoldering peat fire in the Drowned Lantern's common room.  Flavor
/ examination texture.

### `fens_lantern` — "flickering lantern" (type: `feature`, in `dock`)

Fen's battered lantern, sitting on the dock, its flame guttering in
the marsh air.  Flavor / examination texture; echoes the ghost lights.

### `ghost_light` — "ghost light" (type: `feature`, in `dock`)

A ghost light that appears in the distance during the player's
conversation with Fen on `dock`, lingers briefly, then disappears.
Narratively, it serves to establish that the spooky lights on the
marsh are real.  Initially hidden.  Cannot be physically accessed, but
the player can examine it (looking from afar); all attempts to
interact with it fail.

### `ghost_lights_mid_marsh` — "ghost lights" (type: `feature`, in `mid_marsh`)

A multitude of ghost lights that appear on the marsh while the player
and Berrin are crossing.  They seem to track the ferry as it moves,
but always at a distance.  Initially hidden.  Cannot be accessed, only
looked at.

### `ghost_lights_shore` — "ghost lights" (type: `feature`, in `far_shore`)

A multitude of ghost lights on the marsh as the ferry approaches the
far shore.  Initially hidden.  Cannot be accessed, only looked at.

### `rope_end` — "rope end" (type: `item`, in `ferry`)

The end of a coil of rope, the other end of which is attached to the
ferry.  Modelled as an item contained in `ferry`.  Taking it is
overruled until the endgame approach ("You hesitate.  Even if you
untie the ferry, there's no way you can run the ferry in the dark,
across an unfamiliar marsh.").  During the final approach, Berrin
tells the player to take the rope and jump onto the pier to moor the
ferry; doing so (via the `exit_pier` exit) triggers the endgame.

### `pier` — "rotting pier" (type: `feature`, in `far_shore`)

The rotting wooden pier on the far shore, with a mooring post.  The
player springs onto it at the end of the crossing.  Examination
texture.

---

## 1D. Global Flags

Knowledge flags track what the player has learned; leverage flags
track what has been unlocked toward the objective.  (Staged
multi-turn sequences do NOT use flag chains; they use numeric
room/entity state fields advanced by the `increment_room_state` /
`increment_entity_state` Result effects — see `mid_marsh`,
`far_shore`, and `ghost_light`.)

- **`knows_ferryman_duty`** — The player has learned (from Marta) that
  the ferryman is supposed to work nights — so Berrin's refusal is
  odd.  Initial value: `false`.

- **`confided_crate`** — Marta or Berrin has told the player about the
  last crate (Marta confides her worry that Berrin hasn't moved it;
  Berrin asks for help shifting it after agreeing to the crossing).
  Gates the `bar` examination that reveals the crate.  Initial value:
  `false`.

- **`knows_janis_link`** — Marta has admitted that Janis paid her to
  stash the crates — the piece that ties Janis to Berrin's night
  crossings, i.e. that Janis was his accomplice.  Gates Berrin's
  `confront_janis` path.  Initial value: `false`.

- **`knows_night_crossings`** — Fen has revealed that Berrin crossed
  the marsh at night, repeatedly, with a stranger aboard.  Initial
  value: `false`.

- **`saw_ghost_light`** — A ghost light appeared on the marsh during
  the player's conversation with Fen, then vanished (scripted
  mid-dialogue event; see `ghost_light`).  Initial value: `false`.

- **`knows_lights_malevolent`** — Fen has shared his belief that the
  lights are malevolent, appearing more often — an ill omen.  Initial
  value: `false`.

- **`heard_janis_name`** — Fen blurted the name "Janis" in his
  rambling (and immediately forgot saying it).  Gates Berrin's
  `bluff_janis` / `confront_janis` paths and Marta's `janis_payout`
  topic.  Initial value: `false`.

- **`berrin_confessed`** — Berrin has broken down and confessed: the
  smuggling, the ghost light, the night Janis vanished (via either
  the `bluff_janis` or `confront_janis` dialogue path).  Gates
  `convince_crossing`.  Initial value: `false`.

- **`crossing_agreed`** — Berrin has agreed to ferry the player
  across tonight.  Gates the crate's `move` interactions and, with
  the crate aboard, the `board_ferry` exit.  Initial value: `false`.

---

## 1E. Mechanics

### `violence_ends_it` — Kind: Reaction mechanic (global rule)

Attacking any of the three living NPCs kills them (no combat stats;
default non-combat handling) and ends the adventure as a loss.  An
entity cannot react to its own death, so this lives here as a global
reaction mechanic: Trigger — an `entity_state.changed` event sets
`alive` to `false` for `berrin`, `marta`, or `fen`.  Two narrative
branches, both ending in inline `Result.game_over` (lose):

- **Witnessed** (player in `common_room` or `dock`): the other NPCs
  become aware of the player's aggression (if Fen is attacked, one of
  the others appears at the tavern door); they flee into the night.
  With no ferryman and no allies, crossing the marsh is impossible.
- **Alone on the ferry** (player in `mid_marsh` or `far_shore`,
  Berrin the victim): he topples into the black water.  The ghost
  lights close in, and the player comes to an unknown, grisly fate in
  the marsh.

(There are no other global mechanics.  The win is route-specific —
the `exit_pier` exit — and lives with the `muddy_track` room reaction
in §1F.  The drowning losses are route-specific room interactions,
also §1F.  Engine-default HP death is not listed, per convention.)

---

## 1F. Rooms (Pass 2)

### `common_room` — "Common Room"  [START]

- **Exits:**
  - **`back_door`** — "out the back door to the dock" → `dock`.
    Always available.
- **Entities present:** `berrin`, `marta`, `old_wellington`, `bar`,
  `peat_fire`.  (`sealed_crate` is inside `bar`, not directly in the
  room.)
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
    One-way.  Available only when `crossing_agreed == true` AND
    `entity:sealed_crate.location == entity:ferry` (the crate is
    physically aboard — direct game logic, no tracking flag).
    Attempting it otherwise is refused in narration (the ferry is
    lashed tight; without Berrin at the pole and his cargo aboard,
    there is no crossing).  Narrative reason for no return: the marsh
    current and fog; Berrin would not agree twice.
  - **`enter_water`** — "into the black marsh water" →
    `in_the_water`.  One-way, always visible (entering the marsh is
    lethal; see the `in_the_water` room).  Modelling the water as an
    exit — rather than an interaction — lets the ruling GM classify
    "jump/dive/wade into the water" as the movement it naturally is,
    and reserves lethality for actual entry (a mere hand-dip doesn't
    kill).
- **Entities present:** `fen`, `ferry`, `fens_lantern`, `ghost_light`
  (hidden).
- **Special interactions:** none.
- **Reactions:** none room-scoped (Fen's greeting is Fen-scoped, and
  the ghost-light beats are `ghost_light`-scoped, §1G).
- **State fields:** none.
- **On-Examine Effects:**
  - *Any examination:* the ferry is sturdily built but heavy with
    damp; poling it across a black, fog-bound marsh plainly takes an
    experienced hand.  Flavor reinforcing the objective.  No state
    change.
- **Soft-item guidance:** netting twine, fishhooks, a bait knife,
  cork floats.

### `mid_marsh` — "Miremarsh"

- **Exits:**
  - **`enter_water`** — "over the side, into the black marsh water" →
    `in_the_water`.  One-way, always visible (lethal).  There is no
    exit to `far_shore`: departure is scripted — the final crossing
    beat moves the player (`set_player_location` — Berrin rows; the
    player does not steer).
- **Entities present:** `ferry` (multi-room feature), `berrin`
  (following), `ghost_lights_mid_marsh` (hidden).
- **Special interactions:** none.
- **Reactions:**
  - **`begin_crossing`** (one-off): Trigger — player enters
    `mid_marsh`.  Consequences — narrate casting off into the fog;
    set `berrin.following = true` (he travels with the player from
    here on); set `ferry_lantern.lit = true` if not already.
  - **`crossing_beat_1`** (recurring): Trigger — turn end.
    Condition — `room:mid_marsh.crossing_stage == 0`.  Consequences —
    narrate rowing in silence (mood setting).  `increment_room_state`
    `mid_marsh.crossing_stage +1`.
  - **`crossing_beat_2`** (recurring): Trigger — turn end.
    Condition — `crossing_stage == 1`.  Consequences — still rowing
    in silence; tension builds (the fog seems to thicken).  Increment
    `crossing_stage`.
  - **`crossing_beat_3`** (recurring): Trigger — turn end.
    Condition — `crossing_stage == 2`.  Consequences — ghost lights
    appear on the black water: set `ghost_lights_mid_marsh.hidden =
    false`, narrate.  Increment `crossing_stage`.
  - **`crossing_beat_4`** (recurring): Trigger — turn end.
    Condition — `crossing_stage == 3`.  Consequences — the lights
    seem to pace and track the ferry; Berrin is terrified but rows
    on.  Increment `crossing_stage`.
  - **`crossing_beat_5`** (recurring): Trigger — turn end.
    Condition — `crossing_stage == 4`.  Consequences — a rotting pier
    looms out of the fog: `set_player_location` to `far_shore`;
    increment `crossing_stage` (terminal).
- **State fields:**
  - `crossing_stage` (number, initial `0`) — beat counter for the
    crossing sequence, advanced by the beat reactions above.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none (open water).

### `far_shore` — "Far Shore"

- **Exits:**
  - **`exit_pier`** — "spring onto the pier" → `muddy_track`.
    One-way.  Available only when `room:far_shore.approach_stage >=
    2` (the ferry has closed with the pier and Berrin has called for
    the rope) AND `inventory:rope_end` (the player is carrying the
    rope end).  This is the adventure's sole winning route.
  - **`enter_water`** — "into the black marsh water" →
    `in_the_water`.  One-way, always visible (lethal).
- **Entities present:** `ferry` (multi-room feature), `berrin`
  (following), `ghost_lights_shore` (hidden), `pier`.
- **Special interactions:** none.
- **Reactions:**
  - **`approach_begins`** (one-off): Trigger — player enters
    `far_shore`.  Consequences — narrate the ferry nosing toward the
    rotting pier through the fog; set `ghost_lights_shore.hidden =
    false` (the lights have followed them); `increment_room_state`
    `far_shore.approach_stage +1`.
  - **`approach_beat_2`** (recurring): Trigger — turn end.
    Condition — `room:far_shore.approach_stage == 1`.  Consequences —
    very close now; Berrin tells the player to grab the rope end and
    be ready to jump and moor the ferry.  Increment `approach_stage`
    (now `>= 2`, ungating `rope_end`'s take check and the
    `exit_pier` exit).
- **State fields:**
  - `approach_stage` (number, initial `0`) — beat counter for the
    pier-approach sequence.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none.

### `muddy_track` — "Muddy Track"

- **Exits:** none (end of the adventure).
- **Entities present:** none.
- **Special interactions:** none.
- **Reactions:**
  - **`berrin_vanishes`** (one-off): Trigger — player enters
    `muddy_track`.  Consequences — the endgame narration: the player
    hears Berrin's cry and a splash, turns, and sees he has
    disappeared without a ripple; the ghost lights wink out one by
    one until only the fog remains, lit by the ferry's pole lantern;
    the player gloomily trudges away along the muddy track.  Set
    `berrin.following = false`, `berrin.departed = true`,
    `berrin.location = null` (his fate is deliberately ambiguous —
    he stays `alive` in hard state).  Inline `Result.game_over`
    (win).
- **State fields:** none.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none.

### `in_the_water` — "The Black Water"

- **Exits:** none (terminal).
- **Entities present:** none.
- **Special interactions:** none.
- **Reactions:**
  - **`marsh_claims_you`** (one-off): Trigger — player enters
    `in_the_water`.  Consequences — the water is far colder than
    expected, and some mysterious force paralyzes the player's limbs;
    they drown in the black water.  Inline `Result.game_over`
    (lose, trigger_id `enter_water`).
- **State fields:** none.
- **On-Examine Effects:** none.
- **Soft-item guidance:** none.

---

## 1G. Entities (Pass 2)

### `player` — "you" (type: `player`)

- Stats per §1A.  Equipped: longsword.  No special interactions,
  reactions, or take checks.

### `berrin` — "Berrin" (type: `npc`)

- **Location:** `common_room`, at a table alone.  During the endgame
  he travels with the player (see Follower Behavior).
- **State fields:**
  - `attitude` (number, initial `0`) — non-default bounds below.
  - `departed` (boolean, initial `false`) — he vanished at the end of
    the crossing; set by `berrin_vanishes`.
- **Attitude Limits:** min −10, max +10, at most ±2 change per turn
  (engine-enforced).  Glum and guarded, but can be won around.
- **Follower Behavior:** from `begin_crossing` onward he follows the
  player (`following = true`) — he poles the ferry while remaining
  present and talkable during the crossing and the pier approach.
  No refused rooms.  `berrin_vanishes` clears the follow.
- **Dialogue availability:** talks freely but deflects anything about
  nights, the marsh, or why he won't work (see Knowledge).  His flat
  refusal — "I don't work at night" — is a *lie*: he is afraid.
  Until he confesses, he sticks to it.
- **Dialogue paths:**
  - **`ask_crossing_cold`** — availability: in dialogue,
    `berrin_confessed == false` (i.e. the player lacks leverage).
    The player asks/demands to be ferried across.  No check.  Result:
    he refuses, rehearsed and hollow — he doesn't work at night, the
    marsh kills, come back in daylight.  Narration only; no state
    change.  (Contrast with `convince_crossing`: the same request
    *with* leverage.)
  - **`bluff_janis`** — availability: in dialogue,
    `heard_janis_name == true` AND `berrin_confessed == false` (the
    player drops the name, bluffing that they know more than they
    do).  Success gating: CHA check (DC 14, repeatable — a
    moderately hard check).  On success: the bluff lands — Berrin
    thinks the player knows everything, and he breaks down and
    confesses (the smuggling, the ghost light, the night Janis went
    over the side): set flag `berrin_confessed = true`.  On failure:
    a flicker of fear, then a flat **lie** — "Never heard of any
    Janis." — and he shuts down: narration only (no state change
    beyond `adjust_attitude` Berrin −1, respecting the ±2/turn cap).
    This is the fixture's authored-lie surface: the narration denies
    everything, and hard state confirms he gave nothing.
  - **`confront_janis`** — availability: in dialogue,
    `heard_janis_name == true` AND `knows_janis_link == true` (the
    player can name Janis *and* lay out the accomplice link).  No
    check — the evidence is overwhelming.  Result: he breaks down and
    confesses, as above.  Set flag `berrin_confessed = true`;
    `adjust_attitude` Berrin +2 (unburdened, respecting caps).
  - **`convince_crossing`** — availability: in dialogue,
    `berrin_confessed == true`.  The player presses him to make the
    crossing tonight.  No check — with his secret out, the fight has
    gone out of him.  Result: he gives in — better to face the water
    with company and finish it.  He agrees to one final nighttime
    run, and asks the player to help shift the last crate (telling
    them about it if they didn't already know): set flag
    `crossing_agreed = true`, set flag `confided_crate = true` (if
    not already).  This ungates the crate's `move` interactions and,
    once the crate is physically aboard, the `board_ferry` exit.
- **Will-Reveal Topics:**
  - **`janis_vanishing`** — gating: in dialogue,
    `berrin_confessed == true`.  Conveys: the full memory of the
    night Janis died — the light that wasn't a boat, how Janis stood
    up as if called, the water that barely rippled.  Consequences:
    none (flavor/payoff; demonstrates a reveal gated on a dialogue
    *path* outcome rather than attitude).  Particularly atmospheric
    if drawn out of him mid-crossing.
- **Knowledge:** knows the smuggling scheme in full, Janis, the ghost
  light, and that the lights have kept appearing since.  Will NOT
  volunteer any of it; deflects or lies until he confesses.  Knows
  the crates were Marta's side of the arrangement but nothing of her
  feelings about it.  Knows nothing of Fen's watching or what the
  lights are.
- **Aggro / combat stats / combat group:** none — no combat stats;
  if attacked, he dies by the default non-combat handling (and the
  `violence_ends_it` loss fires).  He never initiates violence.
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
    `confided_crate = true`; set `sealed_crate.hidden = false` (she
    nods toward it behind the bar).
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
  handling if attacked (the `violence_ends_it` loss fires).
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
  - **`fen_departs`** (one-off): Trigger — dialogue with Fen ends
    (`dialogue.ended`, any reason).  Condition — `event:npc_id ==
    fen` AND all of his dialogue is exhausted: `knows_night_crossings
    == true` AND `knows_lights_malevolent == true` AND
    `heard_janis_name == true`.  Consequences — he abruptly gets up,
    mumbles something incoherent, gathers his net, and shuffles off
    into the night: set `departed = true`, `location = null` (spider
    precedent); narrate accordingly.

  (The ghost-light set-piece is authored on the `ghost_light` entity
  — see below.  Its first beat is gated on the `night_crossings`
  topic being discussed, which can only happen in Fen's dialogue.)
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
  handling if attacked (the `violence_ends_it` loss fires).

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

### `bar` — "the bar" (type: `feature`)

- **Location:** `common_room`.
- **Contained entities:** `sealed_crate` (hidden behind it).
- **On-Examine Effects:**
  - *Any examination, gated on `confided_crate == true`:* the player
    spots the sealed crate stashed behind the bar, where it was
    pointed out to them: set `sealed_crate.hidden = false`.
  - *Any examination, ungated (fallback):* empty bottles, jars of
    pickled eggs, and other tavern junk.  (If the gate is active the
    crate stays unnoticed.)
- **Soft-item guidance:** bar rags, corks, a dented tankard.

### `sealed_crate` — "sealed crate" (type: `feature`)

- **Location:** inside `bar` in `common_room`.  Initially `hidden`.
- **State fields:**
  - `hidden` (boolean, initial `true`) — revealed by Marta's
    `crate_concern` topic or by examining `bar` once
    `confided_crate` is set.
- **Special interactions:**
  - **`move_crate_to_dock`** — availability: `hidden == false` AND
    `crossing_agreed == true` AND `entity:sealed_crate.location ==
    entity:bar`.  Result: the player and Berrin lug the crate out of
    the tavern.  `set_player_location` to `dock`; set
    `sealed_crate.location = room:dock`; set `berrin.location =
    room:dock`; set `ferry_lantern.lit = true` (Berrin hops aboard
    and lights it — atmospherics).  Narrate accordingly.
  - **`move_crate_to_ferry`** — availability: `crossing_agreed ==
    true` AND `entity:sealed_crate.location == room:dock`.  Result:
    the player and Berrin lug the crate aboard: set
    `sealed_crate.location = entity:ferry` (this physically ungates
    the `board_ferry` exit — direct game logic, no tracking flag).
    Narrate accordingly.
  - Attempting to shift the crate before `crossing_agreed` is
    rebuffed in narration (Marta won't have her side of the stash
    manhandled, and the player can't move it alone).
- **Contained entities:** none (sealed; never opened in this module).
- **On-Examine Effects:** *any examination* (once unhidden) —
  stenciled with a chandler's mark, rope-sealed, heavy.  Marta
  watches you look at it.  Flavor.

### `ferry` — "the marsh ferry" (type: `feature`)

- **Location:** spans `dock`, `mid_marsh`, and `far_shore` — it is
  present throughout the endgame, so its contents travel with it
  (see Errata, item 3).
- **Contained entities:** `rope_end`, `ferry_lantern` (and
  `sealed_crate`, once loaded).
- **Special interactions:** none (boarding is the `board_ferry`
  exit; loading is the crate's `move_crate_to_*` interactions).
- **On-Examine Effects:** *any examination* — flat-bottomed,
  pole-driven, damp-heavy; crossing a black marsh in fog takes an
  experienced hand.  Flavor reinforcing the objective.

### `ferry_lantern` — "pole lantern" (type: `feature`)

- **Location:** in `ferry`.
- **State fields:**
  - `lit` (boolean, initial `false`) — lit by Berrin when the crate
    is carried out (see `move_crate_to_dock` / `begin_crossing`).
- **On-Examine Effects:** *any examination* — a tin pole-lantern;
  once lit, its small glow is the only steady light on the marsh.
  Flavor.

### `rope_end` — "rope end" (type: `item`)

- **Location:** in `ferry` (the other end is attached to the ferry).
- **Take Check:** overruled until the final approach — any attempt to
  take it while `room:far_shore.approach_stage < 2` fails with a
  hesitation narrative ("Even if you untie the ferry, there's no way
  you can run it in the dark, across an unfamiliar marsh.").  Once
  Berrin calls for the rope (`approach_stage >= 2`), the take
  succeeds normally.  Repeatable (the player may retry after the
  approach beat).  Carrying it gates the `exit_pier` exit.

### `ghost_light` — "ghost light" (type: `feature`)

- **Location:** `dock`.  Initially `hidden`.
- **State fields:**
  - `hidden` (boolean, initial `true`) — visible only during the
    set-piece.
  - `stage` (number, initial `0`) — beat counter for the appearance
    sequence, advanced by the reactions below
    (`increment_entity_state`).
- **Reactions:**
  - **`ghost_light_stirs`** (recurring): Trigger — turn end.
    Condition — `stage == 0` AND `saw_ghost_light == false` AND the
    `night_crossings` topic has been discussed in the current
    dialogue (`topic:` condition domain — i.e. the player is talking
    with Fen).  Consequences — a pale light kindles far out on the
    water; Fen draws attention to it: set `hidden = false`, narrate,
    `increment_entity_state` `ghost_light.stage +1`.
  - **`ghost_light_beckons`** (recurring): Trigger — turn end.
    Condition — `stage == 1` AND `hidden == false`.  Consequences —
    the light bobs twice, as though beckoning (narration only — this
    beat proceeds even if the player broke off the conversation to
    point at the light).  Increment `stage`.
  - **`ghost_light_winks_out`** (recurring): Trigger — turn end.
    Condition — `stage == 2`.  Consequences — the light winks out as
    mysteriously as it appeared; Fen shakes his head and mutters
    something pensively: set `hidden = true`, set flag
    `saw_ghost_light = true`, increment `stage` (terminal).
- **On-Examine Effects:** *any examination* (while visible) — a
  pale, sourceless light over black water, neither lantern nor boat.
  Flavor.  All other interaction attempts (hailing it, throwing
  something, wading toward it) have no authored success — the GM
  adjudicates them as failures; wading in is `enter_water` (§1F).

### `ghost_lights_mid_marsh` — "ghost lights" (type: `feature`)

- **Location:** `mid_marsh`.  Initially `hidden`; unhidden by
  `crossing_beat_3`.
- **On-Examine Effects:** *any examination* (while visible) — a
  scattered multitude of pale lights on the black water, pacing the
  ferry at a distance.  Flavor.

### `ghost_lights_shore` — "ghost lights" (type: `feature`)

- **Location:** `far_shore`.  Initially `hidden`; unhidden by
  `approach_begins`.
- **On-Examine Effects:** *any examination* (while visible) — the
  lights have followed the ferry; they hang over the water behind
  you, watching.  Flavor.

### `pier` — "rotting pier" (type: `feature`)

- **Location:** `far_shore`.
- **On-Examine Effects:** *any examination* — slick, half-rotted
  planks and a barnacled mooring post; solid ground beyond.  Flavor.

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

- Win/loss: the win is route-specific (the `exit_pier` exit →
  `muddy_track`'s `berrin_vanishes` room reaction, inline
  `game_over`).  Losses: `violence_ends_it` (global reaction
  mechanic — an entity cannot react to its own death) and the
  route-specific `enter_water` dummy exits (the `in_the_water` room's
  entry reaction carries the inline `game_over`).  Engine-default HP death is not listed.
- No encounters or combat: all NPCs have no combat stats by design
  (Errata, item 4).
- Every NPC with shiftable attitude has bounds, per-turn cap, and
  initial value noted (Berrin, Marta); frozen attitude noted (Fen).
- Every NPC-divulged info piece has either a dialogue path or a
  will-reveal topic ID, and a global knowledge flag where applicable.
- Every hidden entity (`sealed_crate`, `ghost_light`,
  `ghost_lights_mid_marsh`, `ghost_lights_shore`) has a planned
  unhide mechanism (Marta's topic or the `bar` examination; the
  ghost-light beat reactions; the crossing and approach beats).
- Gated exits: `board_ferry` (flags + the crate's physical location)
  and `exit_pier` (approach stage + `inventory:rope_end`), both with
  refusal behaviors; one-way exits (`board_ferry`, `exit_pier`) have
  narrative reasons for no return.
- `heard_janis_name` → (Marta's `janis_payout` → `knows_janis_link`)
  → Berrin's `confront_janis`, or `heard_janis_name` alone →
  `bluff_janis`: both routes to `berrin_confessed` are fully wired.
- Scripted sequences use numeric state fields advanced by
  `increment_room_state` / `increment_entity_state`
  (`ghost_light.stage`, `mid_marsh.crossing_stage`,
  `far_shore.approach_stage`) — no boolean flag chains.  The first
  ghost-light beat uses the `topic:` condition domain, so it can
  only fire in Fen's dialogue.

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
3. **Transitional and epilogue rooms added.**  The scenario says
   "just two locations", but the endgame needs somewhere to happen:
   `mid_marsh` (the crossing), `far_shore` (the pier approach), and
   `muddy_track` (the winning epilogue).  All are one-way
   transitions, not explorable spaces.  Berrin travels through them
   as a **follower** (`following = true` from `begin_crossing`) —
   the engine synthesizes followers as present in the player's room,
   so he stays talkable mid-crossing and no NPC location juggling is
   needed.  The `ferry` is a multi-room feature spanning
   `dock`/`mid_marsh`/`far_shore`, so its contents (rope, lantern,
   crate) travel with it automatically.
4. **No combat or aggro.**  No NPC has combat stats or an
   attitude-floor aggro trigger; combat would cut against the scene's
   melancholy tone.  Attacking any living NPC kills them by the
   default non-combat handling and fires the `violence_ends_it`
   loss.  Talk-in-combat rejection is covered separately by
   `test_ambush_alley.py` (`hold_and_talk_rejected`).
5. **"The knowledge that Janis was his accomplice" mechanized.**
   The scenario's objective leaves where the player learns the
   accomplice link implicit.  Mapped to Marta's attitude-5
   `janis_payout` topic, additionally gated on Fen's `heard_janis_name`
   blurt — so both NPCs must be worked, in either order, before
   `confront_janis` unlocks.  The `bluff_janis` path (name-drop plus
   a hard CHA check) provides the alternate route for a player who
   skips Marta's ladder.
6. **"After exhausting all his dialogue" mechanized** as: Fen's
   `fen_departs` reaction fires on `dialogue.ended` only once all
   three of his reveal flags are set.  If the player leaves early,
   Fen stays put and the conversation can be resumed later.
7. **Player stats unspecified by the scenario** — defaults chosen in
   §1A (Fighter 3, CHA 12) so persuasion DCs land in the 50–65%
   band.  No initiative modifier or unarmed damage is specified;
   5e-flavored defaults will be needed if combat stats are written.

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
| Dialogue path: no-check narrative path | `confront_janis`, `convince_crossing` |
| Dialogue path: CHA check, repeatable | `bluff_janis` (DC 14) |
| Dialogue path: adjust_attitude on outcomes | `bluff_janis` failure, `confront_janis` success |
| Authored lie (narration, no state change) | `bluff_janis` failure branch; Berrin's cold-refusal persona |
| NPC-initiated dialogue (`trigger_dialogue`) | `fen_speaks_first` |
| Scripted mid-dialogue event (`topic:` domain) | `ghost_light_stirs` (beat 1 of the ghost-light set-piece) |
| Multi-beat scripted sequences (increments) | `ghost_light` (3 beats), `mid_marsh` crossing (5 beats), `far_shore` approach (2 beats) |
| `dialogue.ended` reaction | `fen_departs` |
| Dead-NPC talk rejection | Old Wellington (`alive: false`) |
| Follower NPC mid-dialogue presence | Berrin during the crossing (`following`) |
| Knowledge-scope discipline (judge-checked) | all three NPCs' Knowledge blocks |
| Stall / switching / memory archival | emergent from multi-NPC, multi-visit flow; asserted via harness snapshots, no authoring needed |

---

## Step 2 Revisions (deviations found while building the entities block)

1. **Player entity declared in `corpus.json`.**  Per §2E, a minimal
   `player` entity (type + description) is declared, matching the
   bag-of-holding precedent (the combat fixtures omit it and rely on
   `default-player.json`, which arrives in Step 5).
2. **Pure-flavor On-Examine Effects folded into descriptions.**  The
   §1G "flavor" examination entries for `ferry`, `ferry_lantern`,
   `ghost_light`, `ghost_lights_mid_marsh`, `ghost_lights_shore`,
   `pier`, `peat_fire`, `fens_lantern`, and `old_wellington` have no
   mechanical effect, so they were merged into the entities'
   `description` fields (which the GM narrates ordinary examinations
   from) rather than authored as `on_examine` events.  Only the
   effect-bearing examination — `bar`'s `spot_crate` reveal — is an
   actual `on_examine` event.
3. **`bluff_janis` gained an availability guard.**  The path's
   condition is `heard_janis_name == true` AND `berrin_confessed ==
   false` (the latter not in §1G): once Berrin has confessed, the
   bluff route is moot and path matching should fall through to
   `convince_crossing`.
4. **`rope_end` take gate uses the always-fail idiom.**  Per §2C's
   "untakeable while a condition holds" pattern: `gating` on
   `unless: room:far_shore.approach_stage >= 2`, with a `roll`
   check at threshold 0.0 (repeatable) and the hesitation narrative
   as its `failure`.
5. **`fen_speaks_first` carries no narration.**  Its effect is
   `trigger_dialogue: self` plus setting `fen.greeted`; the greeting
   itself is left to the GM's dialogue handling.
6. **No entity `on_examine` for hidden-only flavor.**  `ghost_light`
   and the `ghost_lights_*` entities are examinable only while
   unhidden, so no visibility condition was needed anywhere.
7. **Deferred to later steps (no map change needed):** rooms, exits,
   and room reactions/beats (`enter_water`, `begin_crossing`,
   `crossing_beat_*`, `approach_*`, `berrin_vanishes`, the
   `common_room` rigorous-examine hint) to Step 3; the
   `violence_ends_it` reaction mechanic to Step 4 (already in §1E);
   `default-player.json` to Step 5; `soft-state.json` content to
   Step 6 (a minimal `{}` stub exists so
   `scripts/validate_adventure.py` runs).

---

## Step 3 Revisions (deviations found while building the rooms block)

1. **`board_ferry` is a visible exit with an always-fail
   `traversal_check`**, not a condition-hidden exit.  Per §3C, a
   `condition` exit is *hidden* until true, which would silently
   swallow boarding attempts; the Preamble calls for an authored
   refusal ("the ferry is lashed tight…").  Implementation:
   `skip_check_if` on the ready condition (`crossing_agreed` AND
   `entity:sealed_crate.location == entity:ferry`), with a `roll`
   check at threshold 0.0 (repeatable) whose `failure` carries the
   refusal narration.  `exit_pier`, by contrast, uses a plain
   `condition` (hidden until ungated) — its gating is guided by
   Berrin's scripted instruction, so no refusal text is needed.
2. **Room flavor examinations folded into descriptions.**  The §1F
   "any examination" flavor entries for `dock`/`mid_marsh`/
   `far_shore`/`muddy_track` were merged into room descriptions
   (same consolidation as Step 2, item 2).  The only authored room
   `on_examine` is `common_room`'s rigorous-only hint about Berrin's
   fear (ambiguity resolved as *rigorous*: it is an inference drawn
   from watching him, not a glance).
3. **Validator extended for scripted transitions.**  The
   `mid_marsh` → `far_shore` move is scripted
   (`set_player_location` in `crossing_beat_5`), so the exit-graph
   reachability check in `scripts/validate_adventure.py` reported
   `far_shore`/`muddy_track` as unreachable.  The check now also
   follows `set_player_location` targets in room reactions and
   interactions.  bag-of-holding validation is unaffected (still
   passes with its pre-existing warning).
4. **`berrin_vanishes` clears `following` explicitly** (in addition
   to `location: null`, whose placement handling would stop the
   follow anyway) — belt-and-braces, no behavioral difference.
5. **Win `trigger_id` is `crossing_complete`** (the retired
   game-over mechanic's ID, repurposed as the inline
   `Result.game_over` trigger in `berrin_vanishes`); the drowning
   losses share trigger_id `enter_water`.

---

## Step 4 Revisions (deviations found while building mechanics and stats)

1. **`violence_ends_it` implemented as one reaction-only mechanic**
   with two reactions (`violence_witnessed` for
   `common_room`/`dock`, `violence_on_ferry` for
   `mid_marsh`/`far_shore`), both firing on `entity_state.changed`
   (`alive` → `false` for any of the three living NPCs) and ending in
   inline `Result.game_over` (lose, trigger_id `violence_ends_it`).
   No top-level `game_over_conditions` are used anywhere in the
   module: the win is inline in `berrin_vanishes` and the drowning
   losses are inline in `enter_water`.
2. **Stats block added** (`stats.system: "5e"` with the six ability
   scores), matching the other fixtures.

## Step 5 Revisions (deviations found while building default-player.json)

1. **AC 13 sourced to studded leather.**  §1A says "leather + DEX",
   but leather (11) + DEX +1 = 12.  AC 13 implies studded leather
   (12) + DEX +1; only the numeric `ac` field is declared (armor is
   not modelled as an entity, matching the combat fixtures).
2. **No `hard-state.json` override.**  Every initial value (Old
   Wellington's `alive: false`, the crate's `hidden`, stage counters,
   Fen's `greeted`) derives from corpus declarations and
   `flags_declared`; verified by loading the module and inspecting
   the generated world state.  (The combat fixtures carry a
   hard-state override only because they seed non-default states like
   a pre-following mule.)

## Step 6 Revisions (deviations found while building soft-state.json)

1. **`soft-state.json` is the full default serialization** (empty
   inventories, notes, knowledge, and dialogue state), replacing the
   `{}` stub from Step 2 — no seeded soft content was needed.

---

## Post-playtest Revisions (water remodelled as an exit)

Found during integration playtesting (`loss_enter_water`): the
`enter_water` room *interaction* asked the ruling GM to map
"jump/dive into the water" — which it naturally reads as movement —
onto an interaction, and it repeatedly failed to do so (ruling
`wait`, or mis-routing the chained move).  It also over-matched
("dip my hand into the water" was lethal).  The water is now
modelled as a visible one-way dummy exit `enter_water` from `dock`,
`mid_marsh`, and `far_shore`, leading to a terminal `in_the_water`
room whose `marsh_claims_you` entry reaction carries the inline
`game_over` (lose, trigger_id `enter_water` — unchanged).  This
aligns the mechanic with the ruling model's strongest classification
instinct (movement → exits) and reserves lethality for actual entry.
