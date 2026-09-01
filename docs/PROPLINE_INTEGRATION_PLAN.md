# PropLine Integration Design Record

Status: implemented through PR #9 and PR #10 on `george-bucky/main`. This document preserves the
delivery contract and review decisions for future maintenance.

The imperative and future-tense sections below are the historical implementation specification,
not instructions or standing authorization for future agents. The execution ledger and resolved
decisions record what was completed.

## Outcome

Add PropLine as a read-only sportsbook evidence source so the draft copilot can inspect current markets for a small candidate shortlist and relevant teams immediately before a pick. Odds remain attributed supporting evidence; they do not replace projections, league settings, roster need, availability, ADP, or draft timing.

## Repository

- Repository: `fantasy-football-mcp-public`
- Base branch: repository default branch at execution time, verified before each task starts
- Active stdio entrypoint: `fantasy_football_multi_league.py`
- Active HTTP entrypoint: `fastmcp_server.py`
- Existing external HTTP pattern: `src/services/espn_news_service.py`
- Existing draft handler: `src/handlers/draft_handlers.py`

## Scope

1. Add a bounded asynchronous PropLine REST client with safe credential handling, caching, normalization, and structured recoverable errors.
2. Expose a standalone `ff_get_sportsbook_odds` tool through the legacy stdio and FastMCP HTTP contracts.
3. Add opt-in PropLine enrichment to the final draft recommendation shortlist after ranking is complete.
4. Document configuration, behavior, market-scope limitations, quota behavior, and live validation steps.
5. Add deterministic mocked regression coverage for the service, tool contracts, and recommendation invariance.

## Non-goals

- No wager placement, bet-slip construction, or sportsbook account integration.
- No default-on PropLine calls and no automatic polling loop.
- No numerical sportsbook bonus, penalty, or reordering in the draft score.
- No claim that next-game props are season projections.
- No scraping sportsbook sites or adding an unofficial fallback.
- No historical odds, line-movement, +EV, or paid PropLine features in the initial integration.
- No changes to `src/mcp_server.py` unless installed-console-script parity is selected at the
  execution gate below.
- No deployment, secret creation, or live Yahoo validation as part of code implementation.

## Product contract

### Standalone tool

Add the following additive MCP tool:

```text
ff_get_sportsbook_odds(
  players?: string[],              # 1-10 exact shortlist names
  teams?: string[],                # 1-10 NFL team names
  scope: "auto" | "season" | "next_game" = "auto",
  markets?: string[],              # optional market keys; disallowed with scope="auto"
  bookmakers?: string[]            # optional book keys; max 10
)
```

At least one player or team is required. Names are at most 100 characters; market/bookmaker keys
are at most 64 characters and must match `^[a-z0-9_]+$`; `markets` and `bookmakers` contain at most
10 unique entries each. Reject invalid, duplicate, over-limit, or empty-string entries before any
network request.

`auto` checks season-long futures first for team/player award evidence and then currently posted next-game markets. It does not manufacture a comparison between the two scopes.

Market defaults are deliberately fixed for v1:

- `season` makes one futures request, then filters the returned catalog locally by the requested
  entities and up to 10 exact market keys. Futures market keys are provider-defined and do not use
  a static allowlist because filtering cannot increase the one-request cost.
- `next_game` uses `h2h`, `spreads`, and `totals` for teams. For players it uses
  `player_pass_yds`, `player_pass_tds`, `player_rush_yds`, `player_reception_yds`,
  `player_receptions`, and `player_anytime_td` unless `markets` supplies a validated subset.
- `auto` applies both rules and preserves their distinct scopes.

For `next_game`, `markets` must be a subset of the nine team/player keys listed above. For
`season`, any syntactically valid market key is a local filter. To avoid ambiguous partitioning,
custom `markets` are rejected when `scope="auto"`; callers wanting custom filters make separate
`season` and `next_game` calls. Bookmaker keys remain provider-defined and are passed to both
endpoint types after validation.

The v1 provider graph is fixed to sport key `football_nfl` and these GET requests:

1. `season`: `/v1/sports/football_nfl/futures` once.
2. `next_game`: `/v1/sports/football_nfl/events` once, then
   `/v1/sports/football_nfl/events/{event_id}/odds` once per eligible event, combining all selected
   player and team markets in that event request.
3. `auto`: the futures request, event discovery, and the same per-event calls—a maximum of
   18 requests for 16 events.

Do not call the bulk team-odds endpoint or market-discovery endpoint in v1, and do not retry inside
a tool call. This keeps the request ceiling deterministic. These paths and response fields are
based on the [official PropLine API reference](https://prop-line.com/docs).

After event discovery, sort unstarted events by `commence_time` and retain at most 16. A standalone
team query is eligible only for events whose stable team key matches; a draft player query with
Yahoo team context is eligible only for that team's event. A standalone player query has no trusted
team context, so it scans all retained events and relies on exact identity matching. When player and
team inputs share an event, send their selected markets together in its single odds request.

Normalized response:

```text
status: "ok" | "partial" | "error"
provider
served_at                   # time this tool response was assembled
scope_requested
sources[]:                  # one entry per underlying futures/events/event-odds response
  id
  kind                      # futures/events/event_odds
  event_id?
  fetched_at                # completion time of the original provider fetch
  served_from_cache
  cache_age_seconds
  cache_ttl_seconds
results[]:
  source_id
  query
  entity_type
  matched_name
  provider_entity_id?       # stable player/team id when supplied
  scope
  event
  bookmaker
  market_key
  market_description
  selection                 # e.g. Over, Under, team, or named futures outcome
  subject                   # player/team the selection describes, when distinct
  period                    # full game when null at the provider
  line?                     # only when the provider supplies a point/handicap
  price
  provider_observed_at      # odds recorded_at or futures last_update
  book_updated_at?
  last_change_at?
unmatched[]:
  query
  entity_type
  reason                    # not_found/ambiguous/no_market/filtered_out/truncated
  candidate_count?
warnings[]
quota:
  source                    # live or cache
  as_of
  daily_limit
  daily_remaining
  reset_at
error?:
  code
  message
  stage                     # validation/configuration/futures/events/event_odds/normalization
  http_status?
  retry_after_seconds?
```

Omit unavailable optional values rather than inventing them. A standalone failure returns
`status="error"`, an empty `results`, the original requests in `unmatched`, and one stable error
envelope. Error codes are `invalid_request`, `not_configured`, `invalid_credentials`,
`access_denied`, `rate_limited`, `provider_timeout`, `provider_error`, and `invalid_response`.
Multi-event calls may return `status="partial"` with event-specific warnings when at least one live
request or cached component completed successfully; if none completed successfully, return
`status="error"`. A successful component may legitimately contain zero odds results.

`status="ok"` means every planned provider request completed, even when no current market exists;
that expected case is represented by `unmatched.reason="no_market"`. `status="partial"` is reserved
for a truncated call or one where only some provider requests failed. Every result references one
`sources` entry, so mixed cache hits and futures/game TTLs remain explicit. For quota, select the
completed live response with the lowest `daily_remaining` and use its full quota header set. If all
components came from cache, reuse the quota snapshot from the most recently fetched cached source,
mark `source="cache"`, and retain that snapshot's `as_of`; omit unavailable quota values.

### Draft enrichment

Add these optional arguments to `ff_get_draft_recommendation` only after the standalone tool is merged:

```text
include_sportsbook_odds: boolean = false
sportsbook_scope: "auto" | "season" | "next_game" = "auto"
sportsbook_shortlist_size: integer = 5  # range 1-5
```

The current recommendation calculation completes first. PropLine is called only for the final top N
candidates and their deduplicated NFL teams, combining shared teams/events into the same bounded
service call. Attach `sportsbook_context.players`, `sportsbook_context.teams`, and
`sportsbook_warnings` without modifying recommendation scores or ordering. Player context contains
player props/futures; team context contains `h2h`, `spreads`, `totals`, and team futures. If PropLine
fails or returns no market, the original recommendation response still succeeds.

## Provider and safety design

- Call `https://api.prop-line.com` directly with the existing `aiohttp` dependency; do not launch or depend on a nested MCP server.
- Read `PROPLINE_API_KEY` from the process environment and send it only in a request header.
- Use HTTPS, an exact host allowlist, no cross-host redirects, a five-second per-request timeout,
  a 15-second overall tool/enrichment budget, and a two-MiB maximum body per response.
- Bound each call to 10 player queries, 10 team queries, the next 16 upcoming NFL events, 18
  provider requests in total, four concurrent requests, and 500 normalized results. If a bound is
  reached, return a truncation warning rather than silently dropping coverage.
- Cache event discovery and current/game markets for 60 seconds and futures for one hour in a
  128-entry LRU cache. Keys include endpoint, sport, market, and bookmaker filters. Cache only
  normalized data, never credentials.
- Expose `Retry-After` and quota headers on `429`, return immediately without sleeping, and never
  log request headers.
- On the first 429, stop scheduling event requests and cancel queued or in-flight local request
  tasks. Preserve work that completed before cancellation. Return `status="partial"` with a
  `rate_limited` error when any live request or cached component completed successfully, even if it
  contained no market; otherwise return `status="error"`. Do not retry.
- Preserve PropLine, bookmaker, market, event, and timestamp provenance.
- Team matching maps normalized NFL names/aliases to PropLine's stable event `home_team_key` or
  `away_team_key`, falling back to an exact canonical display name only when a key is absent.
  Player matching requires an exact normalized outcome-description name; a parenthetical team
  abbreviation may be stripped before comparison. The public tool accepts names alone. Draft
  enrichment also passes the Yahoo team and position internally, uses the team to restrict
  eligible events, and records position as matching context.
- For next-game player props, group matching rows by identity `(event_id, player_id)` when a stable
  id exists, otherwise `(event_id, exact normalized subject)`. Multiple markets, books, lines, and
  Over/Under selections for one identity are legitimate rows, not ambiguity. More than one distinct
  identity after team restriction is ambiguous; after one identity is selected, return all its
  matching rows. For futures, match the exact normalized named outcome against the player/team
  query and apply the same distinct-identity rule. Ambiguous or absent matches go in `unmatched`;
  never guess.
- Treat market absence as unknown, not negative evidence.
- Map missing configuration, 401, 403, 429, timeouts, non-success/network failures, malformed
  content, and invalid input to the stable error codes above. A draft enrichment error is attached
  as `sportsbook_context.status` plus warnings; it never replaces the successful base recommendation.

## PR graph

```text
PR 1: PropLine service + standalone MCP tool
  |
  +-- fresh review task R1
  |
  v
manual/auto merge gate and default-branch verification
  |
  v
PR 2: opt-in draft shortlist enrichment
  |
  +-- fresh review task R2
  |
  v
final readiness / merge gate
```

The two implementation PRs are intentionally sequential. PR 2 depends on the normalized service and public tool contract from PR 1, and both touch the active MCP entrypoints. Parallel implementation would create avoidable contract and file overlap.

## PR 1 — PropLine service and standalone MCP tool

### Outcome

Users and agents can request current PropLine evidence for named players or teams without invoking Yahoo or changing draft rankings.

### Scope and code areas

- Add `src/services/propline_service.py`.
- Export the service from `src/services/__init__.py`.
- Add `handle_ff_get_sportsbook_odds` to `src/handlers/analytics_handlers.py` and export it through `src/handlers/__init__.py`.
- Register the schema and dispatch in `fantasy_football_multi_league.py`.
- Register prompt metadata, wrapper, delegation, and exports in `fastmcp_server.py`.
- Add configuration and usage documentation to `README.md`.
- Add focused service and tool tests under `tests/unit/`.

### Non-goals

- No draft recommendation arguments or enrichment.
- No scoring, recommendation, or Yahoo changes.
- No new SDK dependency.

### Acceptance checks

- Both MCP entrypoints expose the same additive tool name and argument contract.
- Missing `PROPLINE_API_KEY` returns `not_configured` without a network call.
- Season and next-game fixtures normalize into the documented response with provenance.
- Every returned outcome identifies its selection and subject, and includes a line only where the
  provider supplies one.
- Player/team filters, market filters, bookmaker filters, unmatched queries, and ambiguous names behave deterministically.
- Timeouts, redirects, oversized/malformed responses, 401, 403, 429, and 5xx responses fail safely.
- A 429 returns immediately with retry metadata; it does not sleep inside a draft call.
- Request, concurrency, result, timeout, and LRU cache bounds are enforced and covered by tests.
- Input count, string length, syntax, duplicate, raw response byte, and no-retry bounds are covered
  by tests.
- Cached responses preserve the original fetch timestamp and expose cache hit, age, TTL, and
  current serve time.
- Cache TTLs differ between current odds and futures and do not leak data between materially different requests.
- No secret appears in logs, errors, fixtures, or returned payloads.
- Focused Ruff/Black checks on touched files pass.
- Focused unit tests pass, followed by `pytest tests/unit tests/integration -q`.

### Task configuration

- Worker model: GPT-5.6 Sol
- Effort: medium — external API security, public MCP contract, two active entrypoints
- Branch/PR title: `feat: add PropLine sportsbook odds tool`
- Dependency: none beyond execution gates

### Review gate R1

A fresh GPT-5.6 Sol task at low effort reviews the exact PR head for contract parity, credential leakage, failure semantics, cache correctness, bounded networking, and regression coverage. The reviewer does not edit. Confirmed findings return to the implementation worker, which fixes and reruns checks; a newly spawned exact-head reviewer repeats the review until clean before the PR is considered ready.

## PR 2 — Opt-in draft shortlist enrichment

### Outcome

The existing draft recommendation tool can attach timely sportsbook context to its final shortlist when explicitly requested, while returning the same candidates, scores, and ordering as before.

### Scope and code areas

- Extend the draft tool schema and FastMCP wrapper with the three opt-in arguments.
- Thread the arguments through `src/handlers/draft_handlers.py` into the active recommendation flow.
- After final ranking and truncation, call the merged PropLine service for no more than five
  candidates plus their deduplicated NFL teams.
- Attach separate player and team sportsbook context plus top-level warnings with source/timestamp
  provenance.
- Update README examples and draft caveats.
- Add focused regression tests in `tests/unit/test_draft_recommendations.py` plus contract/delegation tests.

### Non-goals

- No score changes or candidate reordering.
- No automatic threshold based on how many picks remain.
- No background refresh or live-draft loop.
- No provider fallback in this PR.

### Acceptance checks

- Default behavior makes no PropLine call and remains byte-for-byte compatible except for intentionally additive schema metadata, if any.
- Enabling enrichment queries only the final N candidates, capped at five.
- Candidate teams are deduplicated, their team markets share event requests with player props, and
  team evidence is attached separately from player evidence.
- With identical base inputs, names, scores, and ordering match the enrichment-disabled response.
- Provider failure, missing credentials, rate limiting, ambiguous match, or no market returns the recommendation plus an explicit warning.
- Game-scoped and season-scoped evidence remain labeled and are never compared as equivalent projections.
- The stdio and FastMCP schemas remain aligned.
- Focused Ruff/Black checks and draft/tool regression tests pass.
- `pytest tests/unit tests/integration -q` passes.

### Task configuration

- Worker model: GPT-5.6 Sol
- Effort: medium — public contract change and live recommendation failure semantics
- Branch/PR title: `feat: add opt-in sportsbook context to draft recommendations`
- Dependency: PR 1 merged and verified on the default branch

### Review gate R2

A fresh GPT-5.6 Sol task at low effort reviews the exact PR head for recommendation invariance, opt-in semantics, bounded calls, scope labeling, graceful degradation, and contract parity. The reviewer does not edit. Confirmed findings return to the implementation worker, which fixes and reruns checks; a newly spawned exact-head reviewer repeats the review until clean before readiness is reported.

## Execution waves and ledger

| Wave | Task | Effort | Dependency | Completion state |
|---|---|---:|---|---|
| 1 | PR #9 service and standalone tool | Medium | Merge/score/entrypoint gates answered | Merged as `ef7da8c` |
| 1 review | R1 fresh exact-head review | Low | PR 1 implementation complete | Complete |
| 2 | PR #10 opt-in draft context | Medium | PR #9 merged and verified | Merged as `4dfccbe` |
| 2 review | R2 fresh exact-head review | Low | PR 2 implementation complete | Complete |

Each PR used an isolated Codex worktree task, with separate read-only review tasks. During execution,
`$mission` recorded task IDs, PRs, dependencies, phases, meaningful updates, and next checks. Merge
authorization was evaluated from the user's explicit direction during that rollout and does not
carry forward. No Sites plan page was created.

## Verification and live rehearsal

### Mocked verification

1. Run the narrow service/tool tests.
2. Run the draft recommendation regressions.
3. Run touched-file Ruff and Black checks.
4. Run `pytest tests/unit tests/integration -q`.
5. Do not run live Yahoo tests or authentication utilities.

### Runtime live-key verification procedure

When a PropLine key is configured through an approved secret mechanism:

1. Query two established players, one ambiguous/missing name, and one NFL team.
2. Confirm fetch/serve/cache timestamps, provider timestamps, bookmaker, scope, quota headers, and
   unmatched behavior.
3. Repeat within the TTL and confirm cache behavior.
4. Enable draft enrichment in a non-live rehearsal and compare the response against enrichment disabled.
5. Confirm identical recommendation names, scores, and ordering.

A successful provider response with no currently posted market is a valid result and must be reported as such. Mocked tests do not prove live market coverage.

## Completed rollout and rollback contract

1. PR #9 added the standalone tool and was merged first.
2. Runtime key configuration remains an operator responsibility outside the repository and must
   never be committed.
3. Live endpoint and market coverage remain runtime checks; mocked tests alone do not establish
   current provider readiness.
4. PR #10 added opt-in draft context and was merged after PR #9.
5. `include_sportsbook_odds=false` remains the default.
6. Immediate behavioral rollback is to omit or disable the opt-in argument. Code rollback remains
   one PR at a time.

Deployment, runtime secret mutation, and live draft operation require separate authorization after code readiness.

## Resolved execution decisions

1. Changes were eligible to merge only after exact-head review and a green babysitting window.
2. No Sites plan page was created; repository documentation remains the source of truth.
3. Sportsbook data is attributed evidence only and does not change the legacy draft recommendation
   score or ordering in the initial PropLine delivery.
4. The integration targets the active stdio and FastMCP entrypoints; installed CLI parity was kept
   outside the initial scope.
