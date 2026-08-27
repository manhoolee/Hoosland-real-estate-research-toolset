#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
EXPECTED_SKILLS="comprehensive-real-estate-expert real-estate-research real-estate-product-strategy real-estate-storyline-marketing real-estate-community-operations wechat-article-exporter real-estate-report-editorial real-estate-report-design real-estate-delivery-qa real-estate-social-promotion hoosland-pdf-output"

$PYTHON -m py_compile "$ROOT"/*/scripts/*.py
for skill in $EXPECTED_SKILLS; do
  test -s "$ROOT/$skill/SKILL.md"
  grep -Fq "## 专业角色与职责" "$ROOT/$skill/SKILL.md"
done
$PYTHON -c 'import json,sys; data=json.load(sys.stdin); expected=sys.argv[1:]; assert data["version"] == "2.3.0"; assert data["skills"] == expected' $EXPECTED_SKILLS < "$ROOT/manifest.json"

ROUTER="$ROOT/comprehensive-real-estate-expert/SKILL.md"
for skill in real-estate-research real-estate-product-strategy real-estate-storyline-marketing real-estate-community-operations wechat-article-exporter real-estate-report-editorial real-estate-report-design real-estate-delivery-qa real-estate-social-promotion hoosland-pdf-output; do
  grep -Fq "\`$skill\`" "$ROUTER"
done
grep -Fq 'Harness 内置 `skill` tool' "$ROUTER"
grep -Fq '**业务专项 → `real-estate-report-editorial` → `real-estate-report-design` → 按需 `hoosland-pdf-output` → `real-estate-delivery-qa`**' "$ROUTER"
grep -Fq '每轮首个 Skill 确定性激活' "$ROUTER"
grep -Fq '不得通过 Harness 内置 `skill` tool 再次调用 `comprehensive-real-estate-expert` 自身' "$ROUTER"
grep -Fq 'Markdown 与独立 HTML 两个成品' "$ROUTER"
for child in real-estate-report-editorial real-estate-report-design hoosland-pdf-output real-estate-social-promotion wechat-article-exporter; do
  grep -Fq '不直接调用任何 Skill' "$ROOT/$child/SKILL.md"
done

if $PYTHON "$ROOT/real-estate-research/scripts/scope_check.py" "$ROOT/tests/fixtures/machang-scope-invalid.json" >/dev/null 2>&1; then
  echo "expected invalid scope fixture to fail" >&2
  exit 1
fi
$PYTHON "$ROOT/real-estate-research/scripts/scope_check.py" "$ROOT/tests/fixtures/machang-scope-valid.json" >/dev/null

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
$PYTHON "$ROOT/comprehensive-real-estate-expert/scripts/init_case.py" "$TMP_DIR/case" --project "Smoke Test" --scope-id "smoke-phase-1" >/dev/null
$PYTHON "$ROOT/comprehensive-real-estate-expert/scripts/validate_case.py" "$TMP_DIR/case" >/dev/null
$PYTHON "$ROOT/real-estate-product-strategy/scripts/product_model.py" "$ROOT/tests/fixtures/machang-product-hypothesis.json" --out-json "$TMP_DIR/model.json" --out-csv "$TMP_DIR/model.csv"
$PYTHON -c 'import json,sys; data=json.load(sys.stdin); audit=data["audit"]; assert data["model_version"] == "2.3.0"; assert audit["as_of_date"]; assert len(audit["input_sha256"]) == 64; assert audit["input_basis"]; assert audit["recalculation_conditions"]; assert audit["units"]; assert audit["rounding"]; assert audit["formulae"]; basis=audit["input_basis"]["segments"]; assert set(basis)=={row["name"] for row in data["segments"]}; assert all(set(row)=={"share","avg_unit_gfa","prices"} and set(row["prices"])=={"conservative","base","optimistic"} for row in basis.values())' < "$TMP_DIR/model.json"
$PYTHON -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); data["total_cost_yuan"]=1000000000; data["input_basis"]["total_cost_yuan"]={"type":"HYPOTHESIS","source_ids":["SMOKE-COST-001"]}; json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)' "$ROOT/tests/fixtures/machang-product-hypothesis.json" "$TMP_DIR/model-cost-input.json"
$PYTHON "$ROOT/real-estate-product-strategy/scripts/product_model.py" "$TMP_DIR/model-cost-input.json" --out-json "$TMP_DIR/model-cost.json"
$PYTHON -c 'import json,sys; data=json.load(sys.stdin); assert "gross_profit_yuan" in data; assert "gross_margin" in data; assert data["audit"]["formulae"]["gross_profit_yuan"]; assert data["audit"]["formulae"]["gross_margin"]' < "$TMP_DIR/model-cost.json"
printf '# Test\n\n## Table\n\n| A | B |\n|---|---|\n| 1 | FACT-A |\n' > "$TMP_DIR/test.md"
$PYTHON "$ROOT/comprehensive-real-estate-expert/scripts/render_report.py" "$TMP_DIR/test.md" "$TMP_DIR/test.html" >/dev/null
test -s "$TMP_DIR/test.html"
grep -Fq 'REAL ESTATE STRATEGY · v2.3' "$TMP_DIR/test.html"

(
  cd "$TMP_DIR"
  $PYTHON -c 'import importlib.util,pathlib,sys; spec=importlib.util.spec_from_file_location("fetch_article", sys.argv[1]); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); article={"title":"Smoke","format":"markdown","article_id":"smoke","content":"# Smoke"}; saved=pathlib.Path(mod.save_article(article)).resolve(); saved.relative_to(pathlib.Path.cwd().resolve()); outside=pathlib.Path.cwd().resolve().parent / "outside"; ok=False
try:
 mod.save_article(article, str(outside))
except ValueError:
 ok=True
assert ok' "$ROOT/wechat-article-exporter/scripts/fetch_article.py"
)
$PYTHON "$ROOT/tests/smoke_wechat.py"
echo "v2.3 smoke tests passed"
