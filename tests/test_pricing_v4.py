"""
STORY    As a speaker, I want one currency for my practice and my coach's time,
         so that any package can pay for a call and a bigger one simply lasts
         longer. (Critical path: payments.)
OUTCOME
  O1  While pricing v4 is off, nothing changes: the shop, the prices and the
      unit are today's.
  O2  With it on, tokens read in hundreds of today's units: Starter $39 for
      3,900, Plus $99 for 11,000, Pro $149 for 18,000; a short Take reads 10,
      chat 1, the free grant 120, the coach's minute 200.
  O3  A package bought with it on is charged and granted at the new price.
  O4  A Take that reaches the coach costs nothing, with v4 on or off: the
      coach answers every Take and no price list carries a review.
  O5  A call can be booked with tokens at its own price, a token a cent; with
      too few tokens, or with v4 off, nothing is booked and the slot is free.
PROVES   O1 -> test_with_v4_off_nothing_changes
         O2 -> test_with_v4_on_the_shop_and_prices_read_in_shown_tokens
         O3 -> test_a_package_bought_with_v4_on_is_charged_and_granted_its_new_price
         O4 -> test_a_take_reaching_the_coach_costs_nothing
         O5 -> test_a_call_booked_with_tokens_costs_its_price_a_token_a_cent,
               test_a_call_tokens_cannot_pay_for_is_not_booked
WHY      Founder 2026-10-26, N198 (the prototype's version 3, "accepted, start
         the build"); N187 for the coach's rate; N205 for the review (items
         3 and 4: "Yes, for the first one, yes").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from services import booking, lab_send, token_packages
from services import token_prices as tp
from services.db import db
from services.token_account import ChargeResult

SETTINGS = {"id": 1, "slug": "artur", "enabled": True, "title": "Call", "host_name": "Artur",
            "duration_min": 15, "price_cents": 3000, "currency": "usd", "horizon_days": 30,
            "timezone": "Europe/Warsaw", "new_user_discount_pct": 0,
            "weekly_hours": {str(d): [["08:00", "18:00"]] for d in range(7)},
            "buffer_before_min": 0, "buffer_after_min": 0, "notice_hours": 0,
            "meet_url": "", "calendar_ics_url": ""}


@pytest.fixture
def v4(monkeypatch):
    monkeypatch.setenv("PRICING_V4_ENABLED", "1")
    monkeypatch.setenv("TOKEN_PRICING_ENABLED", "1")


def test_with_v4_off_nothing_changes(monkeypatch):
    monkeypatch.delenv("PRICING_V4_ENABLED", raising=False)
    sheet = tp.public_price_list()
    assert sheet["display_unit"] == 1 and sheet["coach_minute"] is None
    assert sheet["price_version"] == tp.PRICE_VERSION
    assert sheet["tiers"]["practice"]["usd_per_month"] == 12
    assert sheet["actions"]["chat"] == 150


def test_with_v4_on_the_shop_and_prices_read_in_shown_tokens(v4):
    sheet = tp.public_price_list()
    assert sheet["display_unit"] == 100 and sheet["price_version"] == tp.PRICE_VERSION_V4
    shop = {name: (t["usd_per_month"], t["tokens_per_month"]) for name, t in sheet["tiers"].items()}
    assert shop == {"free": (0, 120), "practice": (39, 3_900), "coaching": (99, 11_000),
                    "intensive": (149, 18_000)}
    actions = sheet["actions"]
    assert actions["take_short"] == 10 and actions["chat"] == 1
    assert "coach_feedback" not in actions and "coach_time" not in actions
    assert sheet["coach_minute"] == 200
    # Nothing stored changes: the free grant is still 12,000 units, and a
    # balance is never shown larger than it is.
    assert tp.grant_for("free") == 12_000 and tp.shown(9_850) == 98


def test_a_package_bought_with_v4_on_is_charged_and_granted_its_new_price(v4):
    spec = token_packages.package_spec("coaching")
    assert (spec["cents"], spec["tokens"]) == (9_900, 1_100_000)


@pytest.mark.parametrize("v4_on", [True, False])
def test_a_take_reaching_the_coach_costs_nothing(monkeypatch, v4_on):
    monkeypatch.setenv("PRICING_V4_ENABLED", "1" if v4_on else "0")
    monkeypatch.setenv("TOKEN_PRICING_ENABLED", "1")
    take = {"id": "s1", "user_id": "u1", "status": "processing", "recording_kind": "spoken"}
    with patch.object(db, "v2_get_session_by_id", return_value=take), \
            patch.object(db.takes, "v2_mark_session_pending_review", return_value=True), \
            patch("services.token_account.charge") as charge:
        sent = lab_send.send_lab_recording_to_coach("s1", "u1", notify_admin=False)
    assert sent["ok"] and sent["coach_review_status"] == "queued"
    charge.assert_not_called()
    assert "coach_feedback" not in tp.public_price_list()["actions"]


def _book(pay_with_tokens=True):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=10, minute=0, second=0,
                                                                     microsecond=0)
    return booking.start_checkout(slug="artur", user_id="u1", start_iso=start.isoformat(),
                                  name="A", email="a@x.co", guest_timezone="UTC",
                                  pay_with_tokens=pay_with_tokens)


@pytest.fixture
def page():
    with patch.object(booking, "get_settings", return_value=dict(SETTINGS)), \
            patch.object(booking, "user_price", return_value=None), \
            patch.object(booking, "db", MagicMock()) as db, \
            patch.object(booking, "_confirm") as confirm:
        yield db, confirm


def test_a_call_booked_with_tokens_costs_its_price_a_token_a_cent(v4, page):
    db, confirm = page
    with patch("services.token_account.charge",
               return_value=ChargeResult(True, 300_000, 800_000, "", "coach_time")) as charge:
        out = _book()
    assert charge.call_args.kwargs["quantity"] == 3000      # $30, 3,000 tokens as shown
    assert db.client.rpc.call_args.args[1]["p_price_cents"] == 0   # nothing charged in money
    assert confirm.call_args.kwargs["paid_tokens"] == 300_000
    assert "/done?booking=" in out["url"] and out["url"].endswith("&tokens=3000")


@pytest.mark.parametrize("v4_on, charged, code", [
    (True, ChargeResult(False, 0, 100_000, "insufficient", "coach_time"), "NOT_ENOUGH_TOKENS"),
    (True, ChargeResult(True, 0, 0, "account_unavailable", "coach_time"), "PAYMENT_ERROR"),
    (False, None, "TOKENS_OFF"),
])
def test_a_call_tokens_cannot_pay_for_is_not_booked(monkeypatch, page, v4_on, charged, code):
    monkeypatch.setenv("PRICING_V4_ENABLED", "1" if v4_on else "0")
    monkeypatch.setenv("TOKEN_PRICING_ENABLED", "1")
    db, confirm = page
    with patch("services.token_account.charge", return_value=charged), \
            pytest.raises(booking.BookingError) as refused:
        _book()
    assert refused.value.code == code
    confirm.assert_not_called()
    if v4_on:   # the slot was held, then given back
        db.client.table.return_value.update.assert_any_call({"status": "cancelled"})
