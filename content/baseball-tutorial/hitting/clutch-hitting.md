---
title: Clutch Hitting
lastUpdated: 2026-04-12
---

## The Clutch Attribute

Some players rise to the occasion when the game is on the line. The **Clutch** attribute represents a hitter's ability to perform in high-leverage situations — late innings, runners in scoring position, close games.

:::rating
attribute: Clutch
scale: 20-80
example: 70
description: A 70-clutch hitter gets a meaningful boost in high-leverage situations. They're the player you want at the plate with the game on the line.
:::

## When Clutch Activates

The clutch modifier kicks in during **high-leverage situations**, which the engine defines as:

- 7th inning or later
- Runner(s) in scoring position
- Score differential of 3 runs or fewer
- Playoff games (all situations get a small leverage boost)

When active, a player's clutch rating provides a **bonus or penalty** to their Contact and Power for that at-bat.

:::compare
| | Clutch Rating | Effect in High Leverage |
|---|---|---|
| | 70-80 | +5 to +10 effective Contact/Power |
| | 50-60 | Neutral — no bonus or penalty |
| | 30-40 | -3 to -7 effective Contact/Power |
| | 20 | -10 effective Contact/Power — folds under pressure |
:::

:::callout type=warning
Clutch is a hidden modifier that doesn't show up in basic stat lines. A player might hit .280 overall but .310 in high-leverage situations purely because of a strong clutch rating. Check the attribute, not just the stats.
:::

## Building Around Clutch

You can't build a whole lineup around clutch, but you can use it strategically:

- Put high-clutch hitters in the **3-5 spots** where they'll bat with runners on most often
- A high-clutch pinch hitter off the bench is extremely valuable in close games
- In the playoffs, clutch becomes even more important — every game is high leverage

:::callout type=tip
Don't trade away your clutch hitters at the deadline, even if their overall numbers look replaceable. That late-game reliability is hard to find and shows up most when it matters most.
:::

:::detail title="Advanced: Clutch and the Leverage Index"
The engine calculates a leverage index for each plate appearance based on inning, score, baserunners, and outs. The clutch modifier scales with this index — a bases-loaded, two-out, bottom-of-the-9th at-bat in a tie game applies the full clutch effect, while a 7th-inning situation with a runner on second applies a partial effect.

In the playoffs, the baseline leverage index is elevated, meaning clutch matters more across the board, not just in obvious high-leverage spots.
:::
