#!/usr/bin/env python3
"""Test script to verify JWKS endpoint connectivity"""
import urllib.request
import urllib.error
import json
import os

# Try to load from .env if available, otherwise use default
try:
    from dotenv import load_dotenv
    load_dotenv()
    SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zignvkswxvtvdzctpkcr.supabase.co")
except ImportError:
    # If dotenv not available, use default URL
    SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zignvkswxvtvdzctpkcr.supabase.co")

# Normalize URL (add https:// if missing)
if SUPABASE_URL and not SUPABASE_URL.startswith(('http://', 'https://')):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_URL = SUPABASE_URL.rstrip('/')

def test_jwks_endpoint():
    """Test if we can reach the Supabase JWKS endpoint"""
    # Supabase JWKS endpoint is at /auth/v1/.well-known/jwks.json
    jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    
    print(f"Testing JWKS endpoint: {jwks_url}")
    print("-" * 60)
    
    try:
        req = urllib.request.Request(jwks_url)
        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            print(f"Status Code: {status_code}")
            
            if status_code == 200:
                data = response.read()
                jwks = json.loads(data.decode('utf-8'))
                print("✅ SUCCESS: JWKS endpoint is reachable")
                print(f"Number of keys: {len(jwks.get('keys', []))}")
                if jwks.get('keys'):
                    print(f"First key ID (kid): {jwks['keys'][0].get('kid')}")
                    print(f"First key algorithm: {jwks['keys'][0].get('alg')}")
                return True
            else:
                print(f"❌ FAILED: Got status code {status_code}")
                return False
                
    except urllib.error.HTTPError as e:
        print(f"❌ FAILED: HTTP Error {e.code}")
        print(f"Response: {e.read().decode('utf-8')}")
        return False
    except urllib.error.URLError as e:
        print(f"❌ FAILED: URL Error - {str(e)}")
        print("This might indicate network restrictions or incorrect URL")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error - {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_jwks_endpoint()
    exit(0 if success else 1)
