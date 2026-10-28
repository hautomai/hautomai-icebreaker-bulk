#!/usr/bin/env python3
"""Build final Madaar CSV: verified (VALID) emails + shortened company.

Reads ./new_leads.csv and ./output/_madaar_verification_cache.json.
Keeps only rows whose email verified as VALID, adds:
  email_valid / email_quality / email_status   (from the verifier)
  shorten company                              (legal-form / special-char cleanup,
                                               with prior curated short preferred)
Writes:
  ./output/madaar_final.csv
  ./output/madaar_summary.md
"""
import csv, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CSV_PATH = HERE / "new_leads.csv"
KSA_CSV = HERE / "ksa.csv"
ENV_PATH = HERE / ".env"
OUT = HERE / "output"
CACHE = OUT / "_madaar_verification_cache.json"
FINAL = OUT / "madaar_final.csv"
SUMMARY = OUT / "madaar_summary.md"

LEGAL_TRAILING = [
    r"\bco\.?$", r"\bcompany$", r"\bl\s*\.?\s*l\s*\.?\s*c\.?$", r"\bllc$",
    r"\bltd\.?$", r"\blimited$", r"\binc\.?$", r"\bincorporated$",
    r"\bcorp\.?$", r"\bcorporation$", r"\bs[\s.]*a[\s.]*$", r"\bsarl$",
    r"\bgmbh$", r"\bplc$", r"\best\.?$", r"\bestablishment$", r"\bfzc$",
    r"\bllp$", r"\bpty$", r"\bgroup$", r"\bholding$",
    r"\bfor\s+(general\s+)?contracting$", r"\bfor\s+trading$",
    r"\bfor\s+construction$", r"\bfor\s+elevators\s+and\s+escalators$",
    r"\btrading\s+and\s+contracting$", r"\bfor\s+contracting\s+co\.?$",
]
LEGAL_LEADING = [r"^شركة\s+", r"^مؤسسة\s+"]
AR_TRAILING = [r"\s+المحدودة$", r"\s+للمقاولات$", r"\s+والمقاولات$", r"\s+للتجارة\s+والمقاولات$"]

def strip_legal(name: str) -> str:
    n = name
    changed = True
    while changed:
        changed = False
        for pat in AR_TRAILING:
            if re.search(pat, n):
                n = re.sub(pat, "", n).strip()
                changed = True
        for pat in LEGAL_TRAILING:
            if re.search(pat, n, re.I):
                n = re.sub(pat, "", n, flags=re.I).strip()
                changed = True
        for pat in LEGAL_LEADING:
            if re.search(pat, n):
                n = re.sub(pat, "", n).strip()
                changed = True
    return n.strip()

def clean_special(name: str) -> str:
    n = re.sub(r"[^\w&\u0600-\u06FF \-]", " ", name, flags=re.UNICODE)
    n = re.sub(r"\s+", " ", n)
    return n.strip()

AR_CHARS = re.compile(r"[\u0600-\u06FF]")
def pick_latin(name: str) -> str:
    parts = [p for p in name.split("|") if p.strip()]
    if len(parts) < 2:
        return name
    def lat(s):
        s = AR_CHARS.sub("", s)
        return sum(c.isalnum() for c in s)
    return max(parts, key=lambda p: lat(p))

def short_company(org_name: str, domain: str, prior: dict) -> str:
    base = (org_name or "").strip()
    if not base:
        return ""
    n = strip_legal(pick_latin(base))
    cleaned = clean_special(n)
    cleaned = strip_legal(cleaned)
    short = cleaned
    p = prior.get(domain or "")
    if p and p.get("short"):
        ps = clean_special(p["short"])
        if len(ps) <= len(cleaned) or not cleaned:
            short = ps
    return short

def norm_domain(v):
    if not v:
        return ""
    v = v.strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.split("/")[0].split("?")[0]

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"{CSV_PATH} not found")

    # prior curated shorts from madaar/ksa.csv (domain -> Company/shorten company)
    prior = {}
    if KSA_CSV.exists():
        with open(KSA_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = norm_domain(r.get("company_domain"))
                if d and d not in prior:
                    prior[d] = {"company": r.get("Company", ""), "short": r.get("shorten company", "")}

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        header = list(csv.reader(f).__next__())
        rows = list(csv.DictReader(open(CSV_PATH, newline="", encoding="utf-8")))

    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    email_fields = {"email_valid", "email_quality", "email_status", "shorten company"}
    new_header = header + [c for c in email_fields if c not in header]

    valid_rows, invalid_rows = [], []
    for r in rows:
        em = (r.get("email") or "").strip().lower()
        rec = cache.get(em, {})
        if len(r) != len(header):
            print(f"WARN row length mismatch for {em}: {len(r)} vs {len(header)}")
        if not rec:
            r["email_valid"] = "UNKNOWN"
            r["email_quality"] = ""
            r["email_status"] = "not_checked"
        else:
            quality = (rec.get("quality") or "").strip()
            status = (rec.get("status") or "").strip()
            result = (rec.get("result") or "").strip()
            err = (rec.get("error") or "").strip()
            valid = bool(not err and quality == "good" and result == "ok")
            r["email_valid"] = "TRUE" if valid else "FALSE"
            r["email_quality"] = quality
            r["email_status"] = status or err or result
        domain = norm_domain(r.get("organization_primary_domain") or r.get("organization_website_url"))
        r["shorten company"] = short_company(r.get("organization_name"), domain, prior)
        (valid_rows if r["email_valid"] == "TRUE" else invalid_rows).append(r)

    OUT.mkdir(exist_ok=True)
    with open(FINAL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=new_header, extrasaction="ignore")
        w.writeheader()
        w.writerows(valid_rows)

    lines = ["# Madaar final report", ""]
    lines.append(f"- Input rows: {len(rows)}")
    lines.append(f"- Unique emails in cache: {len(cache)}")
    lines += ["", "## Email verification summary", ""]
    from collections import Counter
    q = Counter((x.get("email_valid"), x.get("email_quality"), x.get("email_status")) for x in rows)
    valid = sum(1 for x in rows if x["email_valid"] == "TRUE")
    notc = sum(1 for x in rows if x["email_valid"] == "UNKNOWN")
    lines.append(f"- VALID: {valid}")
    lines.append(f"- NOT valid/checked: {len(rows) - valid}")
    lines.append(f"- rows with no verification record: {notc}")
    lines.append("")
    lines.append("| valid | quality | status | count |")
    lines.append("|---|---|---|---|")
    for (v, qq, ss), c in sorted(q.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {v} | {qq} | {ss} | {c} |")
    lines += ["", "## Companies (VALID rows)", ""]
    from collections import defaultdict
    by_org = defaultdict(int)
    for x in valid_rows:
        k = x.get("organization_name") or "(none)"
        by_org[k] += 1
    lines.append("| company | rows |")
    lines.append("|---|---|")
    for k, c in sorted(by_org.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {c} |")
    lines += ["", "## Sample short names (VALID rows)", ""]
    lines.append("| organization_name | shorten company |")
    lines.append("|---|---|")
    for x in valid_rows[:40]:
        lines.append(f"| {x.get('organization_name', '')} | {x.get('shorten company', '')} |")

    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"final rows (VALID): {len(valid_rows)} / {len(rows)}")
    print(f"wrote {FINAL}\nwrote {SUMMARY}")

    # sanity check on shorten company coverage + sample
    empties = [x for x in valid_rows if not x.get("shorten company")]
    print("VALID rows with empty shorten company:", len(empties))
    print("\n-- sample (up to 25) --")
    for x in valid_rows[:25]:
        print(f"  {x.get('organization_name','')!r:50s} -> {x.get('shorten company')!r}")

if __name__ == "__main__":
    main()