---
title: Offensive Strategy
lastUpdated: 2026-04-12
---

## Your Offensive Gameplan

Your gameplan controls how your team approaches offense during simulated games. You set the strategy; the engine executes it.

:::link
target: gameplan
label: Go to your gameplan settings →
league: auto
:::

## Key Offensive Settings

### Steal Frequency

Controls how often your baserunners attempt stolen bases.

- **Conservative** — only the fastest runners steal in obvious situations
- **Moderate** — runners with good speed will attempt steals in favorable counts
- **Aggressive** — frequent steal attempts, even with moderate-speed runners

:::callout type=tip
Aggressive stealing only works if you have fast runners. If your team's average speed is below 50, keep it conservative — caught stealings kill rallies.
:::

### Bunt Tendency

Controls sacrifice bunt and bunt-for-hit frequency.

- **Rare** — only pitchers bunt (if applicable)
- **Normal** — situational bunts to advance runners in close games
- **Frequent** — bunts even in early innings to manufacture runs

### Hit-and-Run

Controls how often you call the hit-and-run play.

- Works best with high-contact hitters who can put the ball in play
- Risky with low-contact hitters — a swing and miss means a caught stealing
- Most effective with runners who have decent (not elite) speed

:::callout type=warning
The hit-and-run is high risk, high reward. It can advance runners and avoid double plays, but it backfires badly when the batter strikes out. Use it with your high-contact hitters, not your power guys.
:::

## Building Around Your Roster

Your offensive strategy should match your roster's strengths:

:::compare
| | Roster Type | Recommended Strategy |
|---|---|---|
| | Fast, high-contact | Aggressive steals, frequent bunts, hit-and-run |
| | Power-heavy, slow | Conservative steals, rare bunts, patient approach |
| | Balanced | Moderate everything, adjust per matchup |
| | Young/developing | Conservative — avoid high-risk plays while players develop |
:::

:::detail title="Advanced: How the engine processes offensive decisions"
Each base situation in a game, the engine evaluates whether to attempt a steal, bunt, or hit-and-run based on your settings and the specific players involved. Your strategy setting acts as a frequency modifier — "aggressive stealing" doesn't mean every runner steals every time, it means the engine's threshold for attempting a steal is lower.

The engine also considers game state: score, inning, outs, and count. Even with aggressive settings, it won't attempt a steal in a blowout or with two outs.
:::
