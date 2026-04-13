---
title: Pitching Strategy
lastUpdated: 2026-04-12
---

## Pitching Gameplan Settings

Your pitching strategy controls when starters are pulled, how the bullpen is used, and the overall approach to the mound.

:::link
target: gameplan
label: Configure pitching strategy →
league: auto
:::

## Starter Management

### Pitch Count Limit

Sets the maximum pitches your starters throw before being pulled:

- **Low (80-90)** — protects the starter's stamina and arm, but uses more of the bullpen
- **Moderate (95-105)** — balanced approach
- **High (110-120)** — lets starters pitch deep, saves the bullpen but increases fatigue

:::callout type=tip
Early in the season, higher pitch counts are fine. As the season wears on and stamina degrades, consider lowering the limit to keep your starters healthy for the stretch run.
:::

### Quick Hook vs. Long Leash

Controls how quickly you pull a struggling starter:

- **Quick Hook** — pull the starter at the first sign of trouble (2-3 runs in an inning)
- **Normal** — standard management
- **Long Leash** — let the starter work through jams

## Bullpen Usage

### Closer Usage

- **Save situations only** — closer only enters with a lead of 3 or fewer in the 9th
- **High leverage** — closer can enter in the 8th in critical moments
- **Flexible** — closer available whenever the game is close in late innings

### Pitching Aggressiveness

Controls how your pitchers attack the strike zone:

:::compare
| | Setting | Approach | Best With |
|---|---|---|---|
| | Aggressive | Attack the zone, throw strikes | High-Stuff pitchers |
| | Balanced | Mix of strikes and balls | Most staffs |
| | Careful | Work the edges, nibble | High-Control pitchers |
:::

:::callout type=warning
Careful pitching with low-Control pitchers leads to walks. If your pitcher doesn't have the command to paint corners, he's better off being aggressive and trusting his stuff.
:::

## Matchup Considerations

The engine makes some automatic decisions based on matchups:

- Left-handed pitchers face left-handed hitters less effectively (and vice versa)
- Platoon advantages matter — the engine considers handedness when selecting relievers
- In high-leverage situations, the engine prioritizes your best available arm regardless of role

:::detail title="Advanced: Pitching strategy interactions"
Your pitching and offensive strategies interact. For example:

- An aggressive pitching approach paired with strong defense means more balls in play but more outs made
- A careful pitching approach works best when your offense can build leads, because walks are less dangerous with a cushion
- Quick hook + deep bullpen is a valid strategy that maximizes reliever specialization
:::
