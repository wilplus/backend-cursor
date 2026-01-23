import sentry_sdk
import os
from dotenv import load_dotenv

load_dotenv()

dsn = os.getenv("SENTRY_DSN")

if not dsn:
    print("⚠️  SENTRY_DSN not set in .env")
    print("Skipping Sentry test. Add your DSN to test.")
    exit(0)

sentry_sdk.init(
    dsn=dsn,
    traces_sample_rate=1.0,
)

# Trigger a test error
try:
    1 / 0
except Exception as e:
    sentry_sdk.capture_exception(e)

print("✅ Test error sent to Sentry!")
print("Check your Sentry dashboard: https://sentry.io")
