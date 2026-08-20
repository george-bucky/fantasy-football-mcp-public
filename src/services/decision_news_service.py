"""Attach attributed news evidence to fantasy-football decisions."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from .espn_news_service import get_espn_nfl_news_batch
from .rotowire_service import get_rotowire_player_news_batch


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _espn_item_matches(item: dict[str, Any], player_name: str) -> bool:
    requested = _normalize(player_name)
    athlete_names = [
        str(ref.get("name") or "")
        for ref in item.get("athlete_refs", [])
        if isinstance(ref, dict)
    ]
    searchable = " ".join(
        [
            *athlete_names,
            *item.get("players", []),
            item.get("headline", ""),
            item.get("summary", ""),
        ]
    )
    return bool(requested and requested in _normalize(searchable))


async def get_decision_news_context(
    player_names: Sequence[str], *, per_player_limit: int = 2
) -> dict[str, Any]:
    """Fetch each source once and map recent evidence to requested players."""
    names = list(dict.fromkeys(name.strip() for name in player_names if name.strip()))
    by_player = {
        name: {"espn": [], "rotowire": [], "espn_athlete_refs": []}
        for name in names
    }
    if not names:
        return {"by_player": by_player, "sources": [], "warnings": []}

    espn_result, rotowire_result = await asyncio.gather(
        get_espn_nfl_news_batch(players=names, limit=50),
        get_rotowire_player_news_batch(players=names, limit=50),
        return_exceptions=True,
    )

    sources: list[str] = []
    warnings: list[str] = []
    if isinstance(espn_result, Exception):
        warnings.append(f"ESPN news unavailable: {espn_result}")
    elif espn_result.get("status") == "success":
        sources.append(str(espn_result.get("source") or "ESPN NFL News API"))
        for item in espn_result.get("items", []):
            if not isinstance(item, dict):
                continue
            for name in names:
                player_context = by_player[name]
                if (
                    len(player_context["espn"]) < per_player_limit
                    and _espn_item_matches(item, name)
                ):
                    matching_refs = [
                        ref
                        for ref in item.get("athlete_refs", [])
                        if isinstance(ref, dict)
                        and _normalize(str(ref.get("name") or "")) == _normalize(name)
                    ]
                    player_context["espn"].append(
                        {
                            key: item.get(key)
                            for key in (
                                "article_id",
                                "headline",
                                "summary",
                                "published_at",
                                "url",
                                "byline",
                                "premium",
                            )
                        }
                        | {
                            "athlete_refs": matching_refs,
                            "team_refs": item.get("team_refs", []),
                            "source": espn_result.get("source"),
                        }
                    )
                    for ref in matching_refs:
                        if ref not in player_context["espn_athlete_refs"]:
                            player_context["espn_athlete_refs"].append(ref)
    else:
        warnings.append(
            f"ESPN news unavailable: {espn_result.get('error', 'unknown error')}"
        )

    if isinstance(rotowire_result, Exception):
        warnings.append(f"RotoWire news unavailable: {rotowire_result}")
    elif rotowire_result.get("status") == "success":
        sources.append(str(rotowire_result.get("source") or "RotoWire NFL RSS"))
        for item in rotowire_result.get("items", []):
            if not isinstance(item, dict) or not item.get("player"):
                continue
            for name in names:
                player_context = by_player[name]
                if (
                    len(player_context["rotowire"]) < per_player_limit
                    and _normalize(str(item["player"])) == _normalize(name)
                ):
                    player_context["rotowire"].append(
                        {**item, "source": rotowire_result.get("source")}
                    )
    else:
        warnings.append(
            f"RotoWire news unavailable: {rotowire_result.get('error', 'unknown error')}"
        )

    return {"by_player": by_player, "sources": sources, "warnings": warnings}
