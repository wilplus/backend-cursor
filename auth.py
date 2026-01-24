import jwt
from jwt import PyJWKClient
from functools import wraps
from flask import request, jsonify
from config import Config
import sentry_sdk
import logging

config = Config()
logger = logging.getLogger(__name__)

# Global JWKS client (PyJWKClient handles caching automatically)
_jwks_client = None

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

def get_jwks_client():
    """Get or create the JWKS client"""
    global _jwks_client
    
    if _jwks_client is None:
        try:
            # Normalize URL to ensure it has protocol
            supabase_url = _normalize_supabase_url(config.SUPABASE_URL)
            jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
            
            logger.info(f"Initializing JWKS client with URL: {jwks_url}")
            
            # PyJWKClient automatically handles:
            # - Caching of JWKS (enabled by default)
            # - Key rotation
            # - Error handling
            # - Retries
            # Simple initialization - PyJWKClient handles caching automatically
            _jwks_client = PyJWKClient(jwks_url)
            
            logger.info("JWKS client initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize JWKS client: {str(e)}"
            logger.error(error_msg)
            sentry_sdk.capture_exception(e)
            raise Exception(f"JWKS client initialization failed: {str(e)}")
    
    return _jwks_client

def get_signing_key(token):
    """Get the signing key for a JWT token from JWKS using PyJWKClient"""
    try:
        # First, check the token algorithm
        unverified_header = jwt.get_unverified_header(token)
        algorithm = unverified_header.get("alg")
        
        # If token uses HS256 (HMAC), use JWT secret instead of JWKS
        if algorithm == "HS256":
            if not config.SUPABASE_JWT_SECRET:
                raise Exception("HS256 token requires SUPABASE_JWT_SECRET but it's not configured")
            logger.debug("Token uses HS256, verifying with JWT secret")
            return config.SUPABASE_JWT_SECRET
        
        # For ES256/RS256, use JWKS
        jwks_client = get_jwks_client()
        
        # PyJWKClient automatically:
        # - Fetches the JWKS if not cached
        # - Finds the correct key by kid from the token header
        # - Handles key rotation
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        
        logger.debug(f"Successfully retrieved signing key for token")
        return signing_key.key
        
    except jwt.DecodeError as e:
        logger.error(f"Failed to decode JWT header: {str(e)}")
        raise Exception(f"Invalid token format: {str(e)}")
    except Exception as e:
        error_msg = f"Error getting signing key: {str(e)}"
        logger.error(error_msg)
        sentry_sdk.capture_exception(e)
        raise Exception(f"Failed to get signing key from JWKS: {str(e)}")

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
        # Check algorithm to determine which algorithms to allow
        unverified_header = jwt.get_unverified_header(token)
        algorithm = unverified_header.get("alg")
        
        if algorithm == "HS256":
            # HS256 uses symmetric key (JWT secret)
            algorithms = ["HS256"]
        else:
            # ES256/RS256 use asymmetric keys from JWKS
            algorithms = ["ES256", "RS256"]
        
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=algorithms,
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
