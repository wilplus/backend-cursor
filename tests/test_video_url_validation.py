#!/usr/bin/env python3
"""Tests for send-assignment video_url validation. Run: python3 test_video_url_validation.py"""
import sys
sys.path.insert(0, ".")
from services.video_url_validation import validate_video_url, VIDEO_URL_MAX_LENGTH


def test_valid_https():
    assert validate_video_url("https://example.com/watch?v=1") == "https://example.com/watch?v=1"
    assert validate_video_url("  https://loom.com/share/abc  ") == "https://loom.com/share/abc"


def test_valid_http():
    assert validate_video_url("http://example.com/v") == "http://example.com/v"


def test_rejected():
    assert validate_video_url(None) is None
    assert validate_video_url("") is None
    assert validate_video_url("   ") is None
    assert validate_video_url("ftp://x.com") is None
    assert validate_video_url("javascript:alert(1)") is None
    assert validate_video_url(123) is None
    assert validate_video_url([]) is None


def test_max_length():
    prefix = "https://example.com/"
    long_ok = prefix + "a" * (VIDEO_URL_MAX_LENGTH - len(prefix))
    assert validate_video_url(long_ok) is not None
    long_bad = prefix + "a" * (VIDEO_URL_MAX_LENGTH - len(prefix) + 1)
    assert validate_video_url(long_bad) is None


def main():
    test_valid_https()
    test_valid_http()
    test_rejected()
    test_max_length()
    print("OK: all validate_video_url tests passed")


if __name__ == "__main__":
    main()
