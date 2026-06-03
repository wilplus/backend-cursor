"""Unit tests for services.domains (willab beta §2 — domain enum + seed).

Dependency-free module; no stubs needed.

Run: python3 -m unittest test_domains
"""
from __future__ import annotations

import unittest


class DomainEnumTests(unittest.TestCase):

    def test_exactly_five_domains(self):
        from services.domains import VALID_DOMAINS
        self.assertEqual(len(VALID_DOMAINS), 5)

    def test_canonical_keys(self):
        from services.domains import VALID_DOMAINS
        self.assertEqual(set(VALID_DOMAINS), {
            "public_speaking", "sales", "executive_presence",
            "customer_service", "interview_prep",
        })

    def test_is_valid_domain(self):
        from services.domains import is_valid_domain
        self.assertTrue(is_valid_domain("sales"))
        self.assertFalse(is_valid_domain("marketing"))
        self.assertFalse(is_valid_domain(None))
        self.assertFalse(is_valid_domain(42))
        self.assertFalse(is_valid_domain(""))


class VocabSeedTests(unittest.TestCase):

    def test_every_domain_has_a_seed(self):
        from services.domains import VALID_DOMAINS, DOMAIN_VOCABULARY_SEED
        for d in VALID_DOMAINS:
            self.assertIn(d, DOMAIN_VOCABULARY_SEED)
            self.assertTrue(len(DOMAIN_VOCABULARY_SEED[d]) >= 1)

    def test_default_returns_list_copy(self):
        from services.domains import default_domain_vocabulary
        out = default_domain_vocabulary("sales")
        self.assertIsInstance(out, list)
        self.assertIn("objection", out)
        # mutating the returned list must not corrupt the seed
        out.append("XXX")
        self.assertNotIn("XXX", default_domain_vocabulary("sales"))

    def test_unknown_domain_returns_empty(self):
        from services.domains import default_domain_vocabulary
        self.assertEqual(default_domain_vocabulary("nope"), [])
        self.assertEqual(default_domain_vocabulary(None), [])

    def test_seed_matches_spec_public_speaking(self):
        """Spot-check one domain against the §2 table verbatim."""
        from services.domains import default_domain_vocabulary
        self.assertEqual(
            default_domain_vocabulary("public_speaking"),
            ["keynote", "slide", "audience", "podium", "Q&A", "pacing"],
        )


if __name__ == "__main__":
    unittest.main()
