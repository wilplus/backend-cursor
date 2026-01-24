#!/usr/bin/env python3
"""Test script to make an authenticated request to Flask backend"""
import urllib.request
import urllib.error
import json
import sys

def test_authenticated_request(token, endpoint="http://localhost:5000/user/profile"):
    """
    Test an authenticated request to the Flask backend
    
    Args:
        token: Supabase JWT token (get this from your frontend or Supabase client)
        endpoint: Flask backend endpoint URL
    """
    print(f"Testing authenticated request to: {endpoint}")
    print("-" * 60)
    
    # Create request with Authorization header
    req = urllib.request.Request(endpoint)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            data = response.read()
            result = json.loads(data.decode('utf-8'))
            
            print(f"Status Code: {status_code}")
            print(f"Response: {json.dumps(result, indent=2)}")
            
            if status_code == 200:
                print("\n✅ SUCCESS: Authentication worked!")
                return True
            else:
                print(f"\n❌ FAILED: Got status code {status_code}")
                return False
                
    except urllib.error.HTTPError as e:
        data = e.read().decode('utf-8')
        print(f"❌ FAILED: HTTP Error {e.code}")
        try:
            error_json = json.loads(data)
            print(f"Error: {json.dumps(error_json, indent=2)}")
        except:
            print(f"Response: {data}")
        return False
    except urllib.error.URLError as e:
        print(f"❌ FAILED: URL Error - {str(e)}")
        print("Make sure Flask is running on http://localhost:5000")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error - {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_auth_request.py <JWT_TOKEN> [endpoint]")
        print("\nExample:")
        print("  python3 test_auth_request.py 'your-supabase-jwt-token'")
        print("  python3 test_auth_request.py 'your-token' 'http://localhost:5000/user/profile'")
        print("\nTo get a token:")
        print("  1. From your frontend: Check browser DevTools > Application > Local Storage")
        print("     Look for 'sb-<project-ref>-auth-token'")
        print("  2. From Supabase client:")
        print("     from supabase import create_client")
        print("     supabase = create_client(url, key)")
        print("     response = supabase.auth.sign_in_with_password({'email': '...', 'password': '...'})")
        print("     token = response.session.access_token")
        sys.exit(1)
    
    token = sys.argv[1]
    endpoint = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:5000/user/profile"
    
    success = test_authenticated_request(token, endpoint)
    sys.exit(0 if success else 1)
