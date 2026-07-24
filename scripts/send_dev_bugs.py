#!/usr/bin/env python3
"""Send the dev-bugs digest (standalone alternative to bin/railway-devbugs-cron.sh).

Emails all OPEN dev-bugs to config.DEV_BUGS_TO as an LLM-ready triage prompt
(images attached) and marks them shipped. This runs the SAME routine as the
"Send now" button and the curl cron — use whichever fits your Railway setup.

Railway cron (Pattern B — no HTTP round-trip): second service, Start Command:
    python3 scripts/send_dev_bugs.py
Cron Schedule: 0 9 */3 * *   (every 3rd day). This path needs the app env
(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RESEND_API_KEY, SEND_EMAILS=true,
DEV_BUGS_TO) on the cron service.
"""
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main() -> int:
    from services.dev_bugs import send_open_bugs
    try:
        n = send_open_bugs()
    except Exception as e:  # noqa: BLE001
        print(f"dev-bugs: send failed: {e}", file=sys.stderr)
        return 1
    print(f"dev-bugs: sent {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
