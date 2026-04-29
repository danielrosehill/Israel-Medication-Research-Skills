---
name: medicine-availability-check
description: Orchestrator for "is drug X available to me in Israel" questions. Chains the per-source lookup skills in the right order — start with the user's health fund (currently Maccabi via `maccabi-medicine-lookup`) for the practical answer (listed? in basket? copay? prior approval?), reach for the patient-facing pharma reference (`drug-co-il-lookup`) only if the user needs clinical context (active ingredient, leaflet, equivalents), and reach for the official Israeli Drug Registry (`israel-drugs-registry-lookup`) only if regulatory status is in question (is it currently registered, who holds the licence, is the registration cancelled). Use when the user asks something like "is X available", "can I get X on Maccabi", "is X covered", "is X still sold in Israel", or any open-ended availability/coverage question that doesn't already pin down which database to hit.
---

# Medicine availability check (orchestrator)

This skill **does not** make HTTP calls of its own. It decides which of the underlying lookup skills to invoke, in what order, and how to merge their answers.

The three lookup skills it orchestrates:

| Skill | Source | Answers |
|---|---|---|
| `maccabi-medicine-lookup` | Maccabi member-facing catalogue | Listed by Maccabi? In basket? Prescription? Prior approval? List price + per-tier copay |
| `drug-co-il-lookup` | drug.co.il (Pharmacists Organization) | Active ingredient, ATC, dosage form, equivalents, MOH patient leaflet (lay/clinical) |
| `israel-drugs-registry-lookup` | israeldrugs.health.gov.il (MOH regulatory) | Registration number, licence holder, official indication text, registration status (active/cancelled), all leaflet revisions |

## Decision rules

Resolve the user's actual question first, then call only what's needed.

### Step 1 — always start with the health fund

For "is X available", the **practical** answer almost always lives at the health fund. Currently this is **Maccabi only** (Klalit/Meuchedet/Leumit equivalents are not yet covered). Call `maccabi-medicine-lookup` first.

If the Maccabi catalogue lists the drug, you already have:
- listed ✓
- prescription requirement
- basket inclusion (Maccabi's view)
- prior-approval requirement
- list price + Maccabi-tier copays

For the typical user question this is enough — answer and stop. Do **not** also ping the other two sources by reflex; that wastes time and quota.

### Step 2 — pharma reference only if clinical context is needed

Call `drug-co-il-lookup` **only if** the user's question involves anything Maccabi can't answer:

- Active ingredient / ATC code (the user wants to compare or find equivalents)
- Patient information leaflet (the user wants to read the leaflet)
- Equivalent / generic drugs (same active ingredient, different brand)
- Approved indication in plain English

If the Maccabi answer was "not listed" and the user wants to know **what the drug actually is** before acting, this is the layer to use.

### Step 3 — gov registry only if regulatory status is genuinely in play

Call `israel-drugs-registry-lookup` **only if** the question hinges on a regulatory fact:

- "Is this still registered in Israel?" / "Did they cancel it?"
- "Who holds the licence?" (e.g. for a complaint, customs query, importer change)
- "Give me the official indication text" (not the lay version — the legally-binding wording)
- The drug isn't on Maccabi **and** isn't on drug.co.il, so the user wants to confirm whether it ever was/still is licensed.
- The user explicitly asked for the registration number (דרגיסטר).

Day-to-day "can I get this from my pharmacy?" questions almost never need this layer.

## Don't call all three by default

The strong default is **one source, the right one**. Each extra call adds latency, may hit a transient outage on a different site, and dilutes the answer with information the user didn't ask for. Climb the ladder only when the prior step left a real gap.

## Handling "not found" outcomes

- **Not on Maccabi**: say so first. Then ask the user whether they want clinical info (escalate to drug.co.il) or regulatory status (escalate to the gov registry). Don't auto-cascade — they may already know it isn't on Maccabi.
- **Not on drug.co.il either**: rare. At that point the gov registry is the right next step — if it isn't there, the drug is not licensed in Israel.
- **Hebrew vs English name issues**: the catalogues differ. drug.co.il indexes both; Maccabi is English-brand-only; the gov registry takes either. If a name lookup fails on Maccabi, try the same query on drug.co.il to recover the English brand, then re-search Maccabi.

## Composing the answer

When the user asked a single concrete question ("is X covered?"), answer that single question with the data from the one source you needed. Don't pad with regulatory or clinical detail they didn't ask for.

When the user asked an open question ("tell me about X for me on Maccabi"), the natural shape is:

1. **Maccabi facts** — listed, prescription, basket, copay, prior approval.
2. **What the drug is** — one line, only if relevant (active ingredient + indication).
3. **Leaflet link** — if the user is likely to want to read it (new prescription, switch).
4. **Regulatory note** — only if `iscanceled` is true on the registry side, or if Maccabi shows it but the registration is suspended; that's a real "this is going off-shelf" signal worth surfacing.

## Future health funds

This skill currently only orchestrates Maccabi on the health-fund side. When Klalit / Meuchedet / Leumit lookup skills land in the same plugin, extend Step 1 to dispatch on the user's stated/configured fund. Until then, if the user is **not** a Maccabi member, say so honestly — drug.co.il and the gov registry can still answer the clinical/regulatory parts but not the "what will I pay" part.
