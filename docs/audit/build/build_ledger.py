#!/usr/bin/env python3
"""Builds docs/audit/LEDGER.md from the audit (data_6oct), the splitter outputs,
the overnight findings (N), the V4 brief mapping (B) and the harness rows (X)."""

import json
import os
import re
import sys
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "LEDGER.md")
AUDIT_URL = "https://claude.ai/artifact/DwAgAoxxszUSd3WV5EJfMk"
DECISION_URL = "https://claude.ai/artifact/UXiVaBvGLRTg83kjmHKY6E"


def cell(s, n=None):
    s = re.sub(r"\s+", " ", str(s if s is not None else "")).strip()
    if n and len(s) > n:
        s = s[:n].rsplit(" ", 1)[0] + "…"
    return s.replace("|", "\\|") or "—"


d = json.load(open(os.path.join(HERE, "..", "night", "audit6", "data_6oct.json")))
lines = json.load(open(os.path.join(HERE, "open_lines.json")))
by_aid = {ln["aid"]: ln for ln in lines}
rows = []
for i in range(1, 7):
    rows += json.load(open(os.path.join(HERE, f"s{i}.out.json")))
N = json.load(open(os.path.join(HERE, "n_rows.json")))
X = json.load(open(os.path.join(HERE, "x_rows.json")))
mapA = (
    json.load(open(os.path.join(HERE, "mapA.out.json")))
    if os.path.exists(os.path.join(HERE, "mapA.out.json"))
    else []
)
DEC = json.load(open(os.path.join(HERE, "decided.json")))
N += json.load(open(os.path.join(HERE, "new_rows.json")))
mapB = (
    json.load(open(os.path.join(HERE, "mapB.out.json")))
    if os.path.exists(os.path.join(HERE, "mapB.out.json"))
    else {}
)

# ---- integrity checks
base_ids = [r["aid"] for r in rows]
assert len(base_ids) == len(set(base_ids)), "duplicate row ids"
covered = {re.match(r"A\d{3}", a).group(0) for a in base_ids}
missing = [ln["aid"] for ln in lines if ln["aid"] not in covered]
assert not missing, f"audit lines without a row: {missing}"
for r in rows:
    src = by_aid[re.match(r"A\d{3}", r["aid"]).group(0)]
    hay = src.get("unmet") or src.get("title") or ""
    assert r["quote"] in hay, f"quote not verbatim: {r['aid']}"

total_lines = sum(len(a["items"]) for a in d["areas"])
live = sum(1 for a in d["areas"] for it in a["items"] if it["status"] == "LIVE")
sup = sum(1 for a in d["areas"] for it in a["items"] if it["status"] == "SUPERSEDED")
splits = len(rows) - len(lines)


def status_cell(st, why):
    return f"{st} ({cell(why, 90)})" if why else st


out = []
w = out.append
w("# Audit ledger")
w("")
w(
    f"The ledger is the memory of the audit work. If it is not here, it did not happen. Sources of truth, in order: repo CLAUDE.md (fences, locks, filter) → the design lock ({cell('https://claude.ai/artifact/AeRVS91VUAiJLCePB82s3d')}) → the V4 decision page and its Developer brief ({DECISION_URL}) → the audit ({AUDIT_URL}, a list of claims, not facts)."
)
w("")
w(
    "Status values: OPEN, VERIFYING, CONFIRMED, FALSE, DUPLICATE, FOUNDER, PARKED, IN-PR, DONE. Rows are never deleted. Severity: S1 live loop broken · S2 data loss · S3 fence breach · S4 wrong behaviour · S5 cosmetic · S0 not a defect (a founder, ops, content or counsel step, a parked lane, a build item)."
)
w("")
w(
    "\"Verified?\" is **no** on every A-row: the audit is a claim until §2 checks it against the code. The audit evidence column is the audit's claimed evidence, kept as a lead for the verifier. The audit's `switch` field was not re-read on 6 October, so it is left out here."
)
w("")
w(
    "**Approved by the founder 6 October (Navigation Panel W1 A).** Decisions from the panel are applied as DECIDED notes; the full answers are in `docs/audit/PANEL-ANSWERS-2026-10-06.md`."
)
w("")
w("## Count check")
w("")
w(
    f'- The audit (6 October) graded **{total_lines}** lines: {live} LIVE and {sup} SUPERSEDED are "no finding"; the other **{len(lines)}** are findings.'
)
w(
    f"- Audit findings **{len(lines)} → ledger {len(rows)} A-rows** ({len(lines)} + {splits} splits). Every audit line maps to at least one row; every quote is checked verbatim against the audit text by the build script."
)
w(
    f'- Overnight findings (the audit\'s "First" and "What the checks found" sections, and the morning list): **{len(N)} N-rows**, duplicates marked.'
)
w(
    f"- V4 Developer brief: **{len(mapA) + len(mapB.get('build', []))} B-rows** (1.1–1.9 with 1.4b, the exit gate, 2.1–2.4, the six park items), plus the open questions O1–O3 as FOUNDER rows. Every decision row (M, P, W, Q, H, O, screens, rule changes) is mapped in the coverage table at the end."
)
w(f"- Harness: **{len(X)} X-rows**, for approval.")
w("")
st = collections.Counter(r["status"] for r in rows)
w("A-rows by status: " + ", ".join(f"{k} {v}" for k, v in st.most_common()) + ".")
w("")

hdr = "| ID | Source (audit section + exact quote) | Claim in one line | Area | Verified? | Evidence | Filter verdict | Severity | Plan | PR | Test | Status |"
sep = "|---|---|---|---|---|---|---|---|---|---|---|---|"

for n in N:
    if n["id"] in DEC:
        dd = DEC[n["id"]]
        n["status"] = dd["status"]
        n["why"] = "DECIDED " + dd["note"]
        if dd.get("pr"):
            n["pr"] = dd["pr"]
for r in rows:
    if r["aid"] in DEC:
        dd = DEC[r["aid"]]
        r["status"] = dd["status"]
        r["why"] = "DECIDED " + dd["note"]
for x in X:
    if x["id"] in DEC:
        dd = DEC[x["id"]]
        x["status"] = dd["status"]
        x["why"] = "DECIDED " + dd["note"]
for b in list(mapA) + list(mapB.get("build", [])):
    k = "B" + b["id"]
    if k in DEC:
        dd = DEC[k]
        b["status"] = dd["status"]
        b["why"] = "DECIDED " + dd["note"]
        b["unclear"] = ""
w("## N · Overnight findings")
w("")
w(hdr)
w(sep)
for n in N:
    w(
        f"| {n['id']} | {cell(n['source'])} | {cell(n['claim'])} | {n['area']} | {'yes' if n['status'] in ('DONE', 'IN-PR', 'CONFIRMED') else 'no'} | {cell(n['why']) if n['status'] == 'CONFIRMED' else '—'} | — | {n['severity']} | — | {cell(n.get('pr'))} | {cell(n.get('test'))} | {status_cell(n['status'], n['why'] if n['status'] != 'CONFIRMED' else '') + (' · QUESTION: ' + cell(n['unclear']) if n.get('unclear') else '')} |"
    )
w("")

w("## A · Audit findings")
w("")
cur = None
for r in rows:
    src = by_aid[re.match(r"A\d{3}", r["aid"]).group(0)]
    if src["area"] != cur:
        cur = src["area"]
        w("")
        w(f"### {src['area_title']}")
        w("")
        w(hdr)
        w(sep)
    ev = []
    if src.get("backend_evidence") and src["backend_evidence"] != "n/a":
        ev.append("be: " + src["backend_evidence"])
    if src.get("frontend_evidence") and src["frontend_evidence"] != "n/a":
        ev.append("fe: " + src["frontend_evidence"])
    source = f"{src['area_title']} · {src['line_id']} ({src['status']}): “{r['quote']}”"
    why = r.get("why") or ""
    if r.get("unclear"):
        why += " · QUESTION: " + r["unclear"]
    w(
        f"| {r['aid']} | {cell(source)} | {cell(r['claim'])} | {r['area']} | no | {cell(' · '.join(ev), 220)} | — | {r['severity'][:2]} | — | {cell(DEC.get(r['aid'], {}).get('pr'))} | {cell(DEC.get(r['aid'], {}).get('test'))} | {status_cell(r['status'], why) if (r['status'] != 'OPEN' or why.startswith('DECIDED')) else 'OPEN' + (' · QUESTION: ' + cell(r['unclear']) if r.get('unclear') else '')} |"
    )
w("")

w("## B · V4 Developer brief")
w("")
w(
    "Plan before code. Each row says what exists today, the gap, the files it touches, what it reuses and the done-test that proves it."
)
w("")
w(
    "| ID | Source (brief, exact) | Today | Gap | Plan (files · reuses · done-test) | Estimate | Depends on | Clash / risk | Status |"
)
w("|---|---|---|---|---|---|---|---|---|")
for b in list(mapA) + list(mapB.get("build", [])):
    plan = b.get("plan") or {}
    files = plan.get("files")
    files = ", ".join(files) if isinstance(files, list) else files
    reuses = plan.get("reuses")
    reuses = ", ".join(reuses) if isinstance(reuses, list) else reuses
    p = f"files: {cell(files, 200)} · reuses: {cell(reuses, 160)} · done-test: {cell(plan.get('done_test'), 200)}"
    ex = b.get("exists")
    ex = " · ".join(ex) if isinstance(ex, list) else ex
    clash = " · ".join(
        x
        for x in [
            cell(b.get("clash"), 160) if b.get("clash") else "",
            cell(b.get("risks"), 160) if b.get("risks") else "",
        ]
        if x
    )
    dep = b.get("depends_on")
    dep = ", ".join(dep) if isinstance(dep, list) else dep
    why = b.get("why") or ""
    if b.get("unclear"):
        why += " · QUESTION: " + cell(b["unclear"], 200)
    w(
        f"| B{b['id']} | {cell(b.get('title'), 160)} | {b.get('grade', '?')}: {cell(ex, 220)} | {cell(b.get('gap'), 220)} | {p} | {cell(b.get('estimate'), 40)} | {cell(dep, 80)} | {clash or '—'} | {status_cell(b.get('status', 'OPEN'), why)} |"
    )
for o, t in [
    ("O1", "The exact role list and values for importance (1.6)"),
    ("O2", 'The "very low sureness" cut-off that triggers the V3 fallback (1.6)'),
    (
        "O3",
        "Written definitions for each WORDS dimension, one question each, and the external anchor for the sales link (Phase 2 full W; CONSTRUCT fence)",
    ),
]:
    dd = DEC.get("B" + o)
    st = (
        f"{dd['status']} (DECIDED {cell(dd['note'], 120)})"
        if dd
        else "FOUNDER (decide before the task that needs it)"
    )
    w(
        f"| {o} | Decision page, Still open: {cell(t)} | open question | a founder decision | — | — | — | — | {st} |"
    )
w("")

w("## X · The harness (for approval)")
w("")
w(hdr)
w(sep)
for x in X:
    w(
        f"| {x['id']} | {cell(x['source'])} | {cell(x['claim'])} | {x['area']} | — | — | — | S0 | — | — | — | {status_cell(x['status'], x['why'])} |"
    )
w("")

w("## G · Brief gaps and contract amendments")
w("")
w(
    "Decisions on the V4 page that no brief item carries (BG), and contract or lock text that still says the old rule (CA). Each needs your call: add a build row, or amend the text."
)
w("")
w("| ID | Source | Claim in one line | Status |")
w("|---|---|---|---|")
for i, g in enumerate(mapB.get("brief_gaps", []), 1):
    k = f"BG{i:02d}"
    dd = DEC.get(k)
    w(
        f"| {k} | V4 mapping 6 Oct, brief gaps | {cell(g, 400)} | {status_cell(dd['status'], 'DECIDED ' + dd['note']) if dd else 'FOUNDER (add a brief item or drop)'} |"
    )
for i, g in enumerate(mapB.get("contract_amendments_needed", []), 1):
    k = f"CA{i:02d}"
    dd = DEC.get(k)
    w(
        f"| {k} | V4 mapping 6 Oct, contract/lock clash | {cell(g, 400)} | {status_cell(dd['status'], 'DECIDED ' + dd['note']) if dd else 'FOUNDER (amend the text, or narrow the decision)'} |"
    )
w("")

if mapB.get("decisions"):
    w("## Decision record coverage")
    w("")
    w(
        "Every row of the decision page, graded against the code today and mapped to the build row that carries it."
    )
    w("")
    w("| Decision | Short | Today | Evidence | Carried by | Clash |")
    w("|---|---|---|---|---|---|")
    for x in mapB["decisions"]:
        cb = x.get("carried_by")
        cb = ", ".join(cb) if isinstance(cb, list) else cb
        w(
            f"| V4 {x['id']} | {cell(x.get('text_short'), 120)} | {x.get('grade', '?')} | {cell(x.get('evidence'), 200)} | {cell(cb, 80)} | {cell(x.get('clash'), 160)} |"
        )
    w("")

open(OUT, "w").write("\n".join(out) + "\n")
print(
    "wrote",
    OUT,
    "A-rows",
    len(rows),
    "N",
    len(N),
    "B",
    len(mapA) + len(mapB.get("build", [])),
    "X",
    len(X),
)
