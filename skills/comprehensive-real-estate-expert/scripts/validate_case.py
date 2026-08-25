#!/usr/bin/env python3
"""Validate v2.1 project state, source ledger, and claim ledger."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path


REQUIRED_STATE = {"version", "project_name", "scope_id", "stage", "as_of_date", "research_mode", "status"}
SOURCE_REQUIRED = {"source_id", "title", "grade", "retrieved_date", "scope_id", "url_or_path", "status"}
CLAIM_REQUIRED = {"claim_id", "claim_text", "claim_type", "scope_id", "source_ids", "confidence", "status"}
CLAIM_TYPES = {"FACT", "DERIVED", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir")
    args = parser.parse_args()
    root = Path(args.case_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    for name in ["project_state.json", "sources.csv", "claims.csv", "assumptions.md"]:
        if not (root / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        print("INVALID")
        print("\n".join(f"ERROR: {item}" for item in errors))
        return 1

    try:
        state = json.loads((root / "project_state.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"project_state.json unreadable: {exc}")
        state = {}
    missing = REQUIRED_STATE - set(state)
    if missing:
        errors.append(f"project_state missing fields: {', '.join(sorted(missing))}")
    if state.get("version") != "2.1.0":
        warnings.append("project_state version is not 2.1.0")
    try:
        date.fromisoformat(str(state.get("as_of_date", "")))
    except ValueError:
        errors.append("as_of_date must be YYYY-MM-DD")

    source_fields, sources = read_rows(root / "sources.csv")
    claim_fields, claims = read_rows(root / "claims.csv")
    if SOURCE_REQUIRED - set(source_fields):
        errors.append("sources.csv missing required columns")
    if CLAIM_REQUIRED - set(claim_fields):
        errors.append("claims.csv missing required columns")

    source_ids: set[str] = set()
    for index, row in enumerate(sources, 2):
        sid = row.get("source_id", "").strip()
        if not sid:
            errors.append(f"sources.csv:{index} missing source_id")
        elif sid in source_ids:
            errors.append(f"sources.csv:{index} duplicate source_id {sid}")
        source_ids.add(sid)
        if row.get("grade") not in {"A", "B", "C", "D"}:
            errors.append(f"sources.csv:{index} grade must be A/B/C/D")
        if not row.get("scope_id", "").strip():
            errors.append(f"sources.csv:{index} missing scope_id")

    claim_ids: set[str] = set()
    for index, row in enumerate(claims, 2):
        cid = row.get("claim_id", "").strip()
        if not cid or cid in claim_ids:
            errors.append(f"claims.csv:{index} missing or duplicate claim_id")
        claim_ids.add(cid)
        if row.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"claims.csv:{index} invalid claim_type")
        if not row.get("scope_id", "").strip():
            errors.append(f"claims.csv:{index} missing scope_id")
        refs = {item.strip() for item in row.get("source_ids", "").split(";") if item.strip()}
        unknown = refs - source_ids
        if unknown:
            errors.append(f"claims.csv:{index} unknown source_ids: {', '.join(sorted(unknown))}")
        if row.get("claim_type") == "FACT" and not refs:
            errors.append(f"claims.csv:{index} FACT requires a source")
        if row.get("status") == "disputed" and not row.get("contradiction", "").strip():
            warnings.append(f"claims.csv:{index} disputed claim lacks contradiction note")

    if not sources:
        warnings.append("source ledger has no records")
    if not claims:
        warnings.append("claim ledger has no records")

    print("VALID" if not errors else "INVALID")
    for item in errors:
        print(f"ERROR: {item}")
    for item in warnings:
        print(f"WARNING: {item}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
