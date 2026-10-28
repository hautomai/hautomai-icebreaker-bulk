#!/usr/bin/env python3
"""Serper enrichment for apifyapollo.csv organizations.

For each unique organization we run:
  1. a Google search (knowledge graph + organic snippets)
  2. a homepage crawl via Serper's webpage endpoint (when a website URL exists)

and write a compact markdown report so icebreaker/personalization can be
grounded in what the company actually does (not just the LinkedIn headline).

Resumable: results are cached in output/_apify_serper_cache.json; re-running
skips orgs already processed.
"""

import csv
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
CACHE = OUT_DIR / "_apify_serper_cache.json"
REPORT = OUT_DIR / "_apify_enrichment.md"

spec = importlib.util.spec_from_file_location("isearch", HERE / "icebreakers_search.py")
isearch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isearch)

load_env = isearch.load_env
serper_search = isearch.serper_search
site_search = isearch.site_search
crawl_homepage = isearch.crawl_homepage


def snippet_of(org: dict) -> str:
    env = load_env()
    api_key = env.get("serper") or env.get("serper_api_key") or \
        env.get("serper_key") or env.get("serper.dev")
    name = org["name"]
    domain = org["domain"]
    website = org["website"]

    parts = []

    res = serper_search(api_key, f"{name}")
    if res:
        kg = res.get("knowledgeGraph") or {}
        if kg.get("description"):
            parts.append(f"[KG] {kg.get('description','')[:600]}")
        for o in (res.get("organic") or [])[:4]:
            sn = (o.get("snippet") or "").strip()
            if sn and len(sn) > 40:
                parts.append(f"[web] {o.get('title','')[:60]} :: {sn[:400]}")

    if website:
        page = crawl_homepage(api_key, website)
        if page and page.get("text"):
            txt = " ".join(page["text"].split())
            parts.append(f"[homepage] {txt[:900]}")

    time.sleep(0.3)
    return "\n".join(parts)


def main() -> None:
    src = HERE / "apifyapollo.csv"
    with src.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    orgs: dict[str, dict] = {}
    for r in rows:
        dom = (r.get("organization_primary_domain") or "").strip().lower()
        if not dom:
            continue
        orgs.setdefault(dom, {
            "name": (r.get("organization_name") or "").strip(),
            "domain": dom,
            "website": (r.get("organization_website_url") or "").strip(),
            "org_linkedin": (r.get("organization_linkedin_url") or "").strip(),
        })

    cache: dict = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    for dom, org in sorted(orgs.items()):
        if dom in cache:
            continue
        try:
            text = snippet_of(org)
        except Exception as e:
            text = f"[error] {e}"
        cache[dom] = {**org, "text": text}
        # write-through so progress survives interruption
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"done {dom}  ({len(cache)}/{len(orgs)})", flush=True)

    # markdown report
    lines = ["# apifyapollo.csv Serper enrichment", "",
             f"_{len(cache)} orgs_", ""]
    for dom, o in sorted(cache.items()):
        lines.append("---")
        lines.append("")
        lines.append(f"## {o['name']} ({dom})")
        if o.get("website"):
            lines.append(f"- site: {o['website']}")
        if o.get("org_linkedin"):
            lines.append(f"- linkedin: {o['org_linkedin']}")
        lines.append("")
        lines.append(o.get("text", ""))
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport -> {REPORT}")


if __name__ == "__main__":
    main()
