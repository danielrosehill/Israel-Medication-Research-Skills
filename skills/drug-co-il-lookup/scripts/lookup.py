#!/usr/bin/env python3
"""
drug.co.il lookup — search and fetch structured drug records from the
Israeli Pharmacists Organization drug-information site.

Usage:
    lookup.py search "ליסין"
    lookup.py search "lisin"
    lookup.py fetch "https://drug.co.il/drugs/<slug>/"

Output: JSON on stdout.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://drug.co.il"
UA = "Mozilla/5.0 (Israel-Medication-Research-Skills/drug-co-il-lookup)"
TIMEOUT = 20


def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


# ---------- search ----------

@dataclass
class SearchHit:
    name: str
    url: str


def search(query: str) -> list[SearchHit]:
    if len(query.strip()) < 3:
        raise ValueError("drug.co.il requires at least 3 characters")
    html = _get(f"{BASE}/?s={quote(query)}")
    soup = BeautifulSoup(html, "html.parser")
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="/drugs/"]'):
        href = a.get("href", "")
        if "#" in href or not href.startswith(f"{BASE}/drugs/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        name = a.get_text(strip=True)
        if not name:
            continue
        hits.append(SearchHit(name=name, url=href))
    return hits


# ---------- fetch ----------

@dataclass
class Leaflet:
    language: str  # "he" | "en" | "ar" | "other"
    label: str
    url: str


@dataclass
class ActiveIngredient:
    name: str
    amount: str


@dataclass
class Drug:
    url: str
    name_he: str | None = None
    name_en: str | None = None
    manufacturer: str | None = None
    registration_holder: str | None = None
    registration_number: str | None = None
    dosage_form_he: str | None = None
    dosage_form_en: str | None = None
    usage_form_he: str | None = None
    usage_form_en: str | None = None
    active_ingredients: list[ActiveIngredient] = field(default_factory=list)
    atc_code: str | None = None
    atc_name: str | None = None
    in_health_basket: bool | None = None
    in_health_basket_raw: str | None = None
    dispensing: str | None = None  # תנאי ניפוק
    restrictions: str | None = None  # מגבלות
    consumer_prices: str | None = None
    approved_indication: str | None = None
    equivalent_drugs: list[str] = field(default_factory=list)
    leaflets: list[Leaflet] = field(default_factory=list)
    raw_text: str | None = None  # fallback for selector drift


_LANG_MAP = {"עברית": "he", "אנגלית": "en", "ערבית": "ar"}


def _collect_labeled_values(soup: BeautifulSoup) -> dict[str, list[str]]:
    """Walk every `.drugListBoxContent`. If it contains exactly one bold
    label and one or more value paragraphs, record label → values. The site
    uses this shape uniformly for non-tabular fields."""
    out: dict[str, list[str]] = {}
    for box in soup.select(".drugListBoxContent"):
        bolds = box.find_all("b")
        if len(bolds) != 1:
            continue
        label = bolds[0].get_text(strip=True)
        # Value paragraphs are the box's direct <p> children whose text
        # is not the bold label itself
        values: list[str] = []
        for p in box.find_all("p", recursive=True):
            if p.find("b"):
                continue
            t = p.get_text(" ", strip=True)
            if t:
                values.append(t)
        if values:
            out.setdefault(label, []).extend(values)
    return out


def _card_by_title(soup: BeautifulSoup, title: str) -> Tag | None:
    for td in soup.select(".drugListBoxTitle"):
        if td.get_text(strip=True) == title:
            return td.find_parent(class_="card")
    return None


def fetch(url: str) -> Drug:
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    drug = Drug(url=url)

    # ---- name (h2 pair) ----
    h2s = [h.get_text(strip=True) for h in soup.select("h2") if h.get_text(strip=True)]
    if h2s:
        drug.name_he = h2s[0]
    if len(h2s) > 1:
        drug.name_en = h2s[1]

    # ---- uniform label/value fields ----
    labeled = _collect_labeled_values(soup)

    def first(label: str) -> str | None:
        v = labeled.get(label)
        return v[0] if v else None

    drug.manufacturer = first("יצרן")
    drug.registration_holder = first("בעל רישום")
    drug.registration_number = first("מספר רישום")
    drug.dispensing = first("תנאי ניפוק")
    drug.restrictions = first("מגבלות")
    drug.in_health_basket_raw = first("בסל הבריאות")
    if drug.in_health_basket_raw:
        s = drug.in_health_basket_raw.strip()
        if s in {"כן", "Yes"}:
            drug.in_health_basket = True
        elif s in {"לא", "No"}:
            drug.in_health_basket = False

    # ---- dosage form / usage form (bilingual; bold label has no value <p>
    # in the box, so collected as headers — values live in sibling .drugListBoxContent
    # without bolds) ----
    use_card = _card_by_title(soup, "שימוש")
    if use_card:
        # Each `.drugListBoxContent` here holds both a header row (two <b>
        # labels HE/EN) and a value row (two non-bold <p>s HE/EN).
        for box in use_card.select(".drugListBoxContent"):
            bolds = [b.get_text(strip=True) for b in box.find_all("b")]
            if len(bolds) < 2:
                continue
            he_label = bolds[0]
            ps = [p.get_text(strip=True) for p in box.find_all("p")
                  if not p.find("b") and p.get_text(strip=True)]
            if len(ps) < 2:
                continue
            if he_label == "צורת מינון":
                drug.dosage_form_he, drug.dosage_form_en = ps[0], ps[1]
            elif he_label == "דרך מתן":
                drug.usage_form_he, drug.usage_form_en = ps[0], ps[1]

    # ---- active ingredients ----
    ai_card = _card_by_title(soup, "חומר פעיל")
    if ai_card:
        # First .drugListBoxContent is the header (חומר פעיל / כמות).
        # Each subsequent one is name + amount.
        boxes = ai_card.select(".drugListBoxContent")
        for box in boxes[1:]:
            # name lives in the <a class="filterLink"> inside a <form>
            link = box.find("a", class_="filterLink")
            name = link.get_text(strip=True) if link else None
            # amount: a non-link <p> (often wrapped in <b>)
            amount = None
            for p in box.find_all("p"):
                if p.find("a"):
                    continue
                t = p.get_text(" ", strip=True)
                if t:
                    amount = re.sub(r"\s+", " ", t)
                    break
            if name and amount:
                drug.active_ingredients.append(
                    ActiveIngredient(name=name, amount=amount)
                )

    # ---- ATC (read straight from form inputs — labels are confusingly swapped) ----
    atc_card = _card_by_title(soup, "ATC")
    if atc_card:
        code_input = atc_card.select_one('input[name="atc4name"]')
        name_input = atc_card.select_one('input[name="atc4code"]')
        if code_input and code_input.get("value"):
            drug.atc_code = code_input["value"].strip()
        if name_input and name_input.get("value"):
            drug.atc_name = name_input["value"].strip()

    # ---- consumer prices ----
    price_card = _card_by_title(soup, "מחירים לצרכן")
    if price_card:
        body = price_card.select_one(".card-body")
        if body:
            txt = body.get_text(" ", strip=True)
            drug.consumer_prices = txt or None

    # ---- equivalent drugs ----
    eq_card = _card_by_title(soup, "תרופות אחרות בעלות אותם מרכיבים")
    if eq_card:
        for a in eq_card.select("a"):
            t = a.get_text(strip=True)
            if t and t != "הצג עוד":
                drug.equivalent_drugs.append(t)
        if not drug.equivalent_drugs:
            # Fallback: text lines
            content = eq_card.select_one(".drugListBoxContent")
            if content:
                drug.equivalent_drugs = [
                    l for l in (line.strip() for line in content.get_text("\n").splitlines())
                    if l and l != "הצג עוד"
                ]

    # ---- leaflets ----
    leaf_card = _card_by_title(soup, "עלונים")
    if leaf_card:
        for a in leaf_card.select("a[href]"):
            label = a.get_text(strip=True)
            lang = "other"
            for he, code in _LANG_MAP.items():
                if he in label:
                    lang = code
                    break
            drug.leaflets.append(Leaflet(language=lang, label=label, url=a["href"]))

    # ---- approved indication ----
    ind_card = _card_by_title(soup, "התוויה מאושרת")
    if ind_card:
        content = ind_card.select_one(".drugListBoxContent")
        if content:
            drug.approved_indication = content.get_text(" ", strip=True) or None

    # ---- raw text fallback ----
    main = soup.select_one("main") or soup.body or soup
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
            print("fetch requires a URL", file=sys.stderr)
            return 2
        drug = fetch(argv[2])
        json.dump(asdict(drug), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
