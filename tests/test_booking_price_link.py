"""
STORY    As the founder, I want to send a price link that charges exactly its
         price, by card, now, so that special prices can't be tampered with
         or used without paying.
OUTCOME
  O1  A link charges exactly its price, with no first-lesson discount;
      without the link the normal price and discount apply.
  O2  An edited link gives the normal price.
  O3  A link cannot be used to book without paying now (PAY_NOW).
  O4  A link set to zero shows no price and charges nothing.
PROVES   O1 -> test_link_charges_its_exact_price_with_no_first_lesson_discount
         O2 -> test_an_edited_link_gives_the_normal_price
         O3 -> test_a_link_cannot_book_without_paying
         O4 -> test_a_link_at_zero_shows_no_price_and_charges_nothing
WHY      Founder 2026-10-18.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services import booking

SETTINGS = {"id": 1, "slug": "artur", "enabled": True, "title": "1-on-1 lesson", "host_name": "Artur",
            "duration_min": 60, "price_cents": 12000, "currency": "usd", "horizon_days": 30,
            "timezone": "Europe/Warsaw", "new_user_discount_pct": 50}


@pytest.fixture(autouse=True)
def _setup():
    with patch.object(booking.config, "SUPABASE_JWT_SECRET", "test-secret", create=True), \
            patch.object(booking, "get_settings", return_value=dict(SETTINGS)), \
            patch.object(booking, "user_price", return_value=None):
        yield


def test_link_charges_its_exact_price_with_no_first_lesson_discount():
    link = booking.make_price_link(3500)
    assert booking.public_settings("artur", link)["new_user_price_cents"] == 3500
    offer = booking.offer_for("artur", "u1", link)
    assert offer["price_cents"] == 3500 and offer["price_link"] is True
    # Without the link: the normal page and the 50% first lesson.
    assert booking.offer_for("artur", "u1")["price_cents"] == 6000


def test_an_edited_link_gives_the_normal_price():
    sig = booking.make_price_link(3500).split("-")[1]
    assert booking.offer_for("artur", "u1", f"100-{sig}")["price_cents"] == 6000


def test_a_link_cannot_book_without_paying():
    with pytest.raises(booking.BookingError) as e:
        booking.start_checkout(slug="artur", user_id="u1", start_iso="2030-01-01T10:00:00Z",
                               name="A", email="a@x.co", guest_timezone="UTC",
                               skip_payment=True, link=booking.make_price_link(3500))
    assert e.value.code == "PAY_NOW"


def test_a_link_at_zero_shows_no_price_and_charges_nothing():
    link = booking.make_price_link(0)
    assert booking.public_settings("artur", link)["hide_price"] is True
    offer = booking.offer_for("artur", "u1", link)
    assert offer["price_cents"] == 0 and offer["list_price_cents"] == 0 and offer["hide_price"] is True
