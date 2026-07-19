# Scenario Map — "You're Trapped in a Bag!"

Working plan for the adventure module, produced by Step 1 of
`schema/scenario-generation.md` from `scenario.md`.  All IDs are
snake_case; `self` is reserved and unused.

---

## 1A. Adventure Metadata

- **Title:** You're Trapped in a Bag!

- **Credits:** (C) 2023 Sam Seer.  Distributed under Creative Commons
  Attribution-ShareAlike (CC-BY-SA 4.0).  Adapted from a one-page role
  playing adventure submitted to the 2023 One Page Dungeon Competition.

- **Introduction** (verbatim, second-person, no spoilers):

  > You wake up. The last thing you remember is a night out on the
  > town. Now you seem to be in a giant cave made of... canvas?

- **Adventure ID:** `bag_of_holding`

- **Atmosphere** (no spoilers): A vast, lightless cave whose walls are
  woven canvas, lit by a faint, sourceless luminescence.  Everything is
  stale, silent, and unsettlingly scaled; the murk below hides heaped
  piles of discarded oddments.  The tone is pulpy fantasy with a wry,
  slightly gross sense of humor, underlaid by real claustrophobic
  menace: something hungry lurks in the dark, and the way out — if
  there is one — is not obvious.  Escape will require careful
  exploration, deduction, and perhaps a friend.

- **Player stats:** This adventure uses player stats.

  - **Stats used:** the six 5e ability scores (STR, DEX, CON, INT,
    WIS, CHA), proficiency bonus, HP, AC, saving throws.  Skills and
    other 5e mechanics are unused.
  - **Resolution system:** 5e (stat checks, saves, turn-based combat).
  - **Initial player stats:** Class Rogue; Race Human; Level 4;
    STR 10, DEX 13, CON 12, INT 11, WIS 10, CHA 10; Proficiency
    Bonus +2; HP 27 (current 27 / max 27); AC 11 (unarmored + DEX
    bonus); Saving Throws: DEX, INT.
  - **Starting inventory:** empty (the scenario explicitly clears any
    supplied character sheet's inventory).
  - *Omissions (for the post-task report):* the scenario gives no
    player attack/damage stats (unarmed damage, weapon proficiencies)
    and no initiative modifier; reasonable 5e-flavored defaults will be
    needed when combat stats are written.

---

## 1B. Rooms (Pass 1)

### `axe_head` — "Axe Head"  **[START ROOM]**

The top of a giant battleaxe that leans at an angle against the wall of
a still-larger, pitch-dark cave.  Faint luminescence from the canvas
walls is all that prevents total darkness.  Above head height the walls
converge into a low dome, scrunched shut in the center.  The tip of the
blade has made a small rip in the fabric.  The handle, about the width
of a narrow sidewalk, slopes downward into the murk towards
`axe_handle_upper`; one can also drop from here down to `bag_floor`.

### `axe_handle_upper` — "Axe Handle (Upper)"

A stretch of the sloping giant axe handle where a mass of sticky webs
is attached, greatly dimming the wall glow; the player can barely make
out their footing.  Various strange wrapped masses of different sizes
are stuck in the webs.  The handle continues up to `axe_head` and down
(towards denser webs) to `axe_handle_lower`; dropping over the side
into the darkness below is possible but the landing cannot be seen.

### `axe_handle_lower` — "Axe Handle (Lower)"

Here the webs surrounding the handle are very dense and must be forced
through to continue along the path.  Peering over the side, numerous
irregularly-shaped objects are visible on the cave floor below, and a
drop from here looks safe.  Connects up to `axe_handle_upper` and down
to `bag_floor`.

### `bag_floor` — "Bag Floor"

The floor of the cave, covered with a loose pile of giant-sized
rubbish: copper pieces, empty potion bottles, used corks, lint, moldy
sandwiches, and more disgusting items.  The base of the giant axe
rests in the center of the pile; the handle can be clambered back up
from here (to `axe_handle_lower`).  KORBAR is here.  A concealed flap
in the floor (hidden under a giant handkerchief) leads down to
`secret_pocket`.

### `secret_pocket` — "Secret Pocket"

A closet-sized space below the cave floor, accessed by squeezing
through a concealed flap in the floor of `bag_floor`.  Walls of the
same faintly-glowing canvas, but stickier and smellier.  Contains only
a large iron key.  The only exit leads back up to `bag_floor`.

---

## 1C. Entities (Pass 1)

### `player` — "you" (type: `player`)

The player character (stats in §1A).  Starts in `axe_head` with an
empty inventory.

### `giant_axe` — "giant battleaxe" (type: `feature`)

An enormous battleaxe leaning against the cave wall; its head, sloping
handle, and base form the only path between the upper and lower
reaches of the cave.  Spans rooms `axe_head`, `axe_handle_upper`,
`axe_handle_lower`, and `bag_floor`.  Plot detail: it was KORBAR's
weapon when she was full-sized outside.

### `the_rip` — "rip in the canvas" (type: `feature`)

A small rip in the canvas wall at the tip of the axe blade, in
`axe_head`, just within reach of someone walking carefully to the
blade's tip.  Dull gray light winks through it.  The only way to see
(or lose anything through) the outside.

### `padlock` — "giant padlock" (type: `feature`)

A giant padlock that firmly shuts the neck of the bag, dangling outside
the rip down to the player's level, its keyhole barely within reach.
Located at `axe_head` (outside, visible only through `the_rip`);
initially hidden.

### `webs` — "sticky webs" (type: `feature`)

Masses of sticky webbing attached to the giant axe handle, with
strange wrapped objects stuck in them; much denser on the lower
stretch.  Spans `axe_handle_upper` and `axe_handle_lower`.  Too sticky
to be useful; the stuck masses are too tightly wrapped to identify or
extricate.

### `fly` — "Fly" (type: `npc`)

A talking fly, dog-sized relative to the player, stuck in the webs in
`axe_handle_upper`.  Initially hidden (unnoticed); speaks in a weak
nasally whine.  Mortally wounded; dies shortly after being found.

### `spider` — "Spider" (type: `npc`)

A huge spider, hungry for blood, lurking concealed in the shadows
above `axe_handle_lower`.  Initially hidden.  Vain, stupid,
suspicious, and malicious; it can talk but never initiates
conversation.  Combat-capable (stat block in §1G).

### `korbar` — "Korbar" (type: `npc`)

A female Dwarf, drunk and miserable, sitting amidst the rubbish in
`bag_floor` beneath a makeshift shelter made from a giant overturned
soup ladle.  Wears ridiculously noisy heavy plate mail; unarmed.  Her
adventuring party stuffed her in here during a stealth mission and
forgot her.  Cynical and tired, but a potential ally; combat-capable
(stat block in §1G).

### `rubbish_pile` — "pile of giant rubbish" (type: `feature`)

The loose pile of giant-sized refuse covering `bag_floor`: copper
pieces, empty potion bottles, used corks, lint, moldy sandwiches, etc.
Conceals several important things (see §1G).  Holds the
`toenail_sword` within it.

### `toenail_sword` — "giant toenail clipping" (type: `item`)

A giant toenail clipping buried in the `rubbish_pile`; can be pried
loose and wielded as a sword.  Initially hidden (unnoticed).  The
player can carry it.

### `handkerchief` — "giant handkerchief" (type: `feature`)

A filthy, disgustingly damp giant handkerchief draped over a corner of
the rubbish pile in `bag_floor`.  Initially hidden (unnoticed).
Giant-sized, so it cannot be carried in inventory (hence a feature,
not an item).  Moving it aside reveals the flap to `secret_pocket`.

### `key` — "giant iron key" (type: `item`)

A large, extremely heavy iron key lying in `secret_pocket`.  The
player can carry it, but hauling it around is arduous.  It is the only
way out of the bag.

### `plate_armor` — "suit of plate mail" (type: `item`)

KORBAR's rusty, smelly, very noisy suit of heavy plate mail (AC 18),
worn by her at start.  Can be stolen from her, but is far too
cumbersome for the player to wear.

---

## 1D. Global Flags

- **`knows_glow_magical`** — The player has deduced (INT check in
  `axe_head`) that the walls' faint luminescence is magical in nature.
  Initial value: `false`.

- **`knows_astral_plane`** — The player has recognized the gray
  nothingness outside the rip as the Astral Plane.  Initial value:
  `false`.

- **`knows_bag_of_holding`** — The player knows they are inside a
  magical Bag of Holding (a legendary storage item existing in the
  prime and astral planes simultaneously).  Gates spoiler-free
  narration.  Initial value: `false`.

- **`knows_rubbish_is_supplies`** — The player has realized the
  rubbish pile is not random junk but a shrunken adventurer's supplies
  — much like their own missing pack.  Initial value: `false`.

- **`knows_spider_threat`** — The player has been warned that a giant
  spider is out for blood (by the Fly or by Korbar).  Initial value:
  `false`.

- **`knows_secret_pocket`** — Korbar has told the player that a giant
  handkerchief on the rubbish pile covers a secret pocket in the
  floor.  Initial value: `false`.

---

## 1E. Mechanics

Resolution system: 5e (see §1A).  Global game-over conditions and
adventure-wide rules are listed here.  Win/loss conditions reachable
by one specific route are NOT listed here; they are recorded as
game-over consequences on the owning room/entity (see `padlock` and
`the_rip` in §1G).

### `player_death` — Kind: Global game-over condition

If the player's `current_hp` drops to ≤ 0 (spider bite, fall damage,
Korbar's fists, etc.), the player dies: game over (lose).  Checked
continuously (every turn).  *Not stated in the scenario; assumed as
the standard complement of 5e combat — see Errata, item 1.*

### `heavy_key_movement` — Kind: Reaction mechanic (global rule)

While the `key` (tag `heavy`) is in the player's inventory, any
movement between rooms requires a STR check (DC 12, repeatable).  On
failure, the move is canceled: the player struggles to move the heavy
key but can try again.  The check is skipped if `korbar` is in the
same room with `following == true` (and conscious): she assists with
the key.  Applies to all room transitions, including the drop exits
and the secret flap (interpretation — see Errata, item 8).  Narration
should emphasize the difficulty of hauling the key.

*Notes:*

- The spider ambush/attack encounter is deliberately **not** a global
  mechanic: it involves a single NPC, so per the §1E guidance it is
  NPC-scoped — see the `spider` entry (§1G) and the
  `axe_handle_lower` room reactions (§1F).
- The route-specific game-overs — the win (`padlock.insert_key`
  success), the key falling through the rip (`rip_item_dropped` and
  the `insert_key` failure cascade), and squeezing through the rip
  (`the_rip.squeeze_through`) — are recorded on `padlock` and
  `the_rip` in §1G.

---

## 1F. Rooms (Pass 2)

### `axe_head` — "Axe Head"  [START]

- **Exits:**
  - **`down_handle`** → `axe_handle_upper`: "Clamber carefully down
    the axe handle".  No conditions or checks.
  - **`drop_down`** → `bag_floor` (one-way): "Drop down into the
    darkness below".  Side effects on arrival: lose 1d4 DEX, 1d4 CON,
    and 3d6 HP (permanent, per the scenario's implementation note); if
    `korbar` is present in `bag_floor`, narrate her astonishment.
    Return path: climbing back up the handle from `bag_floor`.

- **Entities present:** `player` (start), `giant_axe`, `the_rip`,
  `padlock` (hidden).

- **Special interactions:** none.

- **Reactions:** none (the rip's behaviors are entity-scoped; see
  `the_rip`, §1G).

- **State fields:** none.

- **On-Examine Effects** (any examination): examining the room / the
  walls' glow: INT check (DC 12, non-repeatable).  On success the
  player deduces the luminescence is magical (a side effect of the
  place's magic): set `knows_glow_magical = true`.

### `axe_handle_upper` — "Axe Handle (Upper)"

- **Exits:**
  - **`up_handle`** → `axe_head`: "Clamber back up the axe handle".
    No conditions or checks.
  - **`down_handle`** → `axe_handle_lower`: "Continue down the axe
    handle".  No conditions or checks.
  - **`drop_down`** → `bag_floor` (one-way): "Drop down into the
    unseen darkness below".  Side effects: 2d6 damage (no stat loss).
    Return path: climbing back up from `bag_floor`.

- **Entities present:** `giant_axe`, `webs`, `fly` (hidden).

- **Special interactions:** none.

- **Reactions:** none room-scoped (the Fly's groaning and death are
  entity-scoped; see `fly`, §1G).

- **State fields:** none.

- **On-Examine Effects:** none room-scoped; examining the webs or the
  stuck masses uses the `webs` entity's on-examine effects (§1G).

### `axe_handle_lower` — "Axe Handle (Lower)"

- **Exits:**
  - **`up_handle`** → `axe_handle_upper`: "Force your way back up the
    web-choked handle".  *Web-gated:* if `web_cleared == false` and
    `entered_from == "below"` (i.e., proceeding upward after entering
    from below), the player must first force through the web: STR
    check (DC 14 unarmed, DC 10 if armed with a `weapon`-tagged item;
    repeatable).  On success, set `web_cleared = true` (passage is
    free thereafter).  Any forcing attempt, successful or not,
    triggers reaction `web_spider_attack` if the spider is present.
    Returning in the direction one came from is not impeded.
  - **`down_handle`** → `bag_floor`: "Force your way down the
    web-choked handle".  *Web-gated* exactly as above, but when
    `entered_from == "above"`.
  - **`drop_down`** → `bag_floor` (one-way): "Drop over the side of
    the handle".  Side effects: momentarily winded, otherwise
    uninjured (no mechanical effect).  Not web-gated and does not
    trigger the spider (interpretation — see Errata, item 7).

- **Entities present:** `giant_axe`, `webs`, `spider` (hidden).

- **Special interactions:** none.

- **Reactions:**
  - **`track_entry_direction`** (recurring): Trigger — player enters
    the room.  Consequences — set `entered_from` to `"above"` if the
    player arrived from `axe_handle_upper`, or `"below"` if from
    `bag_floor`.  No narration; exists to implement the directional
    web rule.
  - **`notice_spider_on_entry`** (recurring): Trigger — player enters
    the room.  Condition — `spider` is alive, not `departed`, and
    `hidden == true`.  Consequences — WIS check (DC 13, repeatable);
    on success the player notices the spider lurking above: set
    `spider.hidden = false`.
  - **`web_spider_attack`** (recurring, preemptive): Trigger — player
    attempts a web-gated traversal of exit `up_handle` or
    `down_handle` (whether the STR check succeeds or fails, whether or
    not the spider has been noticed, even mid-dialogue); fires on the
    traversal *attempt*, while the action is still in progress.
    Condition — `spider` is alive, present in the room, and `departed
    == false`.  Consequences — set `spider.hidden = false`,
    `spider.attitude = -10`, `spider.attitude_fixed = true`; the
    traversal is canceled; start combat: enemies [`spider`]; allies
    [`korbar`] only if she is present and `will_fight == true`
    (otherwise she is narrated cowering in fear and does not
    participate).

- **State fields:**
  - `web_cleared` (boolean, initial `false`) — the blocking web has
    been forced through; passage is thenceforth free.
  - `entered_from` (string, initial `""`) — which side the player last
    entered from: `"above"` or `"below"`.

- **On-Examine Effects** (any examination): peering over the side /
  examining what lies beneath: if the player has not yet visited
  `bag_floor` (the reserved `visited` field, referenced but not
  declared), WIS check (DC 11, repeatable); on success the player
  discerns giant empty potion bottles, copper pieces, corks, and
  moldy sandwiches piled below, and — if `korbar` is alive — hears
  faint clanking and muttering from below.  If the player has already
  visited `bag_floor`, this succeeds automatically with no check.

### `bag_floor` — "Bag Floor"

- **Exits:**
  - **`up_handle`** → `axe_handle_lower`: "Clamber back up the axe
    handle".  No conditions or checks.
  - **`secret_flap`** → `secret_pocket` (hidden exit): "Squeeze
    through the flap in the floor".  Availability condition:
    `handkerchief.moved_aside == true` (the flap is revealed only by
    moving the handkerchief aside; see `handkerchief`, §1G).  No
    traversal check.

- **Entities present:** `giant_axe`, `korbar`, `rubbish_pile`,
  `handkerchief` (hidden).  (`toenail_sword` is inside `rubbish_pile`
  and therefore not "present" in the room.)

- **Special interactions:** none.

- **Reactions:** none room-scoped.

- **State fields:** none.

- **On-Examine Effects:** examining the room itself counts as
  examining the `rubbish_pile` (same effects, §1G) — the scenario
  applies the rubbish effects to "examining the rubbish or the room or
  any item within the rubbish", as long as it is an explicit action.

- **Soft-item guidance:** nondescript giant rubbish — copper pieces,
  empty potion bottles, used corks, lint, moldy sandwiches, and more
  disgusting items (see `rubbish_pile`, §1G).

### `secret_pocket` — "Secret Pocket"

- **Exits:**
  - **`flap_up`** → `bag_floor`: "Squeeze back up through the flap".
    No conditions or checks.

- **Entities present:** `key`.

- **Special interactions:** none.

- **Reactions:** none.

- **State fields:** none.

- **On-Examine Effects:** none.

---

## 1G. Entities (Pass 2)

### `player` — "you" (type: `player`)

- **State fields:** standard; note `current_hp` starts at 27 (max 27).
  Inventory empty at start.
- All other entries: n/a (see §1A for stats).

### `giant_axe` — "giant battleaxe" (type: `feature`)

- **Spans rooms:** `axe_head`, `axe_handle_upper`, `axe_handle_lower`,
  `bag_floor`.
- **On-Examine Effects:** examining it reveals it to be an enormous
  battleaxe — its head made the rip in the canvas.  Flavor only; no
  check, no mechanical effect.  (Its connection to Korbar is hers to
  reveal.)
- **Tags / interactions / state fields / reactions:** none.
  (Traversal along the axe is modeled via room exits, §1F.)

### `the_rip` — "rip in the canvas" (type: `feature`)

- **Location:** `axe_head`.
- **State fields:**
  - `squeeze_warned` (boolean, initial `false`) — the player has been
    warned once about squeezing through.
- **Special interactions:**
  - **`squeeze_through`** — try to squeeze one's whole body through
    the rip.  Requires a DEX check (DC 12, non-repeatable).  On
    success: if `squeeze_warned == false`, cancel the action — the GM
    asks the player if they're sure — and set `squeeze_warned =
    true`; if `squeeze_warned == true` (player repeats the action), no
    further check is needed: the player squeezes through and floats
    eternally in the Astral Plane — game over (lose).  On check
    failure: the player cannot fit through (no further effect; see
    Errata, item 5).
- **Reactions:**
  - **`rip_item_dropped`** (recurring): Trigger — an item is
    dropped/transferred through the rip.  Consequences — the item
    disappears into the gray void (permanently removed from play); if
    the item is the `key`, additionally: game over (lose) — the player
    is trapped forever.
- **On-Examine Effects** (any examination): examining the rip
  (sticking one's head through — the scenario declares this equivalent
  to an Examine action) reveals, in narration: (1) the gray nothing
  outside — INT check (DC 12, non-repeatable); on success the player
  recognizes the Astral Plane: set `knows_astral_plane = true`; (2)
  the exterior: the rip is a hole in the wall of a giant sack whose
  neck is firmly shut by a giant padlock dangling within reach — set
  `padlock.hidden = false`; (3) if `knows_astral_plane == true`, a
  further INT check (DC 17, non-repeatable); on success the player
  realizes it is a Bag of Holding: set `knows_bag_of_holding = true`.
  *Narration gating:* none of these features may be narrated before an
  explicit examination; from the main room only dull gray light winks
  through.
- **Tags:** none.

### `padlock` — "giant padlock" (type: `feature`)

- **Location:** `axe_head` (visible only through `the_rip`).
- **State fields:** `hidden` (boolean, initial `true`) — revealed by
  `the_rip`'s on-examine effect.
- **Special interactions:**
  - **`insert_key`** — push the `key` through the rip and into the
    padlock's keyhole.  Availability: `padlock.hidden == false` and
    the `key` is in the player's inventory.  If `korbar` is present in
    `axe_head` and `following == true` (and conscious), she helps.
    STR check: DC 14 alone, DC 10 with Korbar's help; repeatable.  On
    success: the key turns, the padlock opens, the bag opens, the
    player squirms free — game over (win); the GM narrates this
    entertainingly, leaving the player's fate (and Korbar's, if
    following) open-ended.  On failure: immediately roll a DEX check
    (DC 8 — an automatic follow-up roll each time the STR check
    fails, not a player-attempted check); on success the player hauls
    the key back in (no further effect; may retry the STR check); on
    failure the key slips and falls through the rip — game over
    (lose), the player is trapped forever.
- **Tags / reactions / on-examine effects:** none beyond the above.

### `webs` — "sticky webs" (type: `feature`)

- **Spans rooms:** `axe_handle_upper`, `axe_handle_lower`.
- **On-Examine Effects** (any examination; room-dependent):
  - In `axe_handle_upper`: the first examination of the webs or the
    stuck masses turns up the Fly: set `fly.hidden = false` (this
    triggers reaction `fly_warning_on_reveal`).
  - In `axe_handle_lower`: if `spider` is alive, not `departed`, and
    `hidden == true`: WIS check (DC 13, repeatable); on success the
    player notices the spider: set `spider.hidden = false`.
  - In all cases: no other searches turn up anything useful — the
    stuck masses are too tightly wrapped to identify or extricate, and
    the web is too sticky to do anything with (narration guidance).
- **Tags / interactions / state fields / reactions:** none.  (The
  blockable stretch of web is modeled by `axe_handle_lower`'s
  `web_cleared` state field and gated exits, §1F.)

### `fly` — "Fly" (type: `npc`)

- **Location:** `axe_handle_upper` (stuck in the `webs`).
- **State fields:**
  - `hidden` (boolean, initial `true`) — unnoticed until the webs are
    examined.
  - `delivered_warning` (boolean, initial `false`) — it has spoken its
    warning about the spider.
- **Reactions:**
  - **`fly_groaning`** (recurring): Trigger — each turn while the
    player is in `axe_handle_upper`.  Condition — fly alive and
    `hidden == true`.  Consequences — narrate groaning and weak
    warning sounds coming from somewhere in the web; does **not**
    reveal the fly.
  - **`fly_warning_on_reveal`** (one-off): Trigger — `fly.hidden` is
    cleared (entity state set/cleared).  Condition — fly alive and
    `delivered_warning == false`.  Consequences — in a weak nasally
    whine it warns of a giant spider out for blood (it does this
    whether or not the spider has perished): set
    `knows_spider_threat = true` and `delivered_warning = true`.
  - **`fly_dies_after_warning`** (one-off): Trigger — a dialogue with
    the fly occurs, OR the player attempts to leave `axe_handle_upper`
    via any exit (fires on the exit *attempt*, while the fly is still
    in the room).  Condition — fly alive and `delivered_warning ==
    true`.  Consequences — the fly dies: set `alive = false`; narrate
    its fading death.
- **First-Meeting Behavior:** when first found (revealed by examining
  the webs), it speaks its warning about the spider — see reaction
  `fly_warning_on_reveal`.
- **Dialogue paths:** none (it has no other useful information — after
  all, it's a fly).
- **Will-Reveal Topics:**
  - **`spider_warning`** — gating: in dialogue, fly alive.  Conveys:
    a giant spider is out for blood.  Consequences: set
    `knows_spider_threat = true`.  (Normally already delivered by
    `fly_warning_on_reveal` before any dialogue.)
- **Knowledge:** knows nothing useful about this place or anything
  else; it's a fly (albeit a talking one).
- **Aggro:** no combat stats — if attacked, it simply dies (default
  non-combat handling).
- **Combat stats / combat group:** none.

### `spider` — "Spider" (type: `npc`)

- **Location:** `axe_handle_lower`, concealed in the webbing above.
- **Combat stats (verbatim):** STR 14, DEX 16, CON 12, INT 7, WIS 11,
  CHA 4; AC 8; HP 14.  Attacks: Bite (+1 to hit, 1d4+2 piercing
  damage).  On hit: target must make a DC 11 CON save or take 1d8
  poison damage, half on a successful save.  *Not provided: initiative
  modifier, flee DC (see Errata, item 11).*
- **State fields:**
  - `attitude` (number, initial `-2`) — non-default; starts hostile.
  - `hidden` (boolean, initial `true`) — concealed above the room.
  - `departed` (boolean, initial `false`) — it has slunk away for good
    (successful persuasion); a departed spider is removed from play.
  - `attitude_fixed` (boolean, initial `false`) — once true (combat
    triggered), attitude is fixed at -10 permanently.
  - `current_hp` (number, initial `14`) — declared as required for
    combat-capable NPCs; equals the stat block's HP.
- **Attitude Limits:** maximum 0 ("to a maximum of 0"); no minimum
  specified by the scenario; at most ±1 change per turn.  Once
  `attitude_fixed` is set (combat triggered), attitude is fixed at
  -10 permanently, outside the usual limits.
- **Aggro:** default — if attacked by the player, launch turn-based
  combat (it has combat stats): enemies [`spider`]; allies [`korbar`]
  if present and `will_fight == true`.  Combat is also triggered by
  room reaction `web_spider_attack` and its own reaction
  `spider_attacks_on_entry`; any such trigger sets `hidden = false`,
  `attitude = -10`, `attitude_fixed = true`.
- **Reactions:**
  - **`spider_attacks_on_entry`** (recurring): Trigger — player enters
    `axe_handle_lower`.  Condition — spider alive, `departed ==
    false`, and `hidden == false` (i.e., it was *already* revealed
    before the player entered — typically after the player fled and
    returned; see Errata, item 9).  Consequences — it initiates
    combat: enemies [`spider`]; allies [`korbar`] if present and
    `will_fight == true`; set `attitude = -10`, `attitude_fixed =
    true` if not already.
- **Dialogue availability:** it never initiates conversation.  It
  replies (grudgingly) only if `attitude >= -2`.  Being in
  conversation does not prevent its attack triggers.  Attitude changes
  are bounded by its Attitude Limits (above).
- **Dialogue paths:**
  - **`flatter_spider`** — availability: in dialogue, `attitude_fixed
    == false`.  The player is pleasant or flattering.  Success gating:
    CHA check (DC 9, repeatable — rolled once per flattering
    exchange); per the scenario this is applied at post-validation,
    after the narrator proposes the attitude increase.  On success:
    `attitude` +1 (respecting the ±1/turn cap and the max of 0).  On
    failure: attitude unchanged.
  - **`provoke_spider`** — availability: in dialogue, `attitude_fixed
    == false`.  Threats or other negative behavior.  No check:
    `attitude` −1 (respecting the ±1/turn cap; no floor specified by
    the scenario).
  - **`persuade_passage`** — availability: in dialogue, `attitude >=
    0`.  The player tries to convince the spider to let them through.
    If the player is armed (carrying/wielding a `weapon`-tagged item)
    and passes a CHA check (DC 12, non-repeatable): the spider sizes
    them up and grudgingly slinks away, disappearing from the game:
    set `departed = true`.  If the player is unarmed or the check
    fails: the spider verbally agrees — a lie; it remains where it is
    and still attacks per its normal triggers (`web_spider_attack`,
    `spider_attacks_on_entry`).
- **Will-Reveal Topics:**
  - **`korbar_as_prey`** — gating: in dialogue (attitude >= -2).
    Conveys: it knows Korbar only as the delicious two-legs it hasn't
    managed to catch — yet.  Consequences: none (flavor).
- **Knowledge:** it is vain, stupid, suspicious, and malicious, but
  can be flattered; it is hungry for blood; it lurks in the webbing
  above the lower handle.
- **Combat group:** none (fights alone).

### `korbar` — "Korbar" (type: `npc`)

- **Location:** `bag_floor`, sitting amidst the rubbish under a giant
  overturned soup ladle.
- **Combat stats (verbatim):** Class Fighter; Race Dwarf; Level 3;
  STR 15, DEX 10, CON 14, INT 10, WIS 12, CHA 9; Proficiency Bonus
  +2; HP 29; AC 18 (plate); Saving Throws: STR, CON; Damage: 3
  (unarmed).  Inventory: a rusty and smelly suit of plate mail (AC
  18).  *Not provided: initiative modifier (see Errata, item 11).*
- **Contained entities:** [`plate_armor`] (worn).
- **State fields:**
  - `attitude` (number, default `0`) — cynical and tired, but willing
    to converse.
  - `believes_spider_dead` (boolean, initial `false`) — convinced (by
    the player) that the spider is dead.
  - `will_fight` (boolean, initial `false`) — persuaded to stand and
    fight despite her fear; fights alongside the player.
  - `following` (boolean, initial `false`) — following the player as a
    companion (see Follower Behavior below).
  - `unconscious` (boolean, initial `false`) — knocked out at 0 HP for
    the rest of the game (special rule replacing default death; see
    Aggro).
  - `rapport_count` (number, initial `0`) — how many general
    conversation-based attitude increases have been applied (cap 3).
  - `current_hp` (number, initial `29`) — declared as required for
    combat-capable NPCs; equals the stat block's HP.
- **Attitude Limits:** minimum -10 (she attacks on reaching it); no
  maximum specified by the scenario.  Ordinary shifts are at most ±1
  per turn (general increases additionally capped at 3 total via
  `rapport_count`).  The `convince_spider_dead` +3 is a special
  one-off whose implementation must allow it past the per-turn cap.
- **Follower Behavior:** enabled via dialogue path `convince_follow`.
  Refused rooms: `secret_pocket` (her armor can't squeeze through the
  flap).  While following: she helps lug the `key` (skips the
  `heavy_key_movement` STR check when in the same room, §1E), helps at
  the padlock (`insert_key` DC 10 instead of 14), and fights alongside
  the player as an ally whenever combat breaks out in her presence if
  `will_fight == true` (otherwise she cowers).
- **Aggro:** if her `attitude` reaches -10, she attacks: start combat
  (enemies [`korbar`]).  If attacked by the player: default — start
  combat (she has combat stats).  *Special combat rule:* if her HP
  reaches 0 she falls unconscious for the rest of the game (`alive`
  stays true; set `unconscious = true`) instead of dying; the player
  may then also kill her (`alive = false`), which accomplishes
  nothing.  Her body is too heavy to haul anywhere.
- **Reactions:** none beyond the Aggro rules above.
- **Dialogue paths:**
  - **`positive_rapport`** — availability: in dialogue, `rapport_count
    < 3`.  The player engages positively — treats her respectfully,
    commiserates with her plight.  Success gating: GM discretion —
    only if the player makes an actual effort (not handed out like
    candy).  On success: `attitude` +1 and `rapport_count` +1.
  - **`mock_korbar`** — availability: in dialogue.  The player
    engages negatively, e.g., makes fun of her.  Success gating: GM
    discretion.  Effect: `attitude` −1 per turn (minimum -10); at
    -10 she attacks (see Aggro).
  - **`convince_spider_dead`** — availability: in dialogue.  The
    player tries to convince her the spider is dead (regardless of
    whether it's true).  Success gating: the GM must judge the player
    makes a convincing case (based on the dialogue), plus a CHA check
    (DC 15, repeatable); physical evidence — e.g., a body part cut
    from the spider (a soft item) — skips the CHA check.  On success:
    `attitude` +3 and set `believes_spider_dead = true`.
  - **`convince_follow`** — availability: `attitude >= 1` and
    `believes_spider_dead == true`.  The player convinces her to
    follow them up (or down) the axe.  Success gating: CHA check (DC
    8, repeatable).  On success: set `following = true` (see Follower
    Behavior above for what this entails).
  - **`persuade_fight`** — availability: `attitude >= 3`.  The player
    persuades her to stand and fight despite her fear of the spider.
    No check required — the trust already earned is enough.  On
    success: set `will_fight = true`; from then on she fights
    alongside the player whenever combat breaks out in her presence
    (a capable fighter even unarmed).
- **Will-Reveal Topics:**
  - **`spider_stalker`** — gating: none; she readily offers this
    whenever it comes up.  Conveys: a giant spider has been stalking
    her for as long as she's been here; she is very afraid of spiders
    and will refuse to fight it unless persuaded.  Consequences: set
    `knows_spider_threat = true`.
  - **`bag_of_holding_info`** — gating: `attitude >= 1`.  Conveys:
    what this cave is — a Bag of Holding — plus basic information
    about what a Bag of Holding is.  Consequences: set
    `knows_bag_of_holding = true`.
  - **`secret_pocket_info`** — gating: `attitude >= 3`.  Conveys: a
    giant handkerchief on the rubbish pile covers a secret pocket in
    the bag floor; she hasn't been able to see inside (her armor can't
    fit through the flap, and she dares not remove it because of the
    spider).  Consequences: set `handkerchief.hidden = false` and
    `knows_secret_pocket = true`.
- **Knowledge:** her party stuck her in this bag during a stealth
  mission, then forgot about her; she's unsure how long ago — time,
  like space, functions strangely in here; the giant battleaxe was her
  weapon when she was full-sized outside; her armor clatters every
  time she moves; she is unarmed; she is drunk and miserable.
- **Combat group:** none (fights alone, or alongside the player as an
  ally once `will_fight`).

### `rubbish_pile` — "pile of giant rubbish" (type: `feature`)

- **Location:** `bag_floor`.
- **Contained entities:** [`toenail_sword`].  (No open/close
  functionality, so deliberately **no** `container` tag and no `open`
  state field.)
- **On-Examine Effects** (triggered by explicitly examining the pile,
  the room, or any item within it — not by the automatic room-entry
  description; effects 1–3 trigger on any explicit examination):
  1. The player notices the giant toenail clipping in the pile: set
     `toenail_sword.hidden = false`.  (Happens on the first explicit
     examination; no check.)
  2. INT check (DC 8, non-repeatable — the scenario text is
     self-contradictory here; see Errata, item 6): on success the
     player realizes this is not random junk but some adventurer's
     supplies, much like their own missing pack: set
     `knows_rubbish_is_supplies = true`.
  3. If `knows_rubbish_is_supplies == true`, and this is another
     explicit examination, and `knows_bag_of_holding == false`: INT
     check (DC 14, non-repeatable).  On success the player realizes
     they are inside a magical Bag of Holding, and notices the
     rubbish's proportions are uneven — the bag's magic shrinks items
     by different amounts: set `knows_bag_of_holding = true`.
  4. **Rigorous examination only:** if this is not the first
     examination (`toenail_sword.hidden == false`), and
     `handkerchief.hidden == true`: WIS check (DC 15, non-repeatable).
     On success the player notices the giant handkerchief and feels
     it's somehow important: set `handkerchief.hidden = false`.
- **Soft-item guidance:** a pre-generated collection of plausible
  (possibly humorous) giant rubbish items — copper pieces, empty
  potion bottles, used corks, lint, moldy sandwiches, etc. — held as
  soft items, so the GM can accept them into the narrative (for the
  soft-state step).
- **Tags / interactions / state fields / reactions:** none.

### `toenail_sword` — "giant toenail clipping" (type: `item`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).
- **State fields:** `hidden` (boolean, initial `true`) — revealed by
  `rubbish_pile` on-examine effect 1.
- **Tags:** `weapon` (referenced by the web STR check and the
  spider's `persuade_passage` path).
- **Equippable:** yes — wielded in one hand like a shortsword: 1d6
  piercing damage, finesse, light.
- **Take Check:** removing it from the loose pile requires a DEX
  check (DC 8); assumed repeatable — on failure it stays stuck, no
  further effect (see Errata, item 16).  Applies only until the first
  successful take (thereafter the item is held, not in the pile).  It
  then functions as a shortsword.
- **Interactions / reactions / on-examine effects:** none.

### `handkerchief` — "giant handkerchief" (type: `feature`)

- **Location:** `bag_floor`, draped over a corner of the
  `rubbish_pile`.  (A feature, not an item: giant-sized, cannot be
  carried.)
- **State fields:**
  - `hidden` (boolean, initial `true`) — revealed by `rubbish_pile`
    on-examine effect 4, or by `korbar`'s topic `secret_pocket_info`.
  - `moved_aside` (boolean, initial `false`) — lifted/shoved aside,
    exposing the secret flap.
- **Special interactions:**
  - **`move_aside`** — lift the filthy, damp handkerchief or move it
    aside.  Availability: `hidden == false`.  Effect: reveals the
    small flap in the canvas floor underneath, leading down into
    darkness: set `moved_aside = true` (this makes the `bag_floor`
    exit `secret_flap` available, §1F).
- **Tags / reactions / on-examine effects:** none.

### `key` — "giant iron key" (type: `item`)

- **Location:** `secret_pocket` (lying in the room).
- **Tags:** `heavy` (referenced by `heavy_key_movement`, §1E).
- **Equippable:** no.
- **Take Check:** none — the player can carry it; narration should
  emphasize the difficulty of hauling it from point to point.
- **State fields / interactions / reactions / on-examine effects:**
  none.  (See `heavy_key_movement` for the movement rule, `insert_key`
  for the win, and `rip_item_dropped` / `insert_key` for losing it.)

### `plate_armor` — "suit of plate mail" (type: `item`)

- **Location:** worn by `korbar` (contained in her).
- **Equippable:** no — although it is a suit of plate mail (AC 18),
  the player finds it far too cumbersome to wear.
- **Take Check:** availability — `korbar` is `unconscious` or not
  `alive` (stealing it from her; interpretation — see Errata, item
  12).
- **Tags / state fields / interactions / reactions / on-examine
  effects:** none.

---

## 1H. Cleanup

Consistency pass performed: all IDs snake_case and cross-referenced;
exactly one start room (`axe_head`) and one `player` entity; the
player is present in exactly one room; each item/NPC present in at
most one room (`toenail_sword` inside `rubbish_pile`, `plate_armor`
inside `korbar`); features spanning multiple rooms limited to
`giant_axe` and `webs` (per-room behavior of `webs` documented);
every referenced global flag, state field, and tag (`heavy`, `weapon`)
is defined; every initially-hidden entity has an unhide mechanism
(`padlock` ← rip examination; `fly` ← webs examination; `spider` ←
WIS checks or combat triggers; `toenail_sword` and `handkerchief` ←
rubbish examinations / Korbar's topic); the hidden exit `secret_flap`
has a planned reveal mechanism (`handkerchief.moved_aside`); the
one-way drop exits have return paths (climbing the handle); no entity
has the `container` tag (no open/close containers exist in this
scenario — the rubbish pile holds an item without open/close
semantics); no `stackable` items or consumables exist in this
scenario; no non-NPC entity has dialogue or aggro plans; both
combat-capable NPCs (`spider`, `korbar`) have stat blocks and
`current_hp` declarations, and all combat-starting reactions name
their combatants explicitly; every check is marked repeatable or
non-repeatable; every examination effect notes whether rigorous
examination is required; the preemptive reaction
(`web_spider_attack`) is marked as such; attitude limits are noted for
both attitude-shifting NPCs; Korbar's follower room blacklist
(`secret_pocket`) is recorded.

### Errata (deviations and interpretations)

1. **Added `player_death` game-over condition.**  The scenario never
   states that the player loses at 0 HP; assumed as the standard
   companion of 5e combat.
2. **Scenario typos.**  "Axe Head (Upper)" (Dropping) and "Axe Head
   (Lower)" (Web) were read as `axe_handle_upper` / `axe_handle_lower`.
3. **Win/loss scoping.**  Only `player_death` is a global game-over
   condition (§1E).  The win and the two route-specific losses (key
   through the rip; squeezing through the rip) are recorded as
   game-over consequences on `padlock` and `the_rip` (§1G).
4. **Spider encounter scoping.**  The spider attack is a single-NPC
   encounter, so it is NPC-scoped (aggro + entity/room reactions), not
   a global mechanic.
5. **`squeeze_through` failure.**  The scenario specifies no outcome
   for failing the DEX check; treated as a harmless failed attempt.
   Since the check is non-repeatable, a failed first attempt means the
   player can never die this way — a possible scenario hole, flagged
   for the author.
6. **Contradictory check repeatability.**  The rubbish INT check (DC
   8) is described as "a successful repeatable INT check (DC 8,
   non-repeatable)"; treated as non-repeatable.
7. **Drops bypass the web.**  Dropping over the side from
   `axe_handle_lower` is assumed not to require forcing through the
   web and not to trigger the spider (the scenario only mentions web
   traversal "along the path").
8. **Key-hauling scope.**  `heavy_key_movement` is applied to *all*
   room transitions (including drops and the flap squeeze); the
   scenario just says "pass between different rooms".
9. **Spider entry-attack timing.**  `spider_attacks_on_entry` fires
   only if the spider was already revealed at entry — not when the
   entry WIS check reveals it that same moment (otherwise the notice
   check would be a pure trap).
10. **`entered_from` state.**  Added to `axe_handle_lower` to
    implement the directional web rule ("returning in the direction
    from which they came, there is no impedance").
11. **Missing combat numbers.**  Neither NPC stat block gives an
    initiative modifier or flee DC; the player's own attack/damage
    stats are unspecified.  Defaults will be needed later.
12. **Stealing the plate armor.**  Assumed possible only when Korbar
    is unconscious or dead; the scenario just says "the player can
    steal" it.
13. **Korbar at 0 HP.**  Her falling unconscious instead of dying is a
    deviation from default NPC death handling, requiring the custom
    `unconscious` state field and special combat handling.
14. **Korbar's padlock help.**  "If KORBAR is present, she will help"
    at the padlock can only happen if she is `following` (alive and
    conscious), since she otherwise never leaves `bag_floor`.
15. **`rapport_count`.**  Added to enforce the scenario's cap of 3
    general conversation-based attitude increases for Korbar.
16. **Toenail take-check.**  Repeatability of the DEX 8 removal check
    is unspecified; assumed repeatable with no failure side effect.
17. **"Armed" definition.**  For the web STR check and
    `persuade_passage`, "armed" is taken to mean carrying/wielding a
    `weapon`-tagged item (i.e., the `toenail_sword`).
18. **Non-repeatable check tracking.**  Several checks are
    non-repeatable; the engine tracks attempts and rejects repeats.
    Chained checks (e.g., the rip's DC 17 realization requires the
    earlier DC 12 success) are gated via the knowledge flags set on
    success (§1D).
19. **Fly death timing.**  The fly's death-when-the-player-leaves is
    triggered on the player's exit *attempt* (while the fly is still
    in the current room), because an entity reaction can only fire
    while its entity is in the current room.
20. **Follower restriction.**  Korbar's refusal to enter
    `secret_pocket` is recorded as a refused room under her Follower
    Behavior (the engine clears `following` if the player enters such
    a room).
