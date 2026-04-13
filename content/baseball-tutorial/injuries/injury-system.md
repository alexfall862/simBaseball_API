---
title: The Injury System
lastUpdated: 2026-04-12
---

## How Injuries Work

Injuries are a reality of baseball. Players can get hurt during games, and the severity varies from minor day-to-day soreness to season-ending injuries.

## Injury Types

Injuries fall into several categories:

- **Minor** — day-to-day, miss 1-2 subweeks
- **Moderate** — 2-4 weeks on the [IL]{Injured List — where players go when they are too injured to play}
- **Serious** — 6-12 weeks, significant time missed
- **Severe** — season-ending or longer

:::callout type=info
The sim uses a malus (penalty) system for injuries. An injured player's attributes are reduced by a multiplier based on injury type and severity. Even after returning, a player may not be at 100% immediately.
:::

## What Causes Injuries

Injury probability is affected by:

- **Fatigue** — tired players are more injury-prone. Low stamina increases risk
- **Durability** — players with "Tires Easily" or low durability traits get hurt more often
- **Position** — pitchers are more injury-prone than position players
- **Workload** — overused pitchers face increasing injury risk
- **Age** — older players are more susceptible

:::callout type=warning
Pushing fatigued players is the #1 cause of preventable injuries. If a player's stamina is below 40, they're at significantly elevated injury risk. Rest them or accept the consequences.
:::

## Injury Effects

When a player is injured:

1. **They can't play** — removed from the active lineup for the injury duration
2. **Attribute penalty** — the injury reduces their effective ratings
3. **Recovery time** — varies by severity and the player's durability
4. **Reinjury risk** — some injuries increase the chance of future injuries to the same area

:::compare
| | Severity | Time Missed | Attribute Penalty | Reinjury Risk |
|---|---|---|---|---|
| | Minor | 1-2 subweeks | Small (-5%) | Low |
| | Moderate | 2-4 weeks | Moderate (-10-15%) | Low-Moderate |
| | Serious | 6-12 weeks | Significant (-20-30%) | Moderate |
| | Severe | Season+ | Major (-30-50%) | High |
:::

:::detail title="Advanced: Career injuries"
Some players develop chronic conditions after repeated injuries to the same area. A pitcher who tears their UCL twice may have a permanently reduced Velocity ceiling. Career injuries are rare but devastating — they permanently lower a player's potential ratings.

This is another reason to manage workload carefully, especially for young pitchers with high potential. Protecting your investment in development is worth leaving some wins on the table in the short term.
:::
