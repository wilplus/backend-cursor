#!/usr/bin/env python3
"""Test script to verify JWKS endpoint connectivity"""
import requests
import os
from dotenv import load_dotenv

load_dotenv()

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
        response = requests.get(jwks_url, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ SUCCESS: JWKS endpoint is reachable")
            jwks = response.json()
            print(f"Number of keys: {len(jwks.get('keys', []))}")
            if jwks.get('keys'):
                print(f"First key ID (kid): {jwks['keys'][0].get('kid')}")
            return True
        else:
            print(f"❌ FAILED: Got status code {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ FAILED: Request timed out after 10 seconds")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ FAILED: Connection error - {str(e)}")
        print("This might indicate network restrictions or incorrect URL")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error - {str(e)}")
        return False

if __name__ == "__main__":
    success = test_jwks_endpoint()
    exit(0 if success else 1)
