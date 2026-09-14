"""The three Confident Moment playback/exercise RPC names are pinned.

The production statement-timeout hook (D49 §5) names these functions
LITERALLY. A rename, a re-version (`_v2`) or a re-route would make the hook
silently stop covering the renamed one and the 8 s bound would come back
with nothing failing. So the list lives here, and anything that moves one of
the names has to change this file on purpose — which is the moment to update
the hook too.

Pinned on the code side: the repository calls exactly these names, migration
0327 (immutable) defines them, and no later migration creates, drops or
renames a function under one of them. Other references in later migrations
(ALTER … SET statement_timeout, GRANT/REVOKE) are expected and allowed.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "services" / "confident_moment_bundle_repository.py"
DEFINING_MIGRATION = ROOT / "migrations" / "add_confident_moment_coaching_bundle_v1.sql"

PINNED_RPC_NAMES = frozenset({
    "resolve_confident_moment_source_playback_authority_v1",
    "authorize_confident_moment_source_playback_emit_v1",
    "resolve_confident_moment_exercise_offer_v1",
})


def test_the_repository_calls_exactly_the_pinned_names():
    source = REPOSITORY.read_text()
    called = set(re.findall(
        r'"((?:resolve|authorize)_confident_moment_'
        r'(?:source_playback|exercise_offer)[a-z_0-9]*)"', source))
    assert called == PINNED_RPC_NAMES, (
        "the playback/exercise RPC names the repository calls moved — "
        "update the production timeout hook (D49 §5) and then this list: "
        f"{sorted(called ^ PINNED_RPC_NAMES)}")


def test_migration_0327_defines_every_pinned_name():
    sql = DEFINING_MIGRATION.read_text()
    for name in sorted(PINNED_RPC_NAMES):
        assert f"CREATE OR REPLACE FUNCTION public.{name}(" in sql, name


def test_no_later_migration_creates_drops_or_renames_a_pinned_name():
    offenders = []
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        if path == DEFINING_MIGRATION:
            continue
        sql = path.read_text()
        for name in PINNED_RPC_NAMES:
            if re.search(
                    rf"(CREATE(?: OR REPLACE)? FUNCTION|DROP FUNCTION)"
                    rf"\s+(?:IF EXISTS\s+)?(?:public\.)?{name}\b", sql) \
                    or re.search(rf"{name}\b[^;]*RENAME TO", sql):
                offenders.append(f"{path.name}: {name}")
    assert not offenders, (
        "a migration re-defines, drops or renames a pinned playback RPC; "
        "the production timeout hook names it literally — update the hook "
        f"first, then this test: {offenders}")
