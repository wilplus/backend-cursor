from services.project_ownership import (
    issue_guest_owner,
    verify_guest_owner,
)


def test_claimed_or_wrong_guest_owner_is_rejected():
    issued = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": "permanent-user",
        "guest_secret_hash": None,
    }) is None
    other = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": other.secret_hash,
    }) is None
