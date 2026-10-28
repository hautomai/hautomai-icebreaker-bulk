#!/usr/bin/env python3
"""KSA leads enrichment: Serper search + homepage text per website.

Fetches (via Serper) search snippets/KG + homepage text for the sites that the
Apify crawl could not classify cleanly, then caches a compact digest that the
LLM reviews to fill Company + Industry in ksa.csv.

Resumable: entries already in the cache are skipped.
"""
import csv, importlib.util, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CACHE = OUT / "_ksa_sites_cache.json"
DIGEST = OUT / "_ksa_sites.md"

spec = importlib.util.spec_from_file_location("isearch", HERE / "icebreakers_search.py")
isearch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isearch)
load_env, serper_search, crawl_homepage = isearch.load_env, isearch.serper_search, isearch.crawl_homepage

TARGETS = [
    "itruck.com.sa", "noblearchitecture.net", "tasawy.com.sa", "uabco.com",
    "anwar.com.sa", "almarhoon.com.sa", "saharabuilding.com", "yfz.sa",
    "meac.net", "alfaisaltransport.com", "dw.com.sa", "tasami.com.sa",
    "fine-mark.com", "gcscontracting.com", "mubarrad.sa", "radial.com.sa",
    "alhussain.co", "alfatech-ksa.com", "saudibiga.com", "rancogroup.com",
    "baseelunited.com", "mwltd.com.sa", "mehwaraleqtisad.com", "pt-tgc.com",
    "tajdhabi.com", "abtltd.com.sa", "ehco.com.sa", "smart-const.com",
    "qah.sa", "alhaitam.com",
]

KEY_BY_DOMAIN = {
    "itruck.com.sa": "itruck.com.sa",
    "noblearchitecture.net": "noblearchitecture.net",
    "tasawy.com.sa": "tasawy.com.sa",
    "uabco.com": "uabco.com",
    "anwar.com.sa": "anwar.io",
    "almarhoon.com.sa": "almarhoon.com.sa",
    "saharabuilding.com": "saharabuilding.com",
    "yfz.sa": "yfz.sa",
    "meac.net": "meac.eu",
    "alfaisaltransport.com": "alfaisaltransport.com",
    "dw.com.sa": "dw.com.sa",
    "tasami.com.sa": "tasami.com.sa",
    "fine-mark.com": "fine-mark.com",
    "gcscontracting.com": "gcscontracting.com",
    "mubarrad.sa": "mubarrad.sa",
    "radial.com.sa": "radial.com.sa",
    "alhussain.co": "alhussain.co",
    "alfatech-ksa.com": "alfatech-ksa.com",
    "saudibiga.com": "saudibiga.com",
    "rancogroup.com": "rancogroup.com",
    "baseelunited.com": "baseel.sa",
    "mwltd.com.sa": "multiworks.eu",
    "mehwaraleqtisad.com": "mehwaraleqtisad.com",
    "pt-tgc.com": "pt-tgc.com",
    "tajdhabi.com": "tajdhabi.com",
    "abtltd.com.sa": "abtltd.com.sa",
    "ehco.com.sa": "ehco.com.sa",
    "smart-const.com": "smart-const.com",
    "qah.sa": "qah.sa",
    "alhaitam.com": "alhaitam.com",
}

def search_text(domain, api_key):
    parts = []
    res = serper_search(api_key, domain)
    if res:
        kg = res.get("knowledgeGraph") or {}
        if kg.get("title"):
            parts.append("[KG title] " + str(kg["title"])[:120])
        if kg.get("description"):
            parts.append("[KG] " + str(kg["description"])[:600])
        for o in (res.get("organic") or [])[:5]:
            sn = (o.get("snippet") or "").strip()
            if sn and len(sn) > 40:
                parts.append("[web] " + str(o.get("title") or "")[:70] + " :: " + sn[:350])
    return "\n".join(parts)

def homepage_text(domain, api_key):
    for url in ("https://" + domain, "https://www." + domain):
        page = crawl_homepage(api_key, url)
        if page and page.get("text"):
            txt = " ".join(page["text"].split())
            return "[homepage " + url + "] " + txt[:1200]
    return ""

def main():
    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    env = load_env()
    key = env.get("serper") or env.get("serper_api_key") or env.get("serper_key") or env.get("serper.dev")
    if not key:
        sys.exit("Serper key not found in .env")
    for i, dom in enumerate(TARGETS, 1):
        ckey = KEY_BY_DOMAIN[dom]
        v = cache.setdefault(ckey, {"website": "https://" + dom, "text": ""})
        text = v.get("text", "")
        changed = False
        if "[KG" not in text and "[web]" not in text:
            s = search_text(dom, key)
            if s:
                text = s + ("\n" + text if text.strip() else "")
                changed = True
        if "[homepage" not in text:
            h = homepage_text(dom, key)
            if h:
                text = (text + "\n" if text.strip() else "") + h
                changed = True
        if changed:
            v["text"] = text
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"done {i}/{len(TARGETS)}  {dom}", flush=True)
        time.sleep(0.2)
    lines = ["# ksa.csv website enrichment (Serper fallback)", ""]
    for ckey in sorted(cache):
        lines += ["---", "", "## " + ckey, "", cache[ckey].get("text", ""), ""]
    DIGEST.write_text("\n".join(lines), encoding="utf-8")
    print("\nDigest -> " + str(DIGEST))

if __name__ == "__main__":
    main()
