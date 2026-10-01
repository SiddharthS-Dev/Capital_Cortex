"""Synthetic demo dataset (§13). Every row: is_demo = true, source_ref = {"kind": "synthetic_seed"}.

Names are invented syllable compounds (e.g. "Veltaris Climate Fund I"); real investor, fund or programme names
are never used. Opportunities go through the real pipeline (classify → resolve → graph → score), so the demo
exercises the same code as live data. Remove everything with ``make purge-demo``.

Usage (inside the app image): python -m seed.generate [--opportunities 600] [--seed 7]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
from datetime import UTC, date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import text

from cortex.l1_perception.models import Signal
from cortex.l2_representation.pipeline import process_signal
from platform_core.config import get_settings
from platform_core.db import session_scope

SRC = {"kind": "synthetic_seed", "generator": "seed/generate.py"}
COUNTRIES = [
    "US",
    "GB",
    "DE",
    "FR",
    "NL",
    "SE",
    "IE",
    "ES",
    "IT",
    "PL",
    "IN",
    "SG",
    "JP",
    "KR",
    "AU",
    "CA",
    "BR",
    "MX",
    "ZA",
    "KE",
    "NG",
    "AE",
    "IL",
    "CH",
    "DK",
]
PRE = [
    "Vel",
    "Quor",
    "Ard",
    "Lum",
    "Pyr",
    "Ost",
    "Kel",
    "Mar",
    "Zen",
    "Tor",
    "Bri",
    "Cal",
    "Dra",
    "Eno",
    "Fal",
    "Gri",
    "Hal",
    "Ivo",
    "Jor",
    "Kav",
    "Nor",
    "Oph",
    "Sel",
    "Tav",
    "Ul",
    "Vy",
    "Wren",
    "Xan",
    "Yor",
    "Zyl",
]
SUF = ["taris", "vane", "entis", "ora", "exa", "ine", "ova", "ium", "ara", "eth", "anth", "ioc", "ument", "yss"]
THEMES = ["Climate", "Frontier", "Horizon", "Catalyst", "Meridian", "Summit", "Harbor", "Beacon", "Keystone", "Aurora"]
SECTORS = [
    ("clean energy storage", "climate"),
    ("machine learning for logistics", "ai"),
    ("digital health diagnostics", "health"),
    ("advanced manufacturing robotics", "manufacturing"),
    ("regenerative agriculture", "agriculture"),
    ("cybersecurity for SMEs", "cybersecurity"),
    ("water treatment technology", "water"),
    ("fintech for payments", "fintech"),
    ("edtech and workforce training", "education"),
    ("electric mobility", "mobility"),
]
STAGES = ["pre-seed", "seed", "Series A", "Series B", "growth"]
PIPE = (
    ["discovered"] * 8
    + ["qualified"] * 4
    + ["engaged"] * 3
    + ["submitted"] * 2
    + ["diligence", "term_sheet", "committed"]
)

CLASS_TEMPLATES: dict[str, dict] = {
    "venture_equity": {
        "kind": "counterparty",
        "inv": "vc",
        "t": "{stage} equity round for {sector}",
        "d": "{org} invests venture capital in {stage} companies building {sector}.",
        "amt": (250_000, 5_000_000),
    },
    "private_equity": {
        "kind": "counterparty",
        "inv": "pe",
        "t": "Growth equity for {sector} leaders",
        "d": "{org} provides growth capital and minority stake investments in mature {sector} businesses.",
        "amt": (5_000_000, 50_000_000),
    },
    "strategic_corporate": {
        "kind": "counterparty",
        "inv": "cvc",
        "t": "Corporate venture partnership: {sector}",
        "d": "The corporate venture capital arm of {org} makes strategic investments in {sector}.",
        "amt": (500_000, 10_000_000),
    },
    "grant": {
        "kind": "agency",
        "inv": None,
        "t": "{theme} research grant: {sector}",
        "d": "Call for proposals. Non-dilutive grant awards for applied research in {sector}.",
        "amt": (50_000, 750_000),
    },
    "government_program": {
        "kind": "agency",
        "inv": None,
        "t": "National innovation scheme for {sector}",
        "d": "Government program offering public funding and R&D tax credit support for {sector}.",
        "amt": (100_000, 2_000_000),
    },
    "university_program": {
        "kind": "university",
        "inv": None,
        "t": "University research partnership in {sector}",
        "d": "A university innovation centre invites industry research partnerships and tech transfer pilots in {sector}.",
        "amt": (25_000, 300_000),
    },
    "foundation_esg": {
        "kind": "counterparty",
        "inv": "foundation",
        "t": "{theme} impact fund: {sector}",
        "d": "Philanthropic foundation and ESG impact fund backing SDG-aligned work in {sector}.",
        "amt": (50_000, 1_000_000),
    },
    "debt_facility": {
        "kind": "counterparty",
        "inv": "lender",
        "t": "Venture debt term loan for {sector}",
        "d": "{org} offers a term loan and working capital facility to venture-backed {sector} companies.",
        "amt": (1_000_000, 20_000_000),
    },
    "convertible": {
        "kind": "counterparty",
        "inv": "angel",
        "t": "SAFE round with valuation cap: {sector}",
        "d": "Convertible note or SAFE with valuation cap and discount rate for {stage} {sector} startups.",
        "amt": (100_000, 2_000_000),
    },
    "equipment_finance": {
        "kind": "counterparty",
        "inv": "lender",
        "t": "Equipment finance for {sector}",
        "d": "Asset finance and equipment lease programme for {sector} operators.",
        "amt": (200_000, 5_000_000),
    },
    "revenue_based_financing": {
        "kind": "counterparty",
        "inv": "lender",
        "t": "Revenue-based financing for {sector}",
        "d": "Revenue based financing repaid as a percentage of revenue up to a repayment cap, for {sector} companies.",
        "amt": (100_000, 3_000_000),
    },
}


def name(rnd: random.Random, kind: str) -> str:
    stem = rnd.choice(PRE) + rnd.choice(SUF)
    if kind == "agency":
        return f"{stem} {rnd.choice(['Innovation Agency', 'Research Council', 'Development Board'])}"
    if kind == "university":
        return f"University of {stem}"
    return f"{stem} {rnd.choice(THEMES)} {rnd.choice(['Ventures', 'Capital', 'Partners', 'Fund I', 'Fund II', 'Lending', 'Foundation'])}"


async def ensure_source() -> str:
    async with session_scope() as s:
        return str(
            (
                await s.execute(
                    text(
                        "INSERT INTO source (org_id, name, kind, adapter_key, adapter, terms_note, enabled, health, is_demo) VALUES "
                        "(:org, 'Synthetic demo seed', 'internal', 'synthetic_seed', 'manual', 'Fictional records generated by "
                        "seed/generate.py; removed by make purge-demo.', false, 'disabled', true) ON CONFLICT (org_id, adapter_key) "
                        "DO UPDATE SET name = EXCLUDED.name RETURNING id"
                    ),
                    {"org": get_settings().org_id},
                )
            ).scalar_one()
        )


async def seed(n_opps: int, rnd: random.Random) -> dict[str, int]:
    org = get_settings().org_id
    source_id = await ensure_source()
    counts = {
        "organizations": 0,
        "investors": 0,
        "funds": 0,
        "opportunities": 0,
        "contacts": 0,
        "meetings": 0,
        "relationships": 0,
        "snapshots": 0,
        "outcomes": 0,
        "interactions": 0,
        "milestones": 0,
    }
    demo_contacts: list[tuple[str, str]] = []
    async with session_scope() as s:
        # demo self profile (a real, non-demo profile always takes precedence in scoring)
        await s.execute(
            text(
                "INSERT INTO organization (org_id, name, normalized_name, kind, country, profile, source_ref, is_demo) "
                "SELECT :org, 'Inspironics (demo profile)', 'inspironics demo profile', 'self', 'US', CAST(:p AS jsonb), "
                "CAST(:src AS jsonb), true WHERE NOT EXISTS (SELECT 1 FROM organization WHERE kind = 'self' AND is_demo)"
            ),
            {
                "org": org,
                "src": json.dumps(SRC),
                "p": json.dumps(
                    {
                        "description": "Placeholder demo profile: AI software for clean energy storage and industrial analytics.",
                        "strategic_priorities": ["clean energy", "ai", "advanced manufacturing"],
                        "sectors": ["climate_energy", "ai_data"],
                        "tech_tags": ["machine learning", "energy storage", "analytics"],
                        "stage": "seed",
                        "target_geos": ["US", "GB", "DE", "IN"],
                        "esg_tags": ["climate", "clean_energy", "SDG7", "SDG13"],
                        "raise_target": {"min": 250000, "max": 3000000, "currency": "USD"},
                        "currency": "USD",
                    }
                ),
            },
        )

    # ---- opportunities through the real pipeline ----
    classes = list(CLASS_TEMPLATES)
    now = datetime.now(UTC)
    for i in range(n_opps):
        cls = classes[i % len(classes)]
        t = CLASS_TEMPLATES[cls]
        sector, _ = rnd.choice(SECTORS)
        stage = rnd.choice(STAGES)
        org_name = name(rnd, t["kind"])
        country = rnd.choice(COUNTRIES)
        geo = [country] if rnd.random() < 0.7 else rnd.sample(COUNTRIES, k=rnd.randint(2, 5))
        lo, hi = t["amt"]
        amin = round(rnd.uniform(lo, hi) / 1000) * 1000
        amax = round(min(hi * 1.5, amin * rnd.uniform(1.2, 4)) / 1000) * 1000
        deadline = None if rnd.random() < 0.15 else now + timedelta(days=rnd.randint(-20, 300))
        sig = Signal(
            source_key="synthetic_seed",
            external_id=f"demo-{i:05d}",
            title=t["t"].format(stage=stage, sector=sector, theme=rnd.choice(THEMES)),
            description=t["d"].format(org=org_name, stage=stage.lower(), sector=sector),
            counterparty_name=org_name,
            counterparty_kind=t["kind"],
            counterparty_country=country,
            investor_type=t["inv"],
            countries=geo,
            currency="USD" if rnd.random() < 0.85 else "EUR",
            amount_min=amin,
            amount_max=amax,
            deadline=deadline,
            stage_fit=[stage.lower().replace(" ", "_")],
            field_sources={k: "synthetic_seed" for k in ("title", "description", "counterparty_name", "countries")},
        )
        async with session_scope() as s:
            sid = (
                await s.execute(
                    text(
                        "INSERT INTO signal (org_id, source_id, external_id, raw, normalized, content_hash, source_ref, is_demo) "
                        "VALUES (:org, :src, :ext, '{}'::jsonb, CAST(:n AS jsonb), :h, CAST(:ref AS jsonb), true) "
                        "ON CONFLICT (org_id, content_hash) DO NOTHING RETURNING id"
                    ),
                    {
                        "org": org,
                        "src": source_id,
                        "ext": sig.external_id,
                        "n": sig.model_dump_json(),
                        "h": sig.content_hash(),
                        "ref": json.dumps({**SRC, "source_id": source_id}),
                    },
                )
            ).scalar()
        if sid is None:
            continue
        ev = await process_signal(str(sid))
        counts["opportunities"] += 1
        async with session_scope() as s:
            await s.execute(
                text("UPDATE opportunity SET pipeline_stage = CAST(:st AS pipeline_stage) WHERE id = :id"),
                {"st": rnd.choice(PIPE), "id": ev["opportunity_id"]},
            )

    async with session_scope() as s:
        cps = (
            (
                await s.execute(
                    text("SELECT id, name, kind FROM organization WHERE is_demo AND kind <> 'self' ORDER BY name")
                )
            )
            .mappings()
            .all()
        )
        counts["organizations"] = len(cps)
        # ---- investors + funds for counterparties that are capital providers ----
        for cp in cps:
            if cp["kind"] != "counterparty":
                continue
            inv_type = rnd.choice(["vc", "pe", "cvc", "angel", "family_office", "lender", "foundation"])
            inv = (
                await s.execute(
                    text(
                        "INSERT INTO investor (org_id, organization_id, investor_type, thesis_text, stages, geos, ticket_min, ticket_max, "
                        "currency, source_ref, is_demo) VALUES (:org, :o, :t, :th, :st, :g, :tmin, :tmax, 'USD', CAST(:src AS jsonb), true) "
                        "RETURNING id"
                    ),
                    {
                        "org": org,
                        "o": cp["id"],
                        "t": inv_type,
                        "src": json.dumps(SRC),
                        "th": f"{cp['name']} backs {rnd.choice(SECTORS)[0]} and {rnd.choice(SECTORS)[0]} companies.",
                        "st": rnd.sample(["seed", "series_a", "series_b_plus", "growth"], 2),
                        "g": rnd.sample(COUNTRIES, 3),
                        "tmin": 250_000,
                        "tmax": 5_000_000,
                    },
                )
            ).scalar_one()
            counts["investors"] += 1
            if rnd.random() < 0.8:
                await s.execute(
                    text(
                        "INSERT INTO fund (org_id, investor_id, name, vintage, size, currency, thesis_text, status, source_ref, is_demo) "
                        "VALUES (:org, :i, :n, :v, :sz, 'USD', :th, 'investing', CAST(:src AS jsonb), true)"
                    ),
                    {
                        "org": org,
                        "i": inv,
                        "n": f"{cp['name'].split()[0]} Fund {rnd.choice(['I', 'II', 'III'])}",
                        "v": rnd.randint(2019, 2026),
                        "sz": rnd.randint(20, 400) * 1_000_000,
                        "th": "Demo fund thesis",
                        "src": json.dumps(SRC),
                    },
                )
                counts["funds"] += 1
        # ---- contacts, meetings, relationships (L3 inputs for relationship_strength) ----
        firsts = ["Ada", "Bo", "Cyra", "Dev", "Elin", "Faro", "Gia", "Hux", "Ines", "Jax", "Kiri", "Lio", "Mina", "Nox"]
        lasts = ["Orlo", "Pemberly", "Quade", "Rinaldi", "Sorrel", "Tamsin", "Umber", "Vance", "Wilder", "Yarrow"]
        for cp in rnd.sample(list(cps), k=min(len(cps), 160)):
            for _ in range(rnd.randint(1, 3)):
                cname = f"{rnd.choice(firsts)} {rnd.choice(lasts)}"
                cid = (
                    await s.execute(
                        text(
                            "INSERT INTO contact (org_id, organization_id, name, role, emails, consent_basis, source_ref, is_demo) VALUES "
                            "(:org, :o, :n, :r, :e, 'manual_entry', CAST(:src AS jsonb), true) RETURNING id"
                        ),
                        {
                            "org": org,
                            "o": cp["id"],
                            "n": cname,
                            "r": rnd.choice(["Partner", "Principal", "Programme Manager", "Director"]),
                            "e": [f"{cname.split()[0].lower()}@example.invalid"],
                            "src": json.dumps(SRC),
                        },
                    )
                ).scalar_one()
                counts["contacts"] += 1
                demo_contacts.append((str(cid), str(cp["id"])))
                touched = now - timedelta(days=rnd.randint(1, 240))
                # interactions (warmth is derived from these by relationship_service, never set directly)
                for _ in range(rnd.randint(1, 5)):
                    kind = rnd.choice(["email_sent", "email_sent", "email_reply", "call", "meeting"])
                    await s.execute(
                        text(
                            "INSERT INTO interaction (org_id, contact_id, organization_id, kind, direction, occurred_at, summary, weight, "
                            "recorded_by, source_ref, is_demo) VALUES (:org, :c, :o, :k, :d, :t, :sm, 0, 'seed', CAST(:src AS jsonb), true)"
                        ),
                        {"org": org, "c": cid, "o": cp["id"], "k": kind, "d": "outbound" if kind == "email_sent" else "inbound",
                         "t": now - timedelta(days=rnd.randint(1, 300)), "sm": f"Demo {kind.replace('_', ' ')}", "src": json.dumps(SRC)},
                    )  # fmt: skip
                    counts["interactions"] += 1
                if rnd.random() < 0.7:
                    await s.execute(
                        text(
                            "INSERT INTO meeting (org_id, contact_ids, occurred_at, summary, next_steps, source_ref, is_demo) VALUES "
                            "(:org, ARRAY[CAST(:c AS uuid)], :t, :sm, :ns, CAST(:src AS jsonb), true)"
                        ),
                        {
                            "org": org,
                            "c": cid,
                            "t": touched,
                            "sm": f"Intro call with {cname} (demo).",
                            "ns": "Share deck",
                            "src": json.dumps(SRC),
                        },
                    )
                    counts["meetings"] += 1
                    await s.execute(
                        text(
                            "INSERT INTO interaction (org_id, contact_id, organization_id, kind, direction, occurred_at, summary, weight, "
                            "recorded_by, source_ref, is_demo) VALUES (:org, :c, :o, 'meeting', 'internal', :t, :sm, 1, 'seed', "
                            "CAST(:src AS jsonb), true)"
                        ),
                        {"org": org, "c": cid, "o": cp["id"], "t": touched, "sm": f"Intro call with {cname} (demo).", "src": json.dumps(SRC)},
                    )  # fmt: skip
                    counts["interactions"] += 1
                    if rnd.random() < 0.5:
                        kind = rnd.choice(["follow_up", "commitment_expiry"])
                        await s.execute(
                            text(
                                "INSERT INTO milestone (org_id, kind, title, due_at, status, contact_id, organization_id, created_by, "
                                "source_ref, is_demo) VALUES (:org, :k, :t, :due, 'open', :c, :o, 'seed', CAST(:src AS jsonb), true)"
                            ),
                            {"org": org, "k": kind, "c": cid, "o": cp["id"], "src": json.dumps(SRC),
                             "t": f"{'Follow up with' if kind == 'follow_up' else 'Commitment from'} {cname} (demo)",
                             "due": now + timedelta(days=rnd.randint(-20, 40))},
                        )  # fmt: skip
                        counts["milestones"] += 1
        # ---- 18 months of financial snapshots ----
        start = date.today().replace(day=1) - relativedelta(months=18)
        cash = 2_400_000.0
        for m in range(18):
            period = start + relativedelta(months=m)
            revenue = round(40_000 + m * 3_500 + rnd.uniform(-5_000, 5_000), 2)
            opex = round(150_000 + m * 2_000 + rnd.uniform(-8_000, 8_000), 2)
            cash = round(cash - (opex - revenue), 2)
            await s.execute(
                text(
                    "INSERT INTO financial_snapshot (org_id, period, cash, revenue, opex, net_burn, currency, source_ref, is_demo) "
                    "VALUES (:org, :p, :c, :r, :o, :b, 'USD', CAST(:src AS jsonb), true) ON CONFLICT (org_id, period) DO NOTHING"
                ),
                {
                    "org": org,
                    "p": period,
                    "c": cash,
                    "r": revenue,
                    "o": opex,
                    "b": round(opex - revenue, 2),
                    "src": json.dumps(SRC),
                },
            )
            counts["snapshots"] += 1
        # ---- ~80 outcomes (demo "realised" labels; I6 training excludes is_demo rows) ----
        opps = (
            (
                await s.execute(
                    text(
                        "SELECT id, score FROM opportunity WHERE is_demo AND score IS NOT NULL ORDER BY random() LIMIT 80"
                    )
                )
            )
            .mappings()
            .all()
        )
        for o in opps:
            p_win = 0.15 + 0.7 * float(o["score"] or 0)
            result = "won" if rnd.random() < p_win else rnd.choice(["lost", "lost", "withdrawn"])
            await s.execute(
                text(
                    "INSERT INTO outcome (org_id, opportunity_id, result, amount, currency, reason, closed_at, recorded_by, source_ref, is_demo) "
                    "VALUES (:org, :o, :r, :a, 'USD', :why, :t, 'seed', CAST(:src AS jsonb), true)"
                ),
                {
                    "org": org,
                    "o": o["id"],
                    "r": result,
                    "a": rnd.randint(50, 2000) * 1000 if result == "won" else None,
                    "why": "demo outcome",
                    "t": now - timedelta(days=rnd.randint(1, 365)),
                    "src": json.dumps(SRC),
                },
            )
            await s.execute(
                text("UPDATE opportunity SET pipeline_stage = CAST(:st AS pipeline_stage) WHERE id = :id"),
                {"st": "closed" if result == "won" else "lost", "id": o["id"]},
            )
            counts["outcomes"] += 1
    # warmth from the seeded interactions (the same code path as real ones), then rescore the demo opportunities
    from cortex.l3_memory.relationship_service import recompute_contact
    from cortex.l3_memory.warmth import relationships_config

    weights = relationships_config()["weights"]
    async with session_scope() as s:
        for k, w in weights.items():
            await s.execute(text("UPDATE interaction SET weight = :w WHERE is_demo AND kind = :k"), {"w": w, "k": k})
        for cid, _ in demo_contacts:
            await recompute_contact(s, cid, rescore=False)
        counts["relationships"] = len(demo_contacts)
    async with session_scope() as s:
        from cortex.l3_memory.consolidation_job import run as consolidate
        from cortex.l4_reasoning.score_service import rescore_all

        await consolidate(s, since=now - timedelta(days=1))
        await rescore_all(s, "is_demo")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opportunities", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    counts = asyncio.run(seed(args.opportunities, rnd))
    print(json.dumps({"seeded": counts, "fingerprint": hashlib.sha256(json.dumps(counts).encode()).hexdigest()[:12]}))


if __name__ == "__main__":
    main()
