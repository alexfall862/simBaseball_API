---
title: How Weeks Work
lastUpdated: 2026-04-12
---

## The Subweek System

Time in the sim advances in **weeks**, and each week is divided into **4 subweeks**: a, b, c, and d.

Each subweek represents a chunk of games and activities:

:::compare
| | Subweek | What Happens |
|---|---|---|
| | a | Game or rest day, stamina processing |
| | b | Game or rest day, stamina processing |
| | c | Game or rest day, stamina processing |
| | d | Game or rest day, stamina processing, weekly development tick |
:::

## Why Subweeks Matter

The subweek system is the backbone of several key mechanics:

- **Stamina** — players drain energy in game subweeks and recover in rest subweeks
- **Starting rotation** — your 5 starters cycle through the subweeks
- **Bullpen recovery** — relievers need rest subweeks between appearances
- **Injuries** — players can get hurt in any game subweek

:::callout type=info
You don't need to micromanage subweeks. The engine handles scheduling automatically. But understanding the 4-subweek structure helps you understand why stamina management and rotation depth matter.
:::

## Games Per Week

Not every subweek has a game. The schedule includes:

- **3-4 games per week** for most weeks
- **Off days** scattered throughout the season
- **All-Star break** — no games for one week

When a subweek doesn't have a game, all your players get a rest subweek (stamina recovery).

:::callout type=tip
Off days are valuable for stamina recovery. A week with only 3 games means your players get an extra rest subweek. Monitor the schedule to know when you can push your players harder and when to ease up.
:::

## The Weekly Cycle

A typical game week looks like this:

1. **Subweek a** — game day. Starters play, stamina drains
2. **Subweek b** — game day. Different starter pitches
3. **Subweek c** — game day or off day
4. **Subweek d** — game day or off day, plus weekly development processing

After subweek d, the sim advances to the next week and the cycle repeats.

:::detail title="Advanced: Processing order within a subweek"
Within each subweek, events process in this order:

1. The game is simulated by the engine
2. Game stats are recorded (batting lines, pitching lines, fielding)
3. Stamina drain is applied for all players who appeared
4. Stamina recovery is applied for all players who did not appear
5. Injuries are checked and applied
6. (On subweek d only) Weekly development checks run for all active players

This order matters for edge cases — for example, a player who gets injured in a game still incurs the stamina cost from that game.
:::
