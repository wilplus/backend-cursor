"""The test run's defaults.

By invitation (N471, N473) is on in the product from its go-live moment.
The rest of the suite tests routes as they work for a member or a guest of
before, so the run starts with the switch off; tests/test_membership.py turns
it on for itself.
"""
import os

os.environ.setdefault("INVITE_ONLY_SINCE", "off")

# The noticing settings record (services/noticing_settings.py) is read from
# the database in production; the run reads none, so today's constants stand.
from services import noticing_settings  # noqa: E402

noticing_settings.use_reader(lambda: None)
