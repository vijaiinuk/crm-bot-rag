"""Generate the local RSA signing keypair: `make keys`."""

import argparse
import sys

from chatbot.adapters import local_jwt
from chatbot.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing key")
    args = parser.parse_args()

    keys_dir = Settings().keys_dir
    if (keys_dir / local_jwt.PRIVATE_KEY_FILE).exists() and not args.force:
        print(f"key already exists in {keys_dir} (use --force to rotate)", file=sys.stderr)
        return 0
    path = local_jwt.write_private_key(local_jwt.generate_private_key(), keys_dir)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
