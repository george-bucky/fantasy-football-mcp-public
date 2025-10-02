"""MCP tool handlers - imports from handler modules and main file."""

# Import simple handlers from dedicated modules
from .admin_handlers import (
    handle_ff_clear_cache,
    handle_ff_get_api_status,
    handle_ff_refresh_token,
)

# League handlers will need helper functions injected
from .league_handlers import (
    handle_ff_get_league_info,
    handle_ff_get_leagues,
    handle_ff_get_standings,
    handle_ff_get_teams,
)

# Complex handlers - will be imported from main file initially
# Then gradually refactored in future sessions
_handle_ff_get_roster = None
_handle_ff_get_matchup = None
_handle_ff_build_lineup = None
_handle_ff_get_players = None
_handle_ff_compare_teams = None
_handle_ff_get_waiver_wire = None
_handle_ff_get_draft_results = None
_handle_ff_get_draft_rankings = None
_handle_ff_get_draft_recommendation = None
_handle_ff_analyze_draft_state = None
_handle_ff_analyze_reddit_sentiment = None


def inject_complex_handlers(**handlers):
    """Inject complex handler functions from main module.

    This allows us to gradually refactor complex handlers while keeping
    the system working. As handlers are refactored, they can be moved
    to dedicated modules.
    """
    global _handle_ff_get_roster, _handle_ff_get_matchup, _handle_ff_build_lineup
    global _handle_ff_get_players, _handle_ff_compare_teams, _handle_ff_get_waiver_wire
    global _handle_ff_get_draft_results, _handle_ff_get_draft_rankings
    global _handle_ff_get_draft_recommendation, _handle_ff_analyze_draft_state
    global _handle_ff_analyze_reddit_sentiment

    for name, func in handlers.items():
        globals()[name] = func


def inject_league_helpers(**helpers):
    """Inject helper functions needed by league handlers.

    League handlers need access to discover_leagues, get_user_team_info,
    and get_all_teams_info which use global state.
    """
    import src.handlers.league_handlers as league_mod

    for name, func in helpers.items():
        setattr(league_mod, name, func)


__all__ = [
    # Admin handlers (fully extracted)
    "handle_ff_refresh_token",
    "handle_ff_get_api_status",
    "handle_ff_clear_cache",
    # League handlers (extracted but need helper injection)
    "handle_ff_get_leagues",
    "handle_ff_get_league_info",
    "handle_ff_get_standings",
    "handle_ff_get_teams",
    # Complex handlers (to be extracted in future)
    "_handle_ff_get_roster",
    "_handle_ff_get_matchup",
    "_handle_ff_build_lineup",
    "_handle_ff_get_players",
    "_handle_ff_compare_teams",
    "_handle_ff_get_waiver_wire",
    "_handle_ff_get_draft_results",
    "_handle_ff_get_draft_rankings",
    "_handle_ff_get_draft_recommendation",
    "_handle_ff_analyze_draft_state",
    "_handle_ff_analyze_reddit_sentiment",
]
