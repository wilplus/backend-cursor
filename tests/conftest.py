"""The test run's defaults.

By invitation (N471, N473) is on in the product from its go-live moment.
The rest of the suite tests routes as they work for a member or a guest of
before, so the run starts with the switch off; tests/test_membership.py turns
it on for itself.
"""
import os

os.environ.setdefault("INVITE_ONLY_SINCE", "off")
