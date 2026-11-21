# College Offseason UX Checklist (interface)

For the `simsn-interface-v2` team, college side. What the interface needs so college coaches can
follow their program through the offseason. Each item names the API it builds on. A shared,
tickable copy is published as an artifact ("College Offseason UX Checklist"). The pro list is
`OFFSEASON_UX_CHECKLIST.md`; shared foundations (offseason hub, live phase updates, right season
on stats pages, phone width and accessibility) live there and apply here too.

How a college offseason runs (API as of 2026-11-21):

1. Conference tournaments, then the 64-team NCAA tournament (16 four-team double-elimination regionals,
   8 best-of-three super regionals, two four-team College World Series brackets, best-of-three final).
2. End of season: players in the final year of their college contract leave school and enter the draft
   pool as seniors; high school seniors graduate, and committed recruits enroll as freshmen on 4-year
   contracts. Every college player is in the draft pool with his class year. Players age and develop.
3. Draft: MLB clubs may draft any college player. Underclassmen ask for more and refuse more often; a
   refusal returns him to school. When the draft completes: unsigned high school graduates walk on at
   random programs below 28 players (the rest retire), undrafted seniors stay in the free agent pool
   if rated 65+ (else retire), and programs below 25 get generated walk-ons.
4. Recruiting: 20 weeks, 100 points per week (at most 20 per player per week). Commits join when they
   finish high school at a season's end.
5. Training camp for college programs, then opening day.

## Program home

Where the coach starts. Shared foundations from the pro checklist (offseason hub, live phase updates, right season on stats pages, phone width and accessibility) apply here too.

- [ ] **College offseason hub** (`cp-01`). One place showing what affects the program right now: "NCAA tournament: Super regionals", "Draft in progress: 3 of your players drafted", "Recruiting week 6 of 20", with links to each page.
  - `GET /games/timestamp: Phase, IsDraftTime, IsRecruitingLocked`
  - `GET /recruiting/state?league_year_id= (status, current week, total_weeks)`
- [ ] **Offseason turnover summary** (`cp-02`). After the season ends and again after the draft: who left (seniors, signed draftees, retirements), who arrived (committed freshmen, walk-ons) and who came back (draftees who refused). Readable as one story.
  - `Transactions: college_enroll, walkon_enroll, retirement, draft_refused, draft signings`
  - `Roster before and after`
- [ ] **Recruiting only when it is open** (`cp-03`). Recruiting actions appear when the recruiting window is active and say when it opens otherwise. Points are spent per week, so show the week and whether this week's points are still unspent.
  - `Timestamp IsRecruitingLocked`
  - `GET /recruiting/state`
- [ ] **Take over a program** (`cp-04`). A clear flow for a user to request an unclaimed program, with the request's state (pending, approved, rejected) and why a program cannot be requested (already has a coach, not a college program).
  - `POST /college/requests/create {Username, OrgID}`
  - `GET /college/requests/all`
  - `Errors: org_claimed, wrong_league, org_not_found`

## Roster, class years and turnover

A college roster changes every offseason: seniors leave, the draft takes some underclassmen, freshmen and walk-ons arrive.

- [ ] **Class year and eligibility** (`cr-01`). Show Fr, So, Jr, Sr and a redshirt marker on every college player, with "Final year" on players who leave when the season ends. Until backend request 1 lands, derive it: contract year of total years, and redshirt when the contract is flagged as an extension.
  - `Roster: contract_years, contract_current_year, contract_isExtension (redshirt)`
- [ ] **Redshirt action** (`cr-02`). Redshirt a player from the roster, once per player, with a confirmation that says it adds a year of eligibility (his college contract gets one more year). Hide it for players already redshirted.
  - `POST /transactions/redshirt {contract_id, league_year_id}`
  - `400: already redshirted, contract finished`
- [ ] **Roster size against the targets** (`cr-03`). Show the roster count against the walk-on target (28) and the floor (25), and explain both: programs under 28 may receive walk-ons after the draft; programs under 25 get generated walk-ons.
  - `Roster count`
  - `league settings college_roster_target, college_roster_floor (see backend request 5)`
- [ ] **Next season's roster outlook** (`cr-04`). Current roster minus players in their final year, plus committed recruits who finish high school this season: expected size, open spots, and positions thinning out.
  - `Roster`
  - `GET /recruiting/commitments`
  - `GET /recruiting/board/{org}`
- [ ] **Walk-on arrivals** (`cr-05`). Mark players who joined as walk-ons, and explain that they were unsigned high school graduates placed at programs with room.
  - `Transaction type walkon_enroll`
- [ ] **Where seniors went** (`cr-06`). For last season's seniors: drafted and signed, in the free agent pool (rated 65 or better), or retired. Helps coaches see their program's pipeline.
  - `Draft picks`
  - `Free agent pool`
  - `Retirement reason college_undrafted (see pro checklist con-08)`

## The draft, from the program's side

MLB clubs negotiate with the player; the program only watches. Coaches still need to know who might leave and who came back.

- [ ] **Draft-eligible players on my roster** (`cd-01`). Every college player is in the draft pool. Show each one's class year and draft rank, and explain that underclassmen ask for more and often refuse, while seniors are leaving anyway.
  - `GET /draft/eligible: draft_rank, class_year, source = college`
- [ ] **My players in the draft, live** (`cd-02`). During the draft: which of the program's players were picked, by which club, and their signing status (negotiating, signed, refused and returned to school). Until backend request 2 lands, match the roster's player ids against the draft board.
  - `GET /draft/board`
  - `WebSocket draft_pick_made`
  - `draft_signing status: pending, signed, refused`
- [ ] **Returned to school** (`cd-03`). Draftees who refused stay on the roster on their college contract. Say so clearly on the roster and in the turnover summary.
  - `Transaction type draft_refused`

## Recruiting

Twenty weeks the admin advances by hand. Points are spent each week; commitments resolve at the end of each week.

- [ ] **Recruiting hub** (`rc-01`). Week X of 20, window status (pending, active, complete), points available this week (100) and already spent, and a reminder that the admin advances weeks.
  - `GET /recruiting/state?league_year_id=`
  - `GET /recruiting/investments/{org}`
- [ ] **Recruiting board** (`rc-02`). Add and remove recruits; per row: stars, rank, position, status label with its color, the program's interest gauge, competitor logos and the program's own points so far.
  - `GET /recruiting/board/{org}`
  - `POST /recruiting/board/add`
  - `POST /recruiting/board/remove`
  - `docs/recruiting_frontend_guide.md (status labels and colors)`
- [ ] **Weekly point allocation** (`rc-03`). Spread this week's points across the board with live totals; block more than 20 points on one player or more than 100 in a week before submit; show accepted rows and errors from the response.
  - `POST /recruiting/invest {org_id, league_year_id, week, investments[{player_id, points}]} → accepted, errors, budget_remaining`
- [ ] **Commitments and my class** (`rc-04`). A league-wide commitments feed, and the program's own class: committed recruits with stars and position, and when they arrive (at the end of the season in which they finish high school).
  - `GET /recruiting/commitments`
- [ ] **Recruit detail** (`rc-05`). One recruit's page: stars, ratings as the program has scouted them, status, interest gauge, competitors and the program's investment history.
  - `GET /recruiting/player/{player_id}`
  - `GET /api/v1/scouting/player/{player_id}?org_id=&league_year_id=`
- [ ] **Scouting recruits** (`rc-06`). Scouting actions for high school players inline on the board and detail page, with what each action reveals and costs.
  - `docs/scouting-recruiting-frontend-guide.md`
  - `docs/fog-of-war-frontend-guide.md`
- [ ] **Recruit to needs** (`rc-07`). Next to the board, the program's positions that are graduating against positions already committed, so coaches recruit to their real needs.
  - `Roster (final-year players)`
  - `GET /recruiting/commitments`
- [ ] **Week 20 explained** (`rc-08`). At week 20 every uncommitted recruit who has received points commits to the program that invested the most in him; recruits nobody invested in stay uncommitted. Warn coaches in the last weeks.
  - `GET /recruiting/state (current week)`

## Postseason

Conference tournaments and the NCAA tournament end the college season.

- [ ] **Conference tournaments** (`po-01`). Field and results for each conference tournament, and which champions earned automatic bids.
  - `GET /playoffs/conf-tournaments/field/{league_year_id}`
- [ ] **NCAA tournament bracket** (`po-02`). The 64-team bracket in its real shape: 16 four-team double-elimination regionals, 8 best-of-three super regionals, two four-team College World Series brackets and a best-of-three final. Show each team's losses and when it is eliminated.
  - `GET /playoffs/bracket/{league_year_id}/3`
  - `GET /playoffs/bracket-skeleton/{league_year_id}/3`
  - `cws_bracket rows: seed, losses, eliminated`
  - `docs/playoffs_api.md`

## Preseason

Camp and development before the next season.

- [ ] **Training camp for college players** (`pr-01`). College programs set one focus skill and an intensity per player. Point out that young players gain the most, and that four years of camp add up.
  - `docs/training_camp_frontend_guide.md`
  - `GET /training-camp/focus?org_id=`
- [ ] **Development after the season** (`pr-02`). Ratings change when the season ends, and young players change the most. Show the change without presenting the overall rating (a percentile) as a trend.

## Backend requests

Not available from the API yet. Raise these with the API team; the related interface items note where a workaround exists.

- [ ] **1. Class year and redshirt on roster rows** (`cg-01`). An explicit class_year (Fr, So, Jr, Sr) and redshirt flag on college roster rows, so the interface need not derive them (cr-01).
- [ ] **2. College program on draft entries** (`cg-02`). Draft board and eligible entries name the player's college program, or a per-program view of draft outcomes (cd-02).
- [ ] **3. Redshirt checks** (`cg-03`). The redshirt endpoint does not check that the contract is a college contract or that the caller holds it. Add both, and the club token, before exposing it to coaches (cr-02).
- [ ] **4. College notifications** (`cg-04`). Notifications for the program's events: a player drafted, signed or returned to school, a recruit committed to you or elsewhere, a walk-on placed.
- [ ] **5. Roster targets and recruiting limits in the API** (`cg-05`). Expose the college roster target and floor and the recruiting point limits (points per week, per player) so the interface does not hard-code them (cr-03, rc-03).
