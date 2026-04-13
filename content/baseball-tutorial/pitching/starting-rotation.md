---
title: Starting Rotation
lastUpdated: 2026-04-12
---

## Setting Up Your Rotation

Your starting rotation is the group of pitchers who take turns starting games. The sim uses a **5-man rotation** by default, meaning each starter pitches roughly once per week.

:::callout type=info
Since there are 4 subweeks per week, a 5-man rotation means some starters will get an extra rest subweek each cycle. The engine automatically handles rotation ordering — you just need to set who's in the rotation.
:::

## What Makes a Good Starter

Starting pitchers need a different skill set than relievers:

:::compare
| | Attribute | Why It Matters for Starters |
|---|---|---|
| | Stuff | Determines strikeout ability and quality of contact allowed |
| | Control | Keeps pitch counts low, enables deeper starts |
| | Stamina | How many pitches they can throw before tiring — directly limits innings |
:::

:::player-example
position: SP
attributes:
  stuff: 60
  control: 65
  stamina: 70
  velocity: 55
caption: "A workhorse starter — above-average across the board with great stamina. He won't dominate, but he'll give you 6-7 quality innings every start and keep his pitch count manageable."
:::

## Stamina and Pitch Counts

Stamina is the most important attribute specific to starters. It determines:

- How many pitches they can throw before performance degrades
- How deep into games they can go
- How quickly they recover between starts

:::rating
attribute: Stamina
scale: 20-80
example: 65
description: A 65-stamina starter can reliably throw 100-110 pitches per start and go 6-7 innings. They'll be ready for their next turn through the rotation.
:::

## Rotation Depth

Having 5 quality starters is ideal, but many teams don't have that luxury. Strategies for thin rotations:

- **Use your best 3-4 starters** and fill the 5th spot with a "spot starter" or opener
- **Piggyback** — pair a short-start pitcher with a long reliever
- **Monitor fatigue** — if your best starter is wearing down late in the season, consider skipping a turn

:::callout type=tip
It's better to have a mediocre 5th starter who eats innings than to skip him and overwork your bullpen. Bullpen stamina is a finite resource over a long season.
:::

:::league filter=College
College rotations often use a **Friday/Saturday/Sunday** three-man rotation for weekend series, with midweek starters for additional games. Your top 3 pitchers should be your weekend starters.
:::
