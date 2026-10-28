#!/usr/bin/env python3
"""Serper.dev-powered icebreaker builder.

For each company: 1 Google search -> pick the best source text
(knowledge graph -> official site snippet -> CSV description -> other snippets),
extract a short fact using the user's priority rules (paraphrase style,
gerund-lead, compact numbers), enforce the <=140 char icebreaker
(detail <= 53 chars) and fall back to "your growth so far" /
"what you're building" when nothing survives validation.
"""

import csv
import importlib.util
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"

spec = importlib.util.spec_from_file_location(
    "base_rules", HERE / "icebreakers_from_description.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

clean_detail = base.clean_detail
passes_sense_check = base.passes_sense_check
passes_grammar_check = base.passes_grammar_check
rule_superlative = base.rule_superlative_lead
rule_niche = base.rule_niche
rule_method = base.rule_method
rule_cert = base.rule_cert
rule_geo = base.rule_geo
rule_motto = base.rule_motto
rule_service = base.rule_service

FALLBACK_GROWTH = "your growth so far"
FALLBACK_BUILD = "what you're building"
PREFIX = "Been checking out your company on LinkedIn, "
SUFFIX = " piqued my curiosity. Had to send you this!"
DETAIL_MAX = 53

SRC_BONUS = {"knowledge graph": 50, "official site": 40, "homepage": 45,
             "site: snippet": 35, "csv description": 30, "google snippet": 0}

KNOWN_BRANDS = {
    "wells fargo", "experian", "la liga", "serie a", "nba", "nhl",
    "amazon", "ebay", "tesco", "visa", "netflix", "google", "apple",
    "microsoft", "samsung", "nike", "adidas", "bbc", "sky", "itv",
    "vodafone", "nissan", "bmw", "mercedes", "hsbc", "barclays",
    "lloyds", "deloitte", "pwc", "kpmg", "canon",
}

CHANNELS = [
    "pay per click", "search engine optimisation", "social media",
    "email marketing", "link building", "content marketing",
    "affiliate marketing", "google ads", "facebook", "instagram",
    "linkedin", "tiktok", "youtube", "seo", "ppc", "lead generation",
    "hubspot", "marketplaces", "amazon", "ecommerce",
]
CHANNEL_CASE = {
    "seo": "SEO", "ppc": "PPC", "google ads": "Google Ads",
    "facebook": "Facebook", "instagram": "Instagram",
    "linkedin": "LinkedIn", "tiktok": "TikTok", "youtube": "YouTube",
    "social media": "Social Media", "email marketing": "Email Marketing",
    "link building": "Link Building", "content marketing": "Content Marketing",
    "affiliate marketing": "Affiliate Marketing",
    "lead generation": "Lead Generation", "hubspot": "HubSpot",
    "amazon": "Amazon", "ecommerce": "Ecommerce",
    "marketplaces": "Marketplaces", "pay per click": "Pay Per Click",
    "search engine optimisation": "Search Engine Optimisation",
}

INCOMPLETE_RE = re.compile(r"\b(?:including|such as|along with)\b", re.I)
END_CONNECTOR = {"including", "with", "and", "such", "as", "the", "a", "an",
                 "for", "to", "of", "in", "on", "via", "across", "or"}


def load_env() -> dict:
    env = {}
    p = HERE / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip().lower()] = v.strip().strip('"').strip("'")
            else:
                parts = line.split()
                if len(parts) >= 2:
                    env[parts[0].lower()] = parts[1]
    return env


def serper_call(endpoint: str, payload: dict, api_key: str) -> dict | None:
    req = urllib.request.Request(
        f"https://google.serper.dev/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [serper {endpoint} error: {e}]", file=sys.stderr)
        return None


def serper_search(api_key: str, q: str) -> dict | None:
    return serper_call("search", {"q": q, "gl": "uk", "hl": "en", "num": 10}, api_key)


def site_search(api_key: str, domain: str) -> dict | None:
    return serper_call("search", {"q": f"site:{domain}", "gl": "uk", "hl": "en",
                                  "num": 10}, api_key)


def crawl_homepage(api_key: str, url: str) -> dict | None:
    return serper_call("webpage", {"url": url}, api_key)


def csv_keyword(desc: str) -> str:
    desc = desc or ""
    m = base.NICHE_HINT_RE.search(desc)
    if m:
        return m.group(0)
    for w in ("marketing", "media", "design", "agency", "consulting", "seo",
              "events", "sports", "digital"):
        if re.search(r"\b" + w + r"\b", desc, re.I):
            return w
    return "marketing"


def dedupe_texts(texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for src, t in texts:
        key = t[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((src, t))
    return out


def collect_texts(row: dict, res: dict | None, domain: str) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    if res:
        kg = res.get("knowledgeGraph") or {}
        if kg.get("description"):
            texts.append(("knowledge graph", kg["description"]))
        dc = domain.lower().replace("www.", "")
        for o in res.get("organic") or []:
            link = (o.get("link") or "").lower().replace("www.", "")
            if dc in link and o.get("snippet"):
                texts.append(("official site", o["snippet"]))
                break
    if row.get("company_description"):
        texts.append(("csv description", row["company_description"]))
    if res:
        for o in (res.get("organic") or [])[:8]:
            if o.get("snippet") and len(o["snippet"]) > 40:
                texts.append(("google snippet", o["snippet"]))
    return texts


# --------------------------------------------------------------------------
# Rules. Each returns (detail, quality) or None. Higher quality wins.
# --------------------------------------------------------------------------

def rule_goal(text: str):
    m = re.search(
        r"\b(?:our|the)\s+(?:goal|mission|aim|objective)\s+is\s+(?:to\s+)?([^.!;]{4,100})",
        text, re.I)
    if not m:
        m = re.search(
            r"\b(?:our|the)\s+(?:goal|mission)\s*[:\-]\s*([^.!;]{4,100})", text, re.I)
    if not m:
        return None
    g = m.group(1).strip()
    g = re.split(r"\b(?:that['\u2019]?s|which|by\s+creating)\b", g, maxsplit=1)[0]
    g = g.strip(" .,;:!?-")
    gl = g.lower()
    if len(g.split()) > 10:
        return None
    if any(x in gl for x in ("help you", "help your", "your business")) \
            and len(g.split()) < 6:
        return None
    return "your objective to " + g[0].lower() + g[1:], 0


def rule_quantified(text: str):
    m = re.search(
        r"\btreat(?:ed|ing)\s+(?:over\s+|more\s+than\s+)?(\d[\d,.]+\+?)\s*patients\b",
        text, re.I)
    if m:
        return f"{m.group(1)} treated patients", 10
    m = re.search(
        r"\b(?:worked|served|helped)\s+(?:with\s+)?(?:over\s+|more\s+than\s+)?"
        r"(\d[\d,.]+\+?)\s+companies\b", text, re.I)
    if m:
        seg = text[m.end():m.end() + 90]
        geo = ""
        if re.search(r"\bacross\s+the\s+world\b", seg, re.I):
            geo = " the world"
        else:
            g = re.search(
                r"\b(?:across|in|throughout)\s+(?:the\s+)?"
                r"([A-Z][A-Za-z]{2,20}(?:\s+and\s+[A-Z][A-Za-z]{2,20})?)", seg)
            if g:
                gl = g.group(1).lower()
                if any(w in gl for w in ("uk", "england", "scotland", "wales",
                                         "ireland", "europe", "usa", "canada")):
                    geo = " the UK" if any(
                        w in gl for w in ("uk", "england", "scotland", "wales")) \
                        else " " + g.group(1)
        return (f"working with {m.group(1)} companies" +
                (" across" + geo if geo else "")), 8
    m = re.search(
        r"(\d[\d,.]+\+?)\s+(?:(plus)\s+)?(?:(monthly)\s+)?"
        r"(?:(vip|vvip|new|happy|paying|active|satisfied)\s+)?"
        r"(members|readers|followers|clients|customers|leads)\b", text, re.I)
    if m:
        n, monthly, qual, unit = m.group(1), (m.group(3) or ""), \
            (m.group(4) or ""), m.group(5).lower()
        seg = text[m.end():m.end() + 90]
        geo = ""
        g = re.search(
            r"\b(?:across|in|throughout)\s+(?:the\s+)?"
            r"([A-Z][A-Za-z]{2,20}(?:\s+and\s+[A-Z][A-Za-z]{2,20})?)", seg)
        if g:
            gl = g.group(1).lower()
            if any(w in gl for w in ("uk", "england", "scotland", "wales",
                                     "ireland", "europe", "usa", "canada")):
                geo = " the UK" if any(
                    w in gl for w in ("uk", "england", "scotland", "wales")) \
                    else " " + g.group(1)
        head = f"getting {n} {qual} {monthly}{unit}".replace("  ", " ").strip()
        n_val = n.replace(",", "").replace(".", "").rstrip("+")
        if unit == "followers" and n_val.isdigit() and int(n_val) < 10000:
            pass  # trivial social counts are noise - try other sub-rules
        else:
            q = 0
            if unit in ("clients", "customers", "members", "patients"):
                q += 10
            if qual:
                q += 4
            return (head + (" across" + geo if geo else "")), q
    m = re.search(
        r"(?:turn|turning|transform)\w*\s+(?:as\s+high\s+as\s+)?(\d+)%"
        r"[^.!;]{0,60}?(\d+)%\+?\s*(acceptance|conversion|sales)", text, re.I)
    if m:
        return f"turning {m.group(1)}% rejection into {m.group(2)}%+ " \
               f"{m.group(3).lower()}", 12
    m = re.search(r"([>]?\d+[:]\d+)\s*(?:roi|return)", text, re.I)
    if m:
        return f"getting a {m.group(1)} ROI", 10
    m = re.search(r"help\s+(?:you|businesses|clients?)\s+achieve\s+results\s+"
                  r"in\s+(\d+)\s+days", text, re.I)
    if m:
        return f"helping you achieve results in {m.group(1)} days or less", 8
    return None


def rule_longevity(text: str):
    m = re.search(
        r"\b(?:for|over|in\s+business\s+for|with)\s+(?:the\s+last\s+|last\s+)?"
        r"(\d{2})(?:\s*[+]|\s*plus)?\s+years\b", text, re.I)
    if m:
        return f"doing this for over {m.group(1)} years", 0
    return None


DIFFS = [
    (r"\bwe\s+only\s+charge\s+on\s+results\b", "only charging on results"),
    (r"\bwe\s+do\s+everything\s+in[- ]house\b", "doing everything in-house"),
    (r"\bwe\s+don['\u2019]?t\s+work\s+on\s+retainers?\b", "never working on retainers"),
    (r"\bwe\s+don['\u2019]?t\s+use\s+(?:['\u201c\u2018]\s*)?black[ -]?hat\b",
     "never using black hat methods"),
    (r"\bwe\s+don['\u2019]?t\s+sell\s+(?:our\s+|your\s+)?(?:member\s+)?"
     r"(?:and\s+client\s+)?(?:data|details|information)\b", "never selling your data"),
    (r"\bwithout\s+an\s+account\s+manager\s+middleman\b",
     "cutting out the account manager middleman"),
    (r"\bwe\s+don['\u2019]?t\s+charge\s+the\s+earth\b",
     "not charging the earth for marketing services"),
    (r"\b(\d+)-day\s+money[ -]?back\s+guarantee\b",
     lambda m: f"offering a {m.group(1)}-day money back guarantee"),
    (r"\bcancel\s+anytime\b", "letting you cancel anytime"),
    (r"\bno\s+(?:long[ -]?term\s+)?contracts?\b", "working without long contracts"),
]


def rule_differentiator(text: str):
    best = None
    for i, (pat, out) in enumerate(DIFFS):
        m = re.search(pat, text, re.I)
        if m:
            cand = out(m) if callable(out) else out
            q = (len(DIFFS) - i) * 2
            if best is None or q > best[1]:
                best = (cand, q)
    return best


def rule_superlative_being(text: str):
    m = rule_superlative(text)
    if m and not INCOMPLETE_RE.search(m):
        return m, 0
    return None


SPECIAL_CLAIMS = [
    (r"create\s+a\s+plan\s+that\s+you\s+can\s+track",
     "creating a trackable plan that delivers ROI"),
    (r"under\s+one\s+(?:efficient\s+)?roof",
     "providing marketing and design under one roof"),
    (r"empower\w*\s+online\s+service\s+providers",
     "empowering online service providers"),
    (r"blends?\s+insights?,\s*strategy,\s*and\s+creativity",
     "blending insight, strategy and creativity"),
    (r"(?:spark|ignite)\s+product\s+and\s+service\s+innovation",
     "sparking product and service innovation"),
    (r"dedicated\s+to\s+supporting\s+smes[^.!]*?since\s+(?:June\s+)?(\d{4})",
     lambda m: f"helping SMEs grow since {m.group(1)}"),
    (r"serving\s+charities,\s*ngo['\u2019]?s?\s*&\s*purpose[- ]?driven\s+"
     r"business\s+owners", "serving charities and purpose-driven businesses"),
    (r"deliver\w*\s+results\s+for\s+smes?\b[^.!]{0,30}?\bwithout\s+waiting\s+months",
     "delivering results for SMEs without waiting months"),
    (r"we\s+find\s+and\s+manage\s+the\s+best\s+people",
     "how you're finding and managing the best people"),
    (r"steady\s+pipeline\s+of\s+sales\s+opportunities",
     "building outbound systems for B2B pipeline growth"),
    (r"lower\s+their\s+cac\s+and\s+increase\s+ltv",
     "lowering CAC and increasing LTV for subscriptions"),
    (r"companies\s+that\s+frequently\s+get\s+banned\s+from\s+platforms",
     "helping banned companies advertise again"),
    (r"blend\w*\s+brand\s+storytelling",
     "blending brand storytelling and marketing"),
    (r"don['\u2019]?t\s+need\s+(?:a\s+)?sam\b[^.!]*\bfull\s+time",
     "working without a full-time marketer"),
    (r"don['\u2019]?t\s+need\s+(?:a\s+)?full[- ]?time\s+marketer",
     "working without a full-time marketer"),
]


def rule_special_claims(text: str):
    for pat, out in SPECIAL_CLAIMS:
        m = re.search(pat, text, re.I)
        if m:
            cand = out(m) if callable(out) else out
            if not INCOMPLETE_RE.search(cand):
                return cand, 0
    return None


def _channel_context_ok(text: str, pos: int) -> bool:
    pre = text[max(0, pos - 60):pos].lower()
    post = text[pos:pos + 80].lower()
    pre_ok = any(w in pre for w in (
        "specialise in", "specialize in", "specialising in", "specializing in",
        "focus", "run", "running", "manage", "managing", "expert", "specialist",
        "ads", "advertising", "campaigns", "campaign", "all about", "services",
        "service", "ppc", "results", "our passion", "drives", "paid"))
    post_ok = any(w in post for w in (
        "ads", "advertising", "campaigns", "campaign", "results", "visibility",
        "traffic", "ranking", "grow", "growth", "roi", "success", "leads",
        "lead generation"))
    return pre_ok or post_ok


def rule_channel(text: str):
    t = text.lower()
    if re.search(r"linkedin\s+training|training\s+(?:in|on)\s+linkedin", t):
        return "focusing on LinkedIn training", 0
    found: list[str] = []
    for ch in CHANNELS:
        for m in re.finditer(r"\b" + re.escape(ch) + r"\b", t):
            if ch in found:
                continue
            if ch in ("instagram", "facebook", "linkedin", "tiktok", "youtube") \
                    and re.search(r"\bfollow\b|@", t[max(0, m.start() - 40):m.end() + 40]):
                continue
            if _channel_context_ok(t, m.start()):
                found.append(ch)
    if not found:
        return None
    items = [CHANNEL_CASE.get(f, f[0].upper() + f[1:]) for f in found[:3]]
    if len(items) == 1:
        j = items[0]
    elif len(items) == 2:
        j = f"{items[0]} and {items[1]}"
    else:
        j = f"{', '.join(items[:-1])} and {items[-1]}"
    return f"getting these results via {j}", 3 * (len(items) - 1)


def rule_clients(text: str):
    m = re.search(r"\bincluding\s*(?:;|:)?\s*([A-Z][^.!;\n]{3,160})", text)
    if not m:
        m = re.search(r"\b(?:clients?|customers?|partners?)\s+(?:include|includes|"
                      r"are|such as|like)\s+([^.!;\n]{3,160})", text, re.I)
    if not m:
        return None
    g = re.split(r"[.;]", m.group(1))[0]
    toks = g.split()
    chunks: list[list[str]] = []
    cur: list[str] = []
    for w in toks:
        if re.match(r"^[A-Z]", w):
            if re.match(r"^[A-Z][a-z]+['\u2019]s$", w) and cur:
                chunks.append(cur)
                cur = []
            cur.append(w)
        else:
            if cur:
                chunks.append(cur)
                cur = []
    if cur:
        chunks.append(cur)
    names: list[str] = []
    for chunk in chunks:
        chunk = [w for w in chunk if w.lower() not in ("and", "the", "&")]
        if not chunk:
            continue
        if re.match(r"^[A-Za-z]+['\u2019]s$", chunk[0]):
            chunk = chunk[1:]
        if not chunk or not chunk[0][0].isupper():
            continue
        chunk[-1] = chunk[-1].rstrip(",.")
        if not chunk[-1]:
            chunk = chunk[:-1]
        if not chunk:
            continue
        if len(chunk) > 3:
            continue
        if chunk[-1].lower() in ("football", "association", "federation",
                                 "group", "company", "ltd", "limited", "plc",
                                 "inc", "corp"):
            continue
        names.append(" ".join(chunk))
    if not names:
        return None
    known = [n for n in names if n.lower() in KNOWN_BRANDS]
    chosen = known or [n for n in names if len(n.split()) <= 2] or names
    chosen = chosen[:4]
    if len(chosen) == 1:
        head = "working with " + chosen[0]
    elif len(chosen) == 2:
        head = "working with " + chosen[0] + " and " + chosen[1]
    else:
        head = "working with " + ", ".join(chosen[:-1]) + " and " + chosen[-1]
    sub = 90 if known else 38
    return head, sub


def rule_motto_quoted(text: str):
    m = re.search(r"[\"'“‘]([A-Z][^\"'”’]{4,60})[\"'”’]", text)
    if m:
        q = m.group(1).strip(" .,;:!?")
        if 2 <= len(q.split()) <= 8 and not base.PRODUCT_RE.search(q) \
                and not INCOMPLETE_RE.search(q) \
                and not re.search(r"\d", q) \
                and all(len(w) >= 3 for w in q.split()):
            return "believing " + q.lower(), 0
    return None


def rule_niche_q(text: str):
    out = rule_niche(text)
    if not out:
        return None
    if re.search(r"\b[A-Z][a-z]+['\u2019]s\b", out):
        return None  # company-possessive captures like "Foundry's team" are noise
    if base.NICHE_SPEC_RE.search(text) or base.NICHE_EXPERT_RE.search(text) \
            or base.NICHE_DEDIC_RE.search(text):
        return out, 40
    return out, 20


def rule_motto_q(text: str):
    q = rule_motto_quoted(text)
    if q:
        return q[0], 0
    out = rule_motto(text)
    if out:
        if re.match(r"^(?:in|on|for|by|of|to|that|with)\b", out):
            return None  # "believing in this old business saying" - capture noise
        return out, 0
    return None


# base quality per rule (sub-scores add on top); higher wins
BASE_Q = {
    "goal": 100,
    "quantified": 110,
    "differentiator": 90,
    "claims": 85,
    "longevity": 84,
    "superlative": 60,
    "channel": 45,
    "niche": 0,
    "method": 30,
    "clients": 0,
    "cert": 25,
    "geo": 20,
    "motto": 50,
    "service": 15,
}


def build_rules(company: str):
    def _q(fn):
        def wrapped(t):
            out = fn(t)
            if isinstance(out, tuple):
                return out
            return (out, 0) if out else None
        return wrapped
    return [
        ("goal", _q(rule_goal)),
        ("quantified", rule_quantified),
        ("differentiator", rule_differentiator),
        ("claims", rule_special_claims),
        ("longevity", rule_longevity),
        ("superlative", rule_superlative_being),
        ("channel", rule_channel),
        ("niche", rule_niche_q),
        ("method", _q(rule_method)),
        ("clients", rule_clients),
        ("cert", _q(rule_cert)),
        ("geo", _q(rule_geo)),
        ("motto", rule_motto_q),
        ("service", lambda t: _q(lambda x: rule_service(x, company))(t)),
    ]


def cap_detail(d: str, limit: int = DETAIL_MAX) -> str:
    if len(d) <= limit:
        return d
    out = ""
    for w in d.split():
        if len(out) + len(w) + 1 > limit:
            break
        out = (out + " " + w).strip()
    return out


def pick_fallback(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\bbuild|develop|creat|launch|product|platform|app\b", t):
        return FALLBACK_BUILD
    return FALLBACK_GROWTH


def build_detail(texts: list[tuple[str, str]], company: str) -> tuple[str, str, float]:
    rules = build_rules(company)
    best = None
    for idx, (rule_name, fn) in enumerate(rules):
        for source, text in texts:
            try:
                out = fn(text)
            except Exception as e:
                print(f"  [rule {rule_name} error: {e}]", file=sys.stderr)
                continue
            if not out:
                continue
            cand, sub = out
            if rule_name == "superlative":
                cand = "being " + cand
            d = clean_detail(cand)
            if not d:
                continue
            if d.split()[-1].lower() in END_CONNECTOR:
                continue
            quality = BASE_Q[rule_name] + sub
            if quality < 85:  # only curated high-quality rules skip sense/grammar
                if not (passes_sense_check(d) and passes_grammar_check(d)):
                    continue
            d = cap_detail(d)
            if d.split()[-1].lower() in END_CONNECTOR:
                continue
            score = SRC_BONUS.get(source, 0) + quality * 10 + (60 - len(d))
            score += (len(rules) - idx) * 0.01
            if best is None or score > best[0]:
                best = (score, rule_name, d)
    if best:
        return best[2], best[1], best[0]
    return pick_fallback(texts[0][1] if texts else ""), "fallback", -1.0


def find_homepage_url(domain: str, site_res: dict | None) -> str:
    dc = domain.lower().replace("www.", "")
    for o in (site_res or {}).get("organic") or []:
        link = (o.get("link") or "").lower()
        if link.rstrip("/").endswith(dc):
            return o["link"]
    return f"https://{domain}"


def process_company(row: dict, api_key: str) -> dict:
    domain = (row.get("company_domain") or "").strip().lower()
    name = (row.get("company_name") or "").strip()
    notes: list[str] = []
    used_site = used_webpage = disambiguated = False

    # Stage 1: baseline search
    q1 = f"{name} {domain}".strip()
    res = serper_search(api_key, q1)
    texts = collect_texts(row, res, domain)

    # Stage 1b: disambiguation (brand collisions like TaylorMade golf)
    dc = domain.replace("www.", "")
    organic = (res or {}).get("organic") or []
    if res and not any(dc in (o.get("link") or "").lower() for o in organic[:5]):
        term = csv_keyword(row.get("company_description") or "")
        res2 = serper_search(api_key, f"{name} {domain} {term}".strip())
        if res2 and any(dc in (o.get("link") or "").lower()
                        for o in (res2.get("organic") or [])[:5]):
            res = res2
            disambiguated = True
            notes.append(f"re-queried with '{term}' (brand collision)")
        texts = collect_texts(row, res, domain)

    detail, rule, score = build_detail(texts, name)
    q1_detail, q1_rule, cur_score = detail, rule, score

    # Stage 2: site: search (own pages -> quantified outcomes, clients, principles)
    res_site = site_search(api_key, domain)
    site_texts = []
    for o in (res_site or {}).get("organic") or []:
        if o.get("snippet") and len(o["snippet"]) > 40:
            site_texts.append(("site: snippet", o["snippet"]))
    texts2 = texts
    if site_texts:
        texts2 = dedupe_texts(texts + site_texts)
        detail2, rule2, score2 = build_detail(texts2, name)
        if score2 > cur_score:
            used_site = True
            detail, rule, cur_score = detail2, rule2, score2
            notes.append(f"site: search improved to {rule2}")

    # Stage 3: homepage crawl when still nothing solid
    if rule == "fallback":
        url = find_homepage_url(domain, res_site)
        page = crawl_homepage(api_key, url)
        if page and page.get("text") and len(page["text"]) > 100:
            texts3 = dedupe_texts(texts2 + [("homepage", page["text"])])
            detail3, rule3, score3 = build_detail(texts3, name)
            if score3 > cur_score:
                used_webpage = True
                detail, rule, cur_score = detail3, rule3, score3
                notes.append(f"homepage crawl ({url}) -> {rule3}")

    icebreaker = PREFIX + detail + SUFFIX
    return {
        "domain": domain,
        "company": name,
        "q1_rule": q1_rule,
        "q1_detail": q1_detail,
        "final_rule": rule,
        "detail": detail,
        "chars": len(icebreaker),
        "disambiguated": "yes" if disambiguated else "",
        "used_site": "yes" if used_site else "",
        "used_webpage": "yes" if used_webpage else "",
        "notes": "; ".join(notes),
        "icebreaker": icebreaker,
    }


def main() -> None:
    argv = sys.argv[1:]
    csv_file: Path | None = None
    limit: int | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--csv" and i + 1 < len(argv):
            csv_file = Path(argv[i + 1])
            i += 1
        elif a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 1
        i += 1

    if csv_file is None:
        csv_file = HERE / "todo.csv"
    env = load_env()
    api_key = env.get("serper") or env.get("serper_api_key") or \
        env.get("serper_key") or env.get("serper.dev")
    if not api_key:
        sys.exit("Serper API key not found in .env")

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    OUT_DIR.mkdir(exist_ok=True)
    results: list[dict] = []
    processed = 0
    for r in rows:
        domain = (r.get("company_domain") or "").strip().lower()
        if not domain:
            continue
        results.append(process_company(r, api_key))
        processed += 1
        if limit is not None and processed >= limit:
            break

    if not results:
        sys.exit("No rows processed.")

    print(f"\n{'domain':<28} {'q1 rule':<13} {'final rule':<13} {'len':<4} "
          f"detail")
    print("-" * 112)
    n_site = n_web = n_disa = 0
    for r_ in results:
        print(f"{r_['domain']:<28} {r_['q1_rule']:<13} {r_['final_rule']:<13} "
              f"{r_['chars']:<4} {r_['detail']}"
              + (f"   [site:{r_['used_site']} crawl:{r_['used_webpage']} "
                 f"disamb:{r_['disambiguated']}]" if r_['notes'] else ""))
        n_site += r_['used_site'] == "yes"
        n_web += r_['used_webpage'] == "yes"
        n_disa += r_['disambiguated'] == "yes"

    print(f"\nSummary: {n_disa} disambiguated, {n_site} improved by site: search, "
          f"{n_web} rescued by homepage crawl (of {processed}).")
    print("\n--- Details (why / what the new methods added) ---")
    for r_ in results:
        changed = r_['q1_detail'] != r_['detail']
        if not (r_['notes'] or changed):
            continue
        print(f"\n== {r_['domain']}")
        if r_['q1_detail'] != r_['detail']:
            print(f"  Q1 ({r_['q1_rule']:<12}): {r_['q1_detail']}")
            print(f"  FINAL ({r_['final_rule']:<10}): {r_['detail']}")
        else:
            print(f"  ({r_['final_rule']}): {r_['detail']}")
        if r_['notes']:
            print(f"  notes: {r_['notes']}")

    out_path = OUT_DIR / f"{csv_file.stem}_search_review.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nOutput: {out_path}")
    print(f"Processed {processed} unique domains.")


if __name__ == "__main__":
    main()