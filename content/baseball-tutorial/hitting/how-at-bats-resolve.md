---
title: How At-Bats Resolve
lastUpdated: 2026-04-12
---

## Inside the Engine

When a batter steps to the plate in the sim, the game engine runs through a series of checks to determine the outcome. Understanding this process helps you build a better lineup and gameplan.

:::callout type=info
You don't need to understand every detail here to play the sim well. This article is for players who want to know what's happening "under the hood."
:::

## The At-Bat Flow

Each at-bat follows this general sequence:

1. **Pitch selection** — the pitcher chooses a pitch type based on repertoire, count, and game situation
2. **Location roll** — the pitcher's [Control]{A pitcher's ability to locate pitches where intended} determines how close to the target the pitch lands
3. **Swing decision** — the hitter's [Eye]{Plate discipline — ability to distinguish balls from strikes} determines whether they swing
4. **Contact check** — if swinging, [Contact]{How consistently a batter makes solid contact} determines quality of contact
5. **Result determination** — [Power]{Raw power — determines batted ball distance}, launch angle, and fielding determine the outcome

:::detail title="Advanced: The full resolution chain"
The engine processes each pitch in the at-bat until a terminal outcome (strikeout, walk, ball in play, HBP). Key interactions:

- **Stuff vs. Contact**: The pitcher's Stuff rating reduces the hitter's effective Contact. An 80-Stuff pitcher facing a 60-Contact hitter is effectively facing a ~50-Contact hitter.
- **Control vs. Eye**: Determines the ball/strike count progression. High-Control pitchers throw more strikes; high-Eye hitters take more balls.
- **Power vs. ballpark**: Power determines exit velocity. The ballpark dimensions then determine whether a fly ball is a home run, a flyout, or off the wall.
- **Speed**: Affects infield hit probability and double-play avoidance.
- **Fielding**: Defensive ratings of the fielder closest to the batted ball determine whether it's a hit or an out.
:::

## Key Matchups

The most important matchups in each at-bat:

:::compare
| | Matchup | Favors Hitter When | Favors Pitcher When |
|---|---|---|---|
| | Stuff vs. Contact | Contact > Stuff by 15+ | Stuff > Contact by 15+ |
| | Control vs. Eye | Eye > Control by 15+ | Control > Eye by 15+ |
| | Power vs. Park | Power 60+ in small park | Power < 45 in large park |
:::

## What This Means for Your Lineup

- Stack high-Contact hitters against high-Stuff pitchers to avoid strikeouts
- Patient (high-Eye) hitters are especially valuable against wild pitchers
- Power hitters get a boost in smaller ballparks
- Speed matters most when contact is made on the ground — fast players beat out infield hits and avoid double plays

:::callout type=tip
You can't control individual at-bats, but you can stack the odds by understanding these matchups. Over a full season, even small edges add up to wins.
:::
