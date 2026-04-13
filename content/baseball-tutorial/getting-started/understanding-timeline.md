---
title: Understanding the Timeline
lastUpdated: 2026-04-12
---

## Weeks and Subweeks

The sim doesn't play one game at a time. Instead, time advances in **weeks**, and each week is divided into **4 subweeks** (a, b, c, d).

In each subweek, your team may:
- Play a game
- Have a rest day (players recover stamina)
- Have a scheduled off-day

:::callout type=info
The subweek system is what drives stamina drain and recovery. Players who play in a subweek lose stamina; players who rest recover some. This is why rotation management and bench depth matter.
:::

## The Season Flow

A typical season follows this structure:

1. **Preseason** — roster setup, no games
2. **Regular Season** — weekly game schedule, ~24 weeks
3. **All-Star Break** — midseason event
4. **Trade Deadline** — last chance for midseason trades
5. **Postseason** — playoff bracket for qualifying teams
6. **Offseason** — free agency, draft, roster restructuring

:::league filter=College
College seasons are shorter, with conference play, a conference tournament, and the College World Series for qualifying teams.
:::

## What Happens Each Week

When a week advances:

1. **Games are simulated** for each subweek
2. **Stamina drains** for players who played
3. **Stamina recovers** for players who rested
4. **Injuries** may occur during games
5. **Player development** ticks forward for young players
6. **Standings update** based on results

:::detail title="Advanced: How Subweek Processing Works"
Each subweek is processed independently. The engine simulates the game first, then the API processes the results:

1. Stamina costs are subtracted for every player who appeared in the game
2. Recovery is applied for players who did not play that subweek
3. Recovery amount depends on the player's durability trait (Iron Man recovers 1.5x, Tires Easily recovers 0.5x)
4. Base recovery per rest subweek is 5 stamina points

This means a player with normal durability who sits for a full week (4 subweeks) recovers 20 stamina.
:::
