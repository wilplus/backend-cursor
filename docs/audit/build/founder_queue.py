import json
import re
import collections


def cell(s, n=None):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if n and len(s) > n:
        s = s[:n].rsplit(" ", 1)[0] + "…"
    return s.replace("|", "\\|")


rows = []
for i in range(1, 7):
    rows += json.load(open(f"s{i}.out.json"))
N = json.load(open("n_rows.json"))
A = json.load(open("mapA.out.json"))
B = json.load(open("mapB.out.json"))


def kind(t):
    t = t.lower()
    for k, keys in [
        (
            "Ops (Railway, Supabase, config)",
            ["ops", "railway", "supabase", "sql", "config", "env"],
        ),
        (
            "Copy to sign",
            ["copy", "wording", "string", "sign-off", "signoff", "signed"],
        ),
        ("Design lock / designer session", ["design", "designer"]),
        ("Content (videos, text)", ["content", "film", "video"]),
        ("Decision", [""]),
    ]:
        if any(x in t for x in keys):
            return k


out = []
w = out.append
w("# Founder queue (from LEDGER.md)")
w("")
w(
    "Every ledger row that waits on you, grouped. Rows marked **?** also carry a question. Answer by row ID; the full row is in `LEDGER.md`."
)
w("")
w("## 1 · Questions first (rows I could not grade without you)")
w("")
for n in N:
    if n.get("unclear"):
        w(f"- **{n['id']}** — {cell(n['unclear'], 300)}")
for b in list(A) + B["build"]:
    if b.get("unclear"):
        u = b["unclear"]
        u = " / ".join(u) if isinstance(u, list) else u
        w(f"- **B{b['id']}** — {cell(u, 600)}")
for d in B["decisions"]:
    if d.get("unclear"):
        w(f"- **V4 {d['id']}** — {cell(d['unclear'], 300)}")
for r in rows:
    if r.get("unclear"):
        w(f"- **{r['aid']}** ({r['status']}) — {cell(r['unclear'], 300)}")
w("")
w("## 2 · V4 build rows waiting on you")
w("")
for b in list(A) + B["build"]:
    if b.get("status") == "FOUNDER":
        w(f"- **B{b['id']}** {cell(b.get('title'), 90)} — {cell(b.get('why'), 220)}")
for oid, t in [
    ("O1", "importance role list and values"),
    ("O2", '"very low sureness" cut-off for the V3 fallback'),
    ("O3", "written definitions for each WORDS dimension; sales anchor"),
]:
    w(f"- **{oid}** {t}")
w("")
w("## 3 · Decisions no brief item carries (add a build row, or drop)")
w("")
for i, g in enumerate(B["brief_gaps"], 1):
    w(f"- **BG{i:02d}** {cell(g, 300)}")
w("")
w("## 4 · Contract or lock text that still says the old rule (amend)")
w("")
for i, g in enumerate(B["contract_amendments_needed"], 1):
    w(f"- **CA{i:02d}** {cell(g, 300)}")
w("")
w("## 5 · Overnight rows")
w("")
for n in N:
    if n["status"] in ("FOUNDER", "CONFIRMED"):
        w(f"- **{n['id']}** ({n['status']}, {n['severity']}) {cell(n['claim'], 200)}")
w("")
w("## 6 · Audit rows waiting on you, by kind")
grp = collections.defaultdict(list)
for r in rows:
    if r["status"] == "FOUNDER":
        grp[kind(r.get("why", ""))].append(r)
for k in [
    "Ops (Railway, Supabase, config)",
    "Decision",
    "Design lock / designer session",
    "Copy to sign",
    "Content (videos, text)",
]:
    if not grp[k]:
        continue
    w("")
    w(f"### {k} ({len(grp[k])})")
    w("")
    for r in grp[k]:
        w(
            f"- **{r['aid']}**{' **?**' if r.get('unclear') else ''} [{r['area']}] {cell(r['claim'], 180)}"
        )
w("")
w("## 7 · Harness rows X1–X10: approve, change or drop (see LEDGER.md §X)")
open("FOUNDER-QUEUE.md", "w").write("\n".join(out) + "\n")
sec = out.index("## 2 · V4 build rows waiting on you")
print(
    "questions",
    sum(1 for ln in out[:sec] if ln.startswith("- **")),
    "items",
    sum(1 for ln in out if ln.startswith("- **")),
)
print({k: len(v) for k, v in grp.items()})
