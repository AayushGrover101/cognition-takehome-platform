"""Writes the connector catalogue (operations, groups, audit limits) for the apps repository.

Usage: python scripts/export_catalog.py ../cognition-takehome-apps/platform/catalog.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway import config  # noqa: E402

target = Path(sys.argv[1]) if len(sys.argv) > 1 else config.APPS_DIR / "platform" / "catalog.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(config.catalog(), indent=2, sort_keys=True) + "\n")
print(f"Wrote {len(config.catalog()['operations'])} operations to {target}")
