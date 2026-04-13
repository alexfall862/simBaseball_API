---
title: Contact vs. Power
lastUpdated: 2026-04-12
---

## The Tradeoff

Every hitter in the sim has both a [Contact]{How consistently a batter makes solid contact with the ball} rating and a [Power]{Raw power — determines how far the ball travels on contact} rating on the 20-80 scouting scale.

These two attributes are the primary drivers of offensive production, but they create a meaningful tradeoff when building your lineup.

:::callout type=tip
When building a lineup, you don't need all power or all contact. A balanced lineup with a mix of both is usually the most effective.
:::

## What Contact Does

Contact determines how often a batter puts the ball in play with a quality swing. High-contact hitters:

- Strike out less frequently
- Hit for higher batting average
- Produce more singles and doubles
- Are more reliable in hit-and-run situations

:::rating
attribute: Contact
scale: 20-80
example: 70
description: A 70-contact hitter will typically bat .290-.310 with a low strikeout rate.
:::

## What Power Does

Power determines exit velocity and launch angle ceiling. High-power hitters:

- Hit more home runs
- Hit more extra-base hits
- Have higher slugging percentage
- Strike out more often (the tradeoff)

:::rating
attribute: Power
scale: 20-80
example: 65
description: A 65-power hitter will produce 25-35 home runs in a full season.
:::

## Building Your Lineup Around This

:::compare
| | Power-First Build | Contact-First Build | Balanced Build |
|---|---|---|---|
| Team AVG | .240-.255 | .275-.295 | .260-.275 |
| Team HR | 200-240 | 100-140 | 150-190 |
| Team K Rate | High | Low | Medium |
| Run Scoring | Streaky, boom-or-bust | Consistent, manufactured | Moderate both |
| Best When | Pitching is strong | Need consistent runs | General purpose |
:::

:::detail title="Advanced: How the sim resolves the Contact vs. Power check"
When an at-bat occurs, the sim first checks Contact to determine if solid contact is made. If yes, Power determines the trajectory and distance. A high-contact, low-power hitter will make contact often but rarely drive the ball out of the park. A low-contact, high-power hitter will miss more often, but when they connect, the ball goes far.

The interaction is multiplicative — a player with 70 Contact and 70 Power is significantly more dangerous than one with 80/60 in the same attributes, because both checks need to succeed for a home run.
:::

:::league filter=College
In college baseball, player development is faster but careers are shorter. A freshman with 55 Contact may develop to 70 by their junior year, so recruiting for potential is critical.
:::

:::league filter=MLB
In MLB, veterans' Contact ratings tend to decline starting around age 32, while Power can remain stable into the mid-30s. This affects how you value aging free agents differently based on their profile.
:::

## Related

:::link
target: gameplan
label: Set your offensive strategy →
league: auto
:::
