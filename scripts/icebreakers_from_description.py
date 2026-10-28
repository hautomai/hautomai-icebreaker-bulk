#!/usr/bin/env python3
"""Extract an icebreaker detail from each lead's companyDescription.

No web crawling. Priority: quantified outcome > superlative > niche >
methodology > client names > certifications > geography > motto > service.
Fallback: "your growth so far".

Usage : python3 icebreakers_from_description.py [--csv <file>] [--limit N]
Output: output/<stem>_details.csv (original columns + detail + icebreaker)
"""

from __future__ import annotations

import csv
import html as html_mod
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"

FALLBACK = "your growth so far"
ICEBREAKER = "Been checking out your company on LinkedIn, {detail} piqued my curiosity. Had to send you this!"
MAX_WORDS = 14

NUMBER_RE = re.compile(
    r"(?:\d[\d,.]*(?:\s*[%+kKx\u00d7])?)"
    r"|\d[\d,.]+\s*(?:patients|members|clients|customers|leads|locations|"
    r"groups|clubs|users|brands|projects|campaigns|countries|channels|"
    r"followers|stores|offices|employees|million|m|billion|bn)"
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
FUNDING_RE = re.compile(
    r"\b(?:founded|funding|seed|series\s+[a-z]|raised|investor|"
    r"annual revenue|total funding|valuation)\b", re.I
)
WALK_BACK = {
    "over", "more", "than", "nearly", "almost", "up", "to", "exceeding",
    "only", "just", "about", "treated", "grew", "growth", "seen", "gained",
    "helped", "served", "delivered", "generated", "grown", "welcomed",
    "hosted", "supported",
}

SUPERLATIVE_RE = re.compile(
    r"(?:the\s+)?(?:uk['\u2019]?s|world['\u2019]?s|london['\u2019]?s|"
    r"canada['\u2019]?s|europe['\u2019]?s|america['\u2019]?s|#1|"
    r"top\s+[a-z])\s+(?:fastest|largest|leading|first|biggest|most|oldest|"
    r"fastest-growing)\s+[a-z][a-z' -]{2,60}?"
    r"(?=\s*(?:and\s+(?:has|is|boasts|with)\b|,|\.|\u2022|$))", re.I
)
SUPERLATIVE_LEAD_RE = re.compile(
    r"(?:world['\u2019]?s|uk['\u2019]?s|london['\u2019]?s)\s+(?:first|"
    r"leading|fastest|largest|biggest|most|oldest)\s+[a-z][a-z' -]{2,60}?"
    r"(?=\s*(?:and\s+(?:has|is|boasts|with)\b|,|\.|\u2022|$))", re.I
)
VOTED_RE = re.compile(
    r"(?:voted|named|ranked)\s+(?:the\s+)?(?:#\d|top\s+[a-z]+\s+(?:app|"
    r"agency|company|platform))[^.!;]{0,40}", re.I
)

NICHE_SPEC_RE = re.compile(
    r"speciali[sz](?:e|ing|es|ed)?\s+in\s+([^.!;]{3,100})", re.I
)
NICHE_EXPERT_RE = re.compile(
    r"(?:experts?|expertise|specialists?)\s+(?:in|on)\s+([^.!;]{3,100})", re.I
)
NICHE_DEDIC_RE = re.compile(
    r"dedicated\s+to\s+([^.!;]{3,100})"
    r"|exclusively\s+(?:for|serving|to)\s+([^.!;]{3,100})"
    r"|exclusive\s+focus\s+on\s+([^.!;]{3,100})", re.I
)
NICHE_CUT = re.compile(r"(?:,\s*|\b(?:which|that|while|designed|collaborating|"
                       r"collaborates|and\s+helps|to\s+help|for\s+clients)\b)", re.I)
NICHE_TOKENS = [
    "gaming", "sport", "mums", "mum", "baby", "motherhood", "mortgage",
    "bitcoin", "cryptocurrency", "psychotherapy", "counseling", "counselling",
    "coaching", "mental health", "nhs", "pharmacy", "prescription",
    "education", "schools", "law firms", "legal", "saas", "b2b", "b2c",
    "ecommerce", "retail", "beauty", "spa", "salon", "golf", "tabletop",
    "video games", "magento", "affiliate", "ppc", "seo", "social media",
    "augmented reality", "virtual reality", "rpa", "process automation",
    "compliance", "kyc", "aml", "men's health", "mens health", "white label",
    "white-labelled", "marketplace", "connected", "games", "android",
    "iphone", "ios", "web app", "mobile app", "fintech", "venture",
    "startup", "start-up", "wellness", "wine", "hospitality", "automotive",
    "fashion", "luxury", "food",
]
NICHE_HINT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in NICHE_TOKENS) + r")\b", re.I
)
NOUN_PHRASE_BAD = re.compile(
    r"\b(?:we\s+(?:are|'re|do|have|will)|our\s+company|is\s+a\b|are\s+a\b|"
    r"group\s+with|with\s+the|in\s+the|of\s+the|and\s+international|"
    r"has\s+been|that\s+we)\b", re.I
)

METHOD_RE = re.compile(
    r"([A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,3})\s+as\s+a\s+Service"
    r"|proprietary\s+([A-Z]\w*(?:\s+\w+){0,4})"
    r"|(?:our|the)\s+([A-Z]\w*(?:\s+[A-Z]\w*){0,3})\s+(?:framework|system|"
    r"method|methodology|playbook|journey|model|engine|platform|approach|"
    r"process)", re.I
)
PRODUCT_RE = re.compile(r"[A-Z][a-zA-Z0-9]{2,}(?:\u00ae|\u2122)")

CLIENTS_RE = re.compile(
    r"(?:clients?|partners?|customers?)\s+(?:include|includes|are|such as|"
    r"like|working with)\s+([^.!;]{3,120})", re.I
)
CLIENTS_ALT_RE = re.compile(
    r"(?:working|partnering)\s+with\s+([A-Z][\w&.'\u2019 -]{2,90})", re.I
)

CERT_RE = re.compile(
    r"google premier partner|meta business partner|microsoft partner|"
    r"google partner|hubspot partner|accredited|certified|iso\s*\d+|"
    r"soc\s*2|partner program|partner of the year", re.I
)

GEO_RE = re.compile(
    r"(?:across|throughout|around|based\s+in|serving|targeting|covering|"
    r"operating\s+in)\s+([^.!;]{2,80})", re.I
)
GEO_WORDS = [
    "uk", "us", "usa", "europe", "canada", "england", "scotland", "wales",
    "ireland", "london", "glasgow", "gulf", "turkey", "middle east", "asia",
    "africa", "nordic", "sweden", "norway", "denmark", "germany", "france",
    "australia", "new zealand", "european", "british", "scandinavia",
]

MOTTO_RE = re.compile(
    r"\b(?:believe|believes)\s+(?:that\s+)?([a-z][^.!;]{5,90})", re.I
)

SERVICE_RE = re.compile(
    r"(?:we|our company|the company|we['\u2019]?re)\s+"
    r"(provide|providing|offer|offering|deliver|delivering|specialise|"
    r"specialising|specialize|specializing|focus|focusing|help|helping|build|"
    r"building|create|creating|design|designing|develop|developing|manage|"
    r"managing|find|finding|run|running|operate|operating|do|doing|make|"
    r"making|work|working|serve|serving|connect|connecting|support|"
    r"supporting|power|powering|publish|publishing)\s+([^.!]{3,120})", re.I
)
DATA_DRIVEN_RE = re.compile(
    r"(?:we['\u2019]?re|we are)\s+data[ -]?driven\s+to\s+(help|serve|support|"
    r"deliver|build)\s+([^.!;]{3,80})", re.I
)
WILL_RE = re.compile(
    r"^[^.!]{0,40}?\bwill\s+(help|create|develop|build|work|provide|deliver|"
    r"connect|support|take|drive|transform)\s+([^.!]{3,120})", re.I
)

GERUND = {
    "provide": "providing", "offer": "offering", "deliver": "delivering",
    "specialise": "specialising", "specialize": "specializing",
    "focus": "focusing", "help": "helping", "build": "building",
    "create": "creating", "design": "designing", "develop": "developing",
    "manage": "managing", "find": "finding", "run": "running",
    "operate": "operating", "do": "doing", "make": "making",
    "work": "working", "serve": "serving", "connect": "connecting",
    "support": "supporting", "power": "powering", "publish": "publishing",
    "take": "taking", "drive": "driving", "transform": "transforming",
}
for _g in list(GERUND.values()):
    GERUND[_g] = _g

GARBAGE_RE = re.compile(
    r"seems?\s+to\s+be|appears?\s+to\s+be|no description|placeholder|"
    r"scraped|sample text|lorem ipsum", re.I
)

LEAD_STRIP = re.compile(
    r"^(?:we\s+are\s+|we['\u2019]?re\s+|we\s+|our\s+company\s+|the\s+company\s+|"
    r"the\s+firm\s+|the\s+studio\s+|the\s+agency\s+|it['\u2019]?s\s+|its\s+|"
    r"that\s+|and\s+|with\s+|as\s+|a\s+|an\s+|this\s+|which\s+|where\s+|"
    r"having\s+|being\s+|the\s+|our\s+)+", re.I
)


def norm_desc(s: str) -> str:
    s = html_mod.unescape(s or "")
    s = s.replace("\\", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_detail(d: str) -> str:
    d = re.sub(r"\s+", " ", d).strip()
    d = d.strip(" \t.,;:!?\u2013\u2014\u201c\u201d\"'")
    d = re.sub(r"\s*[-|\u2013\u2014]\s*$", "", d)
    words = d.split()
    if len(words) > MAX_WORDS:
        cut = None
        for i in range(MAX_WORDS - 1, 2, -1):
            if words[i].lower() in {"and", "or", "with", "for", "across", "to", "in", "on"}:
                cut = i
                break
        words = words[: cut or MAX_WORDS]
        while words and words[-1].lower() in {"and", "or", "with", "for", "to", "in", "on", "the", "a", "an"}:
            words.pop()
    d = " ".join(words).strip(" .,;:!?")
    d = LEAD_STRIP.sub("", d, count=1)
    d = d.strip(" .,;:!?")
    if d and d[0].isupper():
        first = d.split()[0]
        if not any(c.isupper() for c in first[1:]):
            d = d[0].lower() + d[1:]
    return d


def light_clean(d: str) -> str:
    """Gentle cleanup for whole-sentence candidates (no truncation)."""
    d = re.sub(r"\s+", " ", d).strip(" \t.,;:!?\u2013\u2014\u201c\u201d\"'")
    d = LEAD_STRIP.sub("", d, count=1)
    d = d.strip(" .,;:!?")
    if d and d[0].isupper():
        first = d.split()[0]
        if not any(c.isupper() for c in first[1:]):
            d = d[0].lower() + d[1:]
    return d


def split_sentences(desc: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", desc) if p.strip()]


def _has_year_only_number(s: str) -> bool:
    years = YEAR_RE.findall(s)
    if not years:
        return False
    rest = YEAR_RE.sub("", s)
    return not NUMBER_RE.search(rest)


def rule_quantified(sentences: list[str]) -> str | None:
    best: tuple[float, str] | None = None
    for s in sentences:
        if FUNDING_RE.search(s) or _has_year_only_number(s):
            continue
        m = SUPERLATIVE_RE.search(s)
        if m:
            clause = m.group(0)
            score = 6.0 - len(clause.split()) / 6.0
            if best is None or score > best[0]:
                best = (score, clause)
            continue
        if not NUMBER_RE.search(s):
            continue
        words = s.split()
        idx = next((i for i, w in enumerate(words) if re.search(r"\d", w)), 0)
        while idx > 0 and words[idx - 1].lower() in WALK_BACK:
            idx -= 1
        clause_words = words[idx:]
        for i in range(idx + 2, len(clause_words)):
            if clause_words[i].endswith(","):
                clause_words = clause_words[: i + 1]
                break
        clause = " ".join(clause_words).strip(" ,;:!?")
        score = 12.0
        if re.search(r"\d\s*%|\$\d|\u00a3\d|\u20ac\d", clause):
            score += 3
        if re.search(r"\b(?:treated|members|patients|clients|customers|leads|"
                     r"locations|brands)\b", clause, re.I):
            score += 2
        if re.search(r"\b(?:grew|growth|increased|scaled|reduced|roi|"
                     r"conversion)\b", clause, re.I):
            score += 2
        score -= len(clause.split())
        if best is None or score > best[0]:
            best = (score, clause)
    return best[1] if best else None


def rule_superlative_lead(desc: str) -> str | None:
    m = SUPERLATIVE_LEAD_RE.search(desc)
    if m:
        return m.group(0)
    m = VOTED_RE.search(desc)
    if m:
        return m.group(0)
    return None


def rule_niche(desc: str) -> str | None:
    for pat, prefix in ((NICHE_SPEC_RE, "specialising in "),
                        (NICHE_EXPERT_RE, "expertise in "),
                        (NICHE_DEDIC_RE, "dedicated to ")):
        m = pat.search(desc)
        if m:
            g = next((x for x in m.groups() if x), None) or ""
            g = NICHE_CUT.split(g, maxsplit=1)[0]
            g = g.strip(" .,;:!?")
            if 3 <= len(g) <= 90 and len(g.split()) <= 10:
                return prefix + g
    m = NICHE_HINT_RE.search(desc)
    if m:
        token = m.group(0)
        for s in split_sentences(desc):
            if token.lower() not in s.lower():
                continue
            words = s.split()
            idx = next((i for i, w in enumerate(words)
                        if token.lower() in re.sub(r"[^a-z0-9' -]", "", w.lower())), None)
            if idx is None:
                continue
            clause = words[idx: idx + 9]
            while clause and clause[-1].lower() in {"and", "or", ","}:
                clause.pop()
            c = " ".join(clause).strip(" .,;:!?")
            c = re.split(r"\s+or\s+(?:just\s+about|anything|more)|"
                         r",\s*(?:everything|more)", c, maxsplit=1)[0]
            c = c.strip(" .,;:!?")
            if len(c.split()) >= 2 and not NOUN_PHRASE_BAD.search(c):
                return "focusing on " + c.lower()
    return None


def rule_method(desc: str) -> str | None:
    m = METHOD_RE.search(desc)
    if m:
        g = next((x for x in m.groups() if x), None)
        if g:
            return g
    for pm in PRODUCT_RE.finditer(desc):
        return pm.group(0).rstrip("\u00ae\u2122")
    return None


def rule_clients(desc: str) -> str | None:
    g = None
    m = CLIENTS_RE.search(desc)
    if m:
        g = re.split(r"[.;]", m.group(1))[0]
    else:
        m = CLIENTS_ALT_RE.search(desc)
        if m:
            g = re.split(r"[.;]", m.group(1))[0]
    if not g:
        return None
    first_tokens = [t for t in g.split() if t.strip(" .,;:!?")]
    if len(first_tokens) < 2 or not all(t[0].isupper() for t in first_tokens[:2]):
        return None
    names = [n.strip(" .,;:!?") for n in g.split(",")]
    kept: list[str] = []
    for n in names:
        if len(kept) >= 3:
            break
        if 2 <= len(n) <= 40 and n[0].isupper():
            kept.append(n)
    if not kept:
        return None
    if len(kept) >= 2:
        return "partnering with " + ", ".join(kept[:-1]) + " and " + kept[-1]
    return "partnering with " + kept[0]


def rule_cert(desc: str) -> str | None:
    m = CERT_RE.search(desc)
    if not m:
        return None
    s = m.group(0)
    if s.lower() in {"accredited", "certified"}:
        return "accredited by industry bodies"
    return s.lower() if s[0].isupper() and len(s) < 30 else s


def rule_geo(desc: str) -> str | None:
    for m in GEO_RE.finditer(desc):
        g = m.group(1).strip(" .,;:!?")
        gl = g.lower()
        if any(w in gl for w in GEO_WORDS) and len(g.split()) <= 8 and len(g) >= 3:
            return "serving " + g
    return None


def rule_motto(desc: str) -> str | None:
    m = MOTTO_RE.search(desc)
    if m:
        g = m.group(1).strip(" .,;:!?")
        if 5 <= len(g) <= 80:
            return g
    return None


def _gerundize(text: str) -> str:
    words = text.split()
    for i in range(1, len(words)):
        if words[i - 1].lower() in {"and", "or"} and words[i].lower() in GERUND:
            words[i] = GERUND[words[i].lower()]
    return " ".join(words)


def rule_service(desc: str, company: str) -> str | None:
    m = SERVICE_RE.search(desc)
    if m:
        verb, rest = m.group(1).lower(), m.group(2)
        rest = re.split(r"\b(?:which|that|while|so that|to help)\b", rest, maxsplit=1)[0]
        return _gerundize(f"{GERUND.get(verb, verb + 'ing')} {rest}".strip(" .,;:!?"))
    m = DATA_DRIVEN_RE.search(desc)
    if m:
        rest = re.split(r"\b(?:identifying|which|and\s+focusing)\b",
                        m.group(2), maxsplit=1)[0]
        rest = rest.strip(" .,;:!?")
        return _gerundize(f"{GERUND.get(m.group(1).lower(), m.group(1).lower() + 'ing')} {rest}")
    candidates: list[str] = []
    for s in split_sentences(desc):
        m = WILL_RE.search(s)
        if m:
            rest = re.split(r"\b(?:which|while)\b", m.group(2), maxsplit=1)[0]
            rest = rest.strip(" .,;:!?")
            candidates.append(_gerundize(
                f"{GERUND.get(m.group(1).lower(), m.group(1).lower() + 'ing')} {rest}"))
    for s in split_sentences(desc):
        if GARBAGE_RE.search(s):
            continue
        t = s
        if company:
            cn = company.strip()
            if t.lower().startswith(cn.lower()):
                t = t[len(cn):].lstrip(", :;-")
        t = re.sub(r"^[A-Z][\w']*(?:\s+[A-Z][\w']*){0,4}\s+(?:is|are|was|will|can)\s+",
                   "", t)
        t = re.sub(r"^(?:is|are|will|it['\u2019]?s)\s+", "", t, flags=re.I)
        t = t.strip(" .,;:!?")
        if 3 <= len(t) <= 130 and t[0].isalpha():
            t = light_clean(t)
            if passes_sense_check(t) and passes_grammar_check(t):
                candidates.append(t)
    if candidates:
        return min(candidates, key=_candidate_key)
    return None


DET_WORDS = {"the", "a", "an", "your", "our", "this", "that", "these",
             "those", "my", "his", "her", "its"}

GRAMMAR_BAD = re.compile(
    r"\b(?:we['\u2019]?re|we\s+are|we['\u2019]?ll|we\s+will|we\s+have|"
    r"we\s+want|we\s+just|we\s+do|we\s+don['\u2019]?t|we\s+can|we\s+help|"
    r"i['\u2019]?m\s+|i\s+am\s+|our\s+aim|our\s+goal|our\s+company|"
    r"our\s+clients)\b", re.I
)
LEADING_VERB_BAD = re.compile(
    r"^(?:is|are|was|were|will|has|have|had|do|does|did|can|could|would|"
    r"should|may|might|must|also|even|just|simply|truly|really)\b", re.I
)
SV_AGREE = re.compile(
    r"\b(?:collective|company|agency|studio|firm|business|platform|network|"
    r"community|team|brand|group|organisation|organization|agency)\b"
    r"\s+(?:that|which)\s+(?!\w*s\b)(?:want|give|help|work|specialise|"
    r"specialize|provide|offer|deliver|create|build|make|do|serve|manage|"
    r"find|run|operate)\b", re.I
)


def passes_sense_check(d: str) -> bool:
    """The detail must form a real subject for "piqued my curiosity"."""
    w = d.split()
    return len(w) >= 4 or (len(w) >= 3 and w[0].lower() in DET_WORDS)


def passes_grammar_check(d: str) -> bool:
    return not (GRAMMAR_BAD.search(d) or LEADING_VERB_BAD.search(d)
                or SV_AGREE.search(d))


def _candidate_key(c: str) -> tuple[int, int]:
    first = c.split()[0].lower() if c.split() else ""
    pref = 0 if first.endswith("ing") or re.match(r"\d", first) else 1
    return (pref, len(c.split()))


def extract_detail(desc: str, company: str) -> str:
    desc = norm_desc(desc)
    if not desc:
        return FALLBACK
    sentences = split_sentences(desc)
    for candidate in (
        rule_quantified(sentences),
        rule_superlative_lead(desc),
        rule_niche(desc),
        rule_method(desc),
        rule_clients(desc),
        rule_cert(desc),
        rule_geo(desc),
        rule_motto(desc),
        rule_service(desc, company),
    ):
        if candidate:
            d = clean_detail(candidate)
            if d and passes_sense_check(d) and passes_grammar_check(d):
                return d
    return FALLBACK


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
        matches = sorted(HERE.glob("*.csv"))
        if not matches:
            sys.exit("No CSV found - use --csv <file>")
        csv_file = matches[0]

    OUT_DIR.mkdir(exist_ok=True)
    stem = csv_file.stem

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    processed: dict[str, str] = {}
    for r in rows:
        d = (r.get("companyDomain") or "").strip().lower()
        if not d or d in processed:
            continue
        desc = r.get("companyDescription") or ""
        company = r.get("companyName") or ""
        detail = extract_detail(desc, company)
        processed[d] = detail
        if limit is None or len(processed) <= limit:
            print(f"{d:<32} {detail}")

    out_fields = fieldnames + ["detail", "icebreaker"]
    out_path = OUT_DIR / f"{stem}_details.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for r in rows:
            d = (r.get("companyDomain") or "").strip().lower()
            detail = processed.get(d, FALLBACK)
            out = dict(r)
            out["detail"] = detail
            out["icebreaker"] = ICEBREAKER.format(detail=detail)
            writer.writerow(out)

    print(f"\nOutput: {out_path}")
    print(f"Processed {len(processed)} unique domains, {len(rows)} rows.")


if __name__ == "__main__":
    main()