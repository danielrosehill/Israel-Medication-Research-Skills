---
name: israel-drugs-registry-lookup
description: Look up an Israeli medication in the official Israeli Drug Registry (מאגר התרופות) maintained by the Ministry of Health at israeldrugs.health.gov.il. This is the authoritative regulatory source — registration number (דרגיסטר), license holder, manufacturer, active ingredients with strengths, ATC code, dosage form, route of administration, prescription/OTC status, health-basket inclusion, full approved indication, registration status (active / cancelled / suspended), and links to the official MOH-approved Hebrew/English/Arabic patient leaflet (עלון לצרכן) and prescribing information (עלון לרופא). Use when the user wants the regulatory record — registration number, license holder, official indication text, or whether a drug is currently registered.
---

# Israeli Drug Registry (israeldrugs.health.gov.il) lookup

The Israeli Drug Registry is the **regulatory** drug database — the official MOH list of every medicine licensed in Israel, with the legally-binding registration record. It's the source for "is this drug registered in Israel", "what's its registration number", "who holds the license", and "what's the officially approved indication".

For clinical/patient-facing content (`drug-co-il-lookup`) and Maccabi commercial info (`maccabi-medicine-lookup`), use those skills instead. This skill is the regulatory layer.

## The user-facing flow this skill mirrors

The site's UI flow (the one the user follows in a browser) is:

1. **Landing tab** "חיפוש תרופה לפי שם מסחרי או מרכיב פעיל" (search by trade name or active ingredient) at `https://israeldrugs.health.gov.il/#!/byDrug`.
2. **Type a keyword** in the search box — Hebrew, English, full or partial. Examples: `VYVANSE 70 MG`, `ויואנס`, `acamol`, `lisdexamfetamine`. Optionally tick "הצג תרופות בסל הבריאות בלבד" to restrict to health-basket drugs.
3. **Submit** (חיפוש). The intermediate **results page** lists each match as a card showing: image, Hebrew + English name, active component (`מרכיב פעיל`), dosage form (`צורת מינון`), full registration number (`מספר רישום מלא`, e.g. `153 21 34000 00`), license holder (`שם בעל הרישום`), and a `בסל הבריאות` badge if applicable. Each card has a **"לפרטים נוספים"** (more details) link.
4. **Click "לפרטים נוספים"** to land on the per-drug page at `https://israeldrugs.health.gov.il/#!/medDetails/<url-encoded-reg-num>` (e.g. `…/medDetails/153%2021%2034000%2000`). This page is the **regulatory treasure trove**: full indication text, all manufacturers, ATC code, basket-inclusion record, and the official patient and physician leaflets in PDF.

Steps 2–3 correspond to the `search` operation; step 4 corresponds to `fetch`. The skill skips the UI and calls the same JSON endpoints the Angular app calls.

## Two operations

### 1. Search

```bash
python3 skills/israel-drugs-registry-lookup/scripts/lookup.py search "VYVANSE 70 MG"
python3 skills/israel-drugs-registry-lookup/scripts/lookup.py search "ויואנס"
python3 skills/israel-drugs-registry-lookup/scripts/lookup.py search "acamol"
```

Hits `POST /GovServiceList/IDRServer/SearchByName` with `{val, prescription:false, healthServices:false, pageIndex:1, orderBy:0}`. Matches Hebrew name, English name, or active ingredient. Returns `{results: [...]}` where each entry has `dragRegNum`, `dragHebName`, `dragEnName`, `activeComponents[]`, `dosageForm`, `prescription`, `health` (in basket), `iscanceled`, `dragRegOwner`, `packages[]`, `barcodes`, `indications`, etc. — i.e. the same data the result-card UI binds to (`r.dragHebName`, `r.activeComponentsDisplayName`, `r.dosageForm`, `r.dragRegNum`, `r.dragRegOwner`).

Tip: the `pages` and `results` fields in each entry tell you total pages / total result count. Re-run with `pageIndex:N` (script uses 1) to paginate if needed — at present the script always asks for page 1, fine for the typical case where keyword + dose narrows to ≤1 page.

### 2. Fetch

```bash
python3 skills/israel-drugs-registry-lookup/scripts/lookup.py fetch "153 21 34000 00"
```

Pass the registration number with its native spaces — the JSON body uses the unencoded form (`{"dragRegNum": "153 21 34000 00"}`); URL-encoding with `%20` is only needed when constructing the human-facing `#!/medDetails/...` URL.

Hits `POST /GovServiceList/IDRServer/GetSpecificDrug`. Returns the full regulatory record. Notable top-level keys:

- **Identity & registration**: `dragRegNum`, `dragHebName`, `dragEnName`, `regDate`, `regExpDate`, `applicationDate`, `applicationType` (e.g. תכשיר גנרי), `iscanceled`, `bitulDate`.
- **Holder & manufacturer**: `regOwnerName` (license holder, בעל הרישום), `regManufactureName`, `manufacturers[]` (often multiple sites).
- **Clinical / regulatory**: `dragIndication` (legally-approved indication), `atc`, `activeMetirals[]` (active ingredients with strengths), `dosageForm` / `dosageFormEng`, `usageFormHeb` / `usageFormEng`, `isPrescription`, `isCytotoxic`, `isVeterinary`, `limitations`, `packingLimitation`, `remarks`, `classEffect`.
- **Health basket**: `health` (bool), `salList[]`, `dateOfInclusion`, `indicationIncludedInTheBasket`, `registeredIndicationsAtTimeOfInclusion`, `frameworkOfInclusion`, `useInClalit`.
- **Commercial**: `maxPrice`, `packages[]` (each with size, barcode, prices), `custom` (customs/import note).
- **Brochure** (`brochure[]`): the leaflet PDFs. Each entry has `type`, `url`, `lng`, `creationDateFormat`, `updateDateFormat`. Types observed:
  - `עלון לצרכן` — patient information leaflet (PIL). Default this for non-clinicians.
  - `עלון לרופא` — physician prescribing information.
  - `החמרה לעלון` / `החמרה לעלון לרופא` — formal label-update notices (regulatory amendments to the leaflet — keep, but they are not the leaflet itself).
  PDF URLs resolve under `https://mohpublic.z6.web.core.windows.net/IsraelDrugs/<url>`. `lng` is often null; pick the most recent `creationDateFormat` of the desired `type`.
- **Media**: `images[]` (product photos under the same `mohpublic` host), `videos[]`.

## If the script fails

If the JSON endpoint returns a non-JSON response, the script exits non-zero. Treat that as "this lookup didn't work right now" — ask the user to load the site in their browser and read the page, or try again later. Do not retry in a loop.

## Notes when answering the user

- **Registration status** (`status` / `regStatus`) is the load-bearing field. A drug whose registration has been **cancelled** or **suspended** may still be on shelves (until existing stock clears) but is no longer being licensed — flag this prominently.
- **Registration number** (דרגיסטר, e.g. `037 93 30332 00`) is the regulatory key. Quote it when the user is filing anything administrative (תמ"ל, prior-approval forms, customs).
- **License holder** (בעל הרישום) is the company legally responsible in Israel — not always the manufacturer. Surface both.
- **Active ingredient strengths** are quoted with units exactly as registered (e.g. `PARACETAMOL 500 MG`); do not round.
- **Indication text** (התוויה) is the legally-approved use — quote verbatim, don't paraphrase clinical claims.
- **Leaflet PDFs** live on `mohpublic.z6.web.core.windows.net/IsraelDrugs/`. Default to `עלון לצרכן` (patient PIL); offer `עלון לרופא` on request. The `החמרה לעלון*` entries are regulatory amendment notices, not the current consolidated leaflet — don't surface them as "the leaflet".
- **`medDetails` URL**: when you want to point the user at the human page, build it as `https://israeldrugs.health.gov.il/#!/medDetails/<reg-num>` with spaces replaced by `%20` (e.g. `153%2021%2034000%2000`). The API body uses the un-encoded form.
- The site is **regulatory, not commercial** — no prices, no stock, no Kupah-specific copay. Route those questions to `maccabi-medicine-lookup` (or another Kupah skill).

## Dependencies

`requests`. The site occasionally goes into maintenance mode (returns a 502 with a "DataDashboard-maintanance" SVG) — the script reports this and exits.
