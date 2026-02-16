#!/usr/bin/env python3
"""
Extract the JWT (access_token) from a Supabase auth cookie value.
Supabase splits the session across two cookies (.0 and .1). You can paste either:
- Just the .0 value (starts with base64-eyJ...), or
- The full cookie line including both: "...auth-token.0=base64-eyJ...; ...auth-token.1=jk1N..."
Usage:
  python scripts/extract_jwt_from_cookie.py 'base64-eyJ...'
  python scripts/extract_jwt_from_cookie.py '...auth-token.0=base64-eyJ...; ...auth-token.1=...'
"""
import base64
import json
import sys


def _parse_cookie_input(raw: str) -> str:
    """Return a single base64 string from one or two Supabase auth cookie parts."""
    raw = raw.strip()
    # Supabase uses auth-token.0 and auth-token.1; .0 value often starts with base64-
    if "auth-token.1=" in raw:
        idx = raw.find("auth-token.1=")
        value1 = raw[idx + len("auth-token.1=") :].strip()
        # Remove trailing cookie if present (e.g. "; other=foo")
        if ";" in value1:
            value1 = value1.split(";")[0].strip()
        value0_part = raw[:idx].strip()
        # value0_part is either "sb-...auth-token.0=base64-xxx" or just "base64-xxx" / "xxx"
        if "auth-token.0=" in value0_part:
            value0 = value0_part.split("auth-token.0=", 1)[1].strip()
        else:
            value0 = value0_part
        b64_0 = value0[7:] if value0.startswith("base64-") else value0
        return b64_0 + value1
    if "auth-token.0=" in raw:
        value0 = raw.split("auth-token.0=", 1)[1].strip()
        if ";" in value0:
            value0 = value0.split(";")[0].strip()
        raw = value0[7:] if value0.startswith("base64-") else value0
    elif raw.startswith("base64-"):
        raw = raw[7:]
    return raw


def main():
    if sys.stdin.isatty():
        if len(sys.argv) < 2:
            print("Paste the cookie value as argument, or pipe it:", file=sys.stderr)
            print("  python scripts/extract_jwt_from_cookie.py 'base64-eyJ...'", file=sys.stderr)
            sys.exit(1)
        raw = sys.argv[1].strip()
    else:
        raw = sys.stdin.read().strip()

    b64 = _parse_cookie_input(raw)
    # Keep only valid base64 chars (strip stray quotes, newlines, semicolons from paste)
    b64_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_")
    b64 = "".join(c for c in b64 if c in b64_chars)
    # Add padding if needed (base64 requires length multiple of 4)
    pad = 4 - len(b64) % 4
    if pad != 4:
        b64 = b64 + "=" * pad
    try:
        decoded = base64.b64decode(b64)
    except Exception as e:
        print(f"Base64 decode error: {e}", file=sys.stderr)
        print("Paste the FULL cookie value: copy both auth-token.0 and auth-token.1 from DevTools.", file=sys.stderr)
        sys.exit(1)
    try:
        session = json.loads(decoded.decode("utf-8"))
    except Exception as e:
        print(f"JSON parse error: {e}", file=sys.stderr)
        print("If you pasted both cookies, ensure .0 comes first and nothing is truncated.", file=sys.stderr)
        sys.exit(1)

    jwt = session.get("access_token")
    if not jwt:
        print("No access_token in cookie payload.", file=sys.stderr)
        sys.exit(1)

    print(jwt)

    # Optionally decode payload and print sub (user_id)
    parts = jwt.split(".")
    if len(parts) >= 2:
        try:
            payload_b64 = parts[1].replace("-", "+").replace("_", "/")
            pad = 4 - len(payload_b64) % 4
            if pad != 4:
                payload_b64 += "=" * pad
            payload_json = base64.b64decode(payload_b64).decode("utf-8")
            payload = json.loads(payload_json)
            sub = payload.get("sub")
            if sub:
                print(f"# user_id (sub): {sub}", file=sys.stderr)
        except Exception:
            pass


if __name__ == "__main__":
    main()
