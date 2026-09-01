# Mission

Build a no-Yahoo live-draft assistant that converts public projections, expert consensus,
half-PPR ADP, current player evidence, and screenshot-supplied draft state into fast,
auditable recommendations for Gotham City Football XIV.

## Done criteria

- A prepared offline board is built without Yahoo credentials from source-attributed public data.
- Player value reflects the league's exact scoring and 12-team, two-FLEX replacement levels.
- ADP is a market/timing input rather than the primary player ranking.
- Manual drafted-player and user-roster inputs update recommendations without refetching the board.
- News, injury status, rookie evidence, and PropLine odds are visible with bounded, auditable influence.
- A warm recommendation returns within five seconds and falls back to the last good snapshot.
- Focused mocked tests and the routine unit/integration suite pass.

## Guardrails

- Target only `george-bucky/fantasy-football-mcp-public`; upstream is reference-only.
- Preserve existing Yahoo tools and public contracts; the offline path is additive.
- Never submit a pick, place a wager, or expose credentials.
- Do not turn raw headlines or incomparable betting markets into fabricated projections.
- Quarantine ambiguous player identities and report stale or missing sources.
- No standing merge authorization is recorded here; follow the user's current explicit direction.

## Critical learnings

- Validation: ESPN's public fantasy endpoint returned 500 players with raw 2026 season projections,
  including the stat fields needed to rescore players for custom league rules.
- Validation: Fantasy Football Calculator's free API returned 233 current 12-team half-PPR ADP rows,
  including draft counts, range, and standard deviation.
- Validation: DynastyProcess publishes a weekly open-data expert consensus snapshot with rank
  uncertainty and source dates.
- Constraint: Sleeper's public Week 1 projection endpoint returned 7,627 empty player rows, so
  Sleeper is suitable for player identity, status, depth chart, and trending data, not the primary
  preseason projection source.
- Decision: build a stable base board first, then a manual screenshot-driven live recommendation
  path on top of that contract.
- Decision: corroborated news and comparable season-long odds have a combined, fully audited
  influence capped at three points on a 100-point recommendation score.
- Decision: no Sites plan page; the repository plan remains the source of truth.
- Decision: for the completed implementation rollout, the user authorized auto-merge only after
  review and babysitting succeeded; that historical authorization does not apply to future work.
- Decision: skip the planned full 14-round rehearsal because the real draft may begin immediately;
  keep critical fast-path tests, then run one quick post-merge smoke test and cache a fresh live board.
- Validation: the real Gotham draft exercised the screenshot-driven workflow end to end, and the
  final roster is stored locally under the ignored `data/league_rosters/` directory.
- Validation: the post-merge smoke test exposed a persisted-board reload defect when a defense row
  legitimately had no base score; the validator now accepts that defense-only case while continuing
  to reject unscored offensive players.
- Validation: on 2026-09-01, all five public board sources refreshed successfully, a new 250-player
  snapshot was cached, and a warm recommendation completed in 15.84 milliseconds.

## Status

The core mission is complete. PR #11 and PR #12 are merged on `george-bucky/main`, the real Gotham
draft was completed through the manual screenshot workflow, and a fresh 250-player board is cached.
The post-merge defense-row reload regression has a focused fix and deterministic regression test.

## Execution ledger

| Work item | Dependency | Phase | Last meaningful update | Next check |
|---|---|---|---|---|
| Offline ranking contract | None | Complete | Public projection, ECR, ADP, evidence, and merge policies confirmed | Complete |
| PR 1 implementation | Contract confirmation | Complete | PR #11 merged as `313e48e5`; reviewed head `855186c6` is its second parent | Complete |
| PR 1 fresh review | PR 1 exact head | Complete | Exact-head review clean; 384 unit and 8 integration tests passed | Complete |
| PR 2 implementation | PR 1 merged | Complete | PR #12 merged as `3abcf2d0`; implementation head was `95cf001a` | Complete |
| PR 2 fresh review | PR 2 exact head | Complete | Focused and routine unit/integration tests passed; real draft completed | Complete |
| Defense snapshot reload fix | Post-merge smoke test | Complete | Defense rows with no base score reload; offensive rows remain validated | Complete |
| Gotham roster record | Draft complete | Complete | Local JSON saved under ignored `data/league_rosters/` | Complete |
