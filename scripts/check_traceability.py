"""Traceability gate (§15): every SyRS item needs ≥1 linked test, and every linked test must exist.

Also renders docs/traceability.md. Exit 1 on any gap.
Usage: python scripts/check_traceability.py [--write-md]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "traceability.yaml"
OUT = ROOT / "docs" / "traceability.md"
REQUIRED = [
    "FR-01",
    "FR-02",
    "FR-03",
    "FR-04",
    "FR-04-OUT",
    "FR-05",
    "FR-06",
    "FR-07",
    "FR-08",
    "SyRS-7",
    "SyRS-10",
    "SyRS-11",
    "SyRS-12",
    "SyRS-14",
]


def test_exists(ref: str) -> bool:
    path, _, name = ref.partition("::")
    f = ROOT / path
    if not f.is_file():
        return False
    text = f.read_text(encoding="utf-8")
    if not name:
        return True
    if f.suffix == ".py":
        return re.search(rf"^\s*(async\s+)?def {re.escape(name)}\b", text, re.M) is not None
    if f.suffix == ".rego":
        return re.search(rf"^{re.escape(name)}\b", text, re.M) is not None
    return name in text  # Playwright/vitest titles


def main() -> int:
    data = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    items: dict = data["items"]
    errors: list[str] = []
    for key in REQUIRED:
        if key not in items:
            errors.append(f"{key}: missing from traceability.yaml")
    for key, it in items.items():
        tests = it.get("tests") or []
        if not tests:
            errors.append(f"{key}: no linked test")
        for t in tests:
            if not test_exists(t):
                errors.append(f"{key}: linked test not found: {t}")

    if "--write-md" in sys.argv:
        lines = [
            "# Traceability matrix",
            "",
            "_Generated from `docs/traceability.yaml` by "
            "`scripts/check_traceability.py --write-md`. Do not edit by hand._",
            "",
            "| SyRS | Title | Layer | Phase | Modules | Endpoints | Screens | Tests |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for key, it in items.items():
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    key,
                    it["title"],
                    it["layer"],
                    it["phase"],
                    "<br>".join(f"`{m}`" for m in it.get("modules", [])),
                    "<br>".join(f"`{e}`" for e in it.get("endpoints", [])),
                    ", ".join(it.get("screens", [])),
                    "<br>".join(f"`{t}`" for t in it.get("tests", [])),
                )
            )
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")

    if errors:
        print("TRACEABILITY GATE FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print(f"traceability OK: {len(items)} items, {sum(len(i.get('tests', [])) for i in items.values())} test links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
