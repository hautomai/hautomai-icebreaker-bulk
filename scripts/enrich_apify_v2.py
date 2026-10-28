#!/usr/bin/env python3
"""Serper enrichment for the email-only apifyapollo.csv (v2).

The new CSV only has `email` (+ a title column). We derive the domain from the
email and, for each unique domain, run:
  1. a Google search on the domain (knowledge graph + organic snippets)
  2. a homepage crawl via Serper's webpage endpoint (https://<domain>)

Results are cached in output/_apify_serper_cache_v2.json and rendered to
output/_apify_enrichment_v2.md so icebreaker/personalization can be grounded
in what the company actually does.

Resumable: search snippets / homepage text already present in the cache are
not fetched again on re-run.
"""

import csv
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
CACHE = OUT_DIR / "_apify_serper_cache_v2.json"
REPORT = OUT_DIR / "_apify_enrichment_v2.md"

spec = importlib.util.spec_from_file_location("isearch", HERE / "icebreakers_search.py")
isearch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isearch)

load_env = isearch.load_env
serper_search = isearch.serper_search
crawl_homepage = isearch.crawl_homepage


def search_text(domain: str, api_key: str) -> str:
    """Google search snippets + knowledge graph for the domain."""
    parts = []
    res = serper_search(api_key, domain)
    if res:
        kg = res.get("knowledgeGraph") or {}
        if kg.get("title"):
            parts.append("[KG title] " + kg["title"][:120])
        if kg.get("description"):
            parts.append("[KG] " + kg["description"][:600])
        for o in (res.get("organic") or [])[:4]:
            sn = (o.get("snippet") or "").strip()
            if sn and len(sn) > 40:
                t = (o.get("title") or "")[:70]
                parts.append("[web] " + t + " :: " + sn[:400])
    return "\n".join(parts)


def homepage_text(domain: str, api_key: str) -> str:
    page = crawl_homepage(api_key, "https://" + domain)
    if not (page and page.get("text")):
        page = crawl_homepage(api_key, "https://www." + domain)
    if page and page.get("text"):
        txt = " ".join(page["text"].split())
        return "[homepage] " + txt[:900]
    return ""


def main() -> None:
    src = HERE / "apifyapollo.csv"
    with src.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    domains = sorted({r["email"].split("@")[-1].strip().lower() for r in rows
                      if r.get("email")})

    cache: dict = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    env = load_env()
    api_key = env.get("serper") or env.get("serper_api_key") or \
        env.get("serper_key") or env.get("serper.dev")
    if not api_key:
        sys.exit("Serper API key not found in .env")

    for i, dom in enumerate(domains, 1):
        v = cache.setdefault(dom, {"domain": dom, "text": ""})
        text = v.get("text", "")
        changed = False
        if "[web]" not in text and "[KG" not in text:
            s = search_text(dom, api_key)
            if s:
                text = s + ("\n" + text if text.strip() else "")
                changed = True
        if "[homepage]" not in text:
            h = homepage_text(dom, api_key)
            if h:
                text = (text + "\n" if text.strip() else "") + h
                changed = True
        if changed:
            v["text"] = text
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"done {i}/{len(domains)}  {dom}", flush=True)
        time.sleep(0.25)

    lines = ["# apifyapollo.csv (v2) Serper enrichment", "",
             "_" + str(len(cache)) + " domains_", ""]
    for dom in sorted(cache):
        lines += ["---", "", "## " + dom, "", cache[dom].get("text", ""), ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\nReport -> " + str(REPORT))


if __name__ == "__main__":
    main()
