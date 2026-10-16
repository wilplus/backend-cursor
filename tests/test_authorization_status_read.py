"""The status read on every app open (founder 2026-10-16: it took ~600 ms).

The client reads `pending_deletion` only when the status says blocked and
never reads `pending_project_deletions`, so the two deletion reads run only
for a blocked person, and then side by side. An ordinary open pays the
status read alone.
"""
from __future__ import annotations

from services.processing_authorization import ProcessingAuthorizationService


class _Service(ProcessingAuthorizationService):
    def __init__(self, status):
        self._status, self.reads = status, []

    def status(self, principal_id):
        return dict(self._status)

    def pending_deletion(self, principal_id):
        self.reads.append("deletion")
        return {"kind": "account"}

    def pending_project_deletions(self, principal_id):
        self.reads.append("projects")
        return [{"id": "p1"}]


def test_an_ordinary_open_reads_the_status_alone():
    service = _Service({"authorized": True, "code": "OK"})
    out = service.status_with_deletions("principal-1")
    assert service.reads == []
    assert out["pending_deletion"] is None
    assert out["pending_project_deletions"] == []
    assert out["authorized"] is True


def test_a_blocked_person_gets_both_deletions():
    service = _Service({"authorized": False,
                        "code": "PROCESSING_SERVICE_BLOCKED"})
    out = service.status_with_deletions("principal-1")
    assert sorted(service.reads) == ["deletion", "projects"]
    assert out["pending_deletion"] == {"kind": "account"}
    assert out["pending_project_deletions"] == [{"id": "p1"}]
