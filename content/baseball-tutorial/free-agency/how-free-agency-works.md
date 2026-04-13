---
title: How Free Agency Works
lastUpdated: 2026-04-12
---

## The Three Phases

Free agency in the sim operates as a **3-phase auction system**. When a player becomes a [FA]{Free Agent — a player not under contract who can sign with any team}, all teams can compete to sign them.

### Phase 1: Open Bidding

All teams submit initial bids for the free agents they want. Bids include:

- **Total contract value** (years and salary)
- **Signing bonus** (optional, upfront payment)

The system collects all bids and moves to Phase 2.

### Phase 2: Negotiation

The player considers all bids. Factors in their decision:

- **Money** — total contract value is the biggest factor
- **Competitiveness** — players prefer winning teams
- **Role** — players want to play, not sit on the bench
- **Market** — demand drives up prices

Top free agents may counter-offer or request higher terms.

### Phase 3: Signing

Players sign with their preferred team. If no acceptable offers exist, they may re-enter the market at a lower asking price.

:::callout type=info
Not every free agent signs in the first round. If a player's demands are too high, they may go unsigned until they lower their asking price. Patience can save you money.
:::

## What Drives Free Agent Demands

Player demands are based on their [WAR]{Wins Above Replacement — how many wins a player adds compared to a replacement-level player} and market conditions:

- **High-WAR players** demand big multi-year deals
- **Average players** seek 1-2 year contracts at market rate
- **Declining veterans** may accept short, incentive-laden deals
- **Young free agents** command premiums for their remaining peak years

:::callout type=warning
Overpaying in free agency is one of the most common mistakes. A 4-year deal for a 32-year-old looks reasonable now, but years 3 and 4 are almost always bad value. Build through the draft and use free agency to fill specific holes.
:::

:::link
target: freeagency
label: Browse available free agents →
league: auto
:::

:::detail title="Advanced: WAR-based demand calculation"
The sim calculates each free agent's expected contract using a WAR-based formula:

- Base demand = recent WAR average x dollars-per-WAR market rate
- Age modifier: younger players get a premium, older players get a discount
- Position scarcity: premium positions (SS, C, SP) command more
- Market supply: fewer available free agents at a position = higher prices

Teams that understand this formula can identify bargains — players whose WAR suggests they're worth more than the market is paying.
:::
