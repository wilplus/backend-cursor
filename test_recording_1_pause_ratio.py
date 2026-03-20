import unittest

from services.pause_ratio_selector import select_pause_ratio


class Recording1PauseRatioSelectionTests(unittest.TestCase):
    def test_audio_first_when_request_missing(self):
        value, source = select_pause_ratio(
            b"fake-audio",
            None,
            lambda _audio: 0.27,
        )
        self.assertEqual(source, "audio")
        self.assertAlmostEqual(value, 0.27, places=6)
        self.assertNotAlmostEqual(value, 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
