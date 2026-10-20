"""
STORY    As a speaker deleting my account, I want my older Takes, saved before
         a Take carried its owner, erased with the rest, so that "delete my
         account" does not stop on them (deletion).
OUTCOME
  O1  Before an erasure freezes, my older Takes take my account's owner
      (0485), and the frozen inventory holds no unresolved legacy Take.
  O2  When they cannot be settled, the erasure still stops for review on
      them, exactly as before (fail-closed).
PROVES   O1 -> test_older_takes_take_the_accounts_owner_before_the_freeze
         O2 -> test_an_erasure_that_cannot_settle_them_still_stops_for_review
WHY      Founder 2026-10-20 (option 1): three test accounts' Takes, and most
         real speakers' older Takes (348 of 367 had no owner copy on
         2026-09-16), stopped every erasure with
         LEGACY_TAKE_OWNER_PRINCIPAL_UNRESOLVED.

The SQL of 0485 is proved on the released lane by
tests/test_phase1_deletion_completion_postgres.py (TestALegacyTakeTakesItsOwner);
this covers the Python orchestrator, with test_purge_user_locators.PurgeDb.
"""
from __future__ import annotations

import dataclasses

from services.data_purge import DataPurgeOrchestrator
from tests.test_purge_user_locators import ACCOUNT, PurgeDb

LEGACY = "legacy-take-ownership:unresolved"


class _Db(PurgeDb):
    def __init__(self, *, settles: bool):
        super().__init__({}, account=dataclasses.replace(
            ACCOUNT, unresolved_legacy_take_ids=("take-old",)))
        self.settles = settles

    def _resolve_legacy_take_owners_v1(self, params):
        assert params == {"p_acquisition_principal_id": ACCOUNT.principal_ids[0]}
        if not self.settles:
            raise RuntimeError("function not there")
        self.account = dataclasses.replace(self.account, unresolved_legacy_take_ids=())
        return {"resolved_take_ids": ["take-old"], "unresolved_take_ids": []}


def _frozen_refs(database: _Db) -> list[str]:
    DataPurgeOrchestrator(database).freeze_inventory("purge-1")
    return [row["target_ref"] for row in database.tables["data_purge_targets"]]


def test_older_takes_take_the_accounts_owner_before_the_freeze():
    assert LEGACY not in _frozen_refs(_Db(settles=True))


def test_an_erasure_that_cannot_settle_them_still_stops_for_review():
    database = _Db(settles=False)
    assert LEGACY in _frozen_refs(database)
    legacy = next(row for row in database.tables["data_purge_targets"]
                  if row["target_ref"] == LEGACY)
    assert legacy["state"] == "unknown"
