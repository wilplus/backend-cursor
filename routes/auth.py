from flask import Blueprint, request, jsonify
from supabase import create_client
from config import Config
from auth import require_auth
import sentry_sdk

auth_bp = Blueprint("auth", __name__)
config = Config()

@auth_bp.route("/signup", methods=["POST"])
def signup():
    """Sign up a new user via Supabase"""
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({"code": "INVALID_INPUT", "error": "Email and password required"}), 400
        
        # Create Supabase client (public anon key would be used by frontend, but we can use service role for admin ops)
        # For signup, frontend typically handles this, but we provide endpoint for consistency
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        
        # Sign up user
        response = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True  # Auto-confirm in backend
        })
        
        if not response.user:
            return jsonify({"code": "SIGNUP_FAILED", "error": "Failed to create user"}), 400
        
        # Return user (frontend will handle session)
        return jsonify({
            "user": {
                "id": response.user.id,
                "email": response.user.email
            }
        }), 201
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "SIGNUP_ERROR", "error": str(e)}), 500

@auth_bp.route("/login", methods=["POST"])
def login():
    """Login user via Supabase password grant"""
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({"code": "INVALID_INPUT", "error": "Email and password required"}), 400
        
        # Use Supabase client for password grant
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        
        # Sign in
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if not response.session:
            return jsonify({"code": "LOGIN_FAILED", "error": "Invalid credentials"}), 401
        
        # Return Supabase session tokens
        return jsonify({
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
            "user": {
                "id": response.user.id,
                "email": response.user.email
            }
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "LOGIN_ERROR", "error": str(e)}), 500

@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    """Trigger password reset email via Supabase"""
    try:
        data = request.get_json()
        email = data.get("email")
        
        if not email:
            return jsonify({"code": "INVALID_INPUT", "error": "Email required"}), 400
        
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        
        # Send reset email
        supabase.auth.reset_password_for_email(email)
        
        return jsonify({"message": "Password reset email sent"}), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RESET_ERROR", "error": str(e)}), 500
