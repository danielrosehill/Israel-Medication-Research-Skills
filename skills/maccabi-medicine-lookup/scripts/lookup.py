#!/usr/bin/env python3
"""
Maccabi medicine lookup — search Maccabi Healthcare Services' medicine
catalogue and fetch per-drug pricing/coverage.

Usage:
    lookup.py search "lissin"
    lookup.py search "vyvanse 70"
    lookup.py fetch 37695
    lookup.py fetch "https://www.maccabi4u.co.il/healthguide/medicines/תרופות/37695/"
    lookup.py refresh-index   # force re-download of the catalogue blob

Output: JSON on stdout.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE = "https://www.maccabi4u.co.il"
INDEX_URL = f"{BASE}/healthguide/medicines/"
DRUG_URL_FMT = f"{BASE}/healthguide/medicines/{quote('תרופות')}/{{drug_id}}/"
UA = "Mozilla/5.0 (X11; Linux x86_64) Israel-Medication-Research-Skills/maccabi-medicine-lookup"
TIMEOUT = 30
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "maccabi-medicine-lookup"
INDEX_CACHE = CACHE_DIR / "index.json"
INDEX_TTL_SECONDS = 7 * 24 * 3600  # weekly refresh


def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


# ---------- index (full catalogue, embedded in the medicines homepage) ----------

@dataclass
class IndexEntry:
    id: int
    name: str       # English brand + dose + pack size, e.g. "LISSIN 70MG 30TABS"
    url: str        # absolute URL to drug page


def _fetch_index() -> list[IndexEntry]:
    page = _get(INDEX_URL)
    m = re.search(r'<input id="hiddenForSearch"[^>]*value="([^"]+)"', page)
    if not m:
        raise RuntimeError("could not find hiddenForSearch payload on medicines homepage")
    raw = html.unescape(m.group(1))
    items = json.loads(raw)
    out: list[IndexEntry] = []
    for it in items:
        url_path = it.get("url") or ""
        id_m = re.search(r"/(\d+)/?$", url_path)
        if not id_m:
            continue
        out.append(
            IndexEntry(
                id=int(id_m.group(1)),
                name=(it.get("lable") or it.get("value") or "").strip(),
                url=BASE + url_path,
            )
        )
    return out


def load_index(force_refresh: bool = False) -> list[IndexEntry]:
    if not force_refresh and INDEX_CACHE.exists():
        age = time.time() - INDEX_CACHE.stat().st_mtime
        if age < INDEX_TTL_SECONDS:
            with INDEX_CACHE.open(encoding="utf-8") as f:
                return [IndexEntry(**d) for d in json.load(f)]
    entries = _fetch_index()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_CACHE.open("w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, ensure_ascii=False)
    return entries


def search(query: str, limit: int = 50) -> list[IndexEntry]:
    """Substring match against English brand name + pack size. Tokenised:
    every whitespace-separated token must appear in the entry name (any
    order, case-insensitive)."""
    tokens = [t for t in query.upper().split() if t]
    if not tokens:
        return []
    entries = load_index()
    hits = [e for e in entries if all(t in e.name.upper() for t in tokens)]
    return hits[:limit]


# ---------- fetch (single drug page) ----------

@dataclass
class TermAndApproval:
    label: str
    granted: bool | None     # True if greenV icon, False if other known negative, None unknown
    more_info_url: str | None = None
    more_info_label: str | None = None


@dataclass
class InsurancePlanCoverage:
    plan: str                # e.g. "מכבי שלי", "מכבי זהב", "סל בסיסי"
    eligibility: str | None  # e.g. "מגיל 29"
    copay_text: str | None   # raw Hebrew copay description (percent + minimum-fee notes)


@dataclass
class Drug:
    id: int | None
    url: str
    name: str | None = None
    infomed_url: str | None = None
    terms_and_approvals: list[TermAndApproval] = field(default_factory=list)
    # Convenience booleans derived from `terms_and_approvals`. Maccabi's
    # page only renders terms that are *granted*, so absence ⇒ False.
    in_health_basket: bool = False
    requires_prescription: bool = False
    requires_prior_approval: bool = False
    dosage_form: str | None = None             # צורת מתן
    where_to_purchase: str | None = None
    pharmacy_locator_url: str | None = None
    list_price_ils: float | None = None
    list_price_text: str | None = None
    insurance_coverage: list[InsurancePlanCoverage] = field(default_factory=list)
    # Maccabi shows this banner instead of the per-tier table for some drugs
    # (typically prior-approval / specialty drugs).
    insurance_coverage_note: str | None = None
    pricing_disclaimer: str | None = None
    raw_text: str | None = None


def _drug_url(id_or_url: str) -> tuple[int | None, str]:
    s = id_or_url.strip()
    if s.isdigit():
        i = int(s)
        return i, DRUG_URL_FMT.format(drug_id=i)
    m = re.search(r"/(\d+)/?$", s)
    return (int(m.group(1)) if m else None), s


def _icon_to_granted(img_src: str) -> bool | None:
    name = (img_src or "").lower()
    if "greenv" in name:
        return True
    if "redx" in name or "red_x" in name or "redcross" in name or "redicon" in name:
        return False
    return None


def fetch(id_or_url: str) -> Drug:
    drug_id, url = _drug_url(id_or_url)
    page = _get(url)
    soup = BeautifulSoup(page, "html.parser")
    drug = Drug(id=drug_id, url=url)

    h1 = soup.select_one(".header h1") or soup.select_one("h1")
    if h1:
        drug.name = h1.get_text(strip=True)

    infomed = soup.select_one("a.infomed-Link, a[href*='infomed.co.il']")
    if infomed and infomed.get("href"):
        drug.infomed_url = infomed["href"]

    # ---- terms and approvals ----
    for item in soup.select(".term-and-approval-item"):
        icon = item.select_one(".iconAndDescription img")
        label_p = item.select_one(".iconAndDescription p")
        if not label_p:
            continue
        label = label_p.get_text(" ", strip=True)
        granted = _icon_to_granted(icon.get("src", "") if icon else "")
        more = item.select_one("a.more-info")
        drug.terms_and_approvals.append(TermAndApproval(
            label=label,
            granted=granted,
            more_info_url=more["href"] if more and more.get("href") else None,
            more_info_label=more.get_text(strip=True) if more else None,
        ))

    # Convenience booleans. Maccabi only renders granted terms, so a missing
    # term means False. We additionally require granted is not False (i.e.
    # not an explicit red-X) before flipping to True.
    for t in drug.terms_and_approvals:
        if t.granted is False:
            continue
        if "בסל" in t.label:
            drug.in_health_basket = True
        elif "מרשם" in t.label:
            drug.requires_prescription = True
        elif "אישור" in t.label:
            drug.requires_prior_approval = True

    # ---- dosage form (content-box with h2 "צורת מתן") ----
    for box in soup.select(".content-box"):
        h2 = box.find("h2")
        if h2 and h2.get_text(strip=True) == "צורת מתן":
            p = box.find("p")
            if p:
                drug.dosage_form = p.get_text(" ", strip=True) or None
            break

    # ---- where to purchase ----
    for box in soup.select(".content-box"):
        h2 = box.find("h2")
        if h2 and h2.get_text(strip=True) == "היכן ניתן לרכוש?":
            p = box.find("p")
            if p:
                drug.where_to_purchase = p.get_text(" ", strip=True) or None
            a = box.select_one("a.more-info")
            if a and a.get("href"):
                drug.pharmacy_locator_url = a["href"]
            break

    # ---- cost ----
    cost_box = soup.select_one(".content-box.cost-box")
    if cost_box:
        cost_p = cost_box.select_one(".cost p")
        if cost_p:
            text = cost_p.get_text(" ", strip=True)
            drug.list_price_text = text
            m = re.search(r"([\d,]+(?:\.\d+)?)\s*ש[\"״]ח", text)
            if m:
                try:
                    drug.list_price_ils = float(m.group(1).replace(",", ""))
                except ValueError:
                    pass

        # When Maccabi omits the per-tier table, it shows a single
        # <h3 class="insurance-level-not-included"> banner instead.
        not_included = cost_box.select_one(".insurance-level-not-included")
        if not_included:
            note = re.sub(r"\s+", " ", not_included.get_text(" ", strip=True))
            drug.insurance_coverage_note = note or None

        for plan_box in cost_box.select(".insurance-level-item-box"):
            plan_name_el = plan_box.select_one("h4")
            plan_name = plan_name_el.get_text(strip=True) if plan_name_el else None
            ps = plan_box.find_all("p")
            eligibility = None
            copay = None
            for p in ps:
                t = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
                if not t:
                    continue
                if t.startswith("זכאות"):
                    # "זכאות: <span>מגיל 29</span>"
                    eligibility = t.split(":", 1)[1].strip() if ":" in t else t
                else:
                    copay = t
            drug.insurance_coverage.append(InsurancePlanCoverage(
                plan=plan_name or "",
                eligibility=eligibility,
                copay_text=copay,
            ))

        # Disclaimer paragraph (e.g. "העלות הינה משוערת ותיקבע סופית בעת הניפוק...")
        for p in cost_box.find_all("p"):
            t = p.get_text(" ", strip=True)
            if "משוערת" in t or "תיקבע סופית" in t:
                drug.pricing_disclaimer = re.sub(r"\s+", " ", t)
                break

    # ---- raw text fallback ----
    main = soup.select_one("main") or soup.select_one(".content") or soup.body or soup
    raw = re.sub(r"[ \t]+", " ", main.get_text("\n", strip=True))
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    drug.raw_text = raw

    return drug


# ---------- CLI ----------

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "search":
        if len(argv) < 3:
            print("search requires a query", file=sys.stderr)
            return 2
        hits = search(argv[2])
        json.dump([asdict(h) for h in hits], sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if cmd == "fetch":
        if len(argv) < 3:
            print("fetch requires an id or URL", file=sys.stderr)
            return 2
        drug = fetch(argv[2])
        json.dump(asdict(drug), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if cmd == "refresh-index":
        entries = load_index(force_refresh=True)
        print(f"refreshed: {len(entries)} drugs cached at {INDEX_CACHE}", file=sys.stderr)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
