import jwt
import httpx
from functools import wraps
from flask import request, jsonify
from config import Config
import sentry_sdk
import logging
import time

config = Config()
logger = logging.getLogger(__name__)

# Cache for JWKS
_jwks_cache = None
_jwks_cache_expiry = None

def _normalize_supabase_url(url):
    """Ensure Supabase URL has proper protocol"""
    if not url:
        raise ValueError("SUPABASE_URL is not configured")
    
    # Remove trailing slash if present
    url = url.rstrip('/')
    
    # Add https:// if no protocol is specified
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    return url

def get_jwks():
    """Fetch JWKS from Supabase"""
    global _jwks_cache, _jwks_cache_expiry
    
    # Return cached JWKS if still valid (cache for 1 hour)
    if _jwks_cache and _jwks_cache_expiry and time.time() < _jwks_cache_expiry:
        logger.debug("Using cached JWKS")
        return _jwks_cache
    
    try:
        # Normalize URL to ensure it has protocol
        supabase_url = _normalize_supabase_url(config.SUPABASE_URL)
        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        
        logger.info(f"Fetching JWKS from: {jwks_url}")
        
        response = httpx.get(jwks_url, timeout=10)
        response.raise_for_status()
        
        _jwks_cache = response.json()
        _jwks_cache_expiry = time.time() + 3600  # 1 hour cache
        
        logger.info(f"Successfully fetched JWKS with {len(_jwks_cache.get('keys', []))} keys")
        return _jwks_cache
        
    except httpx.TimeoutException:
        supabase_url = _normalize_supabase_url(config.SUPABASE_URL) if config.SUPABASE_URL else "unknown"
        jwks_url = f"{supabase_url}/.well-known/jwks.json"
        error_msg = f"Timeout while fetching JWKS from {jwks_url}"
        logger.error(error_msg)
        sentry_sdk.capture_message(error_msg, level="error")
        raise Exception(f"JWKS fetch timeout: Unable to reach Supabase JWKS endpoint. Check network connectivity.")
    except httpx.RequestError as e:
        error_msg = f"Network error while fetching JWKS: {str(e)}"
        logger.error(error_msg)
        sentry_sdk.capture_exception(e)
        raise Exception(f"JWKS fetch failed: Network error. Verify SUPABASE_URL is correct and network access is available.")
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code} while fetching JWKS: {e.response.text}"
        logger.error(error_msg)
        sentry_sdk.capture_message(error_msg, level="error")
        raise Exception(f"JWKS fetch failed: HTTP {e.response.status_code}. Verify SUPABASE_URL is correct.")
    except Exception as e:
        error_msg = f"Unexpected error fetching JWKS: {str(e)}"
        logger.error(error_msg)
        sentry_sdk.capture_exception(e)
        raise Exception(f"Failed to fetch JWKS: {str(e)}")

def get_signing_key(token):
    """Get the signing key for a JWT token from JWKS"""
    try:
        jwks = get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        token_kid = unverified_header.get("kid")
        
        logger.debug(f"Looking for key with kid: {token_kid}")
        
        if not jwks.get("keys"):
            raise Exception("JWKS contains no keys")
        
        for key in jwks.get("keys", []):
            if key.get("kid") == token_kid:
                logger.debug(f"Found matching key with kid: {token_kid}")
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)
        
        available_kids = [k.get("kid") for k in jwks.get("keys", [])]
        error_msg = f"Unable to find key with kid '{token_kid}'. Available kids: {available_kids}"
        logger.warning(error_msg)
        raise Exception(error_msg)
    except jwt.DecodeError as e:
        logger.error(f"Failed to decode JWT header: {str(e)}")
        raise Exception(f"Invalid token format: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting signing key: {str(e)}")
        raise

def verify_supabase_token(token):
    """Verify Supabase JWT token and return payload"""
    try:
        # Get signing key from JWKS
        signing_key = get_signing_key(token)
        
        # Normalize Supabase URL for issuer verification
        supabase_url = _normalize_supabase_url(config.SUPABASE_URL)
        issuer = f"{supabase_url}/auth/v1"
        
        logger.debug(f"Verifying token with issuer: {issuer}")
        
        # Verify token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience="authenticated",
            issuer=issuer,
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True}
        )
        
        logger.debug(f"Token verified successfully for user: {payload.get('sub')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        raise Exception("Token expired")
    except jwt.InvalidAudienceError:
        logger.warning("Token has invalid audience")
        raise Exception("Invalid token audience")
    except jwt.InvalidIssuerError:
        logger.warning(f"Token has invalid issuer. Expected: {issuer}")
        raise Exception(f"Invalid token issuer")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        raise Exception(f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"Token verification failed: {str(e)}")

def require_auth(f):
    """Decorator to require valid Supabase JWT authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            logger.warning("Missing Authorization header")
            return jsonify({"code": "UNAUTHORIZED", "error": "Missing Authorization header"}), 401
        
        try:
            # Extract token from "Bearer <token>"
            if not auth_header.startswith("Bearer "):
                logger.warning("Authorization header missing Bearer prefix")
                return jsonify({"code": "UNAUTHORIZED", "error": "Authorization header must start with 'Bearer '"}), 401
            
            token = auth_header.replace("Bearer ", "").strip()
            
            if not token:
                logger.warning("Empty token in Authorization header")
                return jsonify({"code": "UNAUTHORIZED", "error": "Token is empty"}), 401
            
            # Verify token
            payload = verify_supabase_token(token)
            
            # Extract user_id from token
            user_id = payload.get("sub")
            if not user_id:
                logger.warning("Token payload missing 'sub' field")
                return jsonify({"code": "UNAUTHORIZED", "error": "Invalid token payload: missing user ID"}), 401
            
            # Attach user_id to request context
            request.user_id = user_id
            request.token_payload = payload
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Authentication failed: {error_msg}")
            return jsonify({"code": "UNAUTHORIZED", "error": error_msg}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function
