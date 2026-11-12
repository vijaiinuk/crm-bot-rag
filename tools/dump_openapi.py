"""Write the API's OpenAPI schema for the admin app's generated types: `make admin-types`."""

import json
import sys
from pathlib import Path

from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.app import create_app
from chatbot.config import Settings


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "admin/openapi.json")
    app = create_app(Settings(env="test"), entitlements=LocalEntitlementProvider({}))
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
