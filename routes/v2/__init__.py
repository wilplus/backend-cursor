"""Domain modules carved out of the routes/v2_routes.py god-file.

Every module here registers on the shared ``v2_bp`` from
``routes.v2.blueprint``, so endpoint names and the URL map are unchanged
by the split.
"""

# Import order is load-bearing: every module below registers its routes on
# the shared v2_bp at import time, and app.py must have imported all of them
# BEFORE the blueprint is registered on the app (Flask rejects route
# additions to an already-registered blueprint). This is the order the
# routes/v2_routes.py façade used until audit Q-A3 removed it (2026-09-14);
# endpoint names and the URL map are unchanged.
DOMAIN_MODULES = (
    "blueprint", "common", "arcs", "explore_ideal_text", "user_account",
    "mlc2_consent", "training_consent", "rooting_phrase_qualification",
    "confident_moment_bundles",
    # coach_guidance_delivery (the composers' lanes) was deleted with the
    # MLC-3 service loop (founder 2026-09-30, L8; contract 66); the two
    # mlc3_* modules stay as 410 tombstones so the map keeps its shape.
    "mlc3_first_client_service",
    "mlc3_first_client_coach", "confidence_chain_coach",
    "processing_authorization", "lounge", "coach",
    "coach_exercises", "coach_readings", "after_practice", "lend_your_ear",
    "communities",
    "coach_preference", "coach_audit", "coach_words",
    "coach_bubbles",
    "admin", "coaching", "canonical_publish", "auth_alias", "lab_recording",
    "projects", "learning_exposures", "user_sessions", "rings",
    "learning_admin", "research",
)


def register_domains() -> None:
    """Import every /v2 domain module, in order, so each registers its routes
    on ``routes.v2.blueprint.v2_bp``. Idempotent: Python caches imports."""
    import importlib

    for name in DOMAIN_MODULES:
        importlib.import_module(f"routes.v2.{name}")
