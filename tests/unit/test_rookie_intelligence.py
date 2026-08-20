"""Focused contract tests for reviewed rookie-year intelligence."""

import hashlib
import json

import pytest

from src.services.rookie_intelligence import (
    REVIEWED_ARTIFACT_SHA256,
    REVIEWED_MANIFEST_SHA256,
    REVIEWED_SCHEMA_SHA256,
    RookieBoardError,
    apply_rookie_intelligence,
    load_rookie_board,
    rookie_identity_key,
)


def test_vendored_board_is_the_exact_reviewed_rr05_release():
    board = load_rookie_board()

    assert board.artifact_sha256 == REVIEWED_ARTIFACT_SHA256
    assert board.manifest_sha256 == REVIEWED_MANIFEST_SHA256
    assert board.provenance() == {
        "artifact": "rookie-board-2026.json",
        "artifact_sha256": REVIEWED_ARTIFACT_SHA256,
        "manifest_sha256": REVIEWED_MANIFEST_SHA256,
        "schema_sha256": REVIEWED_SCHEMA_SHA256,
        "artifact_version": "1.0.0",
        "schema_version": "1.0.0",
        "producer_commit": "eff4a32d56301f68a22c4a52887f61c577f969dd",
        "generated_at": "2026-08-20T15:52:52.736917Z",
        "data_cutoff": "2026-08-20",
        "draft_class": 2026,
        "scoring_basis": "ppr",
        "target": "rookie_year_ppr_points",
    }
    assert len(board.players) == 80
    assert board.players[0]["base_rank"] == 1
    assert board.players[-1]["base_rank"] == 80


def _player(name, position, rank, p50, canonical_id):
    return {
        "canonical_id": canonical_id,
        "source_ids": {"gsis_id": canonical_id.split(":", 1)[-1]},
        "name": name,
        "position": position,
        "nfl_team": "TST",
        "overall_pick": rank,
        "base_rank": rank,
        "position_rank": rank,
        "tier": 1,
        "rookie_year_ppr": {"p10": p50 - 10, "p50": p50, "p90": p50 + 10},
        "confidence": "high",
        "data_quality_warnings": [],
    }


def _write_board(tmp_path, players):
    schema = {
        "x-schema-version": "1.0.0",
        "required": ["metadata", "players"],
        "$defs": {
            "artifactMetadata": {
                "required": [
                    "schema_version",
                    "artifact_version",
                    "producer_commit",
                    "draft_class",
                    "scoring_basis",
                    "target_definitions",
                    "capabilities",
                ]
            },
            "rookiePlayer": {
                "required": [
                    "canonical_id",
                    "source_ids",
                    "name",
                    "position",
                    "nfl_team",
                    "overall_pick",
                    "base_rank",
                    "position_rank",
                    "tier",
                    "rookie_year_ppr",
                    "confidence",
                    "data_quality_warnings",
                ]
            },
        },
    }
    schema_path = tmp_path / "rookie-board.schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    schema_digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    artifact = {
        "metadata": {
            "schema_version": "1.0.0",
            "artifact_version": "1.0.0",
            "producer_commit": "abcdef1",
            "generated_at": "2026-08-20T12:00:00Z",
            "data_cutoff": "2026-08-20",
            "draft_class": 2026,
            "scoring_basis": "ppr",
            "capabilities": {"rookie_year_predictions": True},
            "target_definitions": {
                "rookie_year_ppr_points": "PPR points in the first NFL regular season."
            },
        },
        "players": players,
    }
    artifact_path = tmp_path / "rookie-board-2026.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest = {
        "artifact_filename": artifact_path.name,
        "artifact_sha256": digest,
        "artifact_version": "1.0.0",
        "schema_version": "1.0.0",
        "producer_commit": "abcdef1",
        "generated_at": "2026-08-20T12:00:00Z",
        "draft_class": 2026,
    }
    manifest_path = tmp_path / "rookie-board-2026.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return (
        artifact_path,
        manifest_path,
        schema_path,
        digest,
        manifest_digest,
        schema_digest,
    )


def test_load_validates_sha_current_class_and_rookie_year_rank(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Rookie One", "RB", 1, 200, "gsis:one"),
            _player("Rookie Two", "WR", 2, 150, "gsis:two"),
        ],
    )

    board = load_rookie_board(
        artifact,
        manifest,
        schema,
        expected_sha256=digest,
        expected_manifest_sha256=manifest_digest,
        expected_schema_sha256=schema_digest,
    )

    assert board.artifact_sha256 == digest
    assert board.provenance()["target"] == "rookie_year_ppr_points"
    assert board.match("Rookie-One", "RB")["match_method"] == (
        "unique_normalized_exact_name_position"
    )
    assert board.match("Rookie One", "WR")["status"] == "not_on_current_rookie_board"


def test_load_rejects_unreviewed_or_misranked_artifact(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Rookie One", "RB", 1, 100, "gsis:one"),
            _player("Rookie Two", "WR", 2, 150, "gsis:two"),
        ],
    )

    with pytest.raises(RookieBoardError, match="descending rookie_year_ppr"):
        load_rookie_board(
            artifact,
            manifest,
            schema,
            expected_sha256=digest,
            expected_manifest_sha256=manifest_digest,
            expected_schema_sha256=schema_digest,
        )
    with pytest.raises(RookieBoardError, match="reviewed manifest"):
        load_rookie_board(
            artifact,
            manifest,
            schema,
            expected_sha256="0" * 64,
            expected_manifest_sha256=manifest_digest,
            expected_schema_sha256=schema_digest,
        )


def test_apply_orders_only_rookies_and_never_falls_back_to_veterans(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Better Rookie", "WR", 1, 200, "gsis:better"),
            _player("Other Rookie", "RB", 2, 150, "gsis:other"),
        ],
    )
    board = load_rookie_board(
        artifact,
        manifest,
        schema,
        expected_sha256=digest,
        expected_manifest_sha256=manifest_digest,
        expected_schema_sha256=schema_digest,
    )
    players = [
        {"name": "Other Rookie", "position": "RB"},
        {"name": "Veteran", "position": "WR"},
        {"name": "Better Rookie", "position": "WR"},
    ]

    context = apply_rookie_intelligence(players, context="waiver", board=board)
    rookie_only = apply_rookie_intelligence(
        players, context="waiver", rookie_only=True, board=board
    )
    no_rookies = apply_rookie_intelligence(
        [{"name": "Veteran", "position": "WR"}],
        context="waiver",
        rookie_only=True,
        board=board,
    )

    assert [row["name"] for row in context["players"]] == [
        "Better Rookie",
        "Veteran",
        "Other Rookie",
    ]
    assert [row["name"] for row in rookie_only["players"]] == [
        "Better Rookie",
        "Other Rookie",
    ]
    assert no_rookies["players"] == []
    assert no_rookies["evidence"]["not_on_current_rookie_board_players"] == 1
    assert no_rookies["evidence"]["quarantined_players"] == 0
    assert "no veterans were returned" in no_rookies["evidence"]["warnings"][-1]


def test_duplicate_exact_identity_is_quarantined(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Same Rookie", "WR", 1, 200, "gsis:one"),
            _player("Same Rookie", "WR", 2, 150, "gsis:two"),
        ],
    )
    board = load_rookie_board(
        artifact,
        manifest,
        schema,
        expected_sha256=digest,
        expected_manifest_sha256=manifest_digest,
        expected_schema_sha256=schema_digest,
    )

    match = board.match("Same Rookie", "WR")

    assert match["status"] == "quarantined"
    assert "ambiguous" in match["warnings"][0]


def test_same_name_different_positions_keep_separate_identity_context(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Same Name", "RB", 1, 200, "gsis:rb"),
            _player("Same Name", "WR", 2, 150, "gsis:wr"),
        ],
    )
    board = load_rookie_board(
        artifact,
        manifest,
        schema,
        expected_sha256=digest,
        expected_manifest_sha256=manifest_digest,
        expected_schema_sha256=schema_digest,
    )

    context = apply_rookie_intelligence(
        [
            {"name": "Same Name", "position": "RB"},
            {"name": "Same Name", "position": "WR"},
        ],
        context="lineup",
        board=board,
    )

    assert (
        context["by_identity"][rookie_identity_key("Same Name", "RB")]["canonical_id"] == "gsis:rb"
    )
    assert (
        context["by_identity"][rookie_identity_key("Same Name", "WR")]["canonical_id"] == "gsis:wr"
    )


def test_loader_rejects_duplicate_json_keys(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [_player("Rookie One", "RB", 1, 200, "gsis:one")],
    )
    manifest.write_text(
        manifest.read_text(encoding="utf-8")[:-1] + ', "draft_class": 2026}',
        encoding="utf-8",
    )
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    with pytest.raises(RookieBoardError, match="Duplicate JSON object key"):
        load_rookie_board(
            artifact,
            manifest,
            schema,
            expected_sha256=digest,
            expected_manifest_sha256=manifest_digest,
            expected_schema_sha256=schema_digest,
        )


def test_equal_p50_requires_canonical_id_ascending(tmp_path):
    artifact, manifest, schema, digest, manifest_digest, schema_digest = _write_board(
        tmp_path,
        [
            _player("Rookie Z", "RB", 1, 200, "gsis:z"),
            _player("Rookie A", "WR", 2, 200, "gsis:a"),
        ],
    )

    with pytest.raises(RookieBoardError, match="canonical_id ascending"):
        load_rookie_board(
            artifact,
            manifest,
            schema,
            expected_sha256=digest,
            expected_manifest_sha256=manifest_digest,
            expected_schema_sha256=schema_digest,
        )
