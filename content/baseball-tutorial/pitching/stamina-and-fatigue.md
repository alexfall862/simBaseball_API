---
title: Stamina & Fatigue
lastUpdated: 2026-04-12
---

## How Stamina Works

Every player in the sim has a **stamina** value from 0 to 100 that represents their current energy level. As players participate in games, their stamina drains. When they rest, it recovers.

Stamina directly affects performance — a tired player performs worse than a fresh one.

:::callout type=important
Stamina management is one of the most impactful strategic decisions in the sim. Running your players into the ground will cost you games, especially down the stretch and in the playoffs.
:::

## Stamina Drain

When a player appears in a game, the engine calculates a **stamina cost** based on their workload:

- **Starting pitchers** — high stamina cost (30-50 per start depending on pitch count)
- **Relief pitchers** — moderate cost (10-25 per appearance)
- **Position players** — lower cost (5-15 per game)

The stamina cost is subtracted from the player's current stamina after each subweek's game.

## Stamina Recovery

Players who **don't play** in a subweek recover stamina. The base recovery rate is **5 points per rest subweek**, modified by the player's durability trait:

:::compare
| | Durability Trait | Recovery Multiplier | Recovery Per Rest |
|---|---|---|---|
| | Iron Man | 1.5x | 7.5 per subweek |
| | Durable | 1.25x | 6.25 per subweek |
| | Normal | 1.0x | 5.0 per subweek |
| | Wears Down | 0.75x | 3.75 per subweek |
| | Tires Easily | 0.5x | 2.5 per subweek |
:::

:::callout type=tip
Durability is an underrated attribute when evaluating players. An Iron Man starter recovers almost twice as fast as a Tires Easily pitcher, which means they're ready for their next start sooner and perform better in the second half.
:::

## Usage Thresholds

The sim uses stamina thresholds to determine when players are available:

:::compare
| | Threshold | Stamina Level | Meaning |
|---|---|---|---|
| | Only Fully Rested | 95+ | Player will only be used when nearly full stamina |
| | Normal | 70+ | Default — player is available for regular use |
| | Play Tired | 40+ | Player is available even when fatigued |
| | Desperation | 0+ | Player is always available regardless of fatigue |
:::

:::callout type=warning
Playing tired players is a tradeoff. A 40-stamina pitcher is significantly worse than the same pitcher at 90 stamina. Only push your players below the Normal threshold when you truly need them — like a playoff push.
:::

## Managing Your Staff

For starting pitchers, the rotation naturally provides rest days. A 5-man rotation means each starter pitches once per week and rests for 3-4 subweeks.

For relievers, you need to be more careful:

- Don't use the same reliever in back-to-back subweeks unless necessary
- Keep at least 2-3 fresh arms available at all times
- Monitor your closer's stamina heading into save situations

:::detail title="Advanced: The drain-then-recover sequence"
Each subweek is processed in order: drain first, then recovery. If a player pitches in subweek A and rests in subweek B, their stamina drains after A and recovers after B.

This means a player who enters a subweek at 75 stamina, pitches (cost: 30), and then rests for one subweek ends up at: 75 - 30 + 5 = 50 stamina (assuming normal durability). It takes multiple rest subweeks to fully recharge.
:::
