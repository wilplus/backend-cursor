"""
STORY    As a guest speaker, I want only my own guest token to open my
         projects, and none once the account is claimed, so that nobody else
         can open my work.
OUTCOME
  O1  The token issued to a guest opens that guest's own unclaimed principal.
  O2  The same token is refused once the principal is claimed, and against
      another guest's secret.
PROVES   O1 -> test_my_own_guest_token_opens_my_projects
         O2 -> test_claimed_or_wrong_guest_owner_is_rejected
"""
from services.project_ownership import (
    issue_guest_owner,
    verify_guest_owner,
)


def test_my_own_guest_token_opens_my_projects():
    issued = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": issued.secret_hash,
    }) == issued.principal_id


def test_claimed_or_wrong_guest_owner_is_rejected():
    issued = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": "permanent-user",
        "guest_secret_hash": issued.secret_hash,
    }) is None
    other = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": other.secret_hash,
    }) is None
