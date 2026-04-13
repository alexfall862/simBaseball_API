---
title: Bullpen Management
lastUpdated: 2026-04-12
---

## Bullpen Roles

Your bullpen is organized into roles that determine when each reliever enters the game:

- **Closer** — pitches the 9th inning in save situations
- **Setup** — pitches the 7th-8th innings to bridge to the closer
- **Middle Relief** — available for the 4th-6th innings
- **Long Relief** — can pitch multiple innings if the starter exits early
- **Mop-Up** — pitches in blowout losses to save better arms

:::callout type=tip
Your closer and setup men should be your best relievers by [Stuff]{A pitcher's overall pitch quality}. Long relievers should have good [Stamina]{How many pitches a pitcher can throw before tiring} since they may pitch 3+ innings.
:::

## How the Sim Uses Your Bullpen

The engine follows your gameplan settings when deciding bullpen usage:

1. **Starter hook** — your pitch count / performance trigger for pulling the starter
2. **Role matching** — the engine selects the reliever whose role matches the game situation
3. **Stamina check** — the engine won't use a reliever below the configured usage threshold
4. **Fallback** — if the primary option is unavailable, the engine goes to the next best available arm

:::callout type=warning
If your bullpen is overworked and multiple relievers are below the stamina threshold, the engine may be forced to use suboptimal options. This is how bullpen meltdowns happen — it usually means you've been using your best arms too aggressively.
:::

## Bullpen Strategy Tips

1. **Don't overuse your closer** — save situations only, not every close game
2. **Rotate middle relievers** — spread the workload to keep arms fresh
3. **Carry enough arms** — 7-8 relievers gives you enough depth for a full week
4. **Match roles to skills** — high-Stuff, low-Stamina pitchers are ideal closers; high-Stamina pitchers make better long relievers

:::link
target: gameplan
label: Configure your bullpen settings →
league: auto
:::

:::detail title="Advanced: Bullpen optimization"
The most effective bullpen strategies focus on keeping your best arms available for high-leverage situations. Consider:

- Setting higher usage thresholds for your closer and setup men so they're always fresh for important moments
- Using mop-up relievers aggressively in blowouts to preserve your key arms
- Having one swing man who can start or relieve in case of doubleheaders or extra-inning games
:::
