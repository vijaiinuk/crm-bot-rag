"""Mint a local JWT: `make token PERSONA=sales_rep@globex` or `make token ADMIN=editor@ops`.

Prints only the token, so it can be captured: TOKEN=$(make -s token PERSONA=...)
"""

import argparse
import sys

from chatbot.adapters import local_jwt
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.dev import load_admins
from chatbot.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--persona", help="role@client, e.g. sales_rep@globex")
    who.add_argument("--admin", help="admin from data/admins.yaml, e.g. editor@ops")
    parser.add_argument("--sub", help="user id (default: derived from persona)")
    parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds")
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="mint for a persona not in personas.yaml (to exercise the 403 path)",
    )
    args = parser.parse_args()

    settings = Settings()
    try:
        key = local_jwt.load_private_key(settings.keys_dir)
    except FileNotFoundError:
        print(f"no signing key in {settings.keys_dir}; run `make keys`", file=sys.stderr)
        return 1

    if args.admin:
        admins = load_admins(settings.admins_path)
        if args.admin not in admins:
            parser.error(f"unknown admin {args.admin!r}; known: {sorted(admins)}")
        print(
            local_jwt.mint_token(
                key,
                sub=f"admin-{args.admin.partition('@')[0]}",
                tenant=settings.admin_tenant,
                role="ops_admin",
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                ttl_s=args.ttl,
                extra_claims={"admin_role": admins[args.admin]},
            )
        )
        return 0

    role, sep, tenant = args.persona.partition("@")
    if not sep or not role or not tenant:
        parser.error("persona must be role@client")

    if not args.allow_unknown:
        known = LocalEntitlementProvider.from_file(settings.personas_path)
        if args.persona not in known.persona_ids:
            parser.error(f"unknown persona {args.persona!r}; known: {sorted(known.persona_ids)}")

    print(
        local_jwt.mint_token(
            key,
            sub=args.sub or f"user-{role}-{tenant}",
            tenant=tenant,
            role=role,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            ttl_s=args.ttl,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
