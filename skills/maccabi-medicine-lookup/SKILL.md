---
name: maccabi-medicine-lookup
description: Look up an Israeli medication on Maccabi Healthcare Services' (מכבי שירותי בריאות) member-facing medicine catalogue. Returns structured JSON — list price in ₪, per-insurance-plan copayment (Maccabi Sheli, Maccabi Zahav, Sal Basisi by age bracket), basket inclusion (סל), prescription requirement, prior-approval requirement (אישור מחלקת אישורי תרופות), dosage form, and a link out to Infomed for clinical info. Use when the user asks about price, coverage, copay, or whether a Maccabi member needs prior approval — including questions about a specific Maccabi insurance tier (שלי / זהב). Drugs are identified by English brand name + dose + pack size (e.g. "LISSIN 70MG 30TABS"). For clinical info (ingredients, side effects, leaflet), use `drug-co-il-lookup` instead.
---

# Maccabi medicine lookup

`maccabi4u.co.il/healthguide/medicines/` is Maccabi's member-facing drug catalogue (~5,260 drugs). Each drug page lists Maccabi-specific commercial info: list price, per-insurance-tier copayment, basket inclusion from Maccabi's POV, prescription/prior-approval requirements, dosage form, and a link out to Infomed for clinical content.

This is **not** a clinical reference — for ingredients, indication, side effects, or leaflets, use `drug-co-il-lookup`.

## Two operations

### 1. Search

Maccabi's medicines homepage embeds the **entire catalogue** as a JSON blob (`<input id="hiddenForSearch">`). The skill downloads it once at first use and caches it at `~/.cache/maccabi-medicine-lookup/index.json` (TTL 7 days). Search is a local case-insensitive token-AND match against the English brand name + pack size.

The index is **never bundled with this skill** — Maccabi's catalogue changes (new drugs, delistings, renaming), and shipping a stale snapshot would mislead users. Always fetch fresh on first run.

```bash
python3 skills/maccabi-medicine-lookup/scripts/lookup.py search "lissin 70"
python3 skills/maccabi-medicine-lookup/scripts/lookup.py search "vyvanse"
```

Returns `[{id, name, url}, ...]`. Names are English-brand-only (e.g. `LISSIN 70MG 30TABS`, `VYVANSE CAPSULE 70MG (30)`) — Hebrew names are not in the index. If the user gives a Hebrew name, translate to the English brand first (or use `drug-co-il-lookup` to find the English brand, then search here).

Each strength/pack-size is its own entry (Lissin 30/50/70 mg, Vyvanse 30/50/70 mg, etc.). When the user is vague about dose, present the matches and ask.

To force a catalogue refresh:
```bash
python3 skills/maccabi-medicine-lookup/scripts/lookup.py refresh-index
```

### 2. Fetch

Pass either a numeric drug id or a full URL.

```bash
python3 skills/maccabi-medicine-lookup/scripts/lookup.py fetch 37695
python3 skills/maccabi-medicine-lookup/scripts/lookup.py fetch "https://www.maccabi4u.co.il/healthguide/medicines/תרופות/37695/"
```

Returns a `Drug` JSON with:

- `name`, `infomed_url`
- `terms_and_approvals[]`: each with `label`, `granted` (bool from green-V/red-X icon), and an optional `more_info_url` (e.g. the booking link for prescription, the prior-approval submission portal). The page typically shows three terms: בסל, מרשם, אישור.
- Convenience booleans derived from those terms: `in_health_basket`, `requires_prescription`, `requires_prior_approval`
- `dosage_form` (Hebrew, e.g. טבליות / כמוסה)
- `where_to_purchase`, `pharmacy_locator_url`
- `list_price_ils` (parsed numeric ₪) + `list_price_text`
- `insurance_coverage[]`: list of `{plan, eligibility, copay_text}` covering Maccabi's own tiers (מכבי שלי, מכבי זהב) and the national-basket entries (סל בסיסי, repeated per age bracket: 6–17, 18–28, 29+). The percentages, the minimum-fee notes (אגרת מינימום), and the eligibility brackets are all kept as raw Hebrew text for fidelity.
- `pricing_disclaimer` (the standard "estimate, finalised at dispensing" caveat)
- `raw_text` fallback for selector drift

## Notes when answering the user

- The list price is the **uninsured** price. What the member actually pays is `list_price × copay_pct` for percentage plans, with a minimum-fee floor for the basket plans.
- A drug being `in_health_basket=true` does **not** mean free — it means subsidised. Always pair with the relevant `insurance_coverage` entry for the user's tier and age.
- `requires_prior_approval=true` is a **practical blocker** — surface it prominently. The `more_info_url` on that term takes the member to the online approval-request form.
- Hebrew text in `copay_text` and `eligibility` is kept verbatim — translate when answering the user, but quote the original numbers (₪ amounts, percentages, age brackets) without rounding.
- This catalogue is Maccabi-only. Klalit / Meuchedet / Leumit have their own equivalents, not covered here.

## Dependencies

`requests` and `beautifulsoup4`. The catalogue cache lives at `~/.cache/maccabi-medicine-lookup/`.
