from __future__ import annotations

import argparse
import secrets
import string
from pathlib import Path

from backend.app.db import init_db
from backend.app.services import create_entry, create_user


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Calorie Counter secrets and optional demo users.",
    )
    parser.add_argument(
        "--admin-code",
        default="",
        help="Use this admin code. If omitted, a secure code is generated.",
    )
    parser.add_argument(
        "--code-pepper",
        default="",
        help="Use this code pepper. If omitted, a secure value is generated.",
    )
    parser.add_argument(
        "--user",
        action="append",
        default=[],
        help="Create a user profile. Repeat flag for multiple users.",
    )
    parser.add_argument(
        "--with-sample-meal",
        action="store_true",
        help="Create one sample meal for each bootstrap user.",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional path to write generated ADMIN_CODE/CODE_PEPPER (append-safe).",
    )

    args = parser.parse_args()

    init_db()

    admin_code = args.admin_code.strip() or _generate_secret_code(prefix="ADMIN")
    code_pepper = args.code_pepper.strip() or secrets.token_urlsafe(32)

    print("Bootstrap complete.")
    print("Set these environment variables:")
    print(f"ADMIN_CODE={admin_code}")
    print(f"CODE_PEPPER={code_pepper}")

    if args.env_file:
        _write_env_file(Path(args.env_file), admin_code, code_pepper)
        print(f"Updated env file: {args.env_file}")

    if args.user:
        print("\nCreated users (codes shown once):")
        for raw_name in args.user:
            user = create_user(raw_name)
            print(f"- {user['name']}: {user['code']}")

            if args.with_sample_meal:
                create_entry(
                    user_id=user["id"],
                    source="manual",
                    dish="Sample Salad",
                    calories_kcal=280,
                    protein_g=12,
                    fiber_g=7,
                    nutrients=["vitamin C", "folate", "potassium"],
                    chemicals=["chlorophyll"],
                    notes="Bootstrap sample meal",
                )


def _generate_secret_code(prefix: str) -> str:
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(18))
    return f"{prefix}-{random_part}"


def _write_env_file(path: Path, admin_code: str, code_pepper: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    lines = [line for line in existing.splitlines() if line.strip()]
    key_to_value = {
        "ADMIN_CODE": admin_code,
        "CODE_PEPPER": code_pepper,
    }
    seen: set[str] = set()
    rewritten: list[str] = []

    for line in lines:
        if "=" not in line:
            rewritten.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in key_to_value:
            rewritten.append(f"{key}={key_to_value[key]}")
            seen.add(key)
        else:
            rewritten.append(line)

    for key, value in key_to_value.items():
        if key not in seen:
            rewritten.append(f"{key}={value}")

    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
