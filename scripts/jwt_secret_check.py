import os
from dotenv import load_dotenv

load_dotenv()

jwt_secret = os.getenv('SUPABASE_JWT_SECRET')

print("\n" + "="*60)
print("TESTING JWT SECRET")
print("="*60)

if not jwt_secret:
    print("❌ SUPABASE_JWT_SECRET not found in .env")
else:
    print(f"✅ JWT Secret loaded (length: {len(jwt_secret)} chars)")
    print(f"✅ First 20 chars: {jwt_secret[:20]}...")
    print("\nJWT verification method: HS256 with secret")
    print("This is the CORRECT method for Supabase!")

print("="*60 + "\n")
