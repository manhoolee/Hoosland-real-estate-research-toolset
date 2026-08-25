# product_model.py 输入结构

```json
{
  "model_version": "2.3.0",
  "project": "示例项目",
  "scope_id": "phase-1-residential",
  "as_of_date": "2026-08-25",
  "currency": "CNY",
  "residential_gfa_sqm": 222740,
  "saleable_ratio": 0.92,
  "segments": [
    {
      "name": "改善",
      "share": 0.6,
      "avg_unit_gfa": 140,
      "prices": {"conservative": 110000, "base": 120000, "optimistic": 130000}
    }
  ],
  "total_cost_yuan": null,
  "recalculation_conditions": [
    "住宅计容面积或可售率发生变化",
    "任一产品段的面积占比、平均户型面积或情景价格更新",
    "取得新的成本口径或研究截至日期变化"
  ],
  "input_basis": {
    "residential_gfa_sqm": {
      "type": "FACT-A",
      "source_ids": ["SRC-LAND-001"]
    },
    "saleable_ratio": {
      "type": "HYPOTHESIS",
      "source_ids": ["HYP-SALEABLE-001"],
      "note": "待工程与经营复核"
    },
    "segments": {
      "改善": {
        "share": {
          "type": "HYPOTHESIS",
          "source_ids": ["SRC-COMP-001", "HYP-MIX-001"]
        },
        "avg_unit_gfa": {
          "type": "HYPOTHESIS",
          "source_ids": ["SRC-COMP-001", "HYP-AREA-001"]
        },
        "prices": {
          "conservative": {
            "type": "HYPOTHESIS",
            "source_ids": ["SRC-COMP-PRICE-001", "HYP-PRICE-LOW-001"]
          },
          "base": {
            "type": "HYPOTHESIS",
            "source_ids": ["SRC-COMP-PRICE-001", "HYP-PRICE-BASE-001"]
          },
          "optimistic": {
            "type": "HYPOTHESIS",
            "source_ids": ["SRC-COMP-PRICE-001", "HYP-PRICE-HIGH-001"]
          }
        }
      }
    }
  }
}
```

规则：`model_version` 为输入契约声明，当前必须使用 `2.3.0`；`as_of_date` 使用 `YYYY-MM-DD`；`currency` 固定为 `CNY`；`share` 合计为 1；面积为平方米；价格为元/平方米；成本为总额人民币元。

`input_basis` 必须覆盖 `residential_gfa_sqm`、`saleable_ratio` 和每个产品段；每个产品段必须逐项覆盖 `share`、`avg_unit_gfa` 以及 conservative/base/optimistic 三个价格输入，不能用一个总括性 `segments` 记录替代逐项证据。提供成本时还必须覆盖 `total_cost_yuan`。每项记录 `type`、非空 `source_ids` 和可选 `note`，其中 `type` 使用 `FACT-A/B/C`、`DERIVED`、`INFERENCE` 或 `HYPOTHESIS`。假设也应使用稳定的假设 ID，不以空来源规避审计。

`recalculation_conditions` 必须列出触发重算的非空条件。输出的 `model_version`、`audit.as_of_date`、`audit.input_sha256`、逐项输入依据、重算条件、单位、公式和舍入规则用于复算与版本追踪；提供成本时公式清单必须同时记录毛利与毛利率。约套数使用最接近整数、正好位于中点时取偶数的规则；其余数值不由脚本自动舍入。脚本输出不代表市场预测、销售承诺或财务事实。
