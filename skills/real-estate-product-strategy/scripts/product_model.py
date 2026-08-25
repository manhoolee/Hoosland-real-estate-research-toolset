#!/usr/bin/env python3
"""Deterministic area, unit, revenue, and optional gross-profit calculator."""

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path


SCENARIOS = ("conservative", "base", "optimistic")
MODEL_VERSION = "2.3.0"
CLAIM_TYPES = {
    "FACT-A", "FACT-B", "FACT-C", "DERIVED", "INFERENCE", "HYPOTHESIS"
}


def _normalize_basis_record(record: object, field: str) -> dict:
    if not isinstance(record, dict) or record.get("type") not in CLAIM_TYPES:
        raise ValueError(f"input_basis.{field}.type is invalid")
    source_ids = record.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(value, str) or not value.strip() for value in source_ids)
    ):
        raise ValueError(
            f"input_basis.{field}.source_ids must be a non-empty string list"
        )
    normalized = {
        "type": record["type"],
        "source_ids": list(dict.fromkeys(value.strip() for value in source_ids)),
    }
    note = record.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError(f"input_basis.{field}.note must be a string")
        normalized["note"] = note.strip()
    return normalized


def _validate_audit(data: dict) -> dict:
    if data.get("model_version") != MODEL_VERSION:
        raise ValueError(f"model_version must be {MODEL_VERSION}")
    as_of_date = data.get("as_of_date")
    if not isinstance(as_of_date, str):
        raise ValueError("as_of_date is required in YYYY-MM-DD format")
    try:
        date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise ValueError("as_of_date must use YYYY-MM-DD format") from exc

    currency = data.get("currency")
    if currency != "CNY":
        raise ValueError("currency must be CNY because monetary outputs use yuan")

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments cannot be empty")
    segment_names: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"segments[{index}] must be an object")
        name = segment.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"segments[{index}].name must be a non-empty string")
        normalized_name = name.strip()
        if normalized_name in segment_names:
            raise ValueError(f"segment names must be unique: {normalized_name}")
        segment_names.append(normalized_name)

    basis = data.get("input_basis")
    if not isinstance(basis, dict):
        raise ValueError("input_basis is required for auditability")
    required = {"residential_gfa_sqm", "saleable_ratio", "segments"}
    if data.get("total_cost_yuan") is not None:
        required.add("total_cost_yuan")
    missing = sorted(required.difference(basis))
    if missing:
        raise ValueError(f"input_basis missing fields: {', '.join(missing)}")
    unexpected = sorted(set(basis).difference(required))
    if unexpected:
        raise ValueError(f"input_basis contains unknown fields: {', '.join(unexpected)}")

    normalized_basis: dict[str, object] = {
        "residential_gfa_sqm": _normalize_basis_record(
            basis["residential_gfa_sqm"], "residential_gfa_sqm"
        ),
        "saleable_ratio": _normalize_basis_record(
            basis["saleable_ratio"], "saleable_ratio"
        ),
    }
    if data.get("total_cost_yuan") is not None:
        normalized_basis["total_cost_yuan"] = _normalize_basis_record(
            basis["total_cost_yuan"], "total_cost_yuan"
        )

    segment_basis = basis["segments"]
    if not isinstance(segment_basis, dict):
        raise ValueError("input_basis.segments must map each segment name to its field evidence")
    missing_segments = sorted(set(segment_names).difference(segment_basis))
    extra_segments = sorted(set(segment_basis).difference(segment_names))
    if missing_segments or extra_segments:
        details = []
        if missing_segments:
            details.append("missing " + ", ".join(missing_segments))
        if extra_segments:
            details.append("unknown " + ", ".join(extra_segments))
        raise ValueError("input_basis.segments does not match segments: " + "; ".join(details))

    normalized_segments: dict[str, dict] = {}
    for name in segment_names:
        record = segment_basis[name]
        if not isinstance(record, dict):
            raise ValueError(f"input_basis.segments.{name} must be an object")
        required_fields = {"share", "avg_unit_gfa", "prices"}
        missing_fields = sorted(required_fields.difference(record))
        extra_fields = sorted(set(record).difference(required_fields))
        if missing_fields or extra_fields:
            raise ValueError(
                f"input_basis.segments.{name} must contain only share, avg_unit_gfa, and prices"
            )
        price_basis = record["prices"]
        if not isinstance(price_basis, dict) or set(price_basis) != set(SCENARIOS):
            raise ValueError(
                f"input_basis.segments.{name}.prices must cover {', '.join(SCENARIOS)}"
            )
        normalized_segments[name] = {
            "share": _normalize_basis_record(
                record["share"], f"segments.{name}.share"
            ),
            "avg_unit_gfa": _normalize_basis_record(
                record["avg_unit_gfa"], f"segments.{name}.avg_unit_gfa"
            ),
            "prices": {
                scenario: _normalize_basis_record(
                    price_basis[scenario], f"segments.{name}.prices.{scenario}"
                )
                for scenario in SCENARIOS
            },
        }
    normalized_basis["segments"] = normalized_segments

    recalculation_conditions = data.get("recalculation_conditions")
    if (
        not isinstance(recalculation_conditions, list)
        or not recalculation_conditions
        or any(
            not isinstance(condition, str) or not condition.strip()
            for condition in recalculation_conditions
        )
    ):
        raise ValueError("recalculation_conditions must be a non-empty string list")
    normalized_recalculation_conditions = list(
        dict.fromkeys(condition.strip() for condition in recalculation_conditions)
    )

    formulae = {
        "saleable_area_sqm": "residential_gfa_sqm * saleable_ratio",
        "segment_area_sqm": "saleable_area_sqm * segment_share",
        "approx_units": "round(segment_area_sqm / avg_unit_gfa_sqm)",
        "revenue_yuan": "segment_area_sqm * scenario_price_yuan_per_sqm",
        "weighted_price_yuan_per_sqm": "scenario_revenue_yuan / saleable_area_sqm",
    }
    if data.get("total_cost_yuan") is not None:
        formulae.update(
            {
                "gross_profit_yuan": "scenario_revenue_yuan - total_cost_yuan",
                "gross_margin": "gross_profit_yuan / scenario_revenue_yuan",
            }
        )

    canonical = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "as_of_date": as_of_date,
        "currency": currency,
        "input_sha256": hashlib.sha256(canonical).hexdigest(),
        "input_basis": normalized_basis,
        "recalculation_conditions": normalized_recalculation_conditions,
        "units": {
            "area": "sqm",
            "price": "CNY/sqm",
            "revenue_and_cost": "CNY",
            "share_and_margin": "ratio",
        },
        "rounding": {
            "approx_units": "nearest integer; ties to even",
            "other_numeric_outputs": "not rounded by the model",
        },
        "formulae": formulae,
    }


def calculate(data: dict) -> dict:
    audit = _validate_audit(data)
    gfa = float(data["residential_gfa_sqm"])
    ratio = float(data["saleable_ratio"])
    if gfa <= 0 or not 0 < ratio <= 1:
        raise ValueError("residential_gfa_sqm must be positive and saleable_ratio in (0, 1]")
    segments = data.get("segments", [])
    if not segments:
        raise ValueError("segments cannot be empty")
    share_total = sum(float(item["share"]) for item in segments)
    if abs(share_total - 1.0) > 1e-6:
        raise ValueError(f"segment shares must total 1.0, got {share_total}")

    saleable = gfa * ratio
    rows = []
    revenues = {scenario: 0.0 for scenario in SCENARIOS}
    for item in segments:
        share = float(item["share"])
        avg_unit = float(item["avg_unit_gfa"])
        if share < 0 or avg_unit <= 0:
            raise ValueError("shares must be non-negative and avg_unit_gfa positive")
        area = saleable * share
        prices = {scenario: float(item["prices"][scenario]) for scenario in SCENARIOS}
        revenue = {scenario: area * prices[scenario] for scenario in SCENARIOS}
        for scenario in SCENARIOS:
            revenues[scenario] += revenue[scenario]
        rows.append({
            "name": item["name"],
            "share": share,
            "saleable_area_sqm": area,
            "avg_unit_gfa_sqm": avg_unit,
            "approx_units": round(area / avg_unit),
            "prices_yuan_per_sqm": prices,
            "revenue_yuan": revenue,
        })

    weighted_prices = {scenario: revenues[scenario] / saleable for scenario in SCENARIOS}
    result = {
        "model_version": MODEL_VERSION,
        "project": data.get("project", ""),
        "scope_id": data["scope_id"],
        "audit": audit,
        "residential_gfa_sqm": gfa,
        "saleable_ratio": ratio,
        "saleable_area_sqm": saleable,
        "segments": rows,
        "weighted_price_yuan_per_sqm": weighted_prices,
        "revenue_yuan": revenues,
        "evidence_note": "Arithmetic output only; assumptions require market and financial validation.",
    }
    if data.get("total_cost_yuan") is not None:
        cost = float(data["total_cost_yuan"])
        result["total_cost_yuan"] = cost
        result["gross_profit_yuan"] = {s: revenues[s] - cost for s in SCENARIOS}
        result["gross_margin"] = {
            s: (revenues[s] - cost) / revenues[s] if revenues[s] else None for s in SCENARIOS
        }
    return result


def write_csv(result: dict, destination: Path) -> None:
    fields = [
        "name", "share", "saleable_area_sqm", "avg_unit_gfa_sqm", "approx_units",
        "price_conservative", "price_base", "price_optimistic",
        "revenue_conservative", "revenue_base", "revenue_optimistic",
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["segments"]:
            writer.writerow({
                "name": row["name"], "share": row["share"],
                "saleable_area_sqm": row["saleable_area_sqm"],
                "avg_unit_gfa_sqm": row["avg_unit_gfa_sqm"],
                "approx_units": row["approx_units"],
                **{f"price_{s}": row["prices_yuan_per_sqm"][s] for s in SCENARIOS},
                **{f"revenue_{s}": row["revenue_yuan"][s] for s in SCENARIOS},
            })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    parser.add_argument("--out-json")
    parser.add_argument("--out-csv")
    args = parser.parse_args()
    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    try:
        result = calculate(data)
    except (KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out_json:
        Path(args.out_json).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.out_csv:
        write_csv(result, Path(args.out_csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
