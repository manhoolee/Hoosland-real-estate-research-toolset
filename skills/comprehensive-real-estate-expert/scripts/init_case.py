#!/usr/bin/env python3
"""Create a minimal v2.1 real-estate project evidence workspace."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path


SOURCE_FIELDS = [
    "source_id", "title", "grade", "publisher", "published_date",
    "retrieved_date", "scope_id", "url_or_path", "status", "notes",
]
CLAIM_FIELDS = [
    "claim_id", "claim_text", "claim_type", "scope_id", "source_ids",
    "as_of_date", "confidence", "status", "contradiction", "notes",
]


def write_csv(path: Path, fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writeheader()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", help="Explicit new or empty project directory")
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--stage", default="定位")
    parser.add_argument("--objective", action="append", default=[])
    parser.add_argument("--mode", choices=["rapid", "standard", "audit"], default="standard")
    args = parser.parse_args()

    root = Path(args.destination).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        parser.error(f"destination is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "calculations").mkdir()
    (root / "outputs").mkdir()
    (root / "sources").mkdir()

    state = {
        "version": "2.1.0",
        "project_name": args.project,
        "scope_id": args.scope_id,
        "stage": args.stage,
        "business_objective": args.objective,
        "as_of_date": date.today().isoformat(),
        "research_mode": args.mode,
        "status": "exploring",
        "confirmed_facts": [],
        "assumptions": [],
        "open_questions": [],
        "decisions": [],
        "next_actions": [],
    }
    (root / "project_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(root / "sources.csv", SOURCE_FIELDS)
    write_csv(root / "claims.csv", CLAIM_FIELDS)
    (root / "assumptions.md").write_text(
        "# 假设与敏感性\n\n| ID | 假设 | 基准值 | 区间 | 单位 | 理由/来源 | 状态 |\n"
        "|---|---|---:|---:|---|---|---|\n",
        encoding="utf-8",
    )
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
