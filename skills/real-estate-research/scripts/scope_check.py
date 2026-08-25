#!/usr/bin/env python3
"""Check parent/component scope consistency and additive totals."""

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    args = parser.parse_args()
    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    parent = data["parent"]
    parent_scope = str(parent["scope_id"])
    parent_value = float(parent["value"])
    tolerance = float(data.get("tolerance", 0.01))
    total = 0.0
    errors: list[str] = []

    for metric in data.get("metrics", []):
        if metric.get("relation", "component") != "component":
            continue
        if str(metric.get("parent_scope_id", "")) != parent_scope:
            errors.append(
                f"{metric.get('name', 'unnamed')}: parent_scope_id "
                f"{metric.get('parent_scope_id')} != {parent_scope}"
            )
        total += float(metric["value"])

    delta = total - parent_value
    if delta > tolerance:
        errors.append(f"component sum {total:g} exceeds parent {parent_value:g} by {delta:g}")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "parent_scope_id": parent_scope,
        "parent_value": parent_value,
        "component_sum": total,
        "remaining": parent_value - total,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
