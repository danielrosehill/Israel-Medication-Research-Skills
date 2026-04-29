---
name: drug-co-il-lookup
description: Look up an Israeli medication on drug.co.il (the drug-information site of the Israeli Pharmacists Organization, ארגון הרוקחות בישראל). Returns structured JSON — Hebrew + English name, manufacturer, active ingredients, ATC code, dosage/usage form, prescription status, health-basket inclusion (סל הבריאות), approved indication, equivalent drugs (generics), and links to MOH-hosted patient leaflets in Hebrew/English/Arabic. Use when the user asks about an Israeli medication by Hebrew or English brand name, generic name, or active ingredient.
---

# drug.co.il lookup

`drug.co.il` is the drug-information site of **ארגון הרוקחות בישראל** (Pharmacists Organization of Israel). Each drug has a public page with manufacturer, active ingredient, ATC, dosage form, prescription/OTC status, health-basket inclusion, approved indication, list of equivalent drugs (same active ingredient, different brand/dose), and links to the official MOH patient leaflet PDFs in Hebrew/English/Arabic.

## Two operations

### 1. Search

Always search first when the user gives a name — slug guessing with percent-encoded Hebrew is fragile. The site uses WordPress search (`?s=<query>`), minimum 3 characters, matches Hebrew name, English name, or active ingredient.

```bash
python3 skills/drug-co-il-lookup/scripts/lookup.py search "ליסין"
python3 skills/drug-co-il-lookup/scripts/lookup.py search "lisdexamfetamine"
```

Returns JSON array of `{name, url}`. Pick the best match (or present options to the user if ambiguous — multiple doses of the same drug each have their own page, e.g. ליסין 30 / 50 / 70 מ"ג).

### 2. Fetch

Fetch the structured record for a specific drug page URL.

```bash
python3 skills/drug-co-il-lookup/scripts/lookup.py fetch "https://drug.co.il/drugs/<slug>/"
```

Returns a `Drug` JSON object with the fields listed above plus `raw_text` (cleaned page text) as a fallback in case a selector breaks — you can answer from `raw_text` if a structured field comes back null.

## Notes when answering the user

- The site is for **patients and the general public**, not just professionals — answer in plain language. Daniel's plugin context says these skills target non-medical users.
- `in_health_basket` (סל הבריאות) is the Israeli-context-critical field — whether the drug is subsidized under the national health basket. Surface it.
- `dispensing` (תנאי ניפוק) tells you prescription vs OTC.
- The `approved_indication` field is the official English indication text — quote it verbatim rather than paraphrasing medical claims.
- Leaflet PDFs are hosted on `mohpublic.z6.web.core.windows.net` (Israeli Ministry of Health). Offer the Hebrew leaflet by default, English/Arabic on request.
- `consumer_prices` is often "לא נמצא מידע" (no data) — the site does not reliably carry prices.
- This site does **not** carry stock/availability — for "is this drug in stock at my Kupah" use the `maccabi-medicine-lookup` skill (or analogous Kupah skills) instead.

## Dependencies

`requests` and `beautifulsoup4`. Both are available in the user's default Python environment.
