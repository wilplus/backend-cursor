import jwt
import httpx
from functools import wraps
from flask import request, jsonify
from config import Config
import sentry_sdk

config = Config()

# Cache for JWKS
_jwks_cache = None
_jwks_cache_expiry = None

def get_jwks():
    """Fetch JWKS from Supabase"""
    global _jwks_cache, _jwks_cache_expiry
    import time
    
    # Return cached JWKS if still valid (cache for 1 hour)
    if _jwks_cache and _jwks_cache_expiry and time.time() < _jwks_cache_expiry:
        return _jwks_cache
    
    try:
        jwks_url = f"{config.SUPABASE_URL}/.well-known/jwks.json"
        response = httpx.get(jwks_url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_expiry = time.time() + 3600  # 1 hour cache
        return _jwks_cache
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise Exception("Failed to fetch JWKS")

def get_signing_key(token):
    """Get the signing key for a JWT token from JWKS"""
    jwks = get_jwks()
    unverified_header = jwt.get_unverified_header(token)
    
    for key in jwks.get("keys", []):
        if key["kid"] == unverified_header.get("kid"):
            return jwt.algorithms.RSAAlgorithm.from_jwk(key)
    
    raise Exception("Unable to find appropriate key")

def verify_supabase_token(token):
    """Verify Supabase JWT token and return payload"""
    try:
        # Get signing key from JWKS
        signing_key = get_signing_key(token)
        
        # Verify token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience="authenticated",
            issuer=f"{config.SUPABASE_URL}/auth/v1",
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True}
        )
        
        return payload
    except jwt.ExpiredSignatureError:
        raise Exception("Token expired")
    except jwt.InvalidTokenError as e:
        raise Exception(f"Invalid token: {str(e)}")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise Exception(f"Token verification failed: {str(e)}")

def require_auth(f):
    """Decorator to require valid Supabase JWT authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            return jsonify({"code": "UNAUTHORIZED", "error": "Missing Authorization header"}), 401
        
        try:
            # Extract token from "Bearer <token>"
            token = auth_header.replace("Bearer ", "").strip()
            
            # Verify token
            payload = verify_supabase_token(token)
            
            # Extract user_id from token
            user_id = payload.get("sub")
            if not user_id:
                return jsonify({"code": "UNAUTHORIZED", "error": "Invalid token payload"}), 401
            
            # Attach user_id to request context
            request.user_id = user_id
            request.token_payload = payload
            
        except Exception as e:
            return jsonify({"code": "UNAUTHORIZED", "error": str(e)}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function
