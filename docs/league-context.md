# Private league context

`src.models.league_context` and `src.services.league_context` provide private,
provider-neutral league context. They are intentionally not connected to either
public MCP server.

## Exact contracts

- Yahoo `league_key`, `team_key`, `player_key`, and the corresponding IDs remain
  strings from fetch through the immutable context. Each canonical key's encoded
  terminal ID must match its separately supplied ID, and team keys must encode
  the requested parent league. Player keys must also encode the same Yahoo game
  component as that league. Names are display data only.
- A missing team count, scoring type, roster slot, or scoring modifier remains
  missing. No standard league or scoring defaults are inserted.
- Every result records a timezone-aware fetch time, a staleness threshold,
  completeness, item/page counts, and warnings. The adapter bypasses the existing
  response cache so `fetched_at` means this fetch completed at that time.
- Availability pagination is complete only after Yahoo returns a page shorter
  than the requested page size. Yahoo `count` metadata is checked against the
  numbered entries; a valid `count=0` is a clean terminator, while malformed or
  truncated entries remain explicit warnings and make the evidence incomplete.
- Every teams, roster, and availability response is bound back to the requested
  league key. Cross-roster identities and roster/available overlaps are checked
  by both exact player key and player ID; overlaps or conflicting mappings fail
  closed as incomplete evidence. API and authentication failures raise visibly.
- Roster-position, scoring-modifier, manager, roster-player, and available-player
  numbered collections preserve Yahoo count evidence. Malformed manager display
  records without a manager ID or GUID are explicit incomplete warnings. Manager
  IDs and GUIDs are reconciled within a team: duplicates and contradictory maps
  are rejected, while distinct partial identities remain separate.

## Replacement-demand rule

Replacement demand is a deterministic league-wide maximum starter demand, using
only the known team count and parsed roster slots:

`demand(position) = team_count * sum(count of starting slots accepting position)`

A flex slot contributes to each position it explicitly accepts. Unknown slots
make settings incomplete and contribute no demand. For example, in
a 12-team league, one QB plus one `Q/W/R/T` slot produces QB demand of 24. This is
a transparent upper bound, not a guessed flex allocation. Bench, IR, unknown
slots, and inputs with an unknown team count produce no added demand.
