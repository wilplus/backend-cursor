import requests
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BASE_URL = "http://localhost:5000"

print("🧪 Integration Test Suite\n")
print("=" * 50)

# Test 1: Health Check
print("\n1️⃣  Testing health endpoint...")
try:
    response = requests.get(f"{BASE_URL}/health")
    if response.status_code == 200:
        print("✅ Health check passed")
        print(f"   Response: {response.json()}")
    else:
        print(f"❌ Health check failed: {response.status_code}")
except Exception as e:
    print(f"❌ Health check error: {e}")

# Test 2: Database Connection
print("\n2️⃣  Testing database connection...")
try:
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    questions = supabase.table('pre_recording_questions').select('*').execute()
    print(f"✅ Database connected")
    print(f"   Found {len(questions.data)} pre-recording questions")
    for q in questions.data:
        print(f"   - {q['question_text']}")
except Exception as e:
    print(f"❌ Database error: {e}")

# Test 3: Storage Connection
print("\n3️⃣  Testing storage connection...")
try:
    files = supabase.storage.from_('audio_recordings').list()
    print("✅ Storage bucket accessible")
    print(f"   Bucket: audio_recordings")
    print(f"   Files in bucket: {len(files)}")
except Exception as e:
    print(f"❌ Storage error: {e}")

# Test 4: OpenAI API Key
print("\n4️⃣  Testing OpenAI API key...")
try:
    if os.getenv("OPENAI_API_KEY", "").startswith("sk-"):
        print("✅ OpenAI API key format valid")
    else:
        print("❌ OpenAI API key missing or invalid format")
except Exception as e:
    print(f"❌ OpenAI error: {e}")

# Test 5: Resend Email
print("\n5️⃣  Testing Resend configuration...")
try:
    if os.getenv("RESEND_API_KEY", "").startswith("re_"):
        print("✅ Resend API key format valid")
        print(f"   From email: {os.getenv('RESEND_FROM_EMAIL')}")
    else:
        print("❌ Resend API key missing or invalid format")
except Exception as e:
    print(f"❌ Resend error: {e}")

print("\n" + "=" * 50)
print("🏁 Integration tests complete!\n")
