#!/usr/bin/env python3
"""Bulk recent-client extraction -> personalized icebreakers CSV.

Reads  : dataset_*.csv (leads)
Writes : output/leads_with_clients.csv
         output/endpoints_found.md
         output/results.json (resume cache)

Usage  : python3 icebreakers_bulk.py [--limit N] [--domain d] [--fresh]
"""

from __future__ import annotations

import csv
import html as html_mod
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lh

HERE = Path(__file__).resolve().parent
CSV_FILE: Path | None = None
OUT_DIR = HERE / "output"
RESULTS_FILE = OUT_DIR / "results.json"
OUT_CSV = OUT_DIR / "leads_with_clients.csv"
REPORT_FILE = OUT_DIR / "endpoints_found.md"


def _default_csv() -> Path:
    for pat in ("dataset_*.csv", "*.csv"):
        matches = sorted(HERE.glob(pat))
        if matches:
            return matches[0]
    raise SystemExit("No input CSV found - use --csv <file>")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
]
TIMEOUT = 9
PAGE_BUDGET = 14
WORKERS = 4
REQUEST_GAP = 0.25

PRIORITY_PATHS = [
    "/case-studies", "/case-study", "/casestudies", "/our-case-studies",
    "/work", "/our-work", "/works", "/recent-work", "/latest-work", "/featured-work",
    "/work-weve-done", "/what-we-did",
    "/portfolio", "/our-portfolio", "/portfolio-work",
    "/projects", "/our-projects", "/recent-projects",
    "/clients", "/our-clients", "/client-list", "/clients-work", "/who-we-work-with",
    "/customers", "/our-customers", "/customer-stories", "/customer-success",
    "/success-stories", "/success", "/results", "/our-results", "/impact",
    "/showcase", "/featured", "/gallery", "/work-gallery",
    "/testimonials", "/references",
]

NAV_KEYWORDS = re.compile(
    r"case|work|portfolio|project|client|result|success|showcase|testimonial|reference|gallery|impact|featured",
    re.I,
)
NAV_EXCLUDE = re.compile(
    r"blog|news|event|career|job|team|about|contact|service|product|legal|privacy|policy|terms|faq|"
    r"support|login|shop|cart|tag|category|author|page/|wp-json|feed|amp|print|download|subscribe|"
    r"article|articles|insights|resources|library|press|media-kit|academy|training|webinar",
    re.I,
)
SITEMAP_KEYWORDS = re.compile(
    r"(case|work|portfolio|project|client|result|success|showcase|testimonial|reference|gallery)",
    re.I,
)
SITEMAP_EXCLUDE = re.compile(
    r"blog|news|event|career|job|team|about|contact|service|product|legal|privacy|policy|terms|faq|"
    r"author|tag/|category/|comment|feed|print|download|subscribe|article|articles|insights|"
    r"resources|library|press|webinar|training|academy|media-kit",
    re.I,
)

SERVICE_TOKENS = {
    "website", "web", "site", "design", "redesign", "development", "dev",
    "marketing", "campaign", "campaigns", "advertising", "ad", "ads",
    "media", "digital", "social", "content", "strategy", "strategies",
    "seo", "sem", "ppc", "email", "ecommerce", "e-commerce", "app", "apps",
    "application", "platform", "software", "product", "products", "solution", "solutions",
    "services", "service", "contest", "program", "launch", "project", "projects",
    "work", "case", "study", "studies", "portfolio", "gallery", "showcase",
    "branding", "brand", "rebrand", "creative", "video", "photography",
    "printing", "print", "packaging", "logo", "icon", "banner", "landing",
    "page", "pages", "ui", "ux", "shop", "store", "booking", "crm", "erp",
    "training", "consulting", "management", "agency", "studio", "firm", "house",
    "custom", "label", "promotions", "marketing", "materials", "visuals", "visual",
    "activation", "campaigns", "creative", "experience", "experiences", "solution",
    "brochure", "brochures", "catalogue", "catalog", "menu", "menus",
}
ADJECTIVE_TOKENS = {
    "nationwide", "national", "international", "global", "regional", "local",
    "digital", "online", "interactive", "responsive", "creative", "custom",
    "multi-channel", "multichannel", "omnichannel", "integrated", "strategic",
    "gamified", "consumer", "corporate", "enterprise", "b2b", "b2c",
    "experiential", "immersive", "retail", "social", "mobile", "smart",
    "personalized", "award-winning", "award winning", "full-service", "full service",
    "new", "latest", "recent", "featured", "top", "best", "our", "the", "a", "an",
    "great", "big", "better", "best", "winning", "awarded", "upcoming", "previous",
    "all", "show", "watch", "view", "see", "read", "learn", "domestic", "student",
    "students", "recruitment", "recruit", "awareness", "campaign", "campaigns",
    "national", "canadian", "local",
}
MONTHS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
FILENAME_GENERIC = {
    "logo", "icon", "badge", "thumb", "thumbnail", "client", "partner",
    "slider", "carousel", "footer", "header", "logo", "logos", "home",
    "hero", "banner", "image", "img", "photo", "bg", "arrow", "btn",
    "accordion", "desktop", "mobile", "tablet", "screen", "screenshot",
    "feature", "features", "category", "categories", "slide", "cover",
    "small", "large", "medium", "default", "placeholder", "tab", "tabs",
    "main", "sub", "side", "front", "back", "top", "bottom", "profile",
    "avatar", "user", "users", "case", "study", "work", "portfolio",
    "project", "projects", "brand", "brands", "mark", "marks", "seal",
    "stamp", "ribbon", "award", "awards", "star", "check", "close",
    "images", "pics", "pic", "photos", "screenshot", "screen", "image",
}
CONNECTORS = {"and", "the", "for", "in", "on", "at", "by", "of", "de", "la", "le", "du", "des", "&", "to", "with", "from", "into", "across"}

CONTEXT_DROP = {
    "digital", "marketing", "campaign", "campaigns", "advertising", "media",
    "social", "content", "strategy", "strategies", "solutions", "solution",
    "services", "service", "website", "web", "design", "development", "creative",
    "agency", "studio", "firm", "platform", "software", "product", "products",
    "project", "projects", "work", "case", "study", "studies", "portfolio",
    "gallery", "showcase", "branding", "brand", "logo", "icon", "image", "photo",
    "video", "ui", "ux", "seo", "sem", "ppc", "online", "app", "apps",
    "application", "mobile", "landing", "page", "pages", "blog", "print",
    "printing", "packaging", "consulting", "management", "engagement",
    "engagements", "collateral", "visuals", "visual", "graphic", "graphics",
    "thumbnail", "thumbnails", "picture", "pictures", "mockup", "mockups",
    "screenshot", "screenshots", "banner", "slide", "slider", "hero",
    "background", "result", "results", "overview", "learn", "more", "read",
    "view", "all", "see", "click", "here", "example", "examples", "sample",
    "samples", "recent", "latest", "featured", "new", "top", "best", "our",
    "the", "and", "of", "for", "in", "on", "at", "with", "from", "to",
    "about", "home", "testimonial", "testimonials", "reference", "references",
    "success", "impact", "client", "clients", "customer", "customers",
    "partner", "partners", "logo", "logos", "footer", "header", "menu",
    "icon", "icons", "button", "link", "links", "sign", "signed", "announce",
    "announces", "announcement", "press", "release", "agreement",
    "video", "videos", "upcoming", "watch", "check", "out",
    "back", "show", "shows", "recruitment", "recruit", "domestic",
    "student", "students", "opportunity", "opportunities", "store",
    "stores", "materials", "material", "calculator", "tool", "tools",
    "portal", "dashboard", "system", "systems", "widget", "plugin",
    "extension", "template", "templates", "theme", "kit", "pack",
    "section", "sections", "page", "pages", "human", "led", "assisted",
    "research", "integrated", "integration", "integrations", "scale",
    "insights", "workflow", "smart", "education", "use", "uses", "cases",
    "interest", "interested", "contact", "us", "today", "need", "want",
    "related", "posts", "post", "questions", "frquentes", "gmb", "wing",
    "podcast", "episode", "certification", "badge", "newsletter",
    "iso", "soc", "gdpr", "hipaa", "pci", "registration", "registrations",
    "compliance", "standard", "standards", "filter", "by", "pourquoi",
    "optimiser", "optimisation", "son", "sa", "ses", "mon", "ma", "mes",
    "google", "growth", "intelligent", "intelligence", "msp", "msps",
    "article", "articles", "blog", "blogs", "feature", "features",
    "banking", "finance", "manufacturing", "logistics", "travel",
    "account", "onboarding", "comment", "faire", "build", "relevance",
    "quickly", "was", "were", "manufactured", "manufacturing",
    "purpose", "performance", "magazine", "channel", "living", "wage",
    "employer", "networking", "write", "based", "driven", "creatively",
    "chief", "officer", "key", "people", "executive", "manager",
    "president", "founder", "staff", "graduate", "scheme", "actions",
    "focus", "understand", "envision", "legals", "difference", "makers",
    "edition", "reports", "castle", "cabinet", "secretary", "actions",
    "award", "awards", "hackney", "half", "rooftop", "cityscape",
    "external", "colleagues", "joke", "street", "art", "wall",
    "whitechapel", "sheffield", "night", "brochure", "years",
    "professionals", "professional", "giving", "talk", "omni", "data",
    "acquisition", "welsh", "bcorp", "certified", "prweek", "power",
    "book", "lifestage", "northern", "golf", "cookie", "cookies",
    "settings", "accept", "reject", "preferences", "manage",
    "uniquely", "taste", "category", "sponsorship", "formalising",
    "socialise", "socialising", "londonbased", "grow", "growing",
    "driving", "opening", "recruiting", "creating", "defining",
    "neighbourhood", "fashionable", "party", "heritage", "footfall",
    "tenant", "referrals", "consumer", "minds", "magistrates",
    "tweet", "tweets", "general", "resources", "week", "tech", "usa",
    "news", "press", "events", "event", "more", "less",
    "purpose-driven", "impactful", "transformative", "digital-first",
    "customer", "customers", "custom",
}

SINGLE_STOP = {
    "home", "about", "work", "portfolio", "clients", "client", "case",
    "studies", "services", "blog", "contact", "team", "careers", "news",
    "testimonials", "results", "projects", "gallery", "studio", "agency",
    "logo", "icon", "image", "media", "marketing", "digital", "design", "web",
    "page", "view", "all", "more", "learn", "read", "submit", "search", "menu",
    "top", "main", "featured", "latest", "recent", "showcase", "references",
    "success", "impact", "partners", "customers", "store", "shop", "quote",
    "contact", "industries", "expertise", "capabilities", "services",
    "experience", "solutions", "strategy", "creative", "brand", "branding",
    "google", "hubspot", "facebook", "instagram", "meta", "microsoft",
    "amazon", "partner", "certified", "linkedin", "twitter", "youtube",
    "homepage", "header", "footer", "navigation", "banner", "thumb",
    "hundreds", "thousands", "millions", "dozens", "hundred", "thousand",
    "million", "solved", "done", "welcome", "ready", "start", "now",
    "today", "add", "images", "image", "get", "lets", "let", "your",
    "you", "they", "we", "us", "it", "our", "more", "most", "some",
    "online", "free", "pro", "premium", "contact", "submit", "watch",
    "why", "what", "how", "when", "where", "who", "which", "make",
    "making", "this", "that", "these", "those", "them", "were", "its",
    "six", "lessons", "learned", "emotion", "billboard", "collage",
    "three", "covid", "corona", "loves", "homebuilding", "industry",
    "industries", "charity", "charities", "fundraising", "guide",
    "putting", "need", "think", "getting", "registered", "money",
    "time", "smarter", "faster", "easy", "simple", "quickly", "right",
    "here", "join", "more", "business", "businesses", "government",
    "community", "communities", "education", "health", "healthcare",
    "finance", "financial", "insurance", "legal", "construction",
    "tourism", "hospitality", "retail", "consumer", "enterprise",
    "corporate", "public", "relations", "communications", "communication",
    "marketing", "advertising", "brand", "branding", "creative",
    "strategy", "strategies", "content", "social", "media", "digital",
    "email", "video", "website", "app", "mobile", "seo", "ppc",
    "agence", "referencement", "refonte", "reputation", "publicite",
    "universite", "marque", "marques", "branding", "conception", "creation",
    "strategie", "numerique", "marketing", "communication", "social",
    "coming", "soon", "launching", "shortly", "under", "construction",
    "human", "use", "uses", "subscribe", "form", "forms", "voici",
    "astuces", "astuce", "pour", "les", "des", "nos", "notre", "vos",
    "votre", "avec", "dans", "chez", "sur", "plus", "bien", "tout",
    "tous", "toute", "faites", "conseils", "conseil", "guide", "guides",
    "besoin", "besoins", "nouveau", "nouvelle", "nouveaux", "meilleur",
    "meilleure", "sera", "etre", "sont", "vous", "nous", "scale",
    "research", "integrated", "integration", "integrations", "insights",
    "workflow", "teams", "smart", "education", "b2b", "b2c",
    "temoignages", "tmoignages", "temoignage", "tmoignage", "cases",
    "related", "posts", "post", "questions", "frquentes", "gmb", "wing",
    "podcast", "episode", "episodes", "certification", "badge", "newsletter",
    "txramp", "quelle", "quel", "quelles", "quels", "est", "suis", "es",
    "sommes", "etes", "sont", "faire", "entreprise", "entreprises",
    "societe", "societes", "monde", "finition", "referencement",
    "referencements", "rencement", "reponse", "reponses", "question",
    "frequentes", "professionnel", "professionnelle", "graphiste",
    "redaction", "contenu", "webdesign", "boutique", "commerce",
    "affaires", "internet", "outils", "logiciel", "logiciels",
    "plateforme", "plateformes", "tarifs", "prix", "equipe", "chef",
    "directeur", "gestion", "campagne", "campagnes", "saas",
    "steve", "dave", "nick", "phil", "mike", "jake", "ben", "tom",
    "sam", "bob", "joe", "jim", "dan", "chris", "alex", "adam", "andy",
    "joel", "luke", "kyle", "cory", "corey", "darren", "derek", "doug",
    "ed", "eddie", "frank", "fred", "gene", "greg", "gus", "ian", "jack",
    "jamie", "jared", "jay", "jeff", "jeremy", "jesse", "jon", "jonathan",
    "jordan", "jose", "juan", "julian", "keith", "ken", "kent", "kerry",
    "kurt", "lee", "leo", "leslie", "lewis", "liam", "loren", "louis",
    "lyle", "marcus", "martin", "max", "miles", "morgan", "nathan",
    "neil", "noah", "norman", "owen", "peter", "philip", "pierre",
    "quentin", "raymond", "reed", "reginald", "rene", "ricardo", "rich",
    "rick", "ricky", "rob", "roger", "ron", "roy", "russell", "seth",
    "shane", "shaun", "shawn", "simon", "stan", "stuart", "syd", "taylor",
    "ted", "terry", "theo", "tony", "travis", "trevor", "tyrone", "vance",
    "victor", "vincent", "wade", "warren", "wayne", "wesley", "walt",
    "xavier", "zach", "zack", "zane", "austin", "benjamin", "blake",
    "brad", "bradley", "brendan", "brent", "brett", "bryce", "byron",
    "cameron", "carlos", "cecil", "cesar", "chad", "chester", "claude",
    "clint", "clyde", "colin", "connor", "curtis", "cyril", "damian",
    "dana", "danny", "darrell", "daryl", "dean", "delbert", "dennis",
    "derrick", "dewayne", "dillon", "dominic", "don", "donald", "duane",
    "dwayne", "dylan", "earl", "edgar", "edwin", "elijah", "ellis",
    "emmanuel", "ernest", "ethan", "eugene", "evan", "felix", "floyd",
    "francis", "francisco", "gabriel", "gavin", "gene", "geoffrey",
    "gerald", "gerard", "gilbert", "glenn", "gordon", "graham", "grant",
    "gregory", "guy", "harold", "harry", "harvey", "hector", "herbert",
    "howard", "hugh", "isaac", "isaiah", "ivan", "jackson", "jacob",
    "james", "jasper", "jed", "jeremiah", "jerome", "jill", "jimmy",
    "joan", "joann", "joey", "johnny", "jorge", "joseph", "josh", "julius",
    "karl", "kelly", "kenny", "kirk", "lance", "larry", "lawrence",
    "leon", "leonard", "les", "lincoln", "lloyd", "logan", "lonnie",
    "lucas", "malcolm", "manuel", "marc", "mario", "marion", "marlon",
    "marshall", "marvin", "mason", "mathew", "maurice", "maxwell",
    "melvin", "micah", "micheal", "miguel", "milton", "mitchell",
    "morris", "nathaniel", "neal", "ned", "nelson", "nicholas", "nigel",
    "oliver", "omar", "orlando", "oscar", "pablo", "parker", "pedro",
    "perry", "pete", "phillip", "rafael", "ralph", "ramon", "randall",
    "randolph", "raul", "reid", "rob", "robbie", "robert", "robin",
    "rocco", "rod", "rodney", "roland", "ronnie", "ross", "rudy",
    "salvatore", "samuel", "santiago", "shannon", "sidney", "solomon",
    "spencer", "stanley", "stewart", "sylvester", "terence", "terrance",
    "terrell", "terrence", "theodore", "tobias", "todd", "tommy",
    "tristan", "troy", "virgil", "wesley", "wilbert", "wilbur", "wilfred",
    "willie", "wilson", "zachary",
}

GENERIC_PHRASES = {
    "real estate", "marketing services", "digital marketing", "social media",
    "web design", "web development", "graphic design", "brand design",
    "logo design", "case studies", "case study", "our clients", "our work",
    "our portfolio", "featured work", "recent work", "client testimonials",
    "customer success", "about us", "get in touch", "contact us",
    "view our work", "see our work", "all rights reserved", "privacy policy",
    "terms of service", "cookies", "learn more", "book a call", "start a project",
    "our projects", "latest work", "our results", "happy customers",
    "our partners", "clients include", "trusted by", "powered by",
    "marketing campaigns", "campaign results", "our team", "meet the team",
    "what we do", "who we are", "our story", "get started", "read more",
    "view all", "more work", "more projects", "more clients", "all work",
    "all projects", "all clients", "portfolio work", "work gallery",
    "related posts", "questions frquentes", "certification badge",
    "wing it podcast", "our podcast", "technology saas",
    "business growth", "marketing strategy", "content marketing",
    "paid media", "digital strategy", "golf networking",
    "the difference makers", "living wage employer", "channel partner",
    "purpose magazine", "write about us", "london-based team",
    "staff showcase", "staff bar", "key people", "chief marketing",
    "difference engine", "data acquisition", "b-corp certified",
    "b corp certified", "giving you time", "business against poverty",
    "welsh government cabinet", "cabinet secretary", "omni ai",
    "london-based team", "prweek power book", "your cookie settings",
    "cookie settings", "life-stage", "golf networking",
    "london based team", "category sponsorship", "welsh. it's in the taste",
    "londonbased team", "latest tweet", "wales tech week",
}

CLIENTS_RE = re.compile(
    r"(?i)(?:clients?\s+(?:include|includes|such as|like|we\s*['\u2019]?ve\s+worked\s+with|"
    r"we\s+work\s+with|we\s+are\s+proud\s+to\s+work\s+with|we\s+serve|featured|"
    r"partners?\s+with|trusted\s+by|used\s+by|powered\s+by)|"
    r"include(?:s)?\s+(?:organizations?|companies?|brands?|firms?|names?)\s+such\s+as)"
    r"\s*[:.\u2013\u2014-]?\s*([^.!?]{8,400})"
)
CASE_TITLE_RE = re.compile(
    r"(?i)case\s*stud(?:y|ies)\s*[:.\u2013\u2014-]\s*([^|\u2013\u2014-]{2,80})"
)
YEAR_RE = re.compile(r"20([0-2][0-9])")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def agency_tokens(company_name: str, domain: str) -> set[str]:
    tokens: set[str] = set()
    for word in re.split(r"[^a-z0-9]+", (company_name or "").lower()):
        if len(word) >= 4:
            tokens.add(word)
    base = domain.split(".")[0]
    for word in re.split(r"[^a-z0-9]+", base.lower()):
        if len(word) >= 3:
            tokens.add(word)
    return tokens


def clean_candidate(s: str) -> str:
    s = html_mod.unescape(s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[\u00ae\u2122\u00a9\u2022]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(?:case\s*stud(?:y|ies)\s*[:.\u2013\u2014-]?\s*)", "", s, flags=re.I)
    s = re.sub(r"\s*[-|\u2013\u2014]\s*$", "", s)
    return s.strip(" \u00a0.,;:!?\"'")


def split_client_context(s: str) -> tuple[str, str]:
    s = clean_candidate(s)
    if not s:
        return "", ""

    def _words_ok(seg: str) -> bool:
        return bool(seg) and seg[0].isupper() and len(seg) >= 3

    # Rule 1: "<service stuff> for <Client>"
    m = re.search(r"\bfor\s+([A-Z][\w.&'\u2019-]*(?:\s+[A-Z][\w.&'\u2019-]*){0,3})\s*$", s)
    if m:
        client = m.group(1).strip(" .;,!?")
        if _words_ok(client):
            pre = s[: m.start()].strip(" .,;:!?\u2013\u2014|-")
            context = _context_words(pre)
            return client, context

    # Rule 2: "Client - subtitle" / "Client: subtitle" / "Client | subtitle"
    parts = re.split(r"\s+[-|\u2013\u2014]\s+|\s*:\s*", s, maxsplit=1)
    if len(parts) == 2 and _words_ok(parts[0]) and _looks_like_client(parts[0]):
        return parts[0].strip(), _context_words(parts[1])

    words = s.split()
    if not words:
        return "", ""

    def _is_service(w: str) -> bool:
        nw = norm(w)
        if nw in SERVICE_TOKENS:
            return True
        if len(nw) > 3 and nw.endswith("s") and nw[:-1] in SERVICE_TOKENS:
            return True
        return False

    first_svc: int | None = None
    for i, w in enumerate(words):
        if w.isdigit():
            first_svc = i
            break
        if _is_service(w):
            first_svc = i
            break
        nw = norm(w)
        if nw in ADJECTIVE_TOKENS or nw in CONNECTORS:
            continue
        if w[0].islower():
            first_svc = i
            break
    if first_svc is None:
        client = s
        cw = client.split()
        while cw and (
            norm(cw[-1]) in ADJECTIVE_TOKENS | CONNECTORS
            or norm(cw[-1]) in SINGLE_STOP
            or norm(cw[-1]) in CONTEXT_DROP
            or cw[-1].isdigit()
        ):
            cw.pop()
        client = " ".join(cw)
        if len(client.split()) > 3:
            return "", ""
        return client, ""

    client_words = words[:first_svc]
    while client_words and (
        norm(client_words[-1]) in ADJECTIVE_TOKENS | CONNECTORS
        or norm(client_words[-1]) in SINGLE_STOP
        or norm(client_words[-1]) in CONTEXT_DROP
        or client_words[-1].isdigit()
    ):
        client_words.pop()
    for i, w in enumerate(client_words):
        if norm(w) in CONNECTORS:
            client_words = client_words[:i]
            break
    if not client_words:
        return "", ""
    client = " ".join(client_words)
    context = " ".join(words[first_svc:])
    return client, _context_words(context)


def _context_words(seg: str) -> str:
    words = re.split(r"[^a-z0-9'\u2019&.]+", html_mod.unescape(seg), flags=re.I)
    kept = [
        w for w in words
        if len(w) >= 3
        and re.search(r"[a-z]", w, re.I)
        and norm(w) not in CONTEXT_DROP
        and norm(w) not in CONNECTORS
    ]
    return " ".join(kept[:3])


def _looks_like_client(s: str) -> bool:
    if not s or not s[0].isupper():
        return False
    words = s.split()
    if len(words) > 4:
        return False
    return any(len(w) >= 3 for w in words)


COMMON_NAMES = {
    "will", "john", "david", "michael", "james", "robert", "william",
    "richard", "thomas", "daniel", "matthew", "charles", "mark", "paul",
    "steven", "andrew", "joshua", "kevin", "brian", "jason", "jeffrey",
    "scott", "eric", "stephen", "ryan", "gary", "george", "peter",
    "anthony", "kenneth", "frank", "edward", "donald", "ronald",
    "timothy", "jennifer", "mary", "patricia", "linda", "elizabeth",
    "barbara", "susan", "jessica", "sarah", "karen", "nancy", "lisa",
    "margaret", "betty", "sandra", "ashley", "kimberly", "emily",
    "donna", "michelle", "carol", "amanda", "melissa", "deborah",
    "stephanie", "rebecca", "sharon", "laura", "cynthia", "kathleen",
    "amy", "angela", "shirley", "anna", "brenda", "pamela", "emma",
    "nicole", "helen", "samantha", "katherine", "christine", "debra",
    "rachel", "carolyn", "janet", "maria", "catherine", "diane",
    "olivia", "julie", "heather", "teresa", "hannah", "sara", "joyce",
    "craig", "bruce", "justin", "brandon", "tyler", "aaron", "patrick",
    "sean", "jerry", "dennis", "walter", "alex", "adam", "henry",
    "chris", "mike", "dan", "tom", "jim", "joe", "sam", "bob", "bill",
    "steve", "dave", "nick", "phil", "jake", "ben", "andy", "joel",
    "luke", "kyle", "cory", "corey", "darren", "derek", "doug", "ed",
    "eddie", "fred", "gene", "greg", "gus", "ian", "jack", "jamie",
    "jared", "jay", "jeff", "jeremy", "jesse", "jon", "jonathan",
    "jordan", "jose", "juan", "julian", "keith", "ken", "kent", "kerry",
    "kurt", "lee", "leo", "leslie", "lewis", "liam", "loren", "louis",
    "lyle", "marcus", "martin", "max", "miles", "morgan", "nathan",
    "neil", "noah", "norman", "owen", "philip", "pierre", "quentin",
    "raymond", "reed", "reginald", "rene", "ricardo", "rich", "rick",
    "ricky", "rob", "roger", "ron", "roy", "russell", "seth", "shane",
    "shaun", "shawn", "simon", "stan", "stuart", "syd", "taylor", "ted",
    "terry", "theo", "tony", "travis", "trevor", "tyrone", "vance",
    "victor", "vincent", "wade", "warren", "wayne", "wesley", "walt",
    "xavier", "zach", "zack", "zane", "austin", "benjamin", "blake",
    "brad", "bradley", "brendan", "brent", "brett", "bryce", "byron",
    "cameron", "carlos", "cecil", "cesar", "chad", "chester", "claude",
    "clint", "clyde", "colin", "connor", "curtis", "cyril", "damian",
    "dana", "danny", "darrell", "daryl", "dean", "delbert", "derrick",
    "dewayne", "dillon", "dominic", "don", "duane", "dwayne", "dylan",
    "earl", "edgar", "edwin", "elijah", "ellis", "emmanuel", "ernest",
    "ethan", "eugene", "evan", "felix", "floyd", "francis", "francisco",
    "gabriel", "gavin", "geoffrey", "gerald", "gerard", "gilbert",
    "glenn", "gordon", "graham", "grant", "gregory", "guy", "harold",
    "harry", "harvey", "hector", "herbert", "howard", "hugh", "isaac",
    "isaiah", "ivan", "jackson", "jacob", "jasper", "jed", "jeremiah",
    "jerome", "jill", "jimmy", "joan", "joann", "joey", "johnny",
    "jorge", "joseph", "josh", "julius", "karl", "kelly", "kenny",
    "kirk", "lance", "larry", "lawrence", "leon", "leonard", "les",
    "lincoln", "lloyd", "logan", "lonnie", "lucas", "malcolm", "manuel",
    "marc", "mario", "marion", "marlon", "marshall", "marvin", "mason",
    "mathew", "maurice", "maxwell", "melvin", "micah", "micheal",
    "miguel", "milton", "mitchell", "morris", "nathaniel", "neal",
    "ned", "nelson", "nicholas", "nigel", "oliver", "omar", "orlando",
    "oscar", "pablo", "parker", "pedro", "perry", "pete", "phillip",
    "rafael", "ralph", "ramon", "randall", "randolph", "raul", "reid",
    "robbie", "robert", "robin", "rocco", "rod", "rodney", "roland",
    "ronnie", "ross", "rudy", "salvatore", "samuel", "santiago",
    "shannon", "sidney", "solomon", "spencer", "stanley", "stewart",
    "sylvester", "terence", "terrance", "terrell", "terrence",
    "theodore", "tobias", "todd", "tommy", "tristan", "troy", "virgil",
    "wilbert", "wilbur", "wilfred", "willie", "wilson", "zachary",
    "anne", "einir", "gareth", "owen", "rhys", "sian", "sophie",
    "georgina", "amelia", "isabella", "sofia", "ella", "grace", "chloe",
    "mia", "charlotte", "ruby", "evie", "daisy", "freya", "florence",
    "rose", "scarlett", "harriet", "eleanor", "matilda", "alice",
    "poppy", "ellie", "isabelle", "jasmine", "maya", "hollie", "amber",
    "caitlin", "lauren", "abigail", "imogen", "gemma", "nicola",
    "kirsty", "fiona", "yvonne",
    "casey", "lori", "dustin", "raza", "valerie", "denise", "marie",
    "jacqueline", "dorothy", "judith", "ruth", "janice", "kathryn",
    "evelyn", "joanne", "judy", "paula", "cheryl", "wanda", "debra",
    "wendy", "carrie", "nina", "allison", "megan", "diana", "tiffany",
    "sonia", "deanna", "marlene", "vicki", "roxanne", "priscilla",
    "sherry", "marta", "tara", "penny", "gwen", "lucy", "violet",
    "frances", "heidi", "june", "louise", "rosemary", "angie",
    "bonnie", "ginny", "holly", "irene", "kate", "keri", "lena",
    "lindsey", "lucille", "molly", "peggy", "phyllis",
    "rita", "roberta", "ronda", "ruthie", "sheila", "stacey",
    "stella", "suzanne", "terri", "tina", "velma", "yvette",
    "alan", "albert", "allen", "alvin", "amos", "angus", "archie",
    "armand", "arnold", "art", "arthur", "barry", "bart", "bert",
    "blair", "boyd", "bradford", "brady", "brett", "brock", "brooks",
    "buddy", "burton", "calvin", "carl", "carlton", "carroll",
    "carter", "cary", "cassius", "cedric", "christian", "christopher",
    "clark", "clay", "clement", "cliff", "clifford", "clifton",
    "cole", "collin", "colton", "conrad", "cornelius", "cornell",
    "cortez", "curt", "dale", "dalton", "damon", "dante", "darcy",
    "darian", "darrell", "darwin", "daryl", "davey", "davis",
    "dawson", "dayton", "deandre", "delmar", "delroy", "denny",
    "deon", "derek", "deron", "devin", "devon", "dexter", "diego",
    "dirk", "domingo", "dorian", "douglas", "doyle", "duke",
    "duncan", "dwight", "earnest", "ebenezer", "edmund", "edwardo",
    "elbert", "eldon", "elgin", "eli", "elias", "eliseo", "elmer",
    "elton", "elvis", "emerson", "emery", "emil", "emmitt", "ephraim",
    "erasmo", "esteban", "everett", "ezra", "fabian", "felipe",
    "felton", "fernando", "fidel", "fletcher", "florian", "forrest",
    "foster", "franklin", "freddie", "freddy", "frederic", "fritz",
    "gabe", "garrett", "garry", "garth", "gaston", "geraldo",
    "gerardo", "germaine", "gil", "gilberto", "gino", "giovanni",
    "glen", "gonzalo", "grady", "grayson", "gretchen", "grover",
    "guadalupe", "guillermo", "gus", "gustavo", "hans", "harlan",
    "harley", "harmon", "harrison", "hayden", "haywood", "heath",
    "herman", "herschel", "hilario", "hilbert", "hilton", "hiram",
    "hollis", "homer", "horace", "horton", "huey", "hugo", "humphrey",
    "hunter", "hyman", "irvin", "irving", "irwin", "jackie", "jacques",
    "jamel", "jameson", "jamil", "jared", "jarod", "jarrett", "jarvis",
    "javier", "jayden", "jedidiah", "jerold", "jerrold", "jess",
    "jessie", "jesus", "jewel", "jimmy", "jocelyn", "joesph", "johan",
    "johann", "jonah", "jonas", "jordon", "josef", "joshua", "jude",
    "judson", "jules", "julio", "junior", "justice", "justyn",
    "kareem", "karlton", "kasey", "keaton", "keegan", "kendall",
    "kendrick", "kenton", "keon", "kerry", "kermit", "kermit",
    "kevin", "kieth", "kim", "king", "kip", "kirby", "knute", "kory",
    "kristopher", "kurtis", "lamar", "lamont", "larry", "lawson",
    "lazaro", "leandro", "lee", "leif", "lemuel", "len", "lenard",
    "lennie", "lennon", "leopold", "leroy", "lesley", "lester",
    "levi", "lin", "linwood", "lionel", "lloyd", "lorenzo", "lou",
    "lowell", "loyd", "luis", "luther", "lyle", "lyndon", "lynn",
    "lynwood", "mack", "madalyn", "malik", "malcom", "mandy", "manny",
    "marcello", "marcelo", "margarito", "mario", "marion", "markus",
    "marlin", "marty", "marvin", "mason", "mateo", "mathias", "matt",
    "mauricio", "maxwell", "mckinley", "mel", "melvin", "mentor",
    "merle", "mervin", "michel", "mickey", "miguel", "mikeal", "mikel",
    "milan", "miles", "millard", "milo", "milton", "mitch", "mitchel",
    "moe", "mohamed", "mohammad", "mohammed", "moises", "monroe",
    "monty", "morris", "mortimer", "moshe", "moses", "murray", "myron",
    "nathaniel", "neil", "nelson", "nestor", "newton", "nicholas",
    "nicky", "niles", "noble", "noel", "nolan", "norbert", "norman",
    "norris", "odell", "ole", "oliver", "ollie", "omar", "orval",
    "orville", "osborne", "osvaldo", "otis", "otto", "owen", "pablo",
    "page", "palmer", "paris", "parker", "pasquale", "pat", "patrice",
    "patricia", "patrik", "patty", "paulie", "pedro", "peyton", "phil",
    "phillip", "pierce", "pierre", "pinkie", "pino", "plato", "porter",
    "prentice", "presley", "price", "prince", "quinn", "quintin",
    "quinton", "rafael", "raleigh", "ralph", "ramiro", "ramos", "randal",
    "randall", "randolph", "randy", "raphael", "rashad", "raul", "ray",
    "rayford", "reggie", "reid", "reinaldo", "remington", "rene",
    "reuben", "rex", "reynaldo", "rhett", "ricardo", "richard", "richie",
    "rickey", "rickie", "rico", "riley", "rob", "robbie", "roberto",
    "rocky", "roddy", "roderick", "rodger", "rodney", "rodolfo",
    "rodrick", "roland", "rolando", "rolf", "rolland", "romero", "ron",
    "ronald", "ronny", "roosevelt", "ross", "rowan", "royce", "ruben",
    "rudolph", "rufus", "rupert", "russ", "rusty", "ryan", "sal",
    "salvador", "sammy", "sanford", "santos", "saul", "scot", "scottie",
    "scotty", "seamus", "sebastian", "seldon", "sergio", "seymour",
    "shad", "sheldon", "sherman", "shirley", "sid", "silas", "silvio",
    "skip", "solomon", "sonny", "stanford", "stanley", "stefan",
    "stephon", "sterling", "steve", "stewart", "stoney", "stuart",
    "sung", "sydney", "sylvester", "talmadge", "tanner", "terrell",
    "terrence", "thad", "thaddeus", "theo", "theodore", "theron",
    "thomas", "thornton", "thurman", "tim", "timmy", "titus", "tobias",
    "todd", "tomas", "tommy", "toney", "tony", "tory", "tracy", "travis",
    "trey", "tristin", "troy", "tucker", "ty", "tyce", "tyler", "tyrell",
    "tyrone", "tyson", "ulysses", "van", "vance", "vaughn", "vern",
    "vernon", "vince", "vincent", "virgil", "vito", "von", "wade",
    "walker", "wallace", "wally", "walter", "walt", "ward", "warner",
    "warren", "waylon", "wayne", "welton", "wendell", "wes", "weston",
    "whitney", "wilber", "wilburn", "wiley", "wilford", "wilfredo",
    "willard", "william", "willis", "willy", "wilmer", "wilson",
    "wilton", "winford", "winston", "woodrow", "wyatt", "xavier",
    "yosef", "zachery", "zane", "zeb", "zion",
}
SINGLE_STOP |= COMMON_NAMES

PARTNER_RE = re.compile(
    r"(?i)([A-Z][\w&.'\u2019-]*(?:\s+[A-Z][\w&.'\u2019-]*){0,2})\s+"
    r"(?:partnered|partnering|collaborated|teamed)\s+with"
)
WORK_FOR_RE = re.compile(
    r"(?i)\b(?:box|boxes|bags|packaging|presentation|campaign|project|"
    r"work|promo|promos|items|products|materials|bottle|bottles|can|cans|"
    r"merch|merchandise|totes|swag)\s+(?:for|with)\s+"
    r"([A-Z][\w&.'\u2019-]*(?:\s+[A-Z][\w&.'\u2019-]*){0,2})"
)
CARD_CLASS_RE = re.compile(
    r"(?i)(^|[\s_-])(case|project|client|work|portfolio|brand|title)([\s_-]|$)"
)


GENERIC_PHRASES_NORMED = {norm(p) for p in GENERIC_PHRASES}


def valid_client(client: str, tokens: set[str]) -> bool:
    client = client.strip()
    if not client or not any(c.isalpha() for c in client):
        return False
    words = client.split()
    if not 1 <= len(words) <= 4:
        return False
    if len(words) == 2 and norm(words[0]) in COMMON_NAMES:
        return False
    if len(words) == 1:
        w = norm(words[0])
        if w in SINGLE_STOP or len(w) < 3:
            return False
    if norm(client) in GENERIC_PHRASES_NORMED:
        return False
    if not client[0].isupper():
        return False
    if any(norm(w) in MONTHS for w in words):
        return False
    for w in words:
        nw = norm(w)
        if nw in tokens:
            return False
        if len(nw) >= 3:
            for tok in tokens:
                if len(tok) >= 3 and (nw in tok or tok in nw):
                    return False
    if all(norm(w) in SINGLE_STOP or norm(w) in CONTEXT_DROP for w in words):
        return False
    return True


def page_score(path: str) -> int:
    p = (path or "").lower()
    if re.search(r"case", p):
        return 100
    if re.search(r"portfolio", p):
        return 96
    if re.search(r"work", p):
        return 95
    if re.search(r"project", p):
        return 92
    if re.search(r"client", p):
        return 90
    if re.search(r"result", p):
        return 88
    if re.search(r"success|impact", p):
        return 86
    if re.search(r"showcase|featured", p):
        return 84
    if re.search(r"testimonial|reference", p):
        return 80
    if re.search(r"gallery", p):
        return 75
    return 40


def last_year(*texts: str) -> int:
    best = 0
    for t in texts:
        for m in YEAR_RE.finditer(t):
            y = 2000 + int(m.group(1))
            if 2020 <= y <= 2035:
                best = max(best, y)
    return best


class TL(threading.local):
    def __init__(self) -> None:
        self.client: httpx.Client | None = None


_tl = TL()


def get_http() -> httpx.Client:
    if _tl.client is None:
        _tl.client = httpx.Client(
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            follow_redirects=True,
            timeout=TIMEOUT,
        )
    return _tl.client


def fetch_page(url: str) -> dict | None:
    for ua in USER_AGENTS:
        try:
            r = get_http().get(url, headers={"User-Agent": ua})
            if r.status_code == 200:
                ct = (r.headers.get("content-type") or "").lower()
                if "html" in ct or "xml" in ct or not ct:
                    return {"url": str(r.url), "content": r.content[:2_000_000]}
                return None
            if r.status_code in (403, 406, 429):
                continue
            return None
        except httpx.HTTPError:
            return None
    return None


def resolve_base(domain: str) -> str | None:
    candidates = [f"https://www.{domain}", f"https://{domain}", f"http://www.{domain}", f"http://{domain}"]
    for cand in candidates:
        page = fetch_page(cand)
        if page:
            return str(page["url"])
    return None


def parse_html(content: bytes):
    try:
        return lh.fromstring(content)
    except Exception:
        return None


def homepage_nav_paths(tree) -> list[str]:
    paths: list[str] = []
    try:
        for a in tree.xpath("//a[@href]"):
            href = (a.get("href") or "").strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript")):
                continue
            url = urljoin("http://x", href)
            path = urlparse(url).path.rstrip("/")
            if not path or len(path) > 60:
                continue
            if NAV_KEYWORDS.search(path) and not NAV_EXCLUDE.search(path):
                if path not in paths:
                    paths.append(path)
    except Exception:
        pass
    paths.sort(key=lambda p: (p.count("/") > 1, p))
    return paths[:10]


def sitemap_urls(base: str) -> list[tuple[str, int]]:
    base_url = urlparse(base)
    origin = f"{base_url.scheme}://{base_url.netloc}"
    found: list[tuple[str, int]] = []
    for sm in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
        page = fetch_page(origin + sm)
        if not page:
            continue
        try:
            root = lh.fromstring(page["content"])
        except Exception:
            continue
        locs = root.xpath("//*[local-name()='loc']/text()")
        dates = {
            u: d
            for u, d in zip(
                locs,
                root.xpath("//*[local-name()='lastmod']/text()") + [""] * len(locs),
            )
        }
        if not locs:
            continue
        sub_indexes = [u for u in locs if u.lower().endswith((".xml", ".xml.gz"))]
        if sub_indexes and len(sub_indexes) >= len(locs) * 0.6:
            for sub in sub_indexes[:1]:
                sub_page = fetch_page(sub)
                if not sub_page:
                    continue
                try:
                    sub_root = lh.fromstring(sub_page["content"])
                except Exception:
                    continue
                sub_locs = sub_root.xpath("//*[local-name()='loc']/text()")
                sub_dates = {
                    u: d
                    for u, d in zip(
                        sub_locs,
                        sub_root.xpath("//*[local-name()='lastmod']/text()") + [""] * len(sub_locs),
                    )
                }
                for u in sub_locs:
                    if SITEMAP_KEYWORDS.search(u) and not SITEMAP_EXCLUDE.search(u):
                        y = last_year(sub_dates.get(u, ""))
                        found.append((u, y))
        else:
            for u in locs:
                if SITEMAP_KEYWORDS.search(u) and not SITEMAP_EXCLUDE.search(u):
                    found.append((u, last_year(dates.get(u, ""))))
        if found:
            break
    found.sort(key=lambda t: -t[1])
    return found[:6]


def extract_candidates(page: dict, is_home: bool) -> list[dict]:
    tree = parse_html(page["content"])
    if tree is None:
        return []
    path = urlparse(page["url"]).path or "/"
    score = page_score(path)
    cands: list[dict] = []

    def _fname_name(src_or_alt: str) -> str | None:
        fname = src_or_alt.rstrip("/").split("/")[-1]
        fname = re.sub(r"\.(png|jpe?g|svg|webp|gif)$", "", fname, flags=re.I)
        tokens = [re.sub(r"\d+$", "", t) for t in re.split(r"[-_.]+", fname)]
        tokens = [t for t in tokens if t and re.search(r"[a-z]", t, re.I)]
        tokens = [t for t in tokens if norm(t) not in FILENAME_GENERIC]
        if len(tokens) >= 1 and all(len(t) >= 3 for t in tokens[:2]):
            return " ".join(t.upper() if len(t) <= 4 else t.capitalize() for t in tokens[:2])
        return None

    for img in tree.xpath("//img[@alt]"):
        a = (img.get("alt") or "").strip()
        a = re.sub(r"\s*[\w-]*\.(jpe?g|jpeg|png|svg|webp|gif)\s*$", "", a, flags=re.I)
        src = img.get("src") or ""
        if len(a) >= 3:
            if re.fullmatch(r"[a-zA-Z0-9_\-]+", a):
                name = _fname_name(a)
                if name:
                    cands.append({"raw": name, "type": "fname", "path": path, "score": score - 10})
            else:
                cands.append({"raw": a, "type": "alt", "path": path, "score": score})
        elif re.match(r"^[a-z0-9_\-./]+\.(png|jpe?g|svg|webp|gif)$", src, re.I):
            name = _fname_name(src)
            if name:
                cands.append({"raw": name, "type": "fname", "path": path, "score": score - 10})

    for h in tree.xpath("//h1|//h2|//h3|//h4"):
        t = " ".join(h.text_content().split())
        if 2 <= len(t) <= 90:
            cands.append({"raw": t, "type": "heading", "path": path, "score": score})

    titles = tree.xpath("//title/text()")
    if titles:
        t = " ".join(titles[0].split())
        m = CASE_TITLE_RE.search(t)
        if m:
            cands.append({"raw": m.group(1), "type": "title", "path": path, "score": score})
        else:
            first = re.split(r"\s*[|\u2013\u2014-]\s*", t, maxsplit=1)[0].strip()
            if 2 <= len(first) <= 50 and len(first.split()) <= 4:
                cands.append({"raw": first, "type": "title", "path": path, "score": score})
            else:
                cands.append({"raw": t, "type": "title", "path": path, "score": score - 20})

    body = tree.text_content()
    for tag in tree.xpath("//script|//style|//noscript|//head"):
        tag.drop_tree()
    body = tree.text_content()
    if len(body) > 300_000:
        body = body[:300_000]
    for m in CLIENTS_RE.finditer(body):
        seg = m.group(1)
        for part in re.split(r"[|\u00b7\n]+|,\s*", seg):
            part = part.strip(" .,;:!?\u2013\u2014")
            if 2 <= len(part) <= 60:
                cands.append({"raw": part, "type": "line", "path": path, "score": score - 10})
    for m in PARTNER_RE.finditer(body):
        subj = m.group(1)
        if 2 <= len(subj) <= 40:
            cands.append({"raw": subj, "type": "partner", "path": path, "score": score - 5})
    for m in WORK_FOR_RE.finditer(body):
        cl = m.group(1)
        if 2 <= len(cl) <= 40:
            cands.append({"raw": cl, "type": "partner", "path": path, "score": score - 5})

    for el in tree.xpath(
        "//*[self::div or self::li or self::span or self::a or self::p][@class or @id]"
    ):
        cls = f"{el.get('class') or ''} {el.get('id') or ''}"
        if not CARD_CLASS_RE.search(cls):
            continue
        if any(el.xpath(".//h1|.//h2|.//h3|.//h4|.//img[@alt]")):
            continue
        t = " ".join(el.text_content().split())
        if 2 <= len(t) <= 45 and not re.search(r"http", t):
            cands.append({"raw": t, "type": "card", "path": path, "score": score - 8})

    if is_home:
        for c in cands:
            c["score"] -= 25
    return cands


def collect_pages(base: str) -> list[dict]:
    base_url = urlparse(base)
    origin = f"{base_url.scheme}://{base_url.netloc}"
    pages: list[dict] = []

    home = fetch_page(origin + "/")
    if not home:
        return pages
    home_tree = parse_html(home["content"])
    body_text = home_tree.text_content() if home_tree is not None else ""
    if home_tree is None or len(body_text.strip()) < 80 or (
        len(body_text) < 5000
        and re.search(
            r"(just a moment|checking your browser|attention required|access denied|"
            r"verify you are human|are you a human|ddos protection|"
            r"enable javascript and cookies|cf-chl|"
            r"not available in your (region|country))",
            body_text, re.I
        )
    ):
        return pages
    pages.append({**home, "path": "/", "home": True})

    nav = homepage_nav_paths(home_tree) if home_tree is not None else []
    sm = sitemap_urls(origin)

    visited = {"/"}
    targets: list[tuple[str, int]] = []

    def _add(p: str, score: int) -> None:
        p = p.rstrip("/") or "/"
        if p in visited or len(p) > 80:
            return
        visited.add(p)
        targets.append((p, score))

    for path in nav[:6]:
        _add(path, 100)
    for u, y in sm[:3]:
        _add(urlparse(u).path, 90 + min(20, y - 2021) if y else 90)
    for path in PRIORITY_PATHS:
        _add(path, page_score(path))

    targets.sort(key=lambda t: -t[1])
    for path, _ in targets[: PAGE_BUDGET - 1]:
        page = fetch_page(origin + path)
        if page:
            pages.append({**page, "path": path, "home": False})
    return pages


PHOTO_WORDS = {
    "person", "people", "woman", "man", "men", "child", "children", "kid",
    "kids", "hiking", "mountain", "mountains", "lake", "bread", "loaf",
    "hand", "hands", "crowd", "glass", "skin", "back", "front", "view",
    "sitting", "standing", "walking", "holding", "wearing", "smiling",
    "filled", "showing", "show", "shows", "missing", "package", "packages",
    "tzatziki", "milkshake", "potatoes", "potato", "balls", "tumbling",
    "reflecting", "reflection", "background", "foreground", "bag", "bottle",
    "bowl", "plate", "food", "dog", "cat", "car", "truck", "building",
    "street", "city", "sky", "tree", "forest", "water", "snow", "landscape",
    "portrait", "headshot", "happy", "yellow", "black", "white", "blue",
    "red", "green", "fresh", "grey", "gray", "brown", "pink", "purple",
    "orange", "color", "colour", "scene", "scenery", "clothes", "clothing",
    "shirt", "jacket", "pants", "shoes", "hair", "face", "head", "eyes",
    "smile", "wave", "flag", "hands", "with", "into", "next", "scroll",
    "loading", "previous", "section", "above", "below", "meet", "our",
    "images", "posts", "showcasing", "showing", "floating", "swimming",
    "running", "dancing", "loves", "love", "together", "gethers", "sink",
    "tap", "kitchen", "rockets", "fetchable", "purple", "happy", "baby",
    "collage", "billboard", "three", "covid", "corona", "sky", "door",
    "window", "wall", "room", "floor", "ceiling", "couch", "chair",
    "table", "desk", "bed", "bag", "shoes", "dress", "suit", "tie",
    "hat", "cap", "glasses", "camera", "phone", "laptop", "computer",
    "screen", "monitor", "keyboard", "mouse", "remote", "clock", "watch",
    "cup", "coffee", "tea", "drink", "plate", "fork", "knife", "spoon",
}

PHOTO_ALT_RE = re.compile(r"(video still|still from|photo of|image of|picture of|stock photo)", re.I)


def _photo_garbage(text: str) -> bool:
    words = [re.sub(r"s$", "", norm(w)) for w in re.split(r"[^a-z0-9']+", (text or "").lower())]
    return any(w in PHOTO_WORDS for w in words if w)


def pick_best(candidates: list[dict], tokens: set[str]) -> dict | None:
    seen: dict[str, dict] = {}
    for c in candidates:
        if PHOTO_ALT_RE.search(c["raw"]):
            continue
        client, context = split_client_context(c["raw"])
        if not valid_client(client, tokens):
            continue
        if _photo_garbage(f"{client} {context} {c['raw']}"):
            continue
        if context and (client.lower() + " ") in context.lower():
            context = ""
        elif context.lower() in client.lower():
            context = ""
        s = c["score"]
        y = last_year(c["raw"], client, context)
        if y:
            s += min(30, max(0, (y - 2021) * 4))
        if c["type"] == "alt":
            s += 2
        elif c["type"] == "title":
            s += 3
        elif c["type"] == "heading":
            s += 1
        key = norm(client)
        best = seen.get(key)
        if best is None or s > best["score"]:
            seen[key] = {
                "client": client,
                "context": " ".join(context.lower().split()),
                "score": s,
                "url": c.get("url", ""),
                "path": c.get("path", ""),
                "type": c["type"],
                "raw": c["raw"],
            }
    if not seen:
        return None
    return max(seen.values(), key=_score_key)


def _score_key(v: dict):
    p = v.get("path", "") or ""
    return (
        v["score"],
        1 if re.search(r"(case|work|portfolio|project|client|result|success|impact)", p, re.I) else 0,
        -len(p),
    )

def process_domain(company: str, domain: str, description: str = "") -> dict:
    result = {
        "company": company,
        "domain": domain,
        "found": False,
        "client": "",
        "context": "",
        "source_url": "",
        "ok_paths": [],
    }
    base = resolve_base(domain)
    if not base:
        return result
    result["ok_paths"] = ["/"]
    pages = collect_pages(base)
    if not pages:
        return result

    tokens = agency_tokens(company, domain)
    for word in re.split(r"[^a-z0-9]+", urlparse(base).hostname or ""):
        if len(word) >= 3:
            tokens.add(word)

    all_cands: list[dict] = []
    for page in pages:
        path = page.get("path", urlparse(page["url"]).path)
        if path not in result["ok_paths"]:
            result["ok_paths"].append(path)
        cands = extract_candidates(page, page.get("home", False))
        for c in cands:
            c["url"] = page["url"]
        all_cands.extend(cands)

    if description:
        for m in CLIENTS_RE.finditer(description):
            for part in re.split(r"[|\u00b7\n]+|,\s*", m.group(1)):
                part = part.strip(" .,;:!?\u2013\u2014")
                if 2 <= len(part) <= 60:
                    all_cands.append({
                        "raw": part, "type": "line", "path": "(csv description)",
                        "score": 50, "url": "company description",
                    })

    best = pick_best(all_cands, tokens)
    if best:
        result["found"] = True
        result["client"] = best["client"]
        result["context"] = best["context"]
        result["source_url"] = best["url"]
    return result


def icebreaker(client: str, context: str) -> str:
    full = client if not context else f"{client} {context}"
    if not full:
        full = "your last client"
    return f"Been checking out your portfolio, crazy results for {full}. Congrats!"


def load_company_domains() -> list[dict]:
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    seen: dict[str, dict] = {}
    for r in rows:
        d = (r.get("companyDomain") or "").strip().lower()
        if not d:
            continue
        seen.setdefault(d, {
            "company": r.get("companyName") or "",
            "description": r.get("companyDescription") or "",
        })
    return [{"company": v["company"], "domain": d, "description": v["description"]} for d, v in seen.items()]


def main() -> None:
    global CSV_FILE, RESULTS_FILE, OUT_CSV, REPORT_FILE
    argv = sys.argv[1:]
    limit = None
    fresh = False
    only_domain = None
    csv_arg = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 1
        elif a == "--domain" and i + 1 < len(argv):
            only_domain = argv[i + 1].lower()
            i += 1
        elif a == "--csv" and i + 1 < len(argv):
            csv_arg = Path(argv[i + 1])
            i += 1
        elif a == "--fresh":
            fresh = True
        i += 1

    if csv_arg:
        CSV_FILE = csv_arg
        stem = csv_arg.stem
        RESULTS_FILE = OUT_DIR / f"{stem}_results.json"
        OUT_CSV = OUT_DIR / f"{stem}_leads_with_clients.csv"
        REPORT_FILE = OUT_DIR / f"{stem}_endpoints_found.md"
    else:
        CSV_FILE = _default_csv()
        stem = CSV_FILE.stem
        RESULTS_FILE = OUT_DIR / f"{stem}_results.json"
        OUT_CSV = OUT_DIR / f"{stem}_leads_with_clients.csv"
        REPORT_FILE = OUT_DIR / f"{stem}_endpoints_found.md"

    OUT_DIR.mkdir(exist_ok=True)
    results: dict[str, dict] = {}
    if not fresh and RESULTS_FILE.exists():
        results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    targets = load_company_domains()
    if only_domain:
        targets = [t for t in targets if t["domain"] == only_domain]
    if limit:
        targets = targets[:limit]

    remaining = [t for t in targets if t["domain"] not in results]
    if not remaining:
        print(f"All {len(targets)} domains already processed (--fresh to redo).")
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process_domain, t["company"], t["domain"], t.get("description", "")): t for t in remaining}
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # pragma: no cover
                    res = {"company": t["company"], "domain": t["domain"], "found": False,
                           "client": "", "context": "", "source_url": "", "ok_paths": []}
                    print(f"ERROR {t['domain']}: {exc}", file=sys.stderr)
                results[t["domain"]] = res
                done += 1
                status = f"{res['client']} {res['context']}".strip() if res["found"] else "NO CLIENT"
                print(f"[{done}/{len(remaining)}] {t['domain']:<30} -> {status}")
                RESULTS_FILE.write_text(json.dumps(results, indent=1), encoding="utf-8")
                time.sleep(0.05)

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    out_fields = fieldnames + ["recentClient", "context", "sourceUrl", "icebreaker"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for r in rows:
            d = (r.get("companyDomain") or "").strip().lower()
            res = results.get(d, {})
            client = res.get("client", "")
            context = res.get("context", "")
            out = dict(r)
            out["recentClient"] = client if client else "your last client"
            out["context"] = context
            out["sourceUrl"] = res.get("source_url", "")
            out["icebreaker"] = icebreaker(client, context)
            writer.writerow(out)

    _write_report(results)
    found = sum(1 for r in results.values() if r.get("found"))
    print(f"\nDone: {len(targets)} domains, client found on {found}, "
          f"fallback on {len(targets) - found}.")
    print(f"Output: {OUT_CSV}")
    print(f"Report: {REPORT_FILE}")


def _write_report(results: dict[str, dict]) -> None:
    path_counts: dict[str, int] = {}
    client_path_counts: dict[str, int] = {}
    reachable = 0
    for res in results.values():
        if not res.get("ok_paths"):
            continue
        reachable += 1
        for p in res["ok_paths"]:
            path_counts[p] = path_counts.get(p, 0) + 1
            if res.get("found") and res.get("source_url", "").endswith(p):
                client_path_counts[p] = client_path_counts.get(p, 0) + 1

    lines = [
        "# Where do these sites showcase their case studies / clients?",
        "",
        f"_{len(results)} leads scanned, {reachable} sites reachable._",
        "",
        "## Most used endpoints",
        "",
        "| Path | Sites (200 OK) | Sites with client info |",
        "|---|---|---|",
    ]
    for p, n in sorted(path_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {p} | {n} | {client_path_counts.get(p, 0)} |")
    lines += ["", "## Per site", "", "| Company | Domain | Client | Source |", "|---|---|---|---|"]
    for res in sorted(results.values(), key=lambda r: r["domain"]):
        if res.get("found"):
            client = f"{res['client']} {res['context']}".strip()
            src = res.get("source_url", "")
        else:
            client = "- (fallback: your last client)"
            src = "unreachable / no client found"
        lines.append(f"| {res.get('company', '')} | {res['domain']} | {client} | {src} |")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()