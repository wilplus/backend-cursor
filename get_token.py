#!/usr/bin/env python3
"""Script to get a JWT token from Supabase for testing"""
import os
from dotenv import load_dotenv

load_dotenv()

def get_token_from_supabase():
    """Get a JWT token by signing in to Supabase"""
    try:
        from supabase import create_client
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url:
            print("❌ SUPABASE_URL not found in .env")
            return None
        
        if not supabase_key:
            print("❌ SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY not found in .env")
            print("   You need one of these to create a Supabase client")
            return None
        
        print(f"Connecting to Supabase: {supabase_url}")
        supabase = create_client(supabase_url, supabase_key)
        
        # Get email and password from user
        print("\n" + "="*60)
        print("Enter your Supabase credentials to get a token")
        print("="*60)
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        
        print("\nSigning in...")
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if response.session:
            token = response.session.access_token
            print("\n✅ SUCCESS! Token retrieved:")
            print("-" * 60)
            print(token)
            print("-" * 60)
            print("\nYou can now use this token to test your Flask backend:")
            print(f'curl -H "Authorization: Bearer {token}" http://localhost:5000/user/profile')
            print("\nOr use the test script:")
            print(f'python3 test_auth_request.py "{token}"')
            return token
        else:
            print("❌ Failed to get session")
            return None
            
    except ImportError:
        print("❌ supabase package not installed")
        print("   Install it with: pip install supabase")
        return None
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    get_token_from_supabase()
