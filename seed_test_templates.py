#!/usr/bin/env python
"""
Create sample test templates (configs + questions) on the platform API.

Requires a moderator, admin, or super_admin account.

Examples (PowerShell):

  $env:PLATFORM_API_URL = "http://127.0.0.1:8000"
  $env:SEED_ADMIN_USERNAME = "your_admin"
  $env:SEED_ADMIN_PASSWORD = "your_password"
  python seed_test_templates.py

  python seed_test_templates.py --api-url http://127.0.0.1:8000 -u admin -p admin123 --count 10

Options:
  --count                Number of distinct tests (default 10)
  --questions-per-test   Questions added per test when empty (default 4)
  --topic-prefix         Topic name prefix (default "Template Pack")
  --dry-run              Print actions only
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests


def api_post(
    session: requests.Session,
    base_url: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    data_form: dict[str, str] | None = None,
    token: str | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base_url.rstrip('/')}{path}"
    response = session.post(url, headers=headers, json=json_body, data=data_form, timeout=timeout)
    if not response.ok:
        detail = f"{response.status_code} error"
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            if response.text:
                detail = response.text
        raise RuntimeError(detail)
    if response.text:
        return response.json()
    return {}


def api_get(
    session: requests.Session,
    base_url: str,
    path: str,
    *,
    token: str,
    timeout: int = 45,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    if not response.ok:
        detail = f"{response.status_code} error"
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            if response.text:
                detail = response.text
        raise RuntimeError(detail)
    if response.text:
        return response.json()
    return {}


def login(session: requests.Session, base_url: str, username: str, password: str) -> str:
    data = api_post(
        session,
        base_url,
        "/auth/login",
        data_form={"username": username.strip(), "password": password},
        token=None,
    )
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Login response missing access_token.")
    return str(token)


def create_or_update_config(
    session: requests.Session,
    base_url: str,
    token: str,
    topic_name: str,
    level_name: str,
    *,
    duration_seconds: int = 900,
    passing_percent: float = 70.0,
    is_active: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = {
        "topic_name": topic_name,
        "level_name": level_name,
        "duration_seconds": duration_seconds,
        "passing_percent": passing_percent,
        "is_active": is_active,
    }
    if dry_run:
        return {"id": 0, "question_count": 0, **payload}
    return api_post(session, base_url, "/admin/test-configs", json_body=payload, token=token)


def add_question(
    session: requests.Session,
    base_url: str,
    token: str,
    test_config_id: int,
    question_text: str,
    options: list[str],
    correct_indices: list[int],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    body = {
        "test_config_id": test_config_id,
        "question_text": question_text,
        "options": options,
        "correct_indices": correct_indices,
    }
    if dry_run:
        return body
    return api_post(session, base_url, "/admin/questions", json_body=body, token=token)


def build_question_templates(test_index: int, q_index: int) -> tuple[str, list[str], list[int]]:
    """Return (question_text, options, correct_indices) with unique option strings."""
    base = f"T{test_index:02d}-Q{q_index + 1}"
    text = (
        f"Sample question {q_index + 1} for template test {test_index}. "
        f"Select the answer labeled [{base}-CORRECT]."
    )
    options = [
        f"{base}-CORRECT (select this)",
        f"{base}-wrong-A",
        f"{base}-wrong-B",
        f"{base}-wrong-C",
    ]
    return text, options, [0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed platform test templates (admin API).")
    parser.add_argument(
        "--api-url",
        default=os.getenv("PLATFORM_API_URL", "https://tester-pykb.onrender.com").rstrip("/"),
        help="platform_api base URL",
    )
    parser.add_argument("-u", "--username", default=os.getenv("SEED_ADMIN_USERNAME", ""), help="admin username or email")
    parser.add_argument("-p", "--password", default=os.getenv("SEED_ADMIN_PASSWORD", ""), help="admin password")
    parser.add_argument("--count", type=int, default=10, help="number of tests to create (default 10)")
    parser.add_argument("--questions-per-test", type=int, default=4, help="questions per empty test (default 4)")
    parser.add_argument("--topic-prefix", default="Template Pack", help='topic name (default "Template Pack")')
    parser.add_argument("--duration-minutes", type=int, default=15, help="timer per test in minutes (default 15)")
    parser.add_argument("--passing-percent", type=float, default=70.0, help="pass threshold (default 70)")
    parser.add_argument("--dry-run", action="store_true", help="print planned actions only")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("Error: provide --username and --password (or SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD).", file=sys.stderr)
        return 1

    if args.count < 1:
        print("Error: --count must be at least 1.", file=sys.stderr)
        return 1

    if args.questions_per_test < 1:
        print("Error: --questions-per-test must be at least 1.", file=sys.stderr)
        return 1

    session = requests.Session()
    duration_seconds = max(30, min(14_400, args.duration_minutes * 60))

    if not args.dry_run:
        try:
            token = login(session, args.api_url, args.username, args.password)
        except Exception as error:
            print(f"Login failed: {error}", file=sys.stderr)
            return 1
        try:
            me = api_get(session, args.api_url, "/auth/me", token=token)
        except Exception as error:
            print(f"Could not read /auth/me: {error}", file=sys.stderr)
            return 1
        role = me.get("role", "")
        if role not in {"moderator", "admin", "super_admin"}:
            print(f"User {me.get('username')} has role {role!r}; moderator, admin, or super_admin required.", file=sys.stderr)
            return 1
    else:
        token = ""

    created_configs = 0
    skipped_configs = 0
    created_questions = 0

    for i in range(1, args.count + 1):
        level_name = f"Assessment {i:02d}"
        topic_name = args.topic_prefix.strip()
        print(f"\n=== {topic_name} / {level_name} ===")

        try:
            cfg = create_or_update_config(
                session,
                args.api_url,
                token,
                topic_name,
                level_name,
                duration_seconds=duration_seconds,
                passing_percent=args.passing_percent,
                is_active=True,
                dry_run=args.dry_run,
            )
        except Exception as error:
            print(f"  Config error: {error}", file=sys.stderr)
            return 1

        test_id = int(cfg.get("id", 0))
        existing_q = int(cfg.get("question_count", 0))

        if args.dry_run:
            print(f"  [dry-run] would ensure config id={test_id or '?'}; existing questions={existing_q}")
            created_configs += 1
            created_questions += args.questions_per_test
            continue

        if existing_q > 0:
            print(f"  Config id={test_id} already has {existing_q} question(s); skipping questions.")
            skipped_configs += 1
            continue

        created_configs += 1
        for q in range(args.questions_per_test):
            text, options, correct = build_question_templates(i, q)
            try:
                add_question(session, args.api_url, token, test_id, text, options, correct, dry_run=False)
                created_questions += 1
                print(f"  Added question {q + 1}/{args.questions_per_test}")
            except Exception as error:
                print(f"  Question error: {error}", file=sys.stderr)
                return 1

    print(
        f"\nDone. configs_seeded_with_questions={created_configs}, "
        f"configs_skipped_already_had_questions={skipped_configs}, questions_added={created_questions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
