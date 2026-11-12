"""Write the API's OpenAPI document. Usage: uv run python scripts/export_openapi.py [--check]

Output: packages/contracts/openapi.json (stable key order, LF). --check exits 1 if it is stale.
"""

import json
import sys
from pathlib import Path

from portal.main import create_app

TARGET = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text(encoding="utf-8") == text else 1)
    TARGET.write_bytes(text.encode("utf-8"))
    print(f"wrote {TARGET}")
