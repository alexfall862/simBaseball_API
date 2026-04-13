---
title: Pitch Types & Repertoire
lastUpdated: 2026-04-12
---

## Why Repertoire Matters

Every pitcher in the sim has a **repertoire** — the set of pitch types they can throw. A larger, more diverse repertoire gives a pitcher more ways to attack hitters, but the quality of each pitch matters more than the quantity.

The primary pitching attribute is [Stuff]{A pitcher's overall pitch quality — how nasty and deceptive their offerings are}. Stuff combines with repertoire to determine how effective a pitcher is.

## Common Pitch Types

Pitchers can have a mix of these pitches:

- **Fastball (FB)** — velocity-based, the foundation of most repertoires
- **Slider (SL)** — sharp lateral break, effective against same-side hitters
- **Curveball (CB)** — big downward break, a classic strikeout pitch
- **Changeup (CH)** — speed differential off the fastball, effective against opposite-side hitters
- **Cutter (CT)** — between a fastball and slider, late movement
- **Sinker (SI)** — sinking action, generates ground balls
- **Splitter (SPL)** — drops sharply, a swing-and-miss pitch

:::callout type=tip
A starter with 3-4 quality pitches can dominate. A reliever can get by with 2 elite pitches since they only face the lineup once. Don't overvalue repertoire size — quality matters more.
:::

## Stuff Rating

Stuff is the master pitching attribute. It represents how nasty and deceptive a pitcher's offerings are:

:::rating
attribute: Stuff
scale: 20-80
example: 68
description: A 68-stuff pitcher has dominant offerings. Hitters will struggle to make quality contact, generating lots of strikeouts and weak contact.
:::

## Velocity

Velocity is a separate attribute that represents fastball speed:

:::rating
attribute: Velocity
scale: 20-80
example: 60
description: A 60-velocity pitcher throws 93-95 mph. Above average heat that complements off-speed pitches well.
:::

:::detail title="Advanced: How Stuff and Velocity interact"
Stuff and Velocity are separate attributes that combine during at-bat simulation. High Stuff with average Velocity produces a pitcher who relies on movement and deception. Average Stuff with high Velocity produces a "power pitcher" who overwhelms with speed.

The most dominant pitchers have both — 65+ Stuff with 65+ Velocity is an elite combination. But you can build a successful pitching staff with a mix of styles.
:::

## Control: The Other Half

Even nasty stuff needs to be thrown in the zone to be effective. [Control]{A pitcher's ability to locate pitches where intended} determines:

- Walk rate ([BB%]{Walk Rate — percentage of plate appearances ending in a walk})
- Ability to pitch to both sides of the plate
- Effectiveness in hitter-friendly counts
- Efficiency (fewer pitches per inning)

:::compare
| | Stuff-First Pitcher | Control-First Pitcher | Complete Pitcher |
|---|---|---|---|
| Stuff | 65-80 | 40-55 | 60-70 |
| Control | 35-50 | 65-80 | 60-70 |
| Strikeouts | Very High | Low-Moderate | High |
| Walks | High | Very Low | Low |
| Style | Dominant but wild | Efficient, few baserunners | Best of both worlds |
| Risk | Blowup starts from walks | Gets hit hard when stuff fades | Expensive to acquire |
:::

:::player-example
position: SP
attributes:
  stuff: 72
  control: 55
  stamina: 60
  velocity: 68
caption: "An ace-caliber starter — elite stuff and velocity, but the average control means he'll have occasional wild games. His high strikeout rate masks the walks."
:::
