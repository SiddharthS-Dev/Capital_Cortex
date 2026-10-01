-- 1M-node synthetic seed for the load test (R3, §14). Run ONLY against the load database (`postgres-load`,
-- database cortex_load); scripts/load_test.py drives it:  psql -v scale=1 -f seed_1m.sql
--
-- Every row: is_demo = true, source_ref = {"kind": "synthetic_seed", "generator": "tests/load/seed_1m.sql"}.
-- Names are invented syllable compounds plus a number; nothing refers to a real investor, fund or programme.
--
-- Vertices get explicit graph ids (_graphid(label_id, n)) and the relational rows use the uuid md5('<kind>:n'),
-- so AGE vertices, their `id` property, the relational row, the `entity` mirror and every edge (AGE and the
-- `relationship_edge` mirror) line up without lookups. One transaction: a failed seed leaves nothing behind.
--
-- scale=1 gives exactly 1,000,000 vertices:
--   Organization 150k, Investor 30k, Fund 20k, GrantProgram 10k, Opportunity 200k, Signal 390k, Contact 200k
-- and ~1.0M edges: OFFERS, DERIVED_FROM, MENTIONS, KNOWS, INTRODUCED, PART_OF, MANAGES, RELATES_TO.
\set ON_ERROR_STOP on
\if :{?scale}
\else
  \set scale 1
\endif
SELECT (150000 * :scale)::bigint AS n_org, (30000 * :scale)::bigint AS n_inv, (20000 * :scale)::bigint AS n_fund,
       (10000 * :scale)::bigint AS n_gp, (200000 * :scale)::bigint AS n_opp, (390000 * :scale)::bigint AS n_sig,
       (200000 * :scale)::bigint AS n_con, (100000 * :scale)::bigint AS n_intro, (50000 * :scale)::bigint AS n_rel
\gset
\set src '{"kind": "synthetic_seed", "generator": "tests/load/seed_1m.sql"}'
\set org '00000000-0000-0000-0000-000000000001'

BEGIN;
SET LOCAL synchronous_commit = off;
LOAD '$libdir/plugins/age';

-- ---------------------------------------------------------------- helpers (session-local)
CREATE FUNCTION pg_temp.r(n bigint, salt int, m bigint) RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT ((hashint8(n * 1000003 + salt) & 2147483647)::bigint) % m $$;
CREATE FUNCTION pg_temp.u(k text, n bigint) RETURNS uuid LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT md5(k || ':' || n)::uuid $$;
CREATE FUNCTION pg_temp.syl(n bigint) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT (ARRAY['Vel','Quor','Ard','Lum','Pyr','Ost','Kel','Mar','Zen','Tor','Bri','Cal','Dra','Eno','Fal',
                'Gri','Hal','Ivo','Jor','Kav','Nor','Oph','Sel','Tav','Ul','Vy','Wren','Xan','Yor','Zyl'])[1 + n % 30]
      || (ARRAY['taris','vane','entis','ora','exa','ine','ova','ium','ara','eth','anth','ioc','ument','yss'])[1 + (n / 30) % 14]
$$;
CREATE FUNCTION pg_temp.orgname(g bigint) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT pg_temp.syl(g) || ' ' ||
         (ARRAY['Climate','Frontier','Horizon','Catalyst','Meridian','Summit','Harbor','Beacon','Keystone','Aurora'])[1 + (g / 420) % 10]
         || ' ' || (ARRAY['Capital','Ventures','Partners','Foundation','Agency','Labs','Holdings','Institute'])[1 + (g / 4200) % 8]
         || ' ' || g
$$;
CREATE FUNCTION pg_temp.country(n bigint) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT (ARRAY['US','GB','DE','FR','NL','SE','IE','ES','IT','PL','IN','SG','JP','KR','AU','CA','BR','MX','ZA','KE',
                'NG','AE','IL','CH','DK'])[1 + n % 25]
$$;
CREATE FUNCTION pg_temp.sector(n bigint) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT (ARRAY['clean energy storage','machine learning for logistics','digital health diagnostics',
                'advanced manufacturing robotics','regenerative agriculture','cybersecurity for SMEs',
                'water treatment technology','fintech for payments','edtech and workforce training',
                'electric mobility'])[1 + n % 10]
$$;
-- counterparty of opportunity g: 20% go to 1,000 hub organisations (~40 opportunities each), the rest spread
CREATE FUNCTION pg_temp.cp(g bigint, n_org bigint) RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN g % 5 = 0 THEN 2 + (g / 5) % 1000 ELSE 2 + pg_temp.r(g, 1, n_org - 1) END
$$;
CREATE FUNCTION pg_temp.contact_org(g bigint, n_org bigint) RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT 2 + pg_temp.r(g, 4, n_org - 1)
$$;

SELECT ag_catalog._label_id('ckg', 'Organization') AS l_org, ag_catalog._label_id('ckg', 'Investor') AS l_inv,
       ag_catalog._label_id('ckg', 'Fund') AS l_fund, ag_catalog._label_id('ckg', 'GrantProgram') AS l_gp,
       ag_catalog._label_id('ckg', 'Opportunity') AS l_opp, ag_catalog._label_id('ckg', 'Signal') AS l_sig,
       ag_catalog._label_id('ckg', 'Contact') AS l_con
\gset

-- ---------------------------------------------------------------- relational rows
INSERT INTO source (id, org_id, name, kind, adapter_key, adapter, terms_note, enabled, health, is_demo)
VALUES (pg_temp.u('source', 1), :'org', 'Synthetic load seed', 'internal', 'load_seed', 'manual',
        'synthetic data for the R3 load test', false, 'ok', true);

INSERT INTO organization (id, org_id, name, normalized_name, kind, country, sectors, profile, source_ref, is_demo)
SELECT pg_temp.u('org', g), :'org',
       CASE WHEN g = 1 THEN 'Loadtest Self Organisation' ELSE pg_temp.orgname(g) END,
       lower(CASE WHEN g = 1 THEN 'loadtest self organisation' ELSE pg_temp.orgname(g) END),
       CASE WHEN g = 1 THEN 'self' WHEN g % 10 = 0 THEN 'agency' WHEN g % 25 = 1 THEN 'university'
            ELSE 'counterparty' END,
       pg_temp.country(g), ARRAY[pg_temp.sector(g)],
       CASE WHEN g = 1 THEN '{"stage": "seed", "sectors": ["climate_energy", "ai_data"], "currency": "USD",
             "esg_tags": ["climate", "clean_energy", "SDG7", "SDG13"], "tech_tags": ["machine learning",
             "energy storage", "analytics"], "description": "Synthetic load-test profile.", "target_geos":
             ["US", "GB", "DE", "IN"], "raise_target": {"max": 3000000, "min": 250000, "currency": "USD"},
             "strategic_priorities": ["clean energy", "ai", "advanced manufacturing"], "country": "US"}'::jsonb
            ELSE '{}'::jsonb END,
       :'src'::jsonb, true
FROM generate_series(1, :n_org) g;

INSERT INTO investor (id, org_id, organization_id, investor_type, thesis_text, stages, geos, ticket_min, ticket_max,
                      currency, source_ref, is_demo)
SELECT pg_temp.u('inv', g), :'org', pg_temp.u('org', g + 1),
       (ARRAY['vc','pe','cvc','angel','family_office','lender','foundation','agency'])[1 + g % 8],
       'Invests in ' || pg_temp.sector(g) || ' across ' || pg_temp.country(g) || ' and neighbouring markets.',
       ARRAY[(ARRAY['pre-seed','seed','Series A','Series B','growth'])[1 + g % 5]], ARRAY[pg_temp.country(g)],
       100000 * (1 + g % 10), 1000000 * (1 + g % 10), 'USD', :'src'::jsonb, true
FROM generate_series(1, :n_inv) g;

INSERT INTO fund (id, org_id, investor_id, name, vintage, size, currency, thesis_text, status, source_ref, is_demo)
SELECT pg_temp.u('fund', g), :'org', pg_temp.u('inv', 1 + (g - 1) % :n_inv),
       pg_temp.syl(g + 7) || ' ' || pg_temp.sector(g) || ' Fund ' || g, 2015 + g % 11, 10000000 * (1 + g % 50),
       'USD', 'Fund thesis: ' || pg_temp.sector(g), (ARRAY['fundraising','investing','harvesting','closed'])[1 + g % 4],
       :'src'::jsonb, true
FROM generate_series(1, :n_fund) g;

INSERT INTO grant_program (id, org_id, agency_org_id, title, description, eligibility, amount_min, amount_max, currency,
                           open_date, deadline, url, source_ref, is_demo)
SELECT pg_temp.u('gp', g), :'org', pg_temp.u('org', 10 * g), pg_temp.syl(g) || ' research programme ' || g,
       'Non-dilutive programme for applied research in ' || pg_temp.sector(g) || '.',
       jsonb_build_object('countries', jsonb_build_array(pg_temp.country(g))), 50000, 750000, 'USD',
       current_date - (g % 90)::int, now() + ((g % 365) || ' days')::interval,
       'https://example.invalid/programmes/' || g, :'src'::jsonb, true
FROM generate_series(1, :n_gp) g;

INSERT INTO signal (id, org_id, source_id, external_id, raw, normalized, content_hash, ingested_at, source_ref, is_demo)
SELECT pg_temp.u('sig', g), :'org', pg_temp.u('source', 1), 'load-' || g,
       jsonb_build_object('title', 'Synthetic signal ' || g, 'body',
         repeat('Synthetic listing text about ' || pg_temp.sector(g) || ' in ' || pg_temp.country(g) || '. ', 12),
         'published_at', now() - ((g % 700) || ' days')::interval),
       jsonb_build_object('title', 'Synthetic signal ' || g, 'countries', jsonb_build_array(pg_temp.country(g))),
       md5('load-signal:' || g), now() - ((g % 700) || ' days')::interval, :'src'::jsonb, true
FROM generate_series(1, :n_sig) g;

-- opportunities: realistic spread of class, stage, status, score band; factors ~2.5 KB like the real scorer's
INSERT INTO opportunity (id, org_id, class, class_source, classification_confidence, class_evidence, title, description,
                         counterparty_id, grant_program_id, fund_id, geography, stage_fit, sectors, esg_tags, amount_min,
                         amount_max, currency, deadline, pipeline_stage, score, score_band, factors, completeness,
                         scored_at, status, archive_reason, signal_id, external_key, url, source_ref, is_demo)
SELECT pg_temp.u('opp', g), :'org', cls::capital_class, 'rule', 0.8,
       jsonb_build_object('method', 'rule', 'matched', jsonb_build_array(cls)),
       CASE cls WHEN 'grant' THEN 'Research grant: ' ELSE initcap(replace(cls, '_', ' ')) || ' for ' END
         || pg_temp.sector(g) || ' #' || g,
       pg_temp.orgname(cp) || ' offers ' || replace(cls, '_', ' ') || ' for companies building ' || pg_temp.sector(g)
         || ' in ' || pg_temp.country(g) || '. Eligibility, ticket size and timing are stated in the listing; '
         || 'applicants should demonstrate traction, a credible team and measurable impact. Reference ' || g || '.',
       pg_temp.u('org', cp),
       CASE WHEN cls IN ('grant', 'government_program') THEN pg_temp.u('gp', 1 + g % :n_gp) END,
       CASE WHEN cls = 'venture_equity' THEN pg_temp.u('fund', 1 + g % :n_fund) END,
       CASE WHEN g % 4 = 0 THEN ARRAY[pg_temp.country(g), pg_temp.country(g + 7)] ELSE ARRAY[pg_temp.country(g)] END,
       ARRAY[(ARRAY['pre-seed','seed','Series A','Series B','growth'])[1 + g % 5]],
       ARRAY[pg_temp.sector(g)], CASE WHEN g % 3 = 0 THEN ARRAY['climate','SDG13'] ELSE '{}' END,
       CASE WHEN g % 9 = 0 THEN NULL ELSE 50000 * (1 + g % 20) END,
       CASE WHEN g % 9 = 0 THEN NULL ELSE 50000 * (1 + g % 20) * (2 + g % 5) END,
       (ARRAY['USD','USD','USD','EUR','GBP'])[1 + g % 5],
       CASE WHEN g % 7 = 0 THEN NULL ELSE now() + (((g % 420) - 30) || ' days')::interval END,
       (ARRAY['discovered','discovered','discovered','discovered','discovered','discovered','discovered','discovered',
              'qualified','qualified','qualified','qualified','engaged','engaged','engaged','submitted','submitted',
              'diligence','term_sheet','committed'])[1 + g % 20]::pipeline_stage,
       sc, band,
       CASE WHEN sc IS NULL THEN NULL ELSE jsonb_build_object(
         'factors', (SELECT jsonb_object_agg(f, jsonb_build_object(
                        'value', round(((pg_temp.r(g, length(f), 1000))::numeric / 1000), 3), 'weight', 0.1,
                        'method', 'synthetic load seed', 'available', true, 'gap', NULL,
                        'evidence', jsonb_build_array(jsonb_build_object('ref', 'opportunity:' || pg_temp.u('opp', g),
                                      'field', f, 'source_ref', :'src'::jsonb)),
                        'contribution', round(((pg_temp.r(g, length(f), 1000))::numeric / 10000), 4)))
                     FROM unnest(ARRAY['stage','timing','geography','sector','ticket','thesis','relationship',
                                       'eligibility','esg','ml_prior']) f),
         'band_reason', 'synthetic', 'profile', jsonb_build_object('name', 'syrs_default', 'version', 1)) END,
       comp, CASE WHEN sc IS NULL THEN NULL ELSE now() - ((g % 30) || ' days')::interval END,
       CASE WHEN g % 20 = 1 THEN 'archived' WHEN g % 10 = 3 THEN 'watchlist' ELSE 'active' END,
       CASE WHEN g % 20 = 1 THEN 'synthetic: below threshold' END,
       pg_temp.u('sig', g), 'load-' || g, 'https://example.invalid/opportunities/' || g, :'src'::jsonb, true
FROM (
  SELECT g, cls, cp, sc, comp,
         CASE WHEN sc IS NULL THEN NULL WHEN comp < 0.45 THEN 'insufficient_evidence'
              WHEN sc >= 0.72 AND comp >= 0.6 THEN 'high' WHEN sc >= 0.5 THEN 'watchlist' ELSE 'archive' END AS band
  FROM (
    SELECT g,
           (ARRAY['venture_equity','private_equity','strategic_corporate','grant','government_program',
                  'university_program','foundation_esg','debt_facility','convertible','equipment_finance',
                  'revenue_based_financing'])[1 + g % 11] AS cls,
           pg_temp.cp(g, :n_org) AS cp,
           CASE WHEN g % 20 = 0 THEN NULL ELSE round((pg_temp.r(g, 2, 10000))::numeric / 10000, 4) END AS sc,
           CASE WHEN g % 20 = 0 THEN NULL ELSE round(0.3 + (pg_temp.r(g, 3, 7000))::numeric / 10000, 4) END AS comp
    FROM generate_series(1, :n_opp) g
  ) a
) b;

INSERT INTO contact (id, org_id, organization_id, name, role, emails, consent_basis, source_ref, is_demo)
SELECT pg_temp.u('con', g), :'org', pg_temp.u('org', pg_temp.contact_org(g, :n_org)),
       pg_temp.syl(g + 3) || ' ' || pg_temp.syl(g * 7 + 11) || 'son ' || g,
       (ARRAY['Partner','Principal','Programme Officer','Associate','Managing Director'])[1 + g % 5],
       ARRAY['contact' || g || '@example.invalid'], 'public_professional', :'src'::jsonb, true
FROM generate_series(1, :n_con) g;

INSERT INTO relationship (id, org_id, from_type, from_id, to_type, to_id, type, strength, last_touch_at, source_ref, is_demo)
SELECT pg_temp.u('rel', g), :'org', 'contact', pg_temp.u('con', g), 'organization',
       pg_temp.u('org', pg_temp.contact_org(g, :n_org)), 'met', round((pg_temp.r(g, 9, 10000))::numeric / 10000, 4),
       now() - ((g % 400) || ' days')::interval, :'src'::jsonb, true
FROM generate_series(1, :n_con) g;

-- 18 months of synthetic financials so the executive dashboard's runway forecast has inputs
INSERT INTO financial_snapshot (id, org_id, period, cash, revenue, opex, net_burn, currency, source_ref, is_demo)
SELECT pg_temp.u('fin', m), :'org', (date_trunc('month', now()) - (m || ' months')::interval)::date,
       2500000 - m * 60000, 40000 + m * 1000, 140000, 100000 - m * 1000, 'USD', :'src'::jsonb, true
FROM generate_series(1, 18) m;

-- ---------------------------------------------------------------- vertices (AGE) + entity mirror
CREATE TEMP TABLE v (label text, tbl text, kind text, n bigint, lid int, name text, extra jsonb) ON COMMIT DROP;
INSERT INTO v SELECT 'Organization', 'organization', 'org', g, :l_org,
                     CASE WHEN g = 1 THEN 'Loadtest Self Organisation' ELSE pg_temp.orgname(g) END, '{}'
              FROM generate_series(1, :n_org) g;
INSERT INTO v SELECT 'Investor', 'investor', 'inv', g, :l_inv, pg_temp.orgname(g + 1) || ' (investor)', '{}'
              FROM generate_series(1, :n_inv) g;
INSERT INTO v SELECT 'Fund', 'fund', 'fund', g, :l_fund, pg_temp.syl(g + 7) || ' ' || pg_temp.sector(g) || ' Fund ' || g, '{}'
              FROM generate_series(1, :n_fund) g;
INSERT INTO v SELECT 'GrantProgram', 'grant_program', 'gp', g, :l_gp, pg_temp.syl(g) || ' research programme ' || g, '{}'
              FROM generate_series(1, :n_gp) g;
INSERT INTO v SELECT 'Opportunity', 'opportunity', 'opp', o.g, :l_opp, o.title,
                     jsonb_build_object('class', o.class::text, 'deadline', coalesce(to_char(o.deadline, 'YYYY-MM-DD"T"HH24:MI:SSOF'), ''))
              FROM (SELECT (regexp_match(external_key, '\d+$'))[1]::bigint AS g, title, class, deadline FROM opportunity
                    WHERE external_key LIKE 'load-%') o;
INSERT INTO v SELECT 'Signal', 'signal', 'sig', g, :l_sig, 'Synthetic signal ' || g, '{"source": "load_seed"}'
              FROM generate_series(1, :n_sig) g;
INSERT INTO v SELECT 'Contact', 'contact', 'con', g, :l_con, pg_temp.syl(g + 3) || ' ' || pg_temp.syl(g * 7 + 11) || 'son ' || g, '{}'
              FROM generate_series(1, :n_con) g;

INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo)
SELECT pg_temp.u('ent-' || kind, n), :'org', label, tbl, pg_temp.u(kind, n), left(name, 300), extra, :'src'::jsonb, true
FROM v;

INSERT INTO ckg."Organization" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'name', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Organization';
INSERT INTO ckg."Investor" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'name', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Investor';
INSERT INTO ckg."Fund" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'name', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Fund';
INSERT INTO ckg."GrantProgram" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'name', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'GrantProgram';
INSERT INTO ckg."Opportunity" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'title', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Opportunity';
INSERT INTO ckg."Signal" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'title', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Signal';
INSERT INTO ckg."Contact" (id, properties)
SELECT ag_catalog._graphid(lid, n), (jsonb_build_object('id', pg_temp.u(kind, n), 'name', left(name, 300), 'is_demo', true,
       'source_ref', :'src') || extra)::text::ag_catalog.agtype FROM v WHERE label = 'Contact';

-- keep AGE's id sequences ahead of the explicit ids, so later CREATE/MERGE don't collide
SELECT setval('ckg."Organization_id_seq"', :n_org), setval('ckg."Investor_id_seq"', :n_inv),
       setval('ckg."Fund_id_seq"', :n_fund), setval('ckg."GrantProgram_id_seq"', :n_gp),
       setval('ckg."Opportunity_id_seq"', :n_opp), setval('ckg."Signal_id_seq"', :n_sig),
       setval('ckg."Contact_id_seq"', :n_con);

-- ---------------------------------------------------------------- edges (AGE) + relationship_edge mirror
CREATE TEMP TABLE e (type text, ak text, an bigint, al int, bk text, bn bigint, bl int) ON COMMIT DROP;
INSERT INTO e SELECT 'OFFERS', 'org', pg_temp.cp(g, :n_org), :l_org, 'opp', g, :l_opp FROM generate_series(1, :n_opp) g;
INSERT INTO e SELECT 'DERIVED_FROM', 'opp', g, :l_opp, 'sig', g, :l_sig FROM generate_series(1, :n_opp) g;
INSERT INTO e SELECT 'MENTIONS', 'sig', g, :l_sig, 'org', 2 + pg_temp.r(g, 5, :n_org - 1), :l_org
              FROM generate_series(:n_opp + 1, :n_sig) g;
INSERT INTO e SELECT 'KNOWS', 'con', g, :l_con, 'org', pg_temp.contact_org(g, :n_org), :l_org FROM generate_series(1, :n_con) g;
INSERT INTO e SELECT DISTINCT 'INTRODUCED', 'con', g, :l_con, 'con', t, :l_con
              FROM (SELECT g, 1 + pg_temp.r(g, 6, :n_con) AS t FROM generate_series(1, :n_intro) g) x WHERE t <> g;
INSERT INTO e SELECT 'PART_OF', 'inv', g, :l_inv, 'org', g + 1, :l_org FROM generate_series(1, :n_inv) g;
INSERT INTO e SELECT 'MANAGES', 'inv', 1 + (g - 1) % :n_inv, :l_inv, 'fund', g, :l_fund FROM generate_series(1, :n_fund) g;
INSERT INTO e SELECT 'OFFERS', 'org', 10 * g, :l_org, 'gp', g, :l_gp FROM generate_series(1, :n_gp) g;
INSERT INTO e SELECT DISTINCT 'RELATES_TO', 'org', a, :l_org, 'org', b, :l_org
              FROM (SELECT 2 + pg_temp.r(g, 7, :n_org - 1) AS a, 2 + pg_temp.r(g, 8, :n_org - 1) AS b
                    FROM generate_series(1, :n_rel) g) x WHERE a <> b;
-- the self organisation knows a few hundred contacts (warm-intro path finder starts here)
INSERT INTO e SELECT 'KNOWS', 'con', g * 997 % :n_con + 1, :l_con, 'org', 1, :l_org FROM generate_series(1, 300) g;

INSERT INTO relationship_edge (org_id, from_entity, to_entity, type, source_ref, is_demo)
SELECT :'org', pg_temp.u('ent-' || ak, an), pg_temp.u('ent-' || bk, bn), type, :'src'::jsonb, true FROM e;

INSERT INTO ckg."OFFERS" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'OFFERS';
INSERT INTO ckg."DERIVED_FROM" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'DERIVED_FROM';
INSERT INTO ckg."MENTIONS" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'MENTIONS';
INSERT INTO ckg."KNOWS" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'KNOWS';
INSERT INTO ckg."INTRODUCED" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'INTRODUCED';
INSERT INTO ckg."PART_OF" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'PART_OF';
INSERT INTO ckg."MANAGES" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'MANAGES';
INSERT INTO ckg."RELATES_TO" (start_id, end_id, properties)
SELECT ag_catalog._graphid(al, an), ag_catalog._graphid(bl, bn), ('{"source_ref": ' || to_json(:'src'::text) || '}')::ag_catalog.agtype
FROM e WHERE type = 'RELATES_TO';

SELECT (SELECT count(*) FROM ckg._ag_label_vertex) AS vertices, (SELECT count(*) FROM ckg._ag_label_edge) AS edges,
       (SELECT count(*) FROM entity) AS entities, (SELECT count(*) FROM relationship_edge) AS mirror_edges;
COMMIT;
