"""The shared /v2 blueprint object.

Lives in its own module so domain modules under ``routes/v2/`` can register
routes on it without importing ``routes.v2_routes`` (which would be a
cycle). The blueprint NAME stays "v2", so endpoint names ("v2.<view_func>")
and therefore the URL map are identical to before the split.
"""
from flask import Blueprint

v2_bp = Blueprint("v2", __name__, url_prefix="/v2")
