"""Compatibility route for native account creation under the v2 prefix."""
from routes.v2.blueprint import v2_bp


@v2_bp.route("/auth/signup", methods=["POST"])
def v2_auth_signup():
    """Delegate to the canonical registration handler."""
    from routes.auth import signup as native_signup

    return native_signup()
