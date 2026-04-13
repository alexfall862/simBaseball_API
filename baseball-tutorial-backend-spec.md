# Baseball Tutorial System — Backend Spec

## Overview

The baseball tutorial is a **Progressive Disclosure Hub** — a mobile-first page where users browse categories, drill into topics, and read markdown-authored articles with interactive elements. Content is authored and stored on the backend and served to the frontend via API.

This is a **pilot system**. Once stable, other sports (football, basketball, hockey) will reuse the same API shape and frontend components with their own content.

---

## API Endpoints

### 1. `GET /api/baseball/tutorial`

Returns the full manifest: all categories and article metadata (but NOT article body content). The frontend uses this to render the hub page and search index.

**Response shape:**

```json
{
  "categories": [
    {
      "id": "hitting",
      "title": "Hitting",
      "icon": "bat",
      "description": "How batting works in the sim",
      "order": 1,
      "leagueFilter": null,
      "articles": [
        {
          "id": "contact-vs-power",
          "title": "Contact vs. Power",
          "summary": "Understanding the tradeoff between contact and power hitters",
          "order": 1,
          "tags": ["beginner", "hitting", "attributes"],
          "leagueFilter": null,
          "lastUpdated": "2026-04-10"
        },
        {
          "id": "plate-discipline",
          "title": "Plate Discipline",
          "summary": "How eye and discipline ratings affect at-bat outcomes",
          "order": 2,
          "tags": ["intermediate", "hitting", "attributes"],
          "leagueFilter": null,
          "lastUpdated": "2026-04-10"
        }
      ]
    },
    {
      "id": "recruiting",
      "title": "Recruiting",
      "icon": "megaphone",
      "description": "How to recruit players in college baseball",
      "order": 11,
      "leagueFilter": "College",
      "articles": []
    }
  ],
  "glossary": {
    "OBP": "On-Base Percentage — how often a batter reaches base safely",
    "WHIP": "Walks + Hits per Inning Pitched — a measure of pitcher efficiency",
    "OVR": "Overall rating — a weighted composite of key attributes for a player's position",
    "WAR": "Wins Above Replacement — how many wins a player adds compared to a replacement-level player",
    "ERA": "Earned Run Average — average earned runs allowed per 9 innings",
    "FIP": "Fielding Independent Pitching — evaluates pitcher skill independent of defense"
  }
}
```

**Field details:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | URL-safe slug, used in the article fetch endpoint |
| `title` | string | Display title |
| `icon` | string | Icon key the frontend maps to a component (see Icon Map below) |
| `description` | string | Short subtitle shown on the category card |
| `order` | number | Sort order (ascending) |
| `leagueFilter` | `"MLB"` \| `"College"` \| `null` | If set, category only appears for that league context. `null` = show for both |
| `articles[].summary` | string | One-line description for search results and article list |
| `articles[].tags` | string[] | Searchable tags. Used for filtering and search ranking |
| `articles[].leagueFilter` | same as above | Article-level league filtering |
| `articles[].lastUpdated` | string (ISO date) | Displayed as "Last updated Apr 10, 2026" |
| `glossary` | Record<string, string> | Term → definition map. Frontend uses this for inline tooltips |

### 2. `GET /api/baseball/tutorial/:categoryId/:articleId`

Returns the full content for a single article.

**Response shape:**

```json
{
  "id": "contact-vs-power",
  "categoryId": "hitting",
  "title": "Contact vs. Power",
  "markdown": "## The Tradeoff\n\nEvery hitter in the sim has both a [Contact]{...} rating and a [Power]{...} rating...\n\n:::rating\nattribute: Power\nscale: 20-80\nexample: 65\ndescription: A 65-power hitter will produce 25-35 home runs in a full season.\n:::\n\n...",
  "tags": ["beginner", "hitting", "attributes"],
  "relatedArticles": [
    { "categoryId": "hitting", "articleId": "plate-discipline", "title": "Plate Discipline" },
    { "categoryId": "roster", "articleId": "setting-your-lineup", "title": "Setting Your Lineup" }
  ],
  "lastUpdated": "2026-04-10"
}
```

### 3. `GET /api/baseball/tutorial/search?q=power+hitting`

Optional but recommended — server-side search across all article titles, summaries, tags, and body content.

**Response shape:**

```json
{
  "results": [
    {
      "categoryId": "hitting",
      "articleId": "contact-vs-power",
      "title": "Contact vs. Power",
      "summary": "Understanding the tradeoff between contact and power hitters",
      "matchSnippet": "...every hitter has both a **Contact** rating and a **Power** rating...",
      "score": 0.95
    }
  ]
}
```

If server-side search is too much work initially, the frontend can do client-side search using the manifest data. But server-side search will scale better and allows searching within article body content without loading every article.

---

## Content Authoring (Backend File Structure)

Content lives in the backend repo as markdown files organized by category:

```
/content/baseball-tutorial/
├── manifest.json              ← category order, metadata, glossary
├── getting-started/
│   ├── welcome.md
│   ├── first-season.md
│   └── understanding-timeline.md
├── hitting/
│   ├── contact-vs-power.md
│   ├── plate-discipline.md
│   ├── how-at-bats-resolve.md
│   └── clutch-hitting.md
├── pitching/
│   ├── pitch-types.md
│   ├── stamina-and-fatigue.md
│   ├── bullpen-management.md
│   └── starting-rotation.md
├── fielding/
│   └── ...
├── roster/
│   └── ...
├── gameplan/
│   └── ...
├── free-agency/
│   └── ...
├── trades/
│   └── ...
├── draft/
│   └── ...
├── recruiting/              ← College only
│   └── ...
├── financials/
│   └── ...
├── season/
│   └── ...
├── injuries/
│   └── ...
├── playoffs/
│   └── ...
└── international-fa/        ← MLB only
    └── ...
```

### manifest.json

The manifest defines category metadata and the glossary. It does NOT contain article content — that lives in the `.md` files. The API reads the manifest for structure and the `.md` files for content.

```json
{
  "categories": [
    {
      "id": "getting-started",
      "title": "Getting Started",
      "icon": "compass",
      "description": "New to the sim? Start here",
      "order": 1,
      "leagueFilter": null,
      "articles": [
        {
          "id": "welcome",
          "file": "getting-started/welcome.md",
          "title": "Welcome to the Sim",
          "summary": "A quick overview of what this baseball simulation is all about",
          "order": 1,
          "tags": ["beginner"],
          "leagueFilter": null,
          "relatedArticles": ["hitting/contact-vs-power", "roster/setting-your-lineup"]
        }
      ]
    }
  ],
  "glossary": {
    "OBP": "On-Base Percentage — how often a batter reaches base safely",
    "WHIP": "Walks + Hits per Inning Pitched",
    "OVR": "Overall rating — weighted composite of key position attributes",
    "ERA": "Earned Run Average — earned runs per 9 innings",
    "FIP": "Fielding Independent Pitching — pitcher skill independent of defense"
  }
}
```

### Article Markdown Format

Each `.md` file is a standard markdown file with optional frontmatter and special block syntax. Here is a complete example:

```markdown
---
title: Contact vs. Power
lastUpdated: 2026-04-10
---

## The Tradeoff

Every hitter in the sim has both a [Contact]{How consistently a batter makes solid contact with the ball} rating and a [Power]{Raw power — determines how far the ball travels on contact} rating on the 20-80 scouting scale.

These two attributes are the primary drivers of offensive production, but they create a meaningful tradeoff when building your lineup.

:::callout type=tip
When building a lineup, you don't need all power or all contact.
A balanced lineup with a mix of both is usually the most effective.
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
When an at-bat occurs, the sim first checks Contact to determine if solid
contact is made. If yes, Power determines the trajectory and distance.
A high-contact, low-power hitter will make contact often but rarely drive
the ball out of the park. A low-contact, high-power hitter will miss more
often, but when they connect, the ball goes far.

The interaction is multiplicative — a player with 70 Contact and 70 Power
is significantly more dangerous than one with 80/60 in the same attributes,
because both checks need to succeed for a home run.
:::

:::league filter=College
In college baseball, player development is faster but careers are shorter.
A freshman with 55 Contact may develop to 70 by their junior year, so
recruiting for potential is critical.
:::

:::league filter=MLB
In MLB, veterans' Contact ratings tend to decline starting around age 32,
while Power can remain stable into the mid-30s. This affects how you
value aging free agents differently based on their profile.
:::

## Related

:::link
target: gameplan
label: Set your offensive strategy →
league: auto
:::
```

---

## Special Block Syntax Reference

The backend serves raw markdown. The frontend parses and renders these special blocks. The backend team just needs to know the syntax to author content correctly.

### 1. Glossary Tooltip — `[term]{definition}`

**Syntax:** `[TERM]{Definition text shown in tooltip}`

**What it does:** The frontend renders TERM as a tappable/hoverable word. On interaction, a tooltip shows the definition.

**Example:**
```markdown
A pitcher's [FIP]{Fielding Independent Pitching — measures pitcher skill independent of defense} is more predictive than ERA.
```

**Notes:**
- Terms also defined in `manifest.json`'s glossary section will be auto-linked even without explicit `[term]{...}` syntax — the frontend scans for known glossary terms in article text.
- Explicit inline definitions override the glossary.

### 2. Rating Visualizer — `:::rating`

**Syntax:**
```markdown
:::rating
attribute: <attribute name>
scale: <min>-<max>
example: <number>
description: <explanation>
:::
```

**What it does:** Renders a visual horizontal scale showing where the example value falls. Color-coded (red for low, blue for high).

**Fields:**
| Field | Required | Description |
|-------|----------|-------------|
| `attribute` | Yes | The name of the attribute being shown |
| `scale` | Yes | Format: `min-max` (usually `20-80` for scouting scale, `0-100` for percentages) |
| `example` | Yes | A specific value to highlight on the scale |
| `description` | Yes | Plain text explanation of what this example value means |

### 3. Callout Block — `:::callout`

**Syntax:**
```markdown
:::callout type=<type>
Content here. Supports **markdown** formatting inside.
:::
```

**Types:**
| Type | Use for | Visual |
|------|---------|--------|
| `tip` | Helpful advice, strategy suggestions | Green accent, lightbulb icon |
| `info` | Neutral informational notes | Blue accent, info icon |
| `warning` | Common mistakes, things to watch out for | Yellow/amber accent, warning icon |
| `important` | Critical mechanics, rules | Red accent, exclamation icon |

### 4. Comparison Table — `:::compare`

**Syntax:**
```markdown
:::compare
| | Column A | Column B |
|---|---|---|
| Row Label | Value | Value |
:::
```

**What it does:** Renders a comparison that's responsive on mobile. On wide screens, shows as a table. On narrow screens, stacks into comparison cards.

**Notes:**
- First column is always the row label
- First row is column headers
- Keep to 2-4 comparison columns for readability
- Supports markdown formatting in cells

### 5. Sim Link — `:::link`

**Syntax:**
```markdown
:::link
target: <route key>
label: <button text>
league: <MLB|College|auto>
:::
```

**What it does:** Renders a tappable button/card that navigates to a page in the sim.

**Route targets available:**
| Target key | Navigates to |
|------------|-------------|
| `team` | Team roster page |
| `gameplan` | Gameplan settings |
| `financials` | Financials page |
| `freeagency` | Free agency page |
| `trades` | Trades page |
| `schedule` | Schedule page |
| `recruiting` | Recruiting page (College only) |
| `draft` | Draft room |
| `stats` | Statistics page |
| `ifa` | International FA (MLB only) |

When `league: auto`, the frontend determines the correct league based on the user's current context.

### 6. Collapsible Detail — `:::detail`

**Syntax:**
```markdown
:::detail title="Section title"
Hidden content here, shown when expanded.
Supports full **markdown** formatting.
:::
```

**What it does:** Renders a collapsible section within an article. Starts collapsed. The user taps to expand.

**Use for:** Advanced mechanics, edge cases, or deep dives that would clutter the main explanation.

### 7. Player Card Example — `:::player-example`

**Syntax:**
```markdown
:::player-example
position: <position code>
attributes:
  <attr1>: <value>
  <attr2>: <value>
  ...
caption: "<explanation text>"
:::
```

**What it does:** Renders a mock player card using the sim's actual player card component. Shows a realistic example with the specified attribute values filled in.

**Position codes:** `SP`, `RP`, `C`, `1B`, `2B`, `3B`, `SS`, `LF`, `CF`, `RF`, `DH`

**Available attributes:**
- **Hitters:** `contact`, `power`, `eye`, `speed`, `fielding`, `arm`, `defense`, `overall`, `potential`
- **Pitchers:** `stuff`, `control`, `stamina`, `velocity`, `movement`, `overall`, `potential`

**Example:**
```markdown
:::player-example
position: SP
attributes:
  stuff: 72
  control: 55
  stamina: 60
  velocity: 68
caption: "This is an ace-caliber starter — elite stuff, but the average control means he'll have occasional wild games."
:::
```

### 8. League Filter — `:::league`

**Syntax:**
```markdown
:::league filter=<MLB|College>
Content only shown for this league context.
:::
```

**What it does:** Content is conditionally rendered based on whether the user accessed the tutorial from an MLB or College Baseball context. Allows a single article to serve both audiences with relevant details.

**Notes:**
- Content outside any `:::league` block is always shown.
- You can have multiple `:::league` blocks in one article.
- If the user has no league context (e.g., accessed via direct URL), both blocks are shown with labels.

---

## Icon Map

The backend sends icon keys as strings. The frontend maps them to components.

| Icon key | Meaning |
|----------|---------|
| `compass` | Getting Started |
| `chart` | Player Attributes / Statistics |
| `bat` | Hitting |
| `target` | Pitching |
| `glove` | Fielding & Defense |
| `clipboard` | Roster Management |
| `brain` | Gameplan & Strategy |
| `handshake` | Free Agency |
| `arrows` | Trades |
| `podium` | The Draft |
| `megaphone` | Recruiting |
| `bank` | Financials |
| `calendar` | Season & Schedule |
| `bandage` | Injuries |
| `trophy` | Playoffs & Postseason |
| `globe` | International FA |

---

## Adding New Content (Workflow)

### Adding a new article to an existing category:

1. Create a new `.md` file in the category folder (e.g., `hitting/new-article.md`)
2. Add frontmatter with `title` and `lastUpdated`
3. Write your content using standard markdown and the special blocks above
4. Add the article entry to `manifest.json` under the correct category
5. Set the `order`, `tags`, and optional `relatedArticles`
6. Deploy — the frontend picks it up automatically

### Adding a new category:

1. Create a new folder under `/content/baseball-tutorial/`
2. Add the category entry to `manifest.json` with an `id`, `title`, `icon`, `description`, and `order`
3. Add `.md` files for articles
4. Deploy — the frontend renders the new category card automatically

### Updating existing content:

1. Edit the `.md` file
2. Update the `lastUpdated` field in the frontmatter (and in `manifest.json` if present)
3. Deploy

### Removing content:

1. Remove the article entry from `manifest.json`
2. Optionally delete the `.md` file
3. Deploy

---

## Caching Recommendations

- **Manifest endpoint** (`GET /api/baseball/tutorial`): Cache for 5-10 minutes. This is loaded on every tutorial page visit.
- **Article endpoint** (`GET /api/baseball/tutorial/:cat/:article`): Cache for 15-30 minutes. Loaded on demand when user opens an article.
- **Search endpoint**: No cache (queries vary).
- Frontend will also cache the manifest in React state for the session duration.

---

## Future Extensibility

This system is designed to be copied for other sports. When football is ready:

1. Create `/content/football-tutorial/` with the same structure
2. Add `GET /api/football/tutorial` and `GET /api/football/tutorial/:cat/:article` endpoints
3. The frontend tutorial components are sport-agnostic — they just need a different API base URL

The frontend React components, markdown renderer, and special block parsers are **shared** — only the content and API URL change per sport.
