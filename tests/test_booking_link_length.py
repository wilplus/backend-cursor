"""
STORY    As the founder, I want a link without a price that books a short
         kick-off of the length I set, so that a new person on the corporate
         plan can sign up and book it when it suits them.
OUTCOME
  O1  A link with a length shows that length, offers only times that fit it
      and books exactly that long, with nothing to pay.
  O2  An edited link gives the normal page and its normal length.
  O3  A link made before links had a length still works, at the page's length.
PROVES   O1 -> test_a_link_with_a_length_shows_it_offers_times_that_fit_and_books_that_long
         O2 -> test_an_edited_link_gives_the_normal_page
         O3 -> test_a_link_made_before_lengths_existed_keeps_the_page_length
WHY      Founder 2026-10-25.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from services import booking

SETTINGS = {"id": 1, "slug": "artur", "enabled": True, "title": "1-on-1 lesson", "host_name": "Artur",
            "duration_min": 60, "price_cents": 12000, "currency": "usd", "horizon_days": 30,
            "timezone": "Europe/Warsaw", "new_user_discount_pct": 50, "buffer_before_min": 0,
            "buffer_after_min": 0, "notice_hours": 0,
            "weekly_hours": {str(d): [["00:00", "23:59"]] for d in range(7)},
            "calendar_ics_url": "", "meet_url": "https://meet.google.com/x"}
ONE_HOUR = {**SETTINGS, "weekly_hours": {str(d): [["09:00", "10:00"]] for d in range(7)}}
# Made by the code before 2026-10-25, with the secret "test-secret": a link
# the founder may already have sent.
LINK_MADE_BEFORE_LENGTHS = "0-605fe4621e93dfe9c30f816f"


@pytest.fixture(autouse=True)
def _setup():
    with patch.object(booking.config, "SUPABASE_JWT_SECRET", "test-secret", create=True), \
            patch.object(booking, "get_settings", return_value=dict(SETTINGS)), \
            patch.object(booking, "user_price", return_value=None):
        yield


def test_a_link_with_a_length_shows_it_offers_times_that_fit_and_books_that_long():
    link = booking.make_price_link(0, 15)
    page = booking.public_settings("artur", link)
    assert page["duration_min"] == 15 and page["hide_price"] is True

    # An hour of opening hours: four quarter-hour starts, one hour-long start.
    day = datetime(2030, 1, 7, tzinfo=timezone.utc)
    window = dict(now=datetime(2030, 1, 1, tzinfo=timezone.utc), busy=[])
    short = booking.open_slots(booking.settings_for_link(ONE_HOUR, link), day, day + timedelta(days=1), **window)
    assert [(s - short[0]).seconds // 60 for s in short] == [0, 15, 30, 45]
    assert len(booking.open_slots(ONE_HOUR, day, day + timedelta(days=1), **window)) == 1

    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
    with patch.object(booking, "db", MagicMock()) as db, patch.object(booking, "_confirm"):
        booking.start_checkout(slug="artur", user_id="u1", start_iso=start.isoformat(), name="A",
                               email="a@x.co", guest_timezone="UTC", link=link)
    held = db.client.rpc.call_args.args[1]
    assert booking._dt(held["p_end_at"]) - booking._dt(held["p_start_at"]) == timedelta(minutes=15)
    assert held["p_price_cents"] == 0


def test_an_edited_link_gives_the_normal_page():
    sig = booking.make_price_link(0, 15).split("-")[2]
    for edited in (f"0-60-{sig}", f"0-{sig}"):  # a longer meeting; the length cut off
        page = booking.public_settings("artur", edited)
        assert page["duration_min"] == 60 and "hide_price" not in page


def test_a_link_made_before_lengths_existed_keeps_the_page_length():
    page = booking.public_settings("artur", LINK_MADE_BEFORE_LENGTHS)
    assert page["hide_price"] is True and page["duration_min"] == 60
