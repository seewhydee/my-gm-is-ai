# Scenario Map — "You're Trapped in a Bag!"

Working plan for the adventure module, produced by Step 1 of
`schema/scenario-generation.md` from `scenario.md`.  All IDs are
snake_case; `self` is reserved and unused.

## Conventions for the JSON conversion

- Checks and DCs cannot branch within a single Resolvable, so
  condition-exclusive variants are written as separate
  interactions/paths: `padlock.insert_key` / `insert_key_assisted`,
  `spider.persuade_passage` / `persuade_passage_unarmed`,
  `the_rip.squeeze_through` / `squeeze_through_confirmed`, and
  Korbar's `positive_rapport_first/second/third`.
- The engine model names the game-over field `trigger_id` (not
  `trigger`).
- Reserved state fields (such as `alive`) need not be declared;
  condition reads of undeclared reserved fields fall back to their
  documented defaults.  Accordingly `alive` is NOT declared on `fly`,
  `spider`, or `korbar`.
- Results cannot increment numeric state, so counters are modeled with
  boolean flags (e.g. Korbar's `rapport_1/2/3`).
- Within one examination, each `on_examine` event's condition is
  evaluated against the pre-examination state, so chained discoveries
  (the rip's INT 12 → INT 17; the rubbish pile's INT 8 → INT 14; the
  staged deep-rubbish finds) inherently require separate examinations,
  matching the scenario.

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
    WIS, CHA), proficiency bonus, HP, AC, saving throws, and **skills**
    (5e skill checks — `stat_check`s whose `stat` names one of the 18
    SRD skills; proficiency comes from
    `player.skill_proficiencies`).
  - **Resolution system:** 5e (stat checks, saves, turn-based combat).
  - **Initial player stats:** Class Rogue; Race Human; Level 4;
    STR 10, DEX 13, CON 12, INT 11, WIS 10, CHA 10; Proficiency
    Bonus +2; HP 27 (current 27 / max 27); AC 11 (unarmored + DEX
    bonus); Saving Throws: DEX, INT.
  - **Skill proficiencies** (recorded in `default-player.json`):
    Acrobatics, Arcana, Athletics, Deception, Insight, Investigation,
    Perception, Persuasion, Sleight of Hand, Stealth.  The adventure
    is written for a Rogue and rewards these; a different class simply
    lacks the +2 proficiency (DCs unchanged).  Checks name skills
    throughout: spider noticing → Perception; rubbish finds →
    Investigation; web forcing → Athletics; spider flattery →
    Persuasion; overheard muttering → Insight; rip squeeze and
    lock-picking climb → Acrobatics; lock-picking tumblers → Sleight
    of Hand; label/scroll reading → Arcana.
  - **Starting inventory:** empty (the scenario explicitly clears any
    supplied character sheet's inventory).
  - **Combat numbers not specified by the scenario** (defaults chosen
    here): spider `initiative_mod` +3 (from DEX 16), flee DC engine
    default 10; Korbar attack +4 (STR 15 plus proficiency +2),
    `initiative_mod` +0 (DEX 10), flee DC engine default.  The
    player's attack/damage behavior (unarmed damage, weapon
    proficiency) is engine-internal — the player model carries no
    such fields — so `default-player.json` holds exactly the
    scenario-given values above.

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
are stuck in the webs; one of the larger masses is, on rigorous
examination, a previous prisoner (`prisoner_husk`).  The handle
continues up to `axe_head` and down (towards denser webs) to
`axe_handle_lower`; dropping over the side into the darkness below is
possible but the landing cannot be seen.

### `axe_handle_lower` — "Axe Handle (Lower)"

Here the webs surrounding the handle are very dense and must be got
through (quietly or loudly) to continue along the path.  Peering over
the side, numerous irregularly-shaped objects are visible on the cave
floor below, and a drop from here looks safe.  The spider lurks in the
webs above (hidden).  A hoard (`spider_hoard`) lies at the web's base
once the spider is gone.  Connects up to `axe_handle_upper` and down
to `bag_floor`.

### `bag_floor` — "Bag Floor"

The floor of the cave, covered with a loose pile of giant-sized
rubbish: copper pieces, empty potion bottles, used corks, lint, moldy
sandwiches, and more disgusting items.  The base of the giant axe
rests in the center of the pile; the handle can be clambered back up
from here (to `axe_handle_lower`).  KORBAR is here, beneath a giant
overturned soup ladle (`korbar_shelter`).  The deep rubbish conceals
four giant potion vats, rations, a giant lockpick, a giant faerie-fire
scroll, and — deepest of all — a Bag of Holding Within
(`bag_within`).  A concealed flap in the floor (hidden under a giant
handkerchief) leads down to `secret_pocket`.

### `secret_pocket` — "Secret Pocket"

A closet-sized space below the cave floor, accessed by squeezing
through a concealed flap in the floor of `bag_floor`.  Walls of the
same faintly-glowing canvas, but stickier and smellier — the oldest
part of the bag.  Contains a large iron key, a sewn-in care label
(`care_label`), a sending stone (`sending_stone`), and a hip flask of
emergency gin (`emergency_gin`).  The only exit leads back up to
`bag_floor`.

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
extricate at a glance — though one of the larger masses, on rigorous
examination, is a previous prisoner (`prisoner_husk`).

### `fly` — "Fly" (type: `npc`)

A talking fly, dog-sized relative to the player, stuck in the webs in
`axe_handle_upper`.  Initially hidden (unnoticed); speaks in a weak
nasally whine.  Mortally wounded; dies shortly after being found —
unless the player frees it (see §1G).

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
player can carry it, but hauling it around is arduous.  It opens the
padlock — the straightforward way out of the bag (a Rogue can also
pick the lock; see `padlock.pick_lock`, §1G).

### `plate_armor` — "suit of plate mail" (type: `item`)

KORBAR's rusty, smelly, very noisy suit of heavy plate mail (AC 18),
worn by her at start.  Can be stolen from her, but is far too
cumbersome for the player to wear.

### `prisoner_husk` — "web-wrapped mass" / "desiccated prisoner" (type: `feature`)

One of the larger wrapped masses in the webs at `axe_handle_upper`;
on rigorous examination it turns out to be a desiccated shrunken
person — a previous prisoner.  Holds the husk loot (see §1G).

### `prisoner_journal` — "prisoner's journal" (type: `item`)

The husk's journal, tucked in its folds.  Readable; delivers two real
hints (the Korbar/secret-pocket muttering, the spider's liking for
compliments) buried in satire, and trails off "The spider is actually
quite reasonable if you—".

### `scroll_of_sleep` — "Scroll of Sleep" (type: `item`)

Lodged in the husk's skeletal grip — the spell the prisoner never got
to cast.  One use; read at the spider to put it to sleep (see §1G).

### `scroll_of_mage_armor` — "Scroll of Mage Armor" (type: `item`)

Tucked in the journal's pages.  One use; read on self (AC 14) or on
Korbar (unlocks doffing the armor before the spider is dead).

### `dagger` — "dagger" (type: `item`, SRD data-pack reference)

A normal-sized dagger found with the husk's belongings.  Referenced
directly from the SRD pack; no corpus entity needed.  A simple-weapon
alternative to the toenail sword.

### `potion_vat_amber` — "amber potion vat" (type: `feature`)

One of four giant unbroken potion bottles in the deep rubbish of
`bag_floor`.  This one is a Potion of Healing (2d4+2); a drop of it
can revive the freed fly (see `fly`).

### `potion_vat_emerald` — "emerald potion vat" (type: `feature`)

The Antivenom: cures `poisoned` and grants the `antivenom` status
effect (CON-save advantage vs. poison) until cleared/rest.

### `potion_vat_crimson` — "crimson potion vat" (type: `feature`)

The Potion of Invisibility: drinking applies the `invisible` status
effect (overridden in corpus to persistent / until-cleared).

### `potion_vat_black` — "ink-black potion vat" (type: `feature`)

The Poison.  The liquid is self-evidently wrong (it drinks the glow,
smells of nothing, radiates cold) — the player's clue.  Sipping burns
(CON save vs. 1d8); drinking fully is a game-over (lose).  "The fine
print kills."

### `giant_rations` — "giant rations" (type: `item`)

Edible-if-revolting rations from the deep rubbish.  Nibbling heals
1 HP; a rapport gift for Korbar.

### `giant_lockpick` — "giant lockpick" (type: `item`)

A giant lockpick, the size of a two-handed staff, from the deep
rubbish.  A simple two-handed weapon (1d6 bludgeoning); a blade for
the web/fly checks; the tool for Picking the Giant Lock (§1G).

### `giant_faerie_fire_scroll` — "giant scroll" (type: `feature`)

A scroll of Faerie Fire, twice the player's height, in the deep
rubbish.  Too large to carry; unfurled with a STR check and read
aloud only in `bag_floor`; its light reveals the handkerchief.

### `bag_within` — "leather pouch" (type: `feature`)

A Bag of Holding Within, in the deepest rubbish.  Opening it (confirmed)
ruptures both bags — game over (lose).

### `care_label` — "care label" (type: `feature`)

The bag's manufacturer's care label, sewn into the seam of
`secret_pocket`.  Reading the fine print (INT/Arcana DC 12) sets
`read_label`.

### `sending_stone` — "sending stone" (type: `feature`)

Half a pair of sending stones in `secret_pocket`; too heavy to move.
`listen` (WIS DC 12) raises the party wizard's voice; `speak_into`
goes unanswered.  Telling Korbar contributes to rapport.

### `emergency_gin` — "hip flask of gin" (type: `item`)

A hip flask (beer-barrel-sized at player scale) in `secret_pocket`.
Lugged out with a STR check (DC 12); a sip heals 1 HP; the premium
rapport gift for Korbar.

### `korbar_shelter` — "overturned soup ladle" (type: `feature`)

Korbar's makeshift shelter on the bag floor.  Rigorous examination
reveals her stash: `party_badge` and `wineskin_dregs`.  Safe rest
spot once her attitude ≥ 1.

### `party_badge` — "party badge" (type: `item`)

An enameled crest — her old adventuring company's badge.  Shown to
Korbar, it unlocks the abandonment dialogue.

### `wineskin_dregs` — "wineskin of dregs" (type: `item`)

From Korbar's stash; she guards it jealously (takeable only while she
is unconscious).  A rapport gift.

### `spider_hoard` — "spider's hoard" (type: `feature`)

The vain spider's hoard at the base of the web in `axe_handle_lower`.
Searchable once the spider is dead, departed, or asleep.  Soft items
only (too cumbersome to carry).

### `spider_corpse` — "spider corpse" (type: `feature`)

The spider's corpse in `axe_handle_lower` once it dies.  Rigorous
examination yields `spider_fang` (hard item) and a venom sac (soft
item).

### `spider_fang` — "spider fang" (type: `item`)

Physical evidence that the spider is dead; makes `convince_spider_dead`
check-free (equivalent to the `spider.alive == false` skip).

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

- **`key_lost`** — The giant key has slipped through the rip and is
  gone forever.  Set by the `insert_key` failure cascade (a
  `then_check` failure cannot carry `game_over` directly) and by
  `rip_item_dropped`; a top-level `game_over_conditions` entry
  watches it.  Initial value: `false`.

- **`toenail_freed`** — The toenail clipping has been pried loose
  once; gates the `toenail_sword` take check so it applies only until
  the first successful take.  Initial value: `false`.

- **`rapport_1` / `rapport_2` / `rapport_3`** — Track Korbar's general
  conversation-based attitude increases (cap 3).  Results cannot
  increment numeric state, so three boolean flags stand in for a
  counter, gating the three `positive_rapport_*` dialogue paths.
  Initial values: `false`.

- **`rubbish_vats_found`** — The deep-rubbish stage-one examination
  (INT/Investigation DC 12) succeeded: the four potion vats, the
  rations, and the lockpick are revealed.  Gates stage two.  Initial:
  `false`.

- **`rubbish_scroll_found`** — The stage-two examination (INT/
  Investigation DC 15) succeeded: the giant faerie-fire scroll is
  revealed.  Gates stage three.  Initial: `false`.

- **`rubbish_bag_found`** — The stage-three examination (INT/
  Investigation DC 17) succeeded: `bag_within` is revealed.  Initial:
  `false`.

- **`read_label`** — The care label's fine print has been deciphered
  (INT/Arcana DC 12).  Makes identifying `bag_within` free.  Initial:
  `false`.

- **`wizard_voice_heard`** — The sending stone has produced the party
  wizard's voice.  Gates Korbar's `tell_about_stone` dialogue path.
  Initial: `false`.

- **`told_about_stone`** — Korbar has been told about the wizard's
  voice (+1 attitude, once).  Initial: `false`.

- **`knows_axe_mark`** — The player has noticed the dwarven smith's
  mark on the giant axe (rigorous examination).  Gates Korbar's
  `ask_about_axe_mark` path.  Initial: `false`.

- **`knows_axe_is_korbars`** — Korbar has confirmed the axe is her own
  forge work (one-time +1 attitude dialogue path).  Initial: `false`.

- **`knows_abandonment`** — Korbar has told the abandonment story
  (party badge or axe-mark follow-up).  Gates the `why_bag_locked`
  topic.  Initial: `false`.

- **`knows_lockpick_method`** — The player has studied the padlock
  (INT DC 12) and realizes it can be picked, and how.  Gates
  `padlock.pick_lock`.  Initial: `false`.

- **`fly_freed`** — The fly has been worked free of the web (DEX
  check on `webs`).  Its death reactions are disabled while freed.
  Initial: `false`.

- **`fly_watching_lower`** — The freed fly has been sent ahead to
  `axe_handle_lower`; its alarm reveals the spider on entry.  Initial:
  `false`.

- **`fly_vouched`** — The freed fly has vouched for the player to
  Korbar (+1 attitude, once).  Initial: `false`.

- **`fly_revived`** — The freed fly was healed with a drop of the
  amber potion; it lives and grants both fly boons.  Initial: `false`.

- **`quiet_cut_failed`** — A quiet web-cut attempt failed: the web
  was disturbed.  A `flag.set` reaction (`quiet_cut_failure_spider`)
  triggers the spider encounter; the flag is then cleared.  Initial:
  `false`.

- **`korbar_armed`** — Korbar has been given a weapon
  (`offer_weapon`).  Lowers `persuade_fight` to attitude 2.  Initial:
  `false`.

- **`korbar_mage_armored`** — The Scroll of Mage Armor was read on
  Korbar.  Lets her doff the armor before the spider is dead.  Initial:
  `false`.

- **`bag_within_warned`** — The player has been warned once about
  opening `bag_within` (the two-step pattern).  Initial: `false`.

- **`bag_within_identified`** — The player has recognized `bag_within`
  as a Bag of Holding (INT/Arcana DC 12, or free with `read_label`).
  Gates the `open_it` interactions.  Initial: `false`.

---

## 1E. Mechanics

Resolution system: 5e (see §1A).  Global game-over conditions and
adventure-wide rules are listed here.  Win/loss conditions reachable
by one specific route are NOT listed here; they are recorded as
game-over consequences on the owning room/entity (see `padlock` and
`the_rip` in §1G).

### `heavy_key_movement` — Kind: Gated traversal checks (global rule)

While the `key` (tag `heavy`) is in the player's inventory, any
movement between rooms requires a STR check (DC 12, repeatable).  On
failure, the move is canceled: the player struggles to move the heavy
key but can try again.  The check is skipped if `korbar` is in the
same room with `following == true` (and conscious): she assists with
the key.  Applies to all room transitions, including the drop exits
and the secret flap (see Design Decisions, item 8).  Narration should
emphasize the difficulty of hauling the key.

*Implementation:* the only construct that cancels movement on a failed
check is an exit's own `traversal_check`, so every exit carries a
gated `traversal_check`: gating `tag:heavy`, STR DC 12 repeatable,
`skip_check_if` Korbar is following, alive, and conscious in the same
room.  Only failure carries narration (emphasizing the key's weight);
success is silent to avoid spamming narration on every move.  Two
exceptions:

- `axe_handle_lower`'s `up_handle`/`down_handle` already carry the web
  `traversal_check`, and an exit supports only one.  While the web
  gates, its STR DC 14 dominates the key's DC 12 anyway; the accepted
  residual gap is that those two exits apply no key check even once
  the web is cleared.
- `flap_up` has no `skip_check_if`: Korbar refuses to enter
  `secret_pocket` (follower blacklist), so she can never be in the
  same room when the player climbs back up through the flap, and the
  assist skip cannot apply there.

### `korbar_knocked_out` — Kind: Reaction mechanic (global rule)

Trigger — Korbar's `current_hp` drops to 0 or below (an
`entity_state.changed` event with `event:entity_id == korbar`,
`event:field == current_hp`, `event:new_value <= 0`; the engine
auto-clears her `alive` field, which disables entity-scoped reactions,
so this must be a mechanic-scope reaction).  Consequences — she falls
unconscious for the rest of the game instead of dying: set
`korbar.alive = true`, `korbar.unconscious = true`,
`korbar.current_hp = 1`, and `korbar.passive = true`; narrate her
collapse.  Special rule replacing default NPC death (see Design
Decisions, item 13).  It is deliberately not `once`: if her HP is
reduced again while unconscious she returns to 1 HP unconscious rather
than being left at ≤ 0 HP.

### `key_lost_game_over` — Kind: Global game-over condition

Lose condition: `flag:key_lost == true` (set by the `insert_key`
failure cascade and by `rip_item_dropped`; a `then_check` failure
cannot carry `game_over` directly).  Narrative: the key has fallen
through the rip; the player is trapped forever.  Implemented as a
top-level `game_over_conditions` entry, `trigger_id`
`key_lost_game_over`.

### `invisible_breaks_on_attack` — Kind: Reaction mechanic (global rule)

Trigger — the player takes an attack action (`interaction.used` with
`event:interaction_id == attack`), while the `invisible` status effect
is active on the player.  Consequences — remove the player's
`invisible` status effect and narrate the veil dropping (the potion
does not survive violence).  `phase: immediate`, so the cure applies
before the attack resolves.  (The engine does not clear `invisible`
on attack — the SRD pack notes this explicitly — so this reaction
implements the SRD behavior.)

### `invisible_breaks_on_combat` — Kind: Reaction mechanic (global rule)

Trigger — `combat.started` while the player has `invisible`.  Reason:
combat is a revealing action (the spider senses the player through the
web, per the vibration logic; any fight drops the veil).  Consequences
— remove the player's `invisible` status effect.  This is what makes
"invisibility + quiet cut" the surest combo: the quiet cut succeeds
without combat, so the veil survives; any fumbled approach starts
combat and drops it.

### `quiet_cut_failure_spider` — Kind: Reaction mechanic (global rule)

Trigger — `flag.set` with `event:flag_id == quiet_cut_failed`.
Condition — the spider is alive, present in `axe_handle_lower`, and
`departed == false` (and not incapacitated).  Consequences — clear the
`quiet_cut_failed` flag (so a later failure can re-trigger) and
`trigger_encounter: "spider"` (the spider senses the disturbance
through the web and attacks; its aggro narrates the reveal and starts
combat).  *Why a mechanic rather than an `interaction.used`
reaction:* a reaction on `interaction.used` fires before the check
resolves and cannot see the outcome; the flag routes the *failure*
outcome into a deferred `flag.set` reaction, implementing the
scenario's "on failure the spider attacks".

### `overhear_korbar_muttering` — Kind: Reaction mechanic (global rule)

Trigger — `rest.completed` (any kind).  Condition — `korbar` alive,
`korbar.attitude >= 1`, and the player in `bag_floor` (her shelter is
the safe rest spot).  Consequences — narrate one of Korbar's muttering
fragments (rotating by knowledge flags: the pocket/secret hint, the
axe-mark hint, the key hint) and offer a free WIS (Insight) check
(DC 11, repeatable) to catch the useful part; success appends a
`reveals` string.  The shelter's safety itself is authored prose —
there is no safe-rest-location construct.

*Notes:*

- Player death is NOT listed as a mechanic: the engine ends the game
  (a loss) automatically whenever the player's HP drops to 0, from any
  source, unless a `player.died` rescue reaction averts it by
  restoring HP above 0.  This adventure has no rescue effects, so
  reaching 0 HP is always lethal — note that the drop exits can
  therefore kill a player weakened by the spider.
- The spider ambush/attack encounter is deliberately **not** a global
  mechanic: it involves a single NPC, so it is NPC-scoped — see the
  `spider` entry (§1G) and the `axe_handle_lower` room reactions (§1F).
- The route-specific game-overs — the win (`padlock.insert_key`
  success or `padlock.pick_lock` success), the key falling through the
  rip (`rip_item_dropped` and the `insert_key` failure cascade), and
  squeezing through the rip (`the_rip.squeeze_through_confirmed`) —
  are recorded on `padlock` and `the_rip` in §1G.

### Status effects (corpus block)

The corpus needs a `status_effects` block with three entries (the
validator warns when a corpus entry replaces a pack entry wholesale —
accepted):

- **`invisible`** (override): `scope: "persistent"`, `duration:
  "until_cleared"`, system effects unchanged (`advantage_on_attack`,
  `disadvantage_against`).  The built-in is combat-scoped/rounds; the
  potion must persist across rooms.  Clearing is reaction-driven
  (`invisible_breaks_on_attack` / `invisible_breaks_on_combat`).
- **`poisoned`** (override): `scope: "persistent"`, `duration:
  "until_cleared"`, system effects unchanged
  (`disadvantage_on_attack`, `disadvantage_on_ability_checks`).  The
  built-in clears at combat end, which would make the antivenom
  pointless.  A long rest still clears it.
- **`antivenom`** (new): `scope: "persistent"`, `duration:
  "until_cleared"`, `system_effects: { "5e": { "save_advantage":
  ["CON"] } }`.  Applied by `potion_vat_emerald.drink`.  Note the
  breadth: this grants advantage on *all* CON saves, not just saves
  vs. poison as the scenario narrates — harmless here, because the
  only CON saves in this adventure are the spider's venom and the
  ink-black sip.

---

## 1F. Rooms (Pass 2)

### `axe_head` — "Axe Head"  [START]

- **Exits:**
  - **`down_handle`** → `axe_handle_upper`: "Clamber carefully down
    the axe handle".  No conditions or checks.
  - **`drop_down`** → `bag_floor` (one-way): "Drop down into the
    darkness below".  Side effects on arrival: lose 2 DEX, 2 CON
    (permanent), and 3d6 HP.  (`alter_stat` accepts only integer
    values, so the scenario's "1d4 DEX, 1d4 CON" is implemented as the
    fixed expectation −2/−2; the HP damage does support dice.)  If
    `korbar` is present in `bag_floor`, narrate her astonishment.
    Return path: climbing back up the handle from `bag_floor`.

- **Entities present:** `player` (start), `giant_axe`, `the_rip`,
  `padlock` (hidden).

- **Special interactions:** none.

- **Reactions:** none (the rip's and padlock's behaviors are
  entity-scoped; see `the_rip` and `padlock`, §1G).

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

- **Entities present:** `giant_axe`, `webs`, `fly` (hidden),
  `prisoner_husk` (hidden).

- **Special interactions:** none.

- **Reactions:** none room-scoped (the Fly's groaning and death, and
  the prisoner husk's reveal, are entity-scoped; see `fly` and
  `prisoner_husk`, §1G).

- **State fields:** none.

- **On-Examine Effects:** none room-scoped; examining the webs or the
  stuck masses uses the `webs` entity's on-examine effects (§1G).

### `axe_handle_lower` — "Axe Handle (Lower)"

- **Exits:**
  - **`up_handle`** → `axe_handle_upper`: "Force your way back up the
    web-choked handle".  *Web-gated:* if `web_cleared == false` and
    `entered_from == "below"` (i.e., proceeding upward after entering
    from below), the player must first get through the web: STR
    (Athletics) check (DC 14 unarmed, DC 10 with a blade-like weapon
    via `using_results` keyed on `toenail_sword`, `dagger`,
    `giant_lockpick`, and the `"*"` wildcard — any hard item the GM
    deems blade-like; exact keys take precedence; repeatable).  On
    success, set `web_cleared = true` (passage is free thereafter).
    Any forcing attempt, successful or not, triggers reaction
    `web_spider_attack` if the spider is present (and not
    incapacitated).  Returning in the direction one came from is not
    impeded.  *Quiet alternatives* (which do not provoke the spider)
    are interactions on the `webs` entity, not exits — an exit
    supports only one `traversal_check` (§1G).
  - **`down_handle`** → `bag_floor`: "Force your way down the
    web-choked handle".  *Web-gated* exactly as above, but when
    `entered_from == "above"`.
  - **`drop_down`** → `bag_floor` (one-way): "Drop over the side of
    the handle".  Side effects: momentarily winded, otherwise
    uninjured (no mechanical effect).  Not web-gated and does not
    trigger the spider (see Design Decisions, item 7).

- **Entities present:** `giant_axe`, `webs`, `spider` (hidden),
  `spider_hoard` (hidden), `spider_corpse` (hidden).

- **Special interactions:** none (the quiet web-cut / invisible-sneak
  interactions live on the `webs` entity, §1G).

- **Reactions:**
  - **`track_entry_direction_from_above`** (recurring): Trigger —
    `traversal.succeeded` on `axe_handle_upper`'s `down_handle` exit.
    Consequences — set `entered_from = "above"`.  No narration; exists
    to implement the directional web rule.  (`room.entered` has no
    origin context, hence the per-source-room pair.)
  - **`track_entry_direction_from_below`** (recurring): Trigger —
    `traversal.succeeded` on `bag_floor`'s `up_handle` exit.
    Consequences — set `entered_from = "below"`.  Known limitation:
    fleeing combat by `move` skips `traversal.succeeded`, so a combat
    flee *into* `axe_handle_lower` leaves `entered_from` stale
    (accepted).
  - **`notice_spider_on_entry`** (recurring): Trigger — player enters
    the room.  Condition — `spider` is alive, not `departed`, and
    `hidden == true`.  Consequences — WIS (Perception) check (DC 13,
    repeatable), implemented as a `then_check` inside the reaction's
    result (reaction effects cannot roll checks directly); on success
    the player notices the spider lurking above: set
    `spider.hidden = false`.  Failure is omitted, so a failed roll is
    silent (the player learns nothing).
  - **`web_spider_attack`** (recurring, preemptive): Trigger —
    `traversal.attempted` on exit `up_handle` or `down_handle`, firing
    only when the attempted traversal is actually web-gated (matching
    `web_cleared` and `entered_from` per exit) — whether the STR check
    would succeed or fail, whether or not the spider has been noticed,
    even mid-dialogue.  `phase: immediate`, while the action is still
    in progress.  Condition — `spider` is alive, present in the room,
    `departed == false`, and *not* `status_effect:spider.
    incapacitated` (a sleeping spider does not attack — the Sleep
    scroll).  Consequences — `trigger_encounter: "spider"`; the
    spider's aggro (§1G) supplies the narration and sets
    `spider.hidden = false`, `spider.attitude = -10`,
    `spider.attitude_fixed = true`; combat starts with enemies
    [`spider`], allies [`korbar`] only if she is present and
    `will_fight == true` (otherwise she is narrated cowering in fear
    and does not participate).  The engine blocks the room transition
    when combat starts, canceling the traversal.
  - **`fly_alarm_reveals_spider`** (recurring): Trigger — player
    enters the room.  Condition — `fly` alive, `flag:
    fly_watching_lower == true`, and `spider` alive, `hidden ==
    true`, and not `departed`.  Consequences — the freed fly's alarm
    buzzes from the web: set `spider.hidden = false` and narrate the
    fly's warning.  (Boon (a) of the freed fly; the watch itself ends
    on this entry — see the two reactions below.)
  - **`fly_dies_after_watch`** (recurring): Trigger — player enters
    the room.  Condition — `fly` alive, `flag:fly_watching_lower ==
    true`, and `flag:fly_revived == false`.  Consequences — the fly's
    watch is over and it is spent: set `flag:fly_watching_lower =
    false` and `fly.alive = false`; narrate its quiet death.  (Fires
    on the same entry as the alarm if the spider was hidden, or alone
    if the spider was already revealed or gone — the fly dies either
    way, per the scenario's "then the fly, exhausted, dies quietly".)
  - **`fly_watch_ends_revived`** (recurring): Trigger — player enters
    the room.  Condition — `fly` alive, `flag:fly_watching_lower ==
    true`, and `flag:fly_revived == true`.  Consequences — set
    `flag:fly_watching_lower = false`; narrate the revived fly
    zipping back to the player's shoulder, its watch done.  (A revived
    fly survives its watch and lives on.)

- **State fields:**
  - `web_cleared` (boolean, initial `false`) — the blocking web has
    been cleared (by force, by quiet cut, by invisible passage, or by
    the spider's own frantic flight); passage is thenceforth free.
  - `entered_from` (string, initial `""`) — which side the player last
    entered from: `"above"` or `"below"`.

- **On-Examine Effects** (any examination), two events (a single
  Result cannot conditionally include Korbar's sounds, so the
  combined "peer over the side" effect is split):
  - `peer_over_side`: if the player has not yet visited `bag_floor`
    (the reserved `visited` field, referenced but not declared), WIS
    check (DC 11, repeatable); on success the player discerns giant
    empty potion bottles, copper pieces, corks, and moldy sandwiches
    piled below.  `skip_check_if` on `room:bag_floor.visited`, so it
    auto-succeeds after a visit.
  - `hear_korbar_below`: condition `korbar` alive and in `bag_floor`;
    WIS check (DC 11, repeatable) with the same `skip_check_if`; on
    success the player hears faint clanking and muttering from below.

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
  `handkerchief` (hidden), `korbar_shelter`.  (The deep-rubbish finds
  — `potion_vat_*`, `giant_rations`, `giant_lockpick`,
  `giant_faerie_fire_scroll`, `bag_within` — are inside
  `rubbish_pile` and therefore not "present" in the room.)

- **Special interactions:** none.

- **Reactions:** none room-scoped.

- **State fields:** none.

- **On-Examine Effects:** examining the room itself counts as
  examining the `rubbish_pile` (same effects, §1G — including the
  staged deep-rubbish examinations) — the scenario applies the rubbish
  effects to "examining the rubbish or the room or any item within the
  rubbish", as long as it is an explicit action.

- **Soft-item guidance:** nondescript giant rubbish — copper pieces,
  empty potion bottles, used corks, lint, moldy sandwiches, and more
  disgusting items (see `rubbish_pile`, §1G).

### `secret_pocket` — "Secret Pocket"

- **Exits:**
  - **`flap_up`** → `bag_floor`: "Squeeze back up through the flap".
    No conditions or checks.

- **Entities present:** `key`, `care_label`, `sending_stone`,
  `emergency_gin`.

- **Special interactions:** none (the label, stone, and gin behaviors
  are entity-scoped; see §1G).

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
- **On-Examine Effects:**
  - `examine_axe` (any examination): reveals it to be an enormous
    battleaxe — its head made the rip in the canvas.  Flavor only; no
    check, no mechanical effect.
  - `examine_forge_mark` (rigorous examination only): the steel bears
    a dwarven smith's mark near the tang — a runic stamp, worn but
    readable.  No check.  Sets `flag:knows_axe_mark = true` and
    appends a `reveals` string.  (It is KORBAR's own forge mark — hers
    to confirm via the `ask_about_axe_mark` dialogue path, §1G.)
- **Tags / interactions / state fields / reactions:** none.
  (Traversal along the axe is modeled via room exits, §1F.)

### `the_rip` — "rip in the canvas" (type: `feature`)

- **Location:** `axe_head`.
- **State fields:**
  - `squeeze_warned` (boolean, initial `false`) — the player has been
    warned once about squeezing through.
- **Special interactions:**
  - **`squeeze_through`** — try to squeeze one's whole body through
    the rip.  Availability: `squeeze_warned == false`.  Requires a DEX
    (Acrobatics) check (DC 12, non-repeatable).  On success: cancel
    the action — the GM asks the player if they're sure — and set
    `squeeze_warned = true`.  On check failure: the player cannot fit
    through (no further effect; see Design Decisions, item 5).
  - **`squeeze_through_confirmed`** — squeeze through anyway.
    Availability: `squeeze_warned == true`.  No further check: the
    player squeezes through and floats eternally in the Astral Plane —
    game over (lose).
- **Reactions:**
  - **`rip_item_dropped`** (recurring): Trigger — `item.lost` with
    `event:item_id == key` and `event:reason == transfer` while the
    player is in `axe_head`.  Consequences — the key tumbles into the
    gray void: set `key.location = null` and `flag:key_lost = true`
    (the `key_lost_game_over` condition ends the game, §1E).  Results
    cannot reference the event's generic item ID, so only the
    plot-critical key case is modeled: any drop of the key while in
    `axe_head` counts as losing it through the rip; other items
    dropped there simply stay in the room (engine default), though the
    narrator may treat small offerings to the void as color.
- **On-Examine Effects** (any examination): examining the rip
  (sticking one's head through — the scenario declares this equivalent
  to an Examine action) reveals, in narration: (1) the gray nothing
  outside — INT check (DC 12, non-repeatable); on success the player
  recognizes the Astral Plane: set `knows_astral_plane = true`; (2)
  the exterior: the rip is a hole in the wall of a giant sack whose
  neck is firmly shut by a giant padlock dangling within reach — set
  `padlock.hidden = false`; (3) if `knows_astral_plane == true`, a
  further INT check (DC 17, non-repeatable); on success the player
  realizes it is a Bag of Holding: set `knows_bag_of_holding = true`;
  (4) `astral_drifter` (any examination, condition
  `flag:knows_astral_plane == true`, recurring — no check): something
  vast drifts past in the gray — a shape like a mountain made of
  silence, or a whale made of stars.  It does not notice the player.
  The player is glad.  Appends a `reveals` string; wonder-and-menace
  garnish, no mechanical effect.
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
    padlock's keyhole, alone.  Availability: `padlock.hidden ==
    false`, the `key` is in the player's inventory, and `korbar` is
    not assisting (not present in `axe_head` with `following == true`
    and conscious).  STR check (DC 14, repeatable).  On success: the
    key turns, the padlock opens, the bag opens, the player squirms
    free — game over (win); the GM narrates this entertainingly,
    leaving the player's fate (and Korbar's, if following) open-ended.
    On failure: immediately roll a DEX check (DC 8 — an automatic
    `then_check` follow-up each time the STR check fails, not a
    player-attempted check); on success the player hauls the key back
    in (no further effect; may retry the STR check); on failure the
    key slips and falls through the rip: set `key.location = null` and
    `flag:key_lost = true` (the `key_lost_game_over` condition ends
    the game — a `then_check` failure cannot carry `game_over`
    directly, §1E).
  - **`insert_key_assisted`** — as `insert_key`, but KORBAR holds and
    turns with the player.  Availability: as `insert_key`, plus
    `korbar` present in `axe_head`, `following == true`, alive and
    conscious (see Design Decisions, item 14).  STR check (DC 10,
    repeatable); same success and failure cascade.
  - **`study_lock`** — examine the keyway closely and work out whether
    it can be picked.  Availability: `padlock.hidden == false`.
    Requires an INT check (DC 12, non-repeatable).  On success the
    player realizes the keyway is a narrow tunnel, and how a two-person
    job could pick it: set `flag:knows_lockpick_method = true` and
    append a `reveals` string.  (The *method* — Korbar holding the
    pick from inside the bag, the player climbing across — is
    narrated; see `pick_lock`.)
  - **`pick_lock`** — the action set-piece.  Availability:
    `flag:knows_lockpick_method == true`, `inventory:giant_lockpick`,
    `korbar.following == true` and alive and conscious (she is in
    `axe_head` with the player), `padlock.hidden == false`.  Chained
    checks (depth 3; each repeatable):
    1. Climb across the pick into the keyway: DEX (Acrobatics) DC 14.
       On failure the player slips and dangles over the gray void
       before Korbar hauls them back (flavor; no damage).
    2. Work the pick head into the tumblers: DEX (Sleight of Hand)
       DC 15.  On failure the pick slips out (flavor; retry).
    3. Turn the tumblers against the spring: STR DC 13.  On success:
       the padlock clicks open — **game over (win)**, `trigger_id`
       `picked_lock`; the escape is narrated like the key win, and the
       player's fate (and Korbar's) is left open-ended.
    *Design notes:* the spider obstacle must already be resolved for
    Korbar to be following (see §1G `korbar`), so lock-picking is an
    alternative *win method*, not a spider bypass.  It works even if
    the key was lost (`key_lost`) — a Rogue's way out.  The player
    climbs *along the pick* spanning the gap; this deliberately does
    not trigger `the_rip.squeeze_through` (the pick provides the
    bridge), and the void below is navigated carefully — the GM should
    narrate the tension.
- **On-Examine Effects:**
  - `read_lock_makers_mark` (any examination, recurring flavor): the
    padlock's steel bears a maker's mark: *"Steadfast Lock Co. —
    tested against 47 rogues.  The 48th is pending."*  Flavor only;
    appends a `reveals` string.  (A wink at the player, pure prose.)
- **Tags / reactions:** none.

### `webs` — "sticky webs" (type: `feature`)

- **Spans rooms:** `axe_handle_upper`, `axe_handle_lower`.
- **On-Examine Effects** (any examination; room-dependent):
  - In `axe_handle_upper`:
    - the first examination of the webs or the stuck masses turns up
      the Fly: set `fly.hidden = false` (this triggers reaction
      `fly_warning_on_reveal`);
    - `reveal_husk` (rigorous examination only; condition
      `entity:prisoner_husk.hidden == true`): one of the larger masses
      is, under careful work, a desiccated shrunken *person* — a
      previous prisoner.  Set `prisoner_husk.hidden = false` and
      append a `reveals` string.  (The husk's own rigorous examination
      then yields its loot; see `prisoner_husk`.)
  - In `axe_handle_lower`:
    - if `spider` is alive, not `departed`, and `hidden == true`: WIS
      (Perception) check (DC 13, repeatable); on success the player
      notices the spider: set `spider.hidden = false`;
    - `reveal_spider_hoard` (rigorous examination only; condition
      `spider_hoard.hidden == true` and the spider is dead (`alive ==
      false`), departed, or incapacitated — `status_effect:spider.
      incapacitated`): the vain spider's hoard: a shiny drift of giant
      copper pieces, a wooden button, a bottle cap, lint-covered
      silver.  Set `spider_hoard.hidden = false`; too cumbersome to
      carry (soft items only); appends a `reveals` string;
    - `reveal_spider_corpse` (rigorous examination only; condition
      `spider_corpse.hidden == true` and `spider.alive == false`):
      the spider's corpse is tangled in the web; set
      `spider_corpse.hidden = false`.  (Its own rigorous examination
      yields `spider_fang` and the venom sac; see `spider_corpse`.)
  - In all cases: no other searches turn up anything useful — the
    web is too sticky to do anything with (narration guidance).
- **Interactions (the quiet path through the web — the loud path is
  the gated exits, §1F):**
  - **`cut_web_quietly`** — slowly and carefully part the web with
    blade and patience.  Availability: `room:axe_handle_lower.
    is_current == true` and `room:axe_handle_lower.web_cleared ==
    false`.  DEX (Stealth) check (DC 13, repeatable; DC 10 with a
    blade via `using_results` keyed on `toenail_sword`, `dagger`,
    `giant_lockpick`, and the `"*"` wildcard — any hard item the GM
    deems blade-like; exact keys take precedence).  On success: set
    `web_cleared = true` *quietly* (no spider provocation) and append
    a `reveals` string.  On failure: set `flag:quiet_cut_failed =
    true` — the web was disturbed; the spider senses it (reaction
    `quiet_cut_failure_spider`, §1E — an encounter, not a traversal
    cancel).  An `interaction.used` reaction cannot see the check
    outcome, so the failure routes through the flag.
  - **`cut_web_quietly_with_korbar`** — same, but while KORBAR follows
    in her plate armor: her clanking imposes **disadvantage** on the
    DEX (Stealth) check.  Availability: as `cut_web_quietly`, plus
    `korbar.following == true`, `korbar.alive == true`, and
    `entity:korbar.korbar_doffed_armor == false`.  (Once she has doffed
    the armor — see `korbar` — her following no longer imposes
    disadvantage, and the base interaction suffices.)
  - **`sneak_past_invisible`** — walk through the web while invisible.
    Availability: `room:axe_handle_lower.is_current == true`,
    `room:axe_handle_lower.web_cleared == false`, and
    `status_effect:invisible` (the crimson potion).  No check: the
    player moves slowly and carefully, and the web transmits nothing —
    set `web_cleared = true` quietly.  *The surest possible path past
    the spider.*  (Invisibility alone, with a careless approach, does
    not guarantee silence — a fumbled quiet *cut* still provokes; see
    `quiet_cut_failure_spider`.)  *Discoverability:* if an invisible
    player attempts a web-gated exit directly, the GM should surface
    this slow-and-careful option rather than springing the loud path
    on them (scenario.md, Narration Notes).
  - **`free_fly`** — work the Fly free of the web.  Availability:
    `room:axe_handle_upper.is_current == true`, `fly` alive,
    `hidden == false` (revealed), and `flag:fly_freed == false`.
    DEX check (DC 13, repeatable; DC 10 with a blade via
    `using_results`, same keys as `cut_web_quietly`).  On success: set
    `flag:fly_freed = true`, narrate the fly crawling free and
    clinging to the player's shoulder (see `fly` for the freed fly's
    boons).  On failure: the fly stays stuck (no further effect;
    retry).
- **Tags / reactions / state fields:** none.  (The blockable stretch
  of web is modeled by `axe_handle_lower`'s `web_cleared` state field
  and gated exits, §1F; the fly-free and quiet-cut outcomes are the
  interactions above.)

### `fly` — "Fly" (type: `npc`)

- **Location:** `axe_handle_upper` (stuck in the `webs`).
- **State fields:**
  - `hidden` (boolean, initial `true`) — unnoticed until the webs are
    examined.
  - `delivered_warning` (boolean, initial `false`) — it has spoken its
    warning about the spider.
- **Attitude:** locked at 0 (min 0 / max 0) — it never shifts.  (The
  validator requires attitude fields on any NPC with dialogue.)
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
    in the room — an entity reaction can only fire while its entity
    is in the current room; see Design Decisions, item 19).
    Condition — fly alive, `delivered_warning == true`, and
    `flag:fly_freed == false` (a freed fly does not die this way — it
    rides with the player).  Consequences — the fly dies: set
    `alive = false`; narrate its fading death.
- **First-Meeting Behavior:** when first found (revealed by examining
  the webs), it speaks its warning about the spider — see reaction
  `fly_warning_on_reveal`.
- **Interactions (the freed fly's boons):**
  - **`fly_guard_lower`** — send the freed fly ahead to
    `axe_handle_lower` to keep watch.  Availability: `flag:fly_freed
    == true`, fly alive, `flag:fly_watching_lower == false`,
    `room:axe_handle_upper.is_current == true` (the fly is located
    there).  Result: set `flag:fly_watching_lower = true` and narrate
    the fly's weak buzz departing downward.  On the player's next
    entry to `axe_handle_lower` the watch ends: the fly's alarm
    reveals a hidden spider (room reaction `fly_alarm_reveals_spider`,
    §1F), and the exhausted fly then dies (room reaction
    `fly_dies_after_watch`, §1F) — unless it was revived, in which
    case it survives (`fly_watch_ends_revived`, §1F).  Boon (a).
  - *(Boon (b) — the vouch — is a KORBAR dialogue path, not a fly
    interaction: the fly is located in `axe_handle_upper`, and entity
    interactions are only available when the entity is in the present
    room.  The freed fly narratively rides with the player, but its
    mechanical vouch lives on `korbar.fly_vouch` (§1G) — available in
    `bag_floor` where Korbar is.)*
  - *(Revival — a drop of the amber healing potion — is an
    interaction on `potion_vat_amber`; see §1G.  A revived fly grants
    both boons over the course of play and survives them.)*
- **Dialogue paths:** none (it has no other useful information — after
  all, it's a fly).
- **Will-Reveal Topics:**
  - **`spider_warning`** — gating: in dialogue, fly alive.  Conveys:
    a giant spider is out for blood.  Consequences: set
    `knows_spider_threat = true`.  (Normally already delivered by
    `fly_warning_on_reveal` before any dialogue.)
  - **`polymorph_claim`** — gating: in dialogue, fly alive and
    `flag:fly_freed == true` (a freed fly has the strength to ramble).
    Conveys: the fly claims to be a polymorphed adventurer — "tell
    Eldrin I— wait.  What was I saying?" — and can no longer remember
    anything.  The scenario never confirms it.  Consequences: none
    (flavor; preserves and deepens the anti-clue joke).
- **Knowledge:** knows nothing useful about this place or anything
  else; it's a fly (albeit a talking one) — though it *claims*
  otherwise.
- **Aggro:** no combat stats — if attacked, it simply dies (default
  non-combat handling).
- **Combat stats / combat group:** none.

---

### `spider` — "Spider" (type: `npc`)

- **Location:** `axe_handle_lower`, concealed in the webbing above.
- **Combat stats (verbatim):** STR 14, DEX 16, CON 12, INT 7, WIS 11,
  CHA 4; AC 8; HP 14.  Attacks: Bite (+1 to hit, 1d4+2 piercing
  damage).  On hit: target must make a DC 11 CON save or take 1d8
  poison damage (half on a successful save) *and*, on a failed save,
  gains the `poisoned` status effect (the bite's venom; the corpus
  overrides `poisoned` to persistent/until-cleared so it lingers after
  combat — the antivenom potion exists to cure it; see §1E, Status
  effects).  Supplied defaults (the scenario gives neither):
  `initiative_mod` +3 (from DEX 16), flee DC engine default 10.
- **AI:** `ai: { flee_below_hp_pct: 30 }` — a losing spider (HP below
  30%) breaks off and flees: the engine removes it from combat and
  sets its engine-owned `fled` state.  Its frantic flight tears
  through the web, and reaction `spider_flee_fallout` (below)
  completes the departure.  Design call: the flight must set
  `departed` — otherwise the (now revealed, still alive) spider would
  re-trigger `spider_attacks_on_entry` on the player's next re-entry.
- **State fields:**
  - `attitude` (number, initial `-2`) — non-default; starts hostile.
  - `hidden` (boolean, initial `true`) — concealed above the room.
  - `departed` (boolean, initial `false`) — it has slunk away for good
    (successful persuasion or flight); a departed spider is removed
    from play.
  - `attitude_fixed` (boolean, initial `false`) — once true (combat
    triggered), attitude is fixed at -10 permanently.
  - `current_hp` (number, initial `14`) — declared as required for
    combat-capable NPCs; equals the stat block's HP.
- **Attitude Limits:** maximum 0 ("to a maximum of 0"); minimum -10
  (the scenario specifies no minimum).  At most ±1 change per turn.
  Once `attitude_fixed` is set (combat triggered), attitude is fixed
  at -10 permanently, outside the usual limits.
- **Aggro:** default — if attacked by the player, launch turn-based
  combat (it has combat stats): enemies [`spider`]; allies [`korbar`]
  if present and `will_fight == true`.  Combat is also triggered by
  room reaction `web_spider_attack` and its own reaction
  `spider_attacks_on_entry`; any such trigger sets `hidden = false`,
  `attitude = -10`, `attitude_fixed = true`.
- **Reactions:**
  - **`spider_attacks_on_entry`** (recurring): Trigger — player enters
    `axe_handle_lower`.  Condition — spider alive, `departed ==
    false`, `hidden == false` (i.e., it was *already* revealed before
    the player entered — typically after the player fled and
    returned; see Design Decisions, item 9), and *not*
    `status_effect:spider.incapacitated` (a sleeping spider does not
    attack on entry).  Consequences — it initiates combat: enemies
    [`spider`]; allies [`korbar`] if present and `will_fight ==
    true`; set `attitude = -10`, `attitude_fixed = true` if not
    already.
  - **`spider_flee_fallout`** (recurring): Trigger — `combat.ended`.
    Condition — `event:reason == victory` (the only end reason when
    the spider flees as the last enemy), the spider is `alive ==
    true` (a killed spider is `alive == false` and is excluded — this
    is what distinguishes "fled" from "killed" without reading the
    engine-owned `fled` state), and `departed == false`.  Consequences
    — narrate the spider's frantic flight tearing through the web; set
    `departed = true`, `location = null` (removed from play, like a
    persuaded spider), and `room:axe_handle_lower.web_cleared = true`
    (the passage it guarded is open).
- **Dialogue availability:** it never initiates conversation.  It
  replies (grudgingly) only if `attitude >= -2`.  Being in
  conversation does not prevent its attack triggers.  Attitude changes
  are bounded by its Attitude Limits (above).
- **Dialogue paths:**
  - **`flatter_spider`** — availability: in dialogue, `attitude_fixed
    == false`.  The player is pleasant or flattering.  Success gating:
    CHA (Persuasion) check (DC 9, repeatable — rolled once per
    flattering exchange); per the scenario this is applied at
    post-validation, after the narrator proposes the attitude
    increase.  On success: `attitude` +1 (respecting the ±1/turn cap
    and the max of 0).  On failure: attitude unchanged.
  - **`provoke_spider`** — availability: in dialogue, `attitude_fixed
    == false`.  Threats or other negative behavior.  No check:
    `attitude` −1 (respecting the ±1/turn cap; minimum -10).
  - **`persuade_passage`** — availability: in dialogue, `attitude >=
    0`, and the player is armed (carrying/wielding a `weapon`-tagged
    item).  The player tries to convince the spider to let them
    through.  CHA check (DC 12, non-repeatable).  On success: the
    spider sizes them up and grudgingly slinks away, disappearing from
    the game: set `departed = true`.  On failure: the spider verbally
    agrees — a lie; it remains where it is and still attacks per its
    normal triggers (`web_spider_attack`, `spider_attacks_on_entry`).
  - **`persuade_passage_unarmed`** — availability: in dialogue,
    `attitude >= 0`, and the player is not armed.  No check: the
    spider verbally agrees to let the player through, but this is a
    lie — it remains where it is and still attacks as above.
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
  18).  Supplied defaults (the scenario gives none): attack +4 (STR 15
  plus proficiency +2), `initiative_mod` +0 (DEX 10), flee DC engine
  default.
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
  - `passive` (boolean, initial `true`) — she cowers and takes no
    actions in combat; cleared when she is persuaded to fight or
    aggros.  (Models "cowering in fear" via the combat AI's `passive`
    entity state.)
  - `current_hp` (number, initial `29`) — declared as required for
    combat-capable NPCs; equals the stat block's HP.
  - `korbar_doffed_armor` (boolean, initial `false`) — she has taken
    off the plate mail (dialogue path `doff_armor`).  Her combat AC
    remains 18 (NPC combat blocks are pre-computed; the doff is
    narrative and stealth-path only — see `doff_armor`), but the
    clanking stops: while `korbar_doffed_armor == true`, her following
    no longer imposes disadvantage on `webs.cut_web_quietly`.
- **Attitude Limits:** minimum -10 (she attacks on reaching it);
  maximum 10 (the scenario specifies none; the engine default of 0
  would block all increases).  `step_per_turn` 3 so the
  `convince_spider_dead` +3 passes the per-turn cap; ordinary paths
  only ever adjust by ±1, so the scenario's ±1/turn behavior is
  preserved.  (The cap of 3 general conversation increases is enforced
  by the `rapport_1/2/3` flags gating the three rapport dialogue
  paths.)
- **Follower Behavior:** enabled via dialogue path `convince_follow`.
  Refused rooms: `secret_pocket` (her armor can't squeeze through the
  flap; the engine clears `following` if the player enters a refused
  room).  While following: she helps lug the `key` (skips the
  `heavy_key_movement` STR check when in the same room, §1E), helps at
  the padlock (`insert_key_assisted`, DC 10 instead of 14), helps hold
  the lockpick for `padlock.pick_lock`, and fights alongside the
  player as an ally whenever combat breaks out in her presence if
  `will_fight == true` (otherwise she cowers).  While following in her
  plate armor (until `doff_armor`), her clanking imposes disadvantage
  on the quiet web-cut; once she has doffed it, she can sneak with the
  player.
- **Aggro:** if her `attitude` reaches -10, she attacks: start combat
  (enemies [`korbar`]).  If attacked by the player: default — start
  combat (she has combat stats).  *Special combat rules:* if her HP
  reaches 0 she falls unconscious for the rest of the game
  (mechanic `korbar_knocked_out`, §1E) instead of dying; attacking her
  while she is `unconscious` simply kills her (`alive = false`), no
  combat — per the scenario's "the player may also kill her, but this
  accomplishes nothing".  Her body is too heavy to haul anywhere.
- **Reactions:** none beyond the Aggro rules above.
- **Dialogue paths:**
  - **`positive_rapport_first` / `positive_rapport_second` /
    `positive_rapport_third`** — three condition-exclusive variants of
    one path (Results cannot increment numeric state, so the cap of 3
    general increases is tracked by the `rapport_1/2/3` flags, each
    variant gated on its flag not yet being set and the previous one
    being set).  Availability: in dialogue.  The player engages
    positively — treats her respectfully, commiserates with her
    plight.  Success gating: GM discretion — only if the player makes
    an actual effort (not handed out like candy).  **Giving her a
    gift — the giant rations, the wineskin dregs, or the emergency gin
    (see `giant_rations`, `wineskin_dregs`, `emergency_gin`) — counts
    as an effort at the GM's discretion** (consented living-NPC
    transfers fire no state-change events, so the gift is adjudicated
    here, inside the rapport paths; no new machinery).  On success:
    `attitude` +1 and the path's `rapport_N` flag is set.
  - **`mock_korbar`** — availability: in dialogue.  The player
    engages negatively, e.g., makes fun of her.  Success gating: GM
    discretion.  Effect: `attitude` −1 per turn (minimum -10); at
    -10 she attacks (see Aggro).
  - **`convince_spider_dead`** — availability: in dialogue.  The
    player tries to convince her the spider is dead (regardless of
    whether it's true).  Success gating: the GM must judge the player
    makes a convincing case (based on the dialogue), plus a CHA check
    (DC 15, repeatable).  Physical evidence skips the check: `spider`
    actually dead (`entity:spider.alive == false`) or
    `inventory:spider_fang` (the harvested fang, §1G — explicit
    concrete evidence).  On success: `attitude` +3 and set
    `believes_spider_dead = true`.
  - **`convince_follow`** — availability: `attitude >= 1` and
    `believes_spider_dead == true`.  The player convinces her to
    follow them up (or down) the axe.  Success gating: CHA check (DC
    8, repeatable).  On success: set `following = true` (see Follower
    Behavior above for what this entails).
  - **`persuade_fight`** — availability: `attitude >= 3`.  The player
    persuades her to stand and fight despite her fear of the spider.
    No check required — the trust already earned is enough.  On
    success: set `will_fight = true` and `passive = false`; from then
    on she fights alongside the player whenever combat breaks out in
    her presence (a capable fighter even unarmed).
  - **`persuade_fight_armed`** — availability: `attitude >= 2`,
    `flag:korbar_armed == true`, `will_fight == false`.  Same result
    as `persuade_fight` (set `will_fight = true` and `passive =
    false`): a weapon in her hands is worth a point of trust.  She
    fights with the blade; her damage stays 3 (combat blocks are
    pre-computed; the GM narrates the difference).
  - **`ask_about_axe_mark`** — availability: `flag:knows_axe_mark ==
    true` (the player noticed the dwarven smith's mark on the giant
    axe, §1G) and `flag:knows_axe_is_korbars == false`.  The player
    asks her about the mark.  Result: she goes very still, then admits
    it is her own forge mark — she forged the axe; it was her weapon;
    it is the only thing she ever made that was worth a damn.
    `adjust_attitude { korbar: 1 }`, set `knows_axe_is_korbars =
    true`, append a `reveals` string.  Also unlocks the abandonment
    topic (below).
  - **`doff_armor`** — availability: `entity:korbar.korbar_doffed_armor
    == false` and (the fear arc) `entity:korbar.believes_spider_dead
    == true` **or** `flag:korbar_mage_armored == true` (magic on her
    skin replaces the steel's protection).  The player convinces her
    to strip the plate.  Result: set `korbar_doffed_armor = true`;
    narrate the clanking armor coming off and her sudden quiet.
    *Engine note:* her combat AC remains 18 (NPC combat blocks are
    pre-computed); the doff's mechanical effect is that her following
    no longer imposes disadvantage on the quiet web-cut
    (`webs.cut_web_quietly`), and the narrative freedom to sneak.
    This is what opens the stealth path before the spider is resolved
    — at the cost of the Mage Armor scroll if done early.
  - **`offer_weapon`** — the player offers her a weapon, split into
    condition-exclusive paths `offer_toenail_sword`, `offer_dagger`,
    and `offer_lockpick` (each gated on that weapon being in the
    player's inventory; see Design Decisions, item 35).  Each path:
    `remove_item` of the offered weapon, set `flag:korbar_armed =
    true`, `adjust_attitude { korbar: 2 }` (a genuine gift), and
    narrate her acceptance.  Base path `offer_weapon` (no weapon in
    inventory): she looks at the player's empty hands — "with what?"
    Availability: in dialogue, `flag:korbar_armed == false`.  A real
    sacrifice decision: the player hands over their only weapon
    (exercising the living-NPC transfer path; consented transfers fire
    no events, so the gift is modeled through the path itself).
    Payoff: `persuade_fight_armed` at attitude 2 instead of 3.
  - **`tell_about_stone`** — availability: `flag:wizard_voice_heard ==
    true` (the sending stone produced a voice, §1G) and
    `flag:told_about_stone == false`.  The player tells Korbar about
    the voice from the stone — a woman's voice calling her name, from
    outside the bag.  Result: she goes pale, then quiet, and thanks
    the player for telling her: +1 attitude (contributes to rapport),
    set `told_about_stone = true`.
  - **`fly_vouch`** — the freed fly's boon (b): the fly rides along
    with the player and, when they next speak with Korbar, buzzes
    around the dwarf's head vouching for them.  Availability:
    `flag:fly_freed == true`, fly alive, `flag:fly_watching_lower ==
    false` (a fly sent ahead to watch is no longer riding with the
    player), and `flag:fly_vouched == false`.  Result:
    `adjust_attitude { korbar: 1 }`, set `flag:fly_vouched = true`
    and `fly.alive = false`; narrate the fly's character reference
    until Korbar swats it away — spent, it dies.  (A revived fly never
    uses this path: `potion_vat_amber.heal_fly` delivers the vouch —
    and the +1 — at revival time, setting `fly_vouched` directly.)
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
  - **`abandonment_story`** — gating: either `inventory:party_badge`
    (the player found her old company's badge in her shelter stash,
    §1G) or `flag:knows_axe_is_korbars == true` (the axe-mark
    conversation, above).  Conveys: who abandoned her — her own
    adventuring party stuffed her in the bag for a stealth mission and
    never let her out; she heard them through the bag's neck, arguing
    about the padlock, before the lock clicked shut.  (The badge also
    makes the story concrete: it is her old company's crest.)
    Consequences: set `knows_abandonment = true`.
  - **`why_bag_locked`** — gating: `flag:knows_abandonment == true`.
    Conveys: the padlock is the party's insurance — whatever went in
    the bag, they wanted to be sure it could not follow them out; she
    has made her peace with being "whatever."  Consequences: none
    (flavor; connects the axe, the padlock, and Korbar into one
    through-line).
- **Knowledge:** her party stuck her in this bag during a stealth
  mission, then forgot about her; she's unsure how long ago — time,
  like space, functions strangely in here; the giant battleaxe was her
  weapon when she was full-sized outside (she *forged* it); her armor
  clatters every time she moves — it is *why* the party abandoned her
  on the stealth mission; she is unarmed; she is drunk and miserable;
  in her cups she mutters fragments of useful truth ("pocket under the
  cloth," "mark on the axe," "the key, the key, the key") — see the
  `overhear_korbar_muttering` mechanic, §1E.
- **Combat group:** none (fights alone, or alongside the player as an
  ally once `will_fight`).

### `rubbish_pile` — "pile of giant rubbish" (type: `feature`)

- **Location:** `bag_floor`.
- **Contained entities:** [`toenail_sword`, `potion_vat_amber`,
  `potion_vat_emerald`, `potion_vat_crimson`, `potion_vat_black`,
  `giant_rations`, `giant_lockpick`, `giant_faerie_fire_scroll`,
  `bag_within`].  (No open/close functionality, so deliberately **no**
  `container` tag and no `open` state field.)
- **On-Examine Effects** (triggered by explicitly examining the pile,
  the room, or any item within it — not by the automatic room-entry
  description; effects 1–3 trigger on any explicit examination):
  1. The player notices the giant toenail clipping in the pile: set
     `toenail_sword.hidden = false`.  (Happens on the first explicit
     examination; no check.)
  2. INT (Investigation) check (DC 8, non-repeatable — the scenario
     text is self-contradictory here; see Design Decisions, item 6):
     on success the player realizes this is not random junk but some
     adventurer's supplies, much like their own missing pack: set
     `knows_rubbish_is_supplies = true`.
  3. If `knows_rubbish_is_supplies == true`, and this is another
     explicit examination, and `knows_bag_of_holding == false`: INT
     check (DC 14, non-repeatable).  On success the player realizes
     they are inside a magical Bag of Holding, and notices the
     rubbish's proportions are uneven — the bag's magic shrinks items
     by different amounts: set `knows_bag_of_holding = true`.
  4. **Rigorous examination only:** if this is not the first
     examination (`toenail_sword.hidden == false`), and
     `handkerchief.hidden == true`: WIS (Perception) check (DC 15,
     non-repeatable).  On success the player notices the giant
     handkerchief and feels it's somehow important: set
     `handkerchief.hidden = false`.  (The faerie-fire scroll's light
     can also reveal it; see `giant_faerie_fire_scroll`.)
  5. **`deep_rubbish_stage_one`** (rigorous examination only):
     condition `flag:rubbish_vats_found == false`.  INT
     (Investigation) check (DC 12, **repeatable** — these staged
     checks gate major content, including a win path, so they must not
     be one-shot; see Design Decisions, item 33).  On success the
     player digs deeper and turns up the *unbroken* finds: set
     `rubbish_vats_found = true`; set `hidden = false` on
     `potion_vat_amber`, `potion_vat_emerald`, `potion_vat_crimson`,
     `potion_vat_black`, `giant_rations`, and `giant_lockpick`; append
     a `reveals` string.  On failure: nothing further — the player can
     try again on a later rigorous examination.
  6. **`deep_rubbish_stage_two`** (rigorous examination only):
     condition `flag:rubbish_vats_found == true` and
     `flag:rubbish_scroll_found == false`.  INT (Investigation) check
     (DC 15, **repeatable**).  On success set `rubbish_scroll_found =
     true`, `giant_faerie_fire_scroll.hidden = false`, append a
     `reveals` string.
  7. **`deep_rubbish_stage_three`** (rigorous examination only):
     condition `flag:rubbish_scroll_found == true` and
     `flag:rubbish_bag_found == false`.  INT (Investigation) check
     (DC 17, **repeatable**).  On success set `rubbish_bag_found =
     true`, `bag_within.hidden = false`, append a `reveals` string
     (the pouch is far too small to be one of the giant's belongings).
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
  check (DC 8); repeatable — on failure it stays stuck, no further
  effect (see Design Decisions, item 16).  Applies only until the
  first successful take (thereafter the item is held, not in the
  pile).  It then functions as a shortsword.
- **Interactions / reactions / on-examine effects:** none.

### `handkerchief` — "giant handkerchief" (type: `feature`)

- **Location:** `bag_floor`, draped over a corner of the
  `rubbish_pile`.  (A feature, not an item: giant-sized, cannot be
  carried.)
- **State fields:**
  - `hidden` (boolean, initial `true`) — revealed by `rubbish_pile`
    on-examine effect 4, by `korbar`'s topic `secret_pocket_info`, or
    by the faerie-fire scroll's light
    (`giant_faerie_fire_scroll.read_aloud`, §1G).
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
- **Take Check:** stealing it is possible only when Korbar is
  unconscious or dead (see Design Decisions, item 12).  While she is
  awake (`korbar.alive == true && korbar.unconscious == false`), the
  take check is a roll with threshold 0.0 — always fails — with an
  explanatory failure narrative.
- **Tags / state fields / interactions / reactions / on-examine
  effects:** none.

---

### `prisoner_husk` — "web-wrapped mass" (type: `feature`)

- **Location:** `axe_handle_upper` (stuck in the `webs`).
- **State fields:** `hidden` (boolean, initial `true`) — revealed by
  the webs' rigorous examination (`webs.reveal_husk`, §1G).
- **Contained entities:** `dagger` (SRD pack reference),
  `prisoner_journal`, `scroll_of_mage_armor`, `scroll_of_sleep` — all
  initially `hidden` (they are the husk's belongings, revealed when
  the husk itself is examined).
- **On-Examine Effects** (rigorous examination only; condition
  `entity:prisoner_husk.hidden == false`): the mass is a desiccated
  shrunken *person* — a previous prisoner, wrapped in the web long
  ago.  The husk is carefully extricated, and its belongings come
  free: set `hidden = false` on `dagger`, `prisoner_journal`,
  `scroll_of_mage_armor`, and `scroll_of_sleep`; append a `reveals`
  string.
- **Interactions / reactions / tags:** none.

### `prisoner_journal` — "prisoner's journal" (type: `item`)

- **Location:** contained in `prisoner_husk` (in `axe_handle_upper`).
- **Interactions:**
  - **`read`** — read the journal.  Availability: `hidden == false`
    (found with the husk).  Result: narrate the entries — lucid at
    first, then devolving into lint-obsession ("Day 41: still no
    rescue.  Day 42: I have named the lint.") — with two real hints in
    passing: (i) on Day 33 the prisoner overheard the dwarf under the
    ladle muttering in her sleep about "a pocket under a cloth"; (ii)
    on Day 39 he notes "the spider does not eat me; it talks at me; it
    likes compliments."  The final entry trails off: "The spider is
    actually quite reasonable if you—".  Append a `reveals` string;
    no mechanical effect (the hints are GM narration; the spider
    flattery and the secret-pocket lore already exist as mechanics).
- **Take Check:** none.  **Tags / state fields / reactions /
  on-examine effects:** none.

### `scroll_of_sleep` — "Scroll of Sleep" (type: `item`)

- **Location:** contained in `prisoner_husk` (in `axe_handle_upper`).
- **Interactions:**
  - **`study_scroll`** — identify the spell.  INT (Arcana) check
    (DC 10, non-repeatable).  On success: narrate the spell (Sleep —
    the spell that has ended more low-level encounters than every
    sword in history combined) and append a `reveals` string; set
    `identified = true` (state field, initial `false`).
  - **`read_at_spider`** — read the scroll aloud in the spider's
    presence.  Availability: `identified == true` (or GM discretion),
    the player in `axe_handle_lower`, and `spider` alive, present
    (location == `room:axe_handle_lower`), `departed == false`, and
    *not* already `status_effect:spider.incapacitated`.  Result: the
    spell washes over the spider: `apply_status_effect { id:
    incapacitated, rounds: 10, target: spider }`,
    `remove_item_count { scroll_of_sleep: 1 }` (one use), and append a
    `reveals` string.  **No save** — faithful to SRD *sleep*.  A
    sleeping spider does not attack (its attack reactions and
    `web_spider_attack` conditions gain "not
    `status_effect:spider.incapacitated`", §1F/§1G) and can simply be
    walked past; attacking it starts combat with it incapacitated
    (skip_turn — a brutal opening, intended).  *Engine note:* the
    built-in `incapacitated` is combat-scoped; out of combat it never
    ticks, so the spider sleeps until the player starts combat (then
    10 rounds) — the spell solves the spider obstacle like killing or
    persuading it does, at the cost of the one-use scroll.
- **Take Check:** none.  **Tags / state fields:** `identified`
  (boolean, initial `false`).  **Reactions / on-examine effects:**
  none.

### `scroll_of_mage_armor` — "Scroll of Mage Armor" (type: `item`)

- **Location:** contained in `prisoner_husk` (in `axe_handle_upper`).
- **Interactions:**
  - **`study_scroll`** — identify the spell.  INT (Arcana) check
    (DC 10, non-repeatable).  On success: narrate (Mage Armor),
    append a `reveals` string, set `identified = true`.
  - **`read_on_self`** — cast it on the player.  Availability:
    `identified == true` (or GM discretion).  Result:
    `apply_status_effect { id: mage_armor, target: player }` (the
    built-in is persistent/until-cleared; base AC becomes 13 + DEX =
    14, up from 11), `remove_item_count { scroll_of_mage_armor: 1 }`
    (one use).  A survivability upgrade for the combat path.
  - **`read_on_korbar`** — cast it on KORBAR.  Availability:
    `identified == true`, `korbar` alive and present in the same room.
    Result: `apply_status_effect { id: mage_armor, target: korbar }`
    (persistent/until-cleared; narrative protection — her combat AC
    stays 18, NPC combat blocks are pre-computed, and the status
    effect's `ac_base` only applies to the player), set
    `flag:korbar_mage_armored = true`, `remove_item_count {
    scroll_of_mage_armor: 1 }`.  Payoff: she will agree to `doff_armor`
    before the spider is dead — opening the stealth path early at the
    cost of the scroll.
  - *(The scroll cannot do both — one use.)*
- **Take Check:** none.  **Tags / state fields:** `identified`
  (boolean, initial `false`).  **Reactions / on-examine effects:**
  none.

### `dagger` — "dagger" (type: `item`, SRD data-pack reference)

- **Location:** contained in `prisoner_husk` (in `axe_handle_upper`).
- No corpus entry needed: referenced directly from the SRD pack
  (simple melee weapon).  A blade for the web/fly `using_results`
  keys; a gift option for `korbar.offer_weapon`.

### `potion_vat_amber` — "amber potion vat" (type: `feature`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).  A giant
  bottle the size of a vat; cannot be carried.
- **State fields:** `hidden` (initial `true`; revealed by
  `rubbish_pile.deep_rubbish_stage_one`), `corked` (initial `true`),
  `identified` (initial `false`), `drained` (initial `false`).
- **Interactions** (all availability: `hidden == false`):
  - **`uncork`** — STR check (DC 10, repeatable).  On success set
    `corked = false` (the cork comes free with a wet pop).
  - **`examine_label`** — read the tiny worn label.  Result-only:
    the fine print is too small and worn to read; an Arcana check is
    needed (see `identify_vat`).
  - **`identify_vat`** — INT (Arcana) check (DC 12, non-repeatable).
    On success: narrate the label ("Potion of Healing — honey-flavored.
    Best served at room temperature, which is not a temperature in
    here") and set `identified = true`; append a `reveals` string.
  - **`sip`** — taste test.  Availability: `corked == false`.  Result:
    the amber liquid is sweet and warm: identify the vat
    (`identified = true`); no other effect.
  - **`drink`** — drink deeply.  Availability: `corked == false`,
    `drained == false`.  Result: `player_heal: "2d4+2"`, set
    `drained = true`; narrate the healing warmth.
  - **`heal_fly`** — give a drop to the freed fly.  Availability:
    `drained == false`, `flag:fly_freed == true`, `fly` alive, and
    `flag:fly_revived == false`.  (The freed fly follows the player
    narratively — no `follower` block for a fly — so "the fly is with
    the player at the vats" is exactly `fly_freed && alive`.)  Result:
    the fly drinks deep and revives: set `fly_revived = true`,
    `fly_watching_lower = true`, and `fly_vouched = true`, and
    `adjust_attitude { korbar: 1 }` (narrated as the fly buzzing
    around the shelter singing the player's praises over the coming
    turns).  A real trade-off: the player's only healing, spent on a
    friend.
- **Reactions / on-examine effects / tags:** none.

### `potion_vat_emerald` — "emerald potion vat" (type: `feature`)

- **Location / state fields:** as `potion_vat_amber`.
- **Interactions** (as `potion_vat_amber` except):
  - **`sip`** — the emerald liquid tastes of cut grass and clean
    water: `identified = true`.
  - **`drink`** — the Antivenom: `cure_status_effects:
    ["poisoned"]`, `apply_status_effect { id: antivenom, target:
    player }` (custom status effect, persistent/until-cleared — CON
    saving throws have advantage while it lasts; see §1E, Status
    effects), set `drained = true`.  The taste of survival.
- **Reactions / on-examine effects / tags:** none.

### `potion_vat_crimson` — "crimson potion vat" (type: `feature`)

- **Location / state fields:** as `potion_vat_amber`.
- **Interactions** (as `potion_vat_amber` except):
  - **`sip`** — the crimson liquid is clear as water and tastes of
    moonlight: `identified = true`.
  - **`drink`** — the Potion of Invisibility:
    `apply_status_effect { id: invisible, target: player }` (the
    corpus overrides `invisible` to persistent/until-cleared, §1E),
    set `drained = true`.  The effect persists across rooms until the
    player attacks or enters combat (mechanics
    `invisible_breaks_on_attack` / `invisible_breaks_on_combat`, §1E)
    or the GM judges a revealing action.  Its natural use:
    `webs.sneak_past_invisible`.
- **Reactions / on-examine effects / tags:** none.

### `potion_vat_black` — "ink-black potion vat" (type: `feature`)

- **Location / state fields:** as `potion_vat_amber`.
- **Interactions** (as `potion_vat_amber` except):
  - **`uncork`** — as the other vats, but the success narration is
    alarming: even uncorked and untouched, the liquid is plainly
    wrong — it seems to drink the faint glow around it, it gives off
    no scent at all, and the air above the rim is cold.  (This is the
    player's clue; drinking it blind is an informed risk, not a
    gotcha — see Design Decisions, item 21.)
  - **`sip`** — the ink-black liquid burns like swallowed lightning:
    CON save (DC 11); on failure `player_damage: "1d8"`, on success
    `player_damage: "half(1d8)"`; either way `identified = true`
    ("your tongue goes numb — this is poison").
  - **`drink`** — drink fully.  Availability: `corked == false`,
    `drained == false`.  Result: the fine print kills: **game over
    (lose)**, `trigger_id` `drank_poison`.  The label (via
    `identify_vat`) warns: "Do not consume.  Contains 100% pure
    essence of death.  Not for human consumption.  Not for dwarf
    consumption.  NOT for consumption."
- **Reactions / on-examine effects / tags:** none.

### `giant_rations` — "giant rations" (type: `item`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).
- **State fields:** `hidden` (initial `true`; revealed by
  `rubbish_pile.deep_rubbish_stage_one`).
- **Interactions:**
  - **`nibble`** — eat a little.  Result: `player_heal: "1"` (the
    GM narrates the revolting taste), `remove_item_count {
    giant_rations: 1 }` (single serving).
- **Take Check:** none.  **Tags:** none.  (Giftable to Korbar — a
  rapport effort at the GM's discretion, §1G `korbar`.)

### `giant_lockpick` — "giant lockpick" (type: `item`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).
- **State fields:** `hidden` (initial `true`; revealed by
  `rubbish_pile.deep_rubbish_stage_one`).
- **Tags:** `weapon` (a blade-like tool for the web/fly checks and the
  spider's `persuade_passage` armed test).
- **Equippable:** yes — a simple two-handed staff-like weapon:
  `equip_tags ["weapon", "simple", "two_handed"]`,
  `damage_expr "1d6"`, `damage_type "bludgeoning"`,
  `properties ["two_handed"]`.
- **Take Check:** none.  **Interactions / reactions / on-examine
  effects:** none beyond use as a tool (see `webs`, `padlock.pick_lock`,
  `korbar.offer_weapon`).

### `giant_faerie_fire_scroll` — "giant scroll" (type: `feature`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).  Twice the
  player's height; too large to carry.
- **State fields:** `hidden` (initial `true`; revealed by
  `rubbish_pile.deep_rubbish_stage_two`), `unfurled` (initial
  `false`).
- **Interactions** (all availability: `hidden == false`):
  - **`identify_scroll`** — INT (Arcana) check (DC 12,
    non-repeatable).  On success: recognize the giant parchment as a
    spell scroll of Faerie Fire; append a `reveals` string.
  - **`unfurl`** — wrestle the giant parchment open.  STR check
    (DC 12, repeatable).  On success set `unfurled = true`; on
    failure the scroll snaps shut (no effect, retry).
  - **`read_aloud`** — read the spell aloud (availability:
    `unfurled == true`).  Result: magical light washes over the room.
    The faerie-fire *status effect* is deliberately not applied to any
    creature (the only in-room creature is Korbar, and lighting up
    one's own ally is counterproductive — the red-herring design);
    instead the light sweeps the rubbish and reveals the concealed
    flap: set `handkerchief.hidden = false` (skipping the WIS
    (Perception) DC 15 check), append a `reveals` string.  The
    scroll is mechanically real but situationally useless in combat —
    a D&D treasure you find that you can't effectively use, exactly as
    intended.  (It can't be carried to the spider.)
- **Reactions / on-examine effects / tags:** none.

### `bag_within` — "leather pouch" (type: `feature`)

- **Location:** inside `rubbish_pile` (in `bag_floor`).
- **State fields:** `hidden` (initial `true`; revealed by
  `rubbish_pile.deep_rubbish_stage_three`).
- **On-Examine Effects:**
  - `identify_bag_within` (any examination of the pouch; condition
    `entity:bag_within.hidden == false` and
    `flag:bag_within_identified == false`): INT (Arcana) check
    (DC 12, non-repeatable), with `skip_check_if` on
    `flag:read_label == true` (the care label's fine print makes it
    unmistakable).  On success: it is a Bag of Holding — the planes
    hold their breath; set `bag_within_identified = true`, append a
    `reveals` string.
- **Interactions:**
  - **`open_it`** — open the pouch.  Availability:
    `flag:bag_within_identified == true` and
    `flag:bag_within_warned == false`.  Result: the pouch's mouth
    yawns; the player's hand feels the pull of somewhere else; the GM
    asks if they are absolutely sure: set `bag_within_warned = true`
    (the two-step warning pattern, like `the_rip.squeeze_through`).
  - **`open_it_confirmed`** — open it anyway.  Availability:
    `bag_within_identified == true` and `bag_within_warned == true`.
    Result: **game over (lose)**, `trigger_id` `bag_within_rupture` —
    both bags rupture; everything is scattered across the Astral
    Plane, narrated with maximum ceremony.
- **Reactions / tags:** none.

### `care_label` — "care label" (type: `feature`)

- **Location:** `secret_pocket`, sewn into the seam.
- **On-Examine Effects:**
  - `read_care_label` (any examination): the main block: "Do not
    wash.  Do not iron.  Do not place living creatures inside.  Do
    not place within another extradimensional space." / "Contents may
    shrink by different amounts.  This is normal." / "Tears
    compromise containment."  Append a `reveals` string.  (Canonizes
    the variable-shrinkage whimsy and the rip's danger.)
  - `read_fine_print` (any examination; condition `flag:read_label ==
    false`): INT (Arcana) check (DC 12, non-repeatable).  On success:
    the fine print — "WARNING: nested extradimensional spaces void all
    warranties.  Do not insert bags into bags.  Do not insert bags
    into bags.  DO NOT INSERT BAGS INTO BAGS."  Set `read_label =
    true`, append a `reveals` string.  (Makes `bag_within`
    identification free.)
- **Interactions / reactions / tags / state fields:** none.

### `sending_stone` — "sending stone" (type: `feature`)

- **Location:** `secret_pocket`.  Too heavy to move.
- **Interactions:**
  - **`listen`** — listen to the stone (repeatable).  WIS check
    (DC 12).  On success: it crackles alive — a distant woman's voice:
    "Korbar?  Korbar, where did you—" then static; set
    `flag:wizard_voice_heard = true`, append a `reveals` string.  On
    failure: nothing but the faint buzz it was tossed in for.
    (Telling Korbar — `tell_about_stone` — contributes to rapport.)
  - **`speak_into`** — shout name, situation, and location into the
    stone.  Result-only: nothing comes back.  Somewhere, a wizard's
    pocket buzzes.  He does not check it.  Append a `reveals` string.
  - **`try_lift`** — try to move the stone.  Roll check (threshold
    0.0, repeatable — always fails): it does not budge (it is far too
    heavy at the player's scale).
- **On-examine effects / reactions / tags / state fields:** none.

### `emergency_gin` — "hip flask of gin" (type: `item`)

- **Location:** `secret_pocket` (jammed into a corner).
- **Take Check:** STR check (DC 12, repeatable) to lug it out of the
  compartment; on failure the flask stays jammed (no further effect).
- **Interactions:**
  - **`sip`** — a sip of liquid courage: `player_heal: "1"` (narrate
    the warmth; no drunkenness mechanics at one sip).
- **Tags / state fields / reactions / on-examine effects:** none.
  (Giftable to Korbar — the premium rapport gift, §1G `korbar`.)

### `korbar_shelter` — "overturned soup ladle" (type: `feature`)

- **Location:** `bag_floor` (Korbar's shelter).
- **On-Examine Effects:**
  - `examine_shelter` (any examination): the giant overturned soup
    ladle, propped against the rubbish; Korbar's meager home.
  - `find_stash` (rigorous examination only; condition
    `party_badge.hidden == true` or `wineskin_dregs.hidden == true`):
    her stash is tucked under the ladle's handle: set `hidden =
    false` on `party_badge` and `wineskin_dregs`; append a `reveals`
    string.  The GM narrates Korbar watching the player like a hawk
    while they poke through her things.
- **Interactions / reactions / tags / state fields:** none.

### `party_badge` — "party badge" (type: `item`)

- **Location:** inside `korbar_shelter` (in `bag_floor`).
- **State fields:** `hidden` (initial `true`; revealed by
  `korbar_shelter.find_stash`).
- **Take Check:** none (a small token; Korbar may grumble but the
  badge is not the wineskin).
- **Interactions / reactions / on-examine effects:** none.  (Shown to
  Korbar — `inventory:party_badge` — it unlocks the
  `abandonment_story` will-reveal topic, §1G `korbar`.)

### `wineskin_dregs` — "wineskin of dregs" (type: `item`)

- **Location:** inside `korbar_shelter` (in `bag_floor`).
- **State fields:** `hidden` (initial `true`; revealed by
  `korbar_shelter.find_stash`).
- **Take Check:** availability — `korbar` is `unconscious` or not
  `alive` (she guards it jealously; while awake the check is a roll
  with threshold 0.0 — always fails — with an explanatory failure
  narrative, like `plate_armor`).  (A rapport gift once acquired;
  giving it back to her is a genuine effort, §1G `korbar`.)
- **Interactions / reactions / on-examine effects / tags:** none.

### `spider_hoard` — "spider's hoard" (type: `feature`)

- **Location:** `axe_handle_lower`, at the base of the web.
- **State fields:** `hidden` (initial `true`; revealed by
  `webs.reveal_spider_hoard` — searchable once the spider is dead,
  departed, or asleep).
- **Soft-item guidance:** a shiny drift — giant copper pieces, a
  wooden button, a bottle cap, lint-covered silver pieces.  All far
  too cumbersome to carry; the GM may let the player pocket one tiny
  soft item as a memento.
- **Interactions / reactions / on-examine effects / tags:** none.

### `spider_corpse` — "spider corpse" (type: `feature`)

- **Location:** `axe_handle_lower`, tangled in the web.
- **State fields:** `hidden` (initial `true`; revealed by
  `webs.reveal_spider_corpse` — searchable once `spider.alive ==
  false`).
- **On-Examine Effects** (rigorous examination only): harvesting the
  corpse: set `spider_fang.hidden = false` and append a `reveals`
  string; the venom sac is a soft item (GM-blessed one-shot blade
  coating or bait — see the soft-item guidance).
- **Interactions / reactions / tags:** none.

### `spider_fang` — "spider fang" (type: `item`)

- **Location:** inside `spider_corpse` (in `axe_handle_lower`).
- **State fields:** `hidden` (initial `true`).
- **Take Check:** none.  **Interactions / reactions / on-examine
  effects:** none.  (Explicit physical evidence: `convince_spider_dead`
  skips its CHA check when `inventory:spider_fang` — equivalent to the
  `spider.alive == false` skip; the fang makes the evidence concrete.)

---

## 1H. Cleanup

Consistency pass performed: all IDs snake_case and cross-referenced;
exactly one start room (`axe_head`) and one `player` entity; the
player is present in exactly one room; each item/NPC present in at
most one room (`toenail_sword` and the deep-rubbish finds inside
`rubbish_pile`; `plate_armor` inside `korbar`; the husk loot inside
`prisoner_husk`; the stash inside `korbar_shelter`; `spider_fang`
inside `spider_corpse`); features spanning multiple rooms limited to
`giant_axe` and `webs` (per-room behavior of `webs` documented);
every referenced global flag, state field, and tag (`heavy`, `weapon`)
is defined; every initially-hidden entity has an unhide mechanism
(`padlock` ← rip examination; `fly` ← webs examination; `spider` ←
Perception checks or combat triggers; `prisoner_husk` ← webs rigorous
examination; the husk loot and `spider_fang` ← the owning entity's
rigorous examination; `toenail_sword`, the four `potion_vat_*`,
`giant_rations`, `giant_lockpick`, `giant_faerie_fire_scroll`, and
`bag_within` ← the staged rubbish examinations; `handkerchief` ←
rubbish Perception check, Korbar's topic, or the faerie-fire scroll;
`spider_hoard` / `spider_corpse` ← webs rigorous examination once the
spider is gone; `party_badge` / `wineskin_dregs` ← `korbar_shelter`
rigorous examination); the hidden exit `secret_flap` has a reveal
mechanism (`handkerchief.moved_aside`); the one-way drop exits have
return paths (climbing the handle); no entity has the `container` tag
(no open/close containers exist in this scenario — the rubbish pile
holds items without open/close semantics); no `stackable` items exist,
but there are consumables (`giant_rations`, `emergency_gin`,
`scroll_of_sleep`, `scroll_of_mage_armor` — one-shots via
`remove_item_count` — and the vat features, drained by state); no
non-NPC entity has dialogue or aggro plans; both combat-capable NPCs
(`spider`, `korbar`) have stat blocks and `current_hp` declarations,
and all combat-starting reactions name their combatants explicitly;
every check is marked repeatable or non-repeatable; every examination
effect notes whether rigorous examination is required; the preemptive
reaction (`web_spider_attack`) is marked as such; attitude limits are
noted for both attitude-shifting NPCs; Korbar's follower room
blacklist (`secret_pocket`) is recorded; the route-specific lose
interactions (key through the rip, squeezing through the rip, the
ink-black vat drink, `bag_within` confirmed opening) and both wins
(key, lock-picking) are recorded on their owning entities; the
spider's AI flee and its `spider_flee_fallout` reaction are recorded
on the spider; the `invisible`-clearing reactions, the quiet-cut
failure encounter, the rest-muttering reaction, and Korbar's
knock-out rescue are mechanic-scope (§1E).

### Design Decisions and Interpretations

1. **Player death handling.**  The scenario never states a lose
   condition for the player's death.  It is not listed as a mechanic:
   the engine handles it automatically (whenever the player's HP drops
   to 0, from any source, the game ends unless a `player.died` rescue
   reaction intervenes).
2. **Scenario typos.**  "Axe Head (Upper)" (Dropping) and "Axe Head
   (Lower)" (Web) were read as `axe_handle_upper` / `axe_handle_lower`.
3. **Win/loss scoping.**  Only `player_death` and `key_lost_game_over`
   are global game-over conditions (§1E).  The wins and the other
   route-specific losses (squeezing through the rip; the poison vat;
   the bag within) are recorded as game-over consequences on their
   owning entities (§1G).
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
    initiative modifier or flee DC, and the player's attack/damage
    stats are unspecified; the defaults chosen are listed in §1A.
12. **Stealing the plate armor.**  Assumed possible only when Korbar
    is unconscious or dead; the scenario just says "the player can
    steal" it.
13. **Korbar at 0 HP.**  Her falling unconscious instead of dying is a
    deviation from default NPC death handling, requiring the custom
    `unconscious` state field and the mechanic-scope rescue
    (`korbar_knocked_out`, §1E).
14. **Korbar's padlock help.**  "If KORBAR is present, she will help"
    at the padlock can only happen if she is `following` (alive and
    conscious), since she otherwise never leaves `bag_floor`.
15. **Rapport cap.**  Results cannot increment numeric state, so the
    scenario's cap of 3 general conversation-based attitude increases
    for Korbar is enforced by the `rapport_1/2/3` flags gating the
    three `positive_rapport_*` paths.
16. **Toenail take-check.**  Repeatability of the DEX 8 removal check
    is unspecified; assumed repeatable with no failure side effect.
17. **"Armed" definition.**  For the web STR check and
    `persuade_passage`, "armed" means carrying/wielding a
    `weapon`-tagged item.  The engine has no way to lower a DC
    automatically when the player is armed, so the armed variants are
    `using_results` overrides keyed on `toenail_sword`, `dagger`, and
    `giant_lockpick`, plus a `"*"` wildcard for anything else the GM
    deems blade-like (exact keys take precedence; the player must
    explicitly "use" the item; each override carries its own
    success/failure with item-specific narration, which the traversal
    resolver honors).
18. **Non-repeatable check tracking.**  The engine tracks attempts of
    non-repeatable checks and rejects repeats.  Chained checks (e.g.,
    the rip's DC 17 realization requires the earlier DC 12 success)
    are gated via the knowledge flags set on success (§1D).
19. **Fly death timing.**  The fly's death-when-the-player-leaves is
    triggered on the player's exit *attempt* (while the fly is still
    in the current room), because an entity reaction can only fire
    while its entity is in the current room.
20. **Follower restriction.**  Korbar's refusal to enter
    `secret_pocket` is recorded as a refused room under her Follower
    Behavior (the engine clears `following` if the player enters such
    a room).
21. **The poison vat's unwarned kill.**  Drinking the ink-black vat
    blind is a game over with no confirm step — deliberate ("Drink
    blind.  Dumb, but free.").  The player's protection is diegetic:
    the liquid's description is alarming (it drinks the glow, smells
    of nothing, radiates cold), and the cautious paths (sip, or read
    the label) both reveal the danger.  The other lose interactions
    keep the established two-step warning pattern
    (`squeeze_through`/`squeeze_through_confirmed`,
    `open_it`/`open_it_confirmed`), so this is the one place a player
    can die on a first try — with fair warning in the prose.
22. **Skills.**  Skill checks are stat checks naming a skill, with
    proficiency from `default-player.json` `skill_proficiencies`
    (§1A).  DCs unchanged from the scenario; +2 proficiency is the
    Rogue's reward.
23. **`invisible` is not engine-cleared on attack.**  The SRD pack
    itself notes "SRD ends the spell when the target attacks... — not
    modeled."  The clearing is implemented by two mechanic-scope
    reactions (`invisible_breaks_on_attack`,
    `invisible_breaks_on_combat`, §1E).
24. **`poisoned` override.**  The built-in `poisoned` is combat-scoped
    (cleared at combat end), which would make the antivenom pointless.
    The corpus overrides `poisoned` to persistent/until-cleared (the
    validator warns on pack overrides — accepted).  A long rest still
    clears it.
25. **Sleep-scroll duration.**  The built-in `incapacitated` is
    combat-scoped `rounds`; out of combat it never ticks, so a slept
    spider sleeps until combat starts (then 10 rounds).  Documented
    behavior, not a bug: the scroll solves the spider like killing or
    persuading it does.
26. **Spider flee discriminator.**  The engine's `fled` state is
    engine-owned runtime state, not a declared field;
    `spider_flee_fallout` distinguishes "fled" from "killed" via
    `combat.ended` `reason == victory` plus `spider.alive == true` (a
    killed spider is `alive == false`).
27. **Lock-picking vs. the rip.**  `padlock.pick_lock` has the player
    climb *along the pick* spanning the gap between the bag and the
    padlock; this deliberately does not trigger
    `the_rip.squeeze_through` (the pick is the bridge).  The GM
    narrates the tension; the void is never free-fallen.
28. **Quiet-cut failure routing.**  `interaction.used` reactions fire
    before a check resolves and cannot see its outcome, so the quiet
    cut's failure sets `flag:quiet_cut_failed`, which a `flag.set`
    reaction (`quiet_cut_failure_spider`, §1E) converts into the
    spider encounter.  This implements "on failure the spider
    attacks" exactly.
29. **Mage Armor on Korbar.**  NPC combat blocks are pre-computed, so
    her AC stays 18 regardless; the scroll on her is narrative
    protection plus the `korbar_mage_armored` flag that unlocks
    early `doff_armor`.  Documented here so the JSON step doesn't
    promise a mechanical AC change.
30. **Faerie Fire scroll target.**  The only in-room creature in
    `bag_floor` is Korbar; lighting an ally is counterproductive, so
    `read_aloud` applies no status effect to a creature.  Its payoff
    is illumination: it reveals the handkerchief.  The red-herring
    design is preserved (it can't be carried to the spider).
31. **Fly revival location.**  `potion_vat_amber.heal_fly` requires
    the freed fly to be present, which means the player is in
    `bag_floor` with the fly riding along — the freed fly follows the
    player narratively (no `follower` block for a fly).
32. **Wineskin guard.**  `wineskin_dregs` take is gated on Korbar
    being unconscious/dead (roll threshold 0.0 while awake), like
    `plate_armor` (item 12's pattern).
33. **Deep-rubbish checks are repeatable.**  The three staged
    Investigation checks (DC 12/15/17) gate most of the adventure's
    treasure — including the giant lockpick, and with it an entire
    win path — so they must not be one-shot: a single failed roll
    should cost time, not content.  The chaining is unchanged: each
    stage is gated on the previous stage's flag, and the
    pre-examination state semantics (see Conventions) keep the stages
    on separate examinations.
34. **Fly boon exclusivity and deaths.**  The freed fly's options are
    a genuine choice: each unrevived boon ends with the fly's death
    (`fly_dies_after_watch` after the watch; the `fly_vouch` path
    after the vouch), and `fly_vouch` requires the fly to still be
    riding with the player (`fly_watching_lower == false`).  A revived
    fly (`fly_revived`) survives and gets both boons: `heal_fly`
    delivers the vouch immediately (setting `fly_vouched` and granting
    the +1), and the watch it grants ends via `fly_watch_ends_revived`
    instead of the fly's death — matching the scenario's "it lives ...
    and does *both*".
35. **`offer_weapon` split (Step 2 revision).**  The map planned
    `offer_weapon` as a single dialogue path with `using_results` keyed
    on the three weapons.  However, `TalkAction` carries no `using`
    field, so a dialogue path's `using_results` is unreachable in
    practice.  During JSON conversion the path was therefore split into
    condition-exclusive variants per the Conventions above:
    `offer_toenail_sword`, `offer_dagger`, and `offer_lockpick` (each
    gated on the weapon being in the player's inventory, with the same
    `remove_item` + `korbar_armed` + +2 attitude result), while the
    base `offer_weapon` path keeps the "with what?" fallback.

### Remaining notes for the JSON conversion

- **Flags:** all flags in §1D must appear in `flags_declared`.
- **Status effects:** the three corpus entries in §1E (Status
  effects).
- **Mechanics:** `invisible_breaks_on_attack`,
  `invisible_breaks_on_combat`, `quiet_cut_failure_spider`,
  `overhear_korbar_muttering`, and `korbar_knocked_out` are
  reaction-only mechanics; `heavy_key_movement` is implemented as
  per-exit traversal checks; `key_lost_game_over` is a top-level
  `game_over_conditions` entry; `spider_flee_fallout` is entity-scoped
  on the spider; the `fly_alarm_*` / `fly_watch_*` /
  `fly_dies_after_watch` reactions are room-scoped on
  `axe_handle_lower`.
- **Stats block:** all six 5e ability scores (system `"5e"`); all six
  are used by checks, saves, conditions, or `alter_stat` results in
  the corpus.
- **`default-player.json`:** exactly the §1A values, including
  `skill_proficiencies`: `["acrobatics", "arcana", "athletics",
  "deception", "insight", "investigation", "perception", "persuasion",
  "sleight of hand", "stealth"]`; location `axe_head`; empty inventory
  and equipment.
- **`soft-state.json`:** the standard null structure; the `reveals`
  strings flow into `revealed_hints`, and the soft items (venom sac,
  hoard mementos, rubbish oddments) live in soft state.
