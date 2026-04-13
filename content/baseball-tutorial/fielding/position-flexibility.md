---
title: Position Flexibility
lastUpdated: 2026-04-12
---

## Playing Out of Position

Players have a primary position, but many can play multiple positions. When a player plays a position that isn't their primary, they take a **defensive penalty** — their effective fielding rating is reduced.

The size of the penalty depends on how far the new position is from their natural one:

:::compare
| | Move | Penalty | Example |
|---|---|---|---|
| | Primary position | None | SS playing SS |
| | Adjacent position | Small (-3 to -5) | SS playing 2B |
| | Different position group | Moderate (-8 to -12) | SS playing 3B |
| | Completely different | Large (-15 to -20) | SS playing LF |
:::

:::callout type=warning
Just because a player *can* play a different position doesn't mean they *should*. A shortstop with 60 Fielding who moves to left field might only field at 45-50 there. Always check the effective rating before making position changes.
:::

## Why Flexibility Matters

Roster flexibility is a major strategic advantage:

- **Bench utility** — a bench player who can play 3-4 positions is worth more than one locked into a single spot
- **Injury coverage** — when a starter goes down, flexible players can fill the gap
- **Platoon options** — platoon a lefty and righty at the same position based on the opposing pitcher
- **Late-game defense** — sub in a better defender for a weak-glove slugger in close games

:::callout type=tip
When evaluating bench players, position flexibility often matters more than raw talent. A 50-OVR utility infielder who can play SS/2B/3B is more valuable off the bench than a 55-OVR player locked into first base.
:::

## The Defensive Spectrum

Positions are ranked by defensive difficulty. Players can generally move "down" the spectrum more easily than "up":

**Harder** → C → SS → 2B → CF → 3B → RF → LF → 1B → DH ← **Easier**

A shortstop can often play second base or third base with minimal penalty. A first baseman trying to play shortstop will be a disaster.

:::detail title="Advanced: How the engine handles position changes"
When a player is assigned to a non-primary position, the engine applies a penalty matrix based on the primary/secondary position pair. Some players also have "secondary position" flags that reduce the penalty — a player listed as SS/2B takes a smaller penalty at 2B than a pure SS would.

The penalty applies to the Fielding attribute only. Arm and Speed remain unchanged, but the lower effective Fielding means more errors and fewer plays made.
:::
