# Offline Draft Ranking Design Record

Status: implemented through PR #11 and PR #12 on `george-bucky/main`. The imperative and
future-tense sections below preserve the historical implementation specification; they are not
instructions or standing authorization for future agents.

## Outcome

Provide a fast draft recommendation without Yahoo authentication. The board is prepared before the
draft, and each live call only applies the latest screenshot-derived drafted players, our roster,
and current pick.

## League profile

- 12 teams, snake draft, slot 11
- Half-PPR
- QB, 2 RB, 2 WR, TE, 2 W/R/T, DEF, 5 bench; no kicker
- Four-point passing touchdowns, minus-two interceptions
- One point for a 40-plus-yard passing touchdown
- Standard rushing/receiving yardage and touchdown scoring
- One-, two-, and three-point rushing/receiving milestone bonuses at 100, 150, and 200 yards
- Six-team playoff; 14 draft rounds

## Evidence contract

### Prepared base board

1. **League-adjusted projection value (recommended 55%)**
   - Read ESPN's raw season stat projections rather than its precomputed fantasy total.
   - Recalculate fantasy points under the league profile.
   - Estimate unsupported milestone counts from recent nflverse weekly game distributions, with a
     position-level fallback for players without sufficient history.
   - Convert total points to value above a replacement baseline derived from this league's mandatory
     starters and two FLEX slots.
2. **Expert consensus (recommended 25%)**
   - Use the current DynastyProcess/nflverse redraft ECR snapshot.
   - Preserve consensus standard deviation, best/worst rank, movement, and snapshot date.
3. **Draft market (recommended 15%)**
   - Use Fantasy Football Calculator's 12-team half-PPR ADP.
   - Preserve draft count, high/low pick, standard deviation, and observation window.
4. **Structured availability confidence (recommended 5%)**
   - Use ESPN and Sleeper active/injury/depth-chart fields.
   - Quarantine inactive or identity-ambiguous players rather than guessing.

Every component is normalized by position and reported separately. Missing evidence reweights only
the available comparable components and produces a warning; it never becomes a zero score.

### Pick-specific adjustment

- Remove every player listed in the screenshot-derived drafted-player set.
- Apply our actual roster requirements and starter/FLEX capacity.
- Measure the tier drop after each candidate.
- Use ADP distribution to estimate whether a player survives to picks 14, 35, and later snake turns.
- Favor the best expected roster value now versus the best likely combination at the next turn.
- Avoid early DEF and unnecessary backup QB/TE through explicit roster-construction rules.

### News and sportsbook evidence

- Structured injury/availability status may change the confidence component.
- ESPN and RotoWire headlines remain attributed review evidence unless they report an explicit,
  corroborated availability change.
- PropLine season odds may provide a small, capped tiebreak only between players covered by the same
  market and comparable bookmakers.
- Next-game props remain separate Week 1 context and cannot act as season projections.
- Missing odds never penalize a player. Team futures never become an individual player projection.
- Recommended total news/odds effect: at most three points on a 100-point score, with the exact
  adjustment and evidence shown.

## Data lifecycle and latency

- Refresh projections, ECR, ADP, identities, news, and season odds before the draft.
- Save a last-known-good local snapshot with source timestamps and checksums.
- Refresh slow-moving sources outside the one-minute pick clock.
- A live recommendation performs no required network calls.
- Warm target: one to three seconds; hard deadline: five seconds.
- When a snapshot is stale or a provider is down, return the recommendation with age and warnings.

## MCP surface

### `ff_prepare_manual_draft`

Accepts a league profile and refresh preference. Fetches, validates, joins, scores, and stores the
prepared board. Returns source freshness, coverage, unsupported scoring fields, and readiness.

### `ff_get_manual_draft_recommendation`

Accepts the league profile identifier, current overall pick, full drafted-player list, and our
roster. Returns the top target, alternatives, tier/position strategy, survival-to-next-pick
estimate, score breakdown, evidence, warnings, and snapshot age.

The caller sends the complete drafted-player state each time. This avoids hidden session drift when
a screenshot is missed or the MCP process restarts.

## PR graph

### PR 1: Prepared offline value board

Outcome: produce a source-attributed, league-adjusted board without Yahoo.

Scope:

- Bounded clients and caches for ESPN projections, DynastyProcess ECR, Fantasy Football Calculator
  ADP, and Sleeper identity/status data.
- Exact player identity joins with ambiguity quarantine.
- League scoring, FLEX-aware replacement value, normalization, and score breakdown.
- `ff_prepare_manual_draft` through the active stdio and FastMCP entrypoints.
- Documentation and deterministic mocked tests.

Non-goals: live draft state, screenshot parsing, Yahoo changes, wagering, lineup optimization, or a
new machine-learning projection model.

Acceptance:

- No Yahoo call occurs.
- One provider can fail without destroying the board.
- Stale and partial data are explicit.
- Exact scoring and replacement-level fixtures are independently testable.
- Focused tests and the routine unit/integration suite pass.

Effort: medium. Dependency: none.

### PR 2: Manual live-draft fast path

Outcome: turn screenshot-extracted picks into a recommendation within five seconds.

Scope:

- `ff_get_manual_draft_recommendation` through both active entrypoints.
- Drafted-player removal, our roster, snake timing, roster construction, tier urgency, and
  next-pick survival.
- Cached ESPN/RotoWire news, rookie evidence, and bounded PropLine evidence on the shortlist.
- Timing/source-age metadata and last-known-good fallback.
- Focused slot-11 snake-timing and two-FLEX fixtures.

Non-goals: optical character recognition inside the MCP, automatic Yahoo pick submission, or live
network calls required during the one-minute clock.

Acceptance:

- The same board and manual state produce deterministic recommendations.
- A missed/ambiguous player name is surfaced instead of silently removed.
- Warm mocked execution stays below five seconds.
- Provider outages cannot block the response.
- Focused tests and the routine unit/integration suite pass.

Effort: medium. Dependency: PR 1 merged to `george-bucky/main`.

## Review, rollout, and verification

- A fresh reviewer pins and reviews each PR's exact head after implementation.
- Findings are resolved and focused tests rerun before progressing.
- During this completed rollout, the user authorized auto-merge only after exact-head review and a
  green babysitting window; that authorization does not carry forward to future changes.
- After PR 2 merges, run one quick end-to-end smoke test, refresh and cache a live board, and report
  recommendation latency, source ages, ambiguous names, and any fallback before accepting real
  screenshot-derived pick batches.

## Non-goals

- Replacing expert projections with raw headline sentiment.
- Treating ADP as expected fantasy production.
- Treating one-game props as rest-of-season forecasts.
- Modifying Yahoo, placing bets, or scraping private/paywalled content.
- Building a web UI or publishing a Sites plan unless separately requested.
