# Tutorial Content Authoring Guide

This guide is for the backend editor UI. It documents every formatting option available when writing tutorial articles, what each one looks like on the frontend, and the exact syntax required. Use this to build preview rendering, toolbar buttons, or insertion templates in the editor.

---

## Standard Markdown

The renderer supports a subset of standard markdown. These work anywhere in article body text.

### Headings

```markdown
## Section Title
### Subsection
#### Small Heading
```

Renders as styled section headers with appropriate sizing and spacing. Use `##` for major sections within an article, `###` for subsections. Avoid `#` (reserved for the article title which is rendered automatically from metadata).

### Bold & Italic

```markdown
This has **bold text** and *italic text* in it.
```

### Inline Code

```markdown
The `stamina` attribute controls pitcher endurance.
```

Renders with a subtle background highlight — good for attribute names, stat abbreviations, or specific values.

### Links

```markdown
Check the [official rules](https://example.com/rules) for details.
```

Opens in a new tab. Only use for external URLs — for linking to other sim pages, use the `:::link` block instead.

### Unordered Lists

```markdown
- High contact rating
- Low strikeout rate
- Better batting average
```

### Ordered Lists

```markdown
1. Set your starting rotation
2. Configure bullpen roles
3. Set pitch count limits
```

### Paragraphs

Plain text separated by blank lines renders as paragraphs with comfortable spacing and readable line height.

---

## Interactive Blocks

These are custom components that render as interactive, styled UI elements on the frontend. Each uses a fenced `:::` syntax. The block starts with `:::blockname` and ends with `:::` on its own line.

**Important rules:**
- The opening `:::` and closing `:::` must each be on their own line
- Blocks cannot be nested inside each other
- Standard markdown (bold, italic, lists) works inside most block content areas
- Blank lines inside blocks are fine

---

### Glossary Tooltip

**What it does:** Renders a term as a tappable word with a dotted underline. When tapped, a tooltip appears with the definition.

**Syntax:**
```markdown
A pitcher's [FIP]{Fielding Independent Pitching — measures pitcher skill independent of defense} is more predictive than ERA.
```

**Format:** `[TERM]{DEFINITION}`

**When to use:** Any time you reference a sim-specific term, stat abbreviation, or concept that a new user might not know. Use generously — these are non-intrusive and only show the tooltip on interaction.

**Notes:**
- Terms defined in the glossary section of the manifest are also auto-linked throughout all articles — if a word in the body text matches a glossary entry, it automatically becomes tappable without explicit `[term]{def}` syntax.
- Explicit inline definitions override the glossary definition for that specific usage.
- Good for contextual definitions that differ from the generic glossary entry.

**Frontend preview:** The term appears as blue text with a dotted underline. Tapping it shows a dark tooltip with the term name and definition.

---

### Rating Visualizer

**What it does:** Renders a horizontal scale bar showing where a specific value falls on a numeric range. Color-coded from red (low) to blue (high).

**Syntax:**
```markdown
:::rating
attribute: Power
scale: 20-80
example: 65
description: A 65-power hitter will produce 25-35 home runs in a full season.
:::
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `attribute` | Yes | The name displayed above the bar (e.g., "Power", "Contact", "Stuff") |
| `scale` | Yes | Format: `min-max`. Usually `20-80` for scouting scale or `0-100` for percentages |
| `example` | Yes | The specific value to highlight on the bar |
| `description` | Yes | Explanation text below the bar — what this example value means in practice |

**When to use:** Any time you're explaining what a specific attribute value means. Turns abstract numbers into something visual.

**Frontend preview:** A rounded card containing the attribute name, a colored pill showing the value, a gradient progress bar, min/max labels, and description text below.

**Example variations:**
```markdown
:::rating
attribute: Contact
scale: 20-80
example: 70
description: A 70-contact hitter will typically bat .290-.310 with a low strikeout rate.
:::

:::rating
attribute: Stamina
scale: 0-100
example: 40
description: A 40-stamina pitcher can only go 4-5 innings before fatigue sets in.
:::
```

---

### Callout Block

**What it does:** Renders a colored callout box with an icon and label. Used for tips, warnings, important notes, and informational asides.

**Syntax:**
```markdown
:::callout type=tip
High-eye batters paired with a patient gameplan strategy will draw
significantly more walks, improving your team's OBP.
:::
```

**Types:**

| Type | Icon | Color | Use for |
|------|------|-------|---------|
| `tip` | Lightbulb | Green | Strategy advice, helpful suggestions, "pro tips" |
| `info` | Info circle | Blue | Neutral information, clarifications, context |
| `warning` | Warning triangle | Amber/Yellow | Common mistakes, things to watch out for, gotchas |
| `important` | Exclamation | Red | Critical rules, mechanics that are easy to misunderstand |

**When to use:** To break up prose and draw attention to a specific piece of advice or information. Every article should have at least one callout. They make articles feel less like a wall of text.

**Notes:**
- Standard markdown works inside callouts (bold, italic, lists, inline code)
- Keep callouts to 1-3 sentences for maximum impact
- Don't put multiple callouts back-to-back — separate them with regular prose

**Frontend preview:** A rounded box with a colored left border, icon + label at top ("Tip", "Warning", etc.), and the content text below.

**Example variations:**
```markdown
:::callout type=warning
Don't invest all your cap space in one star pitcher. If they get injured,
your season is effectively over. Depth wins championships.
:::

:::callout type=important
Players on the IL do NOT count against the active roster limit,
but they DO count against the 40-man roster.
:::

:::callout type=info
Revenue sharing distributes a portion of high-revenue teams' income
to smaller-market teams, helping maintain competitive balance.
:::
```

---

### Comparison Table

**What it does:** Renders a responsive comparison table. On desktop it shows as a standard table; on mobile it automatically stacks into vertical comparison cards so it remains readable without horizontal scrolling.

**Syntax:**
```markdown
:::compare
| | Power Hitter | Contact Hitter | Balanced |
|---|---|---|---|
| AVG | .240-.265 | .280-.310 | .260-.280 |
| HR/Season | 25-40 | 5-15 | 15-25 |
| K Rate | High | Low | Medium |
| Best For | Middle lineup | Top lineup | Flexible |
:::
```

**Format:** Standard markdown table syntax inside the `:::compare` block.

**Rules:**
- First row = column headers (the things being compared)
- First column in each row = the row label (the metric being compared)
- The first cell of the header row (top-left) is typically empty
- Keep to 2-4 comparison columns — more than that gets cramped
- Cell content is plain text (no markdown formatting inside cells)

**When to use:** Any time you're explaining a tradeoff, comparing strategies, or showing side-by-side options. Much more effective than writing "Option A does X while Option B does Y" in prose.

**Frontend preview:** Desktop — clean table with header row and alternating styling. Mobile — each comparison column becomes its own card showing all metrics vertically.

---

### Sim Link

**What it does:** Renders a styled button that navigates the user directly to a page in the simulation app. Connects the tutorial to the actual UI.

**Syntax:**
```markdown
:::link
target: gameplan
label: Set up your gameplan →
league: auto
:::
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `target` | Yes | Which sim page to link to (see target list below) |
| `label` | Yes | Button text shown to the user |
| `league` | Yes | `MLB`, `College`, or `auto` (auto detects from user context) |

**Available targets:**

| Target | Navigates to |
|--------|-------------|
| `team` | Team roster page |
| `gameplan` | Gameplan settings |
| `financials` | Financials / budget page |
| `freeagency` | Free agency page |
| `trades` | Trade portal |
| `schedule` | Season schedule |
| `recruiting` | Recruiting page (College only) |
| `draft` | Draft room |
| `stats` | Statistics page |
| `ifa` | International FA (MLB only) |

**When to use:** At natural transition points — when you've explained a concept and the user should go try it. "Now that you understand how lineups work, go set yours up." Use `league: auto` unless the link is specifically for one league.

**Frontend preview:** A full-width rounded button with blue accent, the label text, and a right-arrow icon. Tapping it navigates to the target page.

---

### Collapsible Detail

**What it does:** Renders a collapsible section that starts closed. The user taps to expand and see the hidden content. Used for advanced information that would clutter the main article flow.

**Syntax:**
```markdown
:::detail title="How is OVR calculated?"
Overall is a weighted composite of a player's key attributes for their
position. For example, a pitcher's OVR weights Stuff and Control more
heavily than Fielding.

The weights are:
- **Pitchers:** Stuff (35%), Control (30%), Stamina (20%), Fielding (15%)
- **Hitters:** Contact (25%), Power (25%), Eye (20%), Speed (15%), Fielding (15%)
:::
```

**Fields:**
- `title` — The text shown on the collapsed header (in quotes)

**When to use:**
- Advanced mechanics that only some users will care about
- Detailed calculations or formulas
- Edge cases and exceptions to general rules
- "How does this actually work under the hood?" explanations

**Notes:**
- Standard markdown works inside (bold, italic, lists)
- Keep the title as a question or descriptive phrase — it should make the user want to click
- Don't hide critical information in detail blocks — the main explanation should stand on its own without expanding

**Frontend preview:** A rounded bordered box with the title and a chevron icon. Clicking toggles the content area open/closed with a rotation animation on the chevron.

---

### Player Card Example

**What it does:** Renders a mock player card showing specific attribute values, mimicking the look of an actual player card in the sim. Makes abstract rating numbers concrete by showing them in context.

**Syntax:**
```markdown
:::player-example
position: SP
attributes:
  stuff: 72
  control: 55
  stamina: 60
  velocity: 68
caption: "An ace-caliber starter — elite stuff, but the average control means he'll have occasional wild games."
:::
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `position` | Yes | Position code (see list below) |
| `attributes` | Yes | Indented key-value pairs, one per line (see attribute list below) |
| `caption` | No | Quoted explanation text shown below the card |

**Position codes:** `SP`, `RP`, `C`, `1B`, `2B`, `3B`, `SS`, `LF`, `CF`, `RF`, `DH`

**Hitter attributes:** `contact`, `power`, `eye`, `speed`, `fielding`, `arm`, `defense`, `overall`, `potential`

**Pitcher attributes:** `stuff`, `control`, `stamina`, `velocity`, `movement`, `overall`, `potential`

**Important:** The `attributes:` line must be followed by indented lines (2 spaces) with `key: value` pairs. Values must be integers.

**When to use:** When explaining what attribute combinations mean in practice. "A 70-power hitter" is abstract; showing a mock card with all the surrounding attributes makes it real.

**Notes:**
- You don't need to include every attribute — just the ones relevant to the point you're making
- The caption should explain what makes this example notable
- Attribute values are color-coded (red for low, green for good, blue for elite)

**Frontend preview:** A bordered card with a position badge, a grid of attribute names and color-coded values, and a caption section at the bottom.

**Example variations:**
```markdown
:::player-example
position: CF
attributes:
  contact: 65
  power: 45
  eye: 70
  speed: 75
  fielding: 70
caption: "A prototypical leadoff hitter — elite speed and plate discipline, gap power but not a home run threat."
:::

:::player-example
position: RP
attributes:
  stuff: 75
  control: 70
  stamina: 30
  velocity: 72
caption: "An elite closer. The low stamina doesn't matter — he only needs to get 3 outs."
:::
```

---

### League Filter

**What it does:** Conditionally shows content based on whether the user is viewing from an MLB or College Baseball context. Allows a single article to serve both audiences with league-specific details.

**Syntax:**
```markdown
:::league filter=MLB
In MLB, the luxury tax kicks in at $230M in total payroll. Teams over
this threshold pay escalating penalties.
:::

:::league filter=College
College baseball does not have a salary system. Instead, you manage
scholarship allocations across your roster.
:::
```

**Fields:**
- `filter` — Either `MLB` or `College`

**When to use:** When an article covers a topic that exists in both leagues but works differently (e.g., roster management, player acquisition). Use league blocks for the differences and keep the shared explanation outside any block.

**Rules:**
- Content outside any `:::league` block is always shown to everyone
- If the user has no league context (e.g., direct URL), both league blocks are shown with labels
- You can have multiple `:::league` blocks in one article — they don't need to be adjacent
- Standard markdown works inside league blocks

**Frontend preview:** A bordered section with a dashed border and a small league label ("MLB" or "College") at the top.

**Pattern for mixed articles:**
```markdown
## Roster Limits

Every team has a limit on how many players can be on the active roster.

:::league filter=MLB
In MLB, you manage a 26-man active roster and a 40-man extended roster.
Players not on the 40-man can be in the minor league system.
:::

:::league filter=College
In college baseball, roster size is limited by scholarship allocations.
You have a fixed number of scholarships to distribute across your roster.
:::

The key to roster management in either league is maintaining depth
at every position.
```

---

## Editor Integration Suggestions

### Toolbar Buttons

Each block type should have a toolbar button that inserts a template:

| Button Label | Inserts |
|-------------|---------|
| Glossary Term | `[term]{definition}` with cursor on "term" |
| Rating Scale | Full `:::rating` block with placeholder values |
| Tip | `:::callout type=tip` block |
| Info | `:::callout type=info` block |
| Warning | `:::callout type=warning` block |
| Important | `:::callout type=important` block |
| Comparison | `:::compare` block with a 2-column table template |
| Sim Link | `:::link` block with placeholder target |
| Expandable Detail | `:::detail title=""` block with cursor in title |
| Player Card | `:::player-example` block with common attributes |
| MLB Only | `:::league filter=MLB` block |
| College Only | `:::league filter=College` block |

### Preview Rendering

For a live preview pane, the backend editor should:

1. **Split** the markdown at `:::` boundaries to identify blocks
2. **Render standard markdown** sections as formatted HTML
3. **Render custom blocks** as styled HTML approximations:
   - Rating → colored progress bar
   - Callout → colored box with left border
   - Compare → HTML table
   - Link → styled button (non-functional in preview, just visual)
   - Detail → collapsible `<details>` element
   - Player Example → simple attribute grid
   - League → bordered section with label
   - Glossary `[term]{def}` → underlined text with title attribute for hover

### Validation Rules

The editor should validate:

- Every `:::blockname` has a matching closing `:::`
- `:::rating` blocks have all 4 required fields (attribute, scale, example, description)
- `:::callout` has a valid type (tip, info, warning, important)
- `:::compare` content starts with a valid markdown table
- `:::link` has target, label, and league fields
- `:::detail` has a title attribute in quotes
- `:::player-example` has position and at least one attribute
- `:::league` has a valid filter (MLB or College)
- `[term]{definition}` brackets are properly matched

### Insertion Templates

These are the exact strings to insert when a toolbar button is clicked:

**Rating:**
```
:::rating
attribute: 
scale: 20-80
example: 50
description: 
:::
```

**Tip Callout:**
```
:::callout type=tip

:::
```

**Comparison:**
```
:::compare
| | Option A | Option B |
|---|---|---|
| Metric | Value | Value |
:::
```

**Sim Link:**
```
:::link
target: team
label: Go to your team →
league: auto
:::
```

**Detail:**
```
:::detail title=""

:::
```

**Player Card (Hitter):**
```
:::player-example
position: CF
attributes:
  contact: 50
  power: 50
  eye: 50
  speed: 50
  fielding: 50
caption: ""
:::
```

**Player Card (Pitcher):**
```
:::player-example
position: SP
attributes:
  stuff: 50
  control: 50
  stamina: 50
  velocity: 50
caption: ""
:::
```

**League Filter:**
```
:::league filter=MLB

:::

:::league filter=College

:::
```
