"""Write docs/openapi.json from the app (CI checks it is current: `make openapi && git diff --exit-code`)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ENV", "test")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cortex.l8_actuation.api.app import create_app  # noqa: E402

spec = create_app().openapi()
out = ROOT / "docs" / "openapi.json"
out.write_text(json.dumps(spec, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} ({len(spec['paths'])} paths)")
