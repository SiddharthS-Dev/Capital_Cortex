# Demo seed (Phase 1)

`make seed` generates the synthetic dataset described in §13: one self-organisation profile, ~300 fictional
investors and funds, ~120 grant programs, ~600 opportunities across all 11 classes and 25 countries, contacts,
meetings, 18 months of financial snapshots, and ~80 realised outcomes.

Rules (enforced by the generator and the I1 constraints):
- every row has `is_demo = true` and `source_ref = {"kind": "synthetic_seed"}`
- names are obviously fictional ("Northwind Climate Fund I"); real investor, fund or program names are never used
- the UI shows the amber DEMO DATA ribbon while any `is_demo` row exists; `make purge-demo` removes them all

Status: coming in Phase 1. `make seed` currently exits with a "Coming in Phase 1" message.
