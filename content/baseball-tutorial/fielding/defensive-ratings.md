---
title: Defensive Ratings Explained
lastUpdated: 2026-04-12
---

## The Defensive Attributes

Defense in the sim is driven by three main attributes:

- **Fielding** — glove skill, how cleanly a player fields grounders and catches fly balls
- **Arm** — throwing arm strength and accuracy
- **Speed** — range and ability to reach balls in the gaps

Each position weights these differently. A shortstop needs all three; a first baseman mostly needs fielding.

:::rating
attribute: Fielding
scale: 20-80
example: 60
description: A 60-fielding player is above average with the glove — reliable on routine plays and capable on difficult ones.
:::

:::rating
attribute: Arm
scale: 20-80
example: 70
description: A 70-arm player has a cannon. Critical for shortstops, third basemen, catchers, and right fielders.
:::

## How Defense Affects Games

When a ball is hit to a fielder, the engine runs a defensive check:

1. **Range check** — can the fielder reach the ball? (Speed + Fielding)
2. **Field check** — does the fielder handle it cleanly? (Fielding)
3. **Throw check** — does the throw beat the runner? (Arm + accuracy)

A missed step in any check turns an out into a hit or an error.

:::callout type=info
Defense is often undervalued by new managers. The difference between a 40-fielding shortstop and a 65-fielding shortstop is roughly 15-20 extra hits allowed per season. That translates to several extra runs — and wins.
:::

## Position-Specific Importance

:::compare
| | Position | Fielding Weight | Arm Weight | Speed Weight |
|---|---|---|---|---|
| | C | Very High | Very High | Low |
| | SS | Very High | High | High |
| | 2B | High | Medium | High |
| | 3B | High | Very High | Medium |
| | CF | High | Medium | Very High |
| | RF | Medium | Very High | High |
| | LF | Medium | Low | High |
| | 1B | Medium | Low | Low |
:::

:::callout type=tip
If you have to sacrifice defense somewhere, first base and left field are the best places to hide a weak glove. Never sacrifice defense at shortstop, catcher, or center field — those positions are too important.
:::
