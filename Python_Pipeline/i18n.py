"""Bilingual string table for the Streamlit dashboard.

Usage:
    from i18n import t
    t("hero_npv")          # returns the string in the active language
    t("fee_label", currency="CNY")   # format-string keys
"""

from __future__ import annotations
from typing import Any

_STRINGS: dict[str, dict[str, Any]] = {
    "en": {
        # ---- Page chrome ----
        "page_title":        "HPWinner LaaS Analyzer",
        "sidebar_title":     "💡 LaaS Deal Analyzer",
        "sidebar_caption":   "HPWinner EMO — Internal Tool",
        "lang_label":        "Language / 语言",

        # ---- Badges & verdicts ----
        "badge_high":        "🟢 High",
        "badge_medium":      "🟡 Medium",
        "badge_speculative": "🔴 Speculative",
        "verdict_go":        "✅ Go",
        "verdict_borderline":"⚠️ Borderline",
        "verdict_no_go":     "❌ No-Go",

        # ---- Sidebar: deal file ----
        "deal_file_header":    "📁 Deal File",
        "select_questionnaire":"Select questionnaire",
        "no_files_error":      "No *filled*.xlsx files found in data/",
        "deal_caption":        "Deal: **{deal_id}** · {n_lights:,} lights · {currency}",
        "load_error":          "Failed to load deal: {error}",

        # ---- Sidebar: product ----
        "product_header":  "🔆 Product",
        "select_product":  "Select product",
        "prod_road":       "AI Road Lamp (grid-powered)",
        "prod_battery":    "AI Battery Lamp (partial grid)",
        "prod_solar":      "AI Solar Lamp (off-grid)",

        # ---- Sidebar: service fee ----
        "fee_header":      "💰 Service Fee (Team Decision)",
        "fee_label":       "Annual fee per light ({currency}/light/yr)",
        "fee_help":        "Suggested floor: {suggested_fee:,.0f} {currency} "
                           "(CAPEX recovery + platform + 30% margin)",
        "fee_zero_warn":   "Service fee is 0 — set a fee using the sidebar slider. "
                           "Suggested starting point: {suggested_fee:,.0f} {currency}/light/yr.",

        # ---- Sidebar: contract & costs ----
        "contract_header":    "📋 Contract & Costs",
        "hardware_label":     "Hardware cost/light ({currency})",
        "installation_label": "Installation cost/light ({currency})",
        "contract_yrs_label": "Contract length (years)",

        # ---- Sidebar: savings sliders ----
        "savings_header": "📊 Savings Assumptions",
        "savings_names": {
            "adaptive_dimming":                   "Adaptive Dimming",
            "predictive_maintenance_inspections":  "Inspection Round Reduction",
            "predictive_maintenance_tickets":      "Fault Ticket Reduction",
            "failure_rate_reduction":              "Failure Rate Reduction",
            "solar_grid_offset":                   "Solar Grid Offset",
        },

        # ---- Sidebar: financial assumptions ----
        "fin_expander":        "⚙️ Financial Assumptions",
        "wacc_label":          "HPWinner WACC (%)",
        "escalator_label":     "Fee escalator (%/yr)",
        "contingency_label":   "Contingency on CAPEX (%)",
        "residual_label":      "Residual value (%)",

        # ---- Sidebar: MC runs ----
        "mc_runs_label": "Monte Carlo runs",
        "mc_runs_help":  "More runs = smoother histogram, slower refresh.",

        # ---- Hero strip ----
        "hero_title":          "Deal Analysis — {deal_id}",
        "hero_npv":            "NPV",
        "hero_irr":            "IRR",
        "hero_payback":        "Payback",
        "hero_cust_save":      "Customer saves Y1",
        "hero_verdict":        "Verdict",
        "payback_over":        "> contract",
        "data_warn_expander":  "⚠️ Data quality warnings",

        # ---- Tabs ----
        "tab_cashflow": "📈 Cashflow",
        "tab_cost":     "💼 Cost Stack",
        "tab_savings":  "🔍 Savings Attribution",
        "tab_risk":     "⚠️ Risk & Sensitivity",

        # ---- Cashflow tab table ----
        "cf_year":    "**Year**",
        "cf_fee":     "**Fee revenue**",
        "cf_net":     "**Net cashflow**",
        "cf_cum":     "**Cumulative**",

        # ---- Chart strings ----
        "chart_cf_title":    "HPWinner Cashflow",
        "chart_cf_x":        "Year",
        "chart_cf_net":      "Net cashflow",
        "chart_cf_cum":      "Cumulative",

        "chart_capex_title":  "CAPEX Breakdown — Total {total}",
        "chart_capex_labels": ["Hardware", "Installation", "Trenching", "Contingency"],

        "chart_tco_title":  "Total Cost of Ownership over {N} Years",
        "chart_tco_x":      ["Status Quo", "LED Replacement", "HPWinner LaaS"],
        "chart_tco_y":      "{currency} (total over contract)",

        "chart_wf_title":   "Annual Savings Attribution (Year 1)",
        "chart_wf_y":       "{currency}/year",
        "chart_wf_labels":  ["Wattage Reduction", "Adaptive Dimming",
                              "Inspection Reduction", "Ticket Reduction",
                              "Failure Rate Reduction", "Solar Grid Offset", "Total"],

        "chart_tornado_title": "Tornado Chart — NPV sensitivity (base: {base})",
        "chart_tornado_x":     "ΔNPV ({currency})",
        "chart_tornado_low":   "Low end",
        "chart_tornado_high":  "High end",

        "chart_mc_title": "NPV Distribution ({n:,} simulations)",
        "chart_mc_x":     "NPV ({currency})",
        "chart_mc_y":     "Count",

        # ---- Cost stack summary table ----
        "tbl_metric":         "Metric",
        "tbl_value":          "Value",
        "tbl_total_capex":    "Total CAPEX",
        "tbl_fee_y1":         "Annual service fee Y1",
        "tbl_cust_vs_sq":     "Customer saves vs status quo",
        "tbl_cust_vs_led":    "Customer saves vs LED replace",
        "tbl_savings_share":  "HPWinner implied savings share",

        # ---- Savings attribution table ----
        "tbl_mechanism":      "Mechanism",
        "tbl_annual_saving":  "Annual saving ({currency})",
        "tbl_pct":            "% of total",
        "row_wattage":        "Wattage reduction",
        "row_dimming":        "Adaptive dimming",
        "row_inspection":     "Inspection reduction",
        "row_ticket":         "Ticket reduction",
        "row_failure":        "Failure rate reduction",
        "row_solar":          "Solar grid offset",
        "row_total":          "**Total**",

        # ---- Risk tab ----
        "tornado_header":  "Tornado Chart — One-at-a-time sensitivity",
        "mc_header":       "Monte Carlo — NPV distribution under uncertainty",
        "mc_caption":      "NPV range: {npv_range}  |  P(NPV > 0): {prob:.0%}  |  Varied: {params}",
        "pb_caption":      "Payback range: {pb_range}  |  P(payback ≤ {yrs}yr): {prob:.0%}",
        "irr_caption":     "IRR range: {irr_range}",

        # ---- Spinners ----
        "spinner_model": "Running model…",
        "spinner_mc":    "Running Monte Carlo simulations…",
    },

    "zh": {
        # ---- Page chrome ----
        "page_title":        "惠普纳 LaaS 方案分析平台",
        "sidebar_title":     "💡 LaaS 方案分析",
        "sidebar_caption":   "惠普纳 EMO 内部工具",
        "lang_label":        "Language / 语言",

        # ---- Badges & verdicts ----
        "badge_high":        "🟢 高置信度",
        "badge_medium":      "🟡 中等置信度",
        "badge_speculative": "🔴 推测性",
        "verdict_go":        "✅ 可行",
        "verdict_borderline":"⚠️ 边缘可行",
        "verdict_no_go":     "❌ 不可行",

        # ---- Sidebar: deal file ----
        "deal_file_header":    "📁 项目文件",
        "select_questionnaire":"选择调查问卷",
        "no_files_error":      "在 data/ 目录中未找到 *filled*.xlsx 文件",
        "deal_caption":        "项目：**{deal_id}** · {n_lights:,} 盏灯 · {currency}",
        "load_error":          "加载项目失败：{error}",

        # ---- Sidebar: product ----
        "product_header":  "🔆 产品选择",
        "select_product":  "选择产品",
        "prod_road":       "AI 路灯（并网型）",
        "prod_battery":    "AI 储能灯（部分并网）",
        "prod_solar":      "AI 太阳能灯（离网型）",

        # ---- Sidebar: service fee ----
        "fee_header":      "💰 服务费（团队决策）",
        "fee_label":       "每灯年服务费（{currency}/灯/年）",
        "fee_help":        "建议下限：{suggested_fee:,.0f} {currency}"
                           "（资本回收 + 平台费 + 30% 利润空间）",
        "fee_zero_warn":   "服务费为 0 — 请通过左侧滑块设置服务费。"
                           "建议起始值：{suggested_fee:,.0f} {currency}/灯/年。",

        # ---- Sidebar: contract & costs ----
        "contract_header":    "📋 合同与成本",
        "hardware_label":     "每灯硬件成本（{currency}）",
        "installation_label": "每灯安装成本（{currency}）",
        "contract_yrs_label": "合同年限（年）",

        # ---- Sidebar: savings sliders ----
        "savings_header": "📊 节省假设",
        "savings_names": {
            "adaptive_dimming":                   "自适应调光",
            "predictive_maintenance_inspections":  "减少巡检次数",
            "predictive_maintenance_tickets":      "减少故障工单",
            "failure_rate_reduction":              "降低故障率",
            "solar_grid_offset":                   "太阳能电网补偿",
        },

        # ---- Sidebar: financial assumptions ----
        "fin_expander":        "⚙️ 财务假设",
        "wacc_label":          "惠普纳 WACC（%）",
        "escalator_label":     "服务费年增长率（%/年）",
        "contingency_label":   "资本支出备用金（%）",
        "residual_label":      "资产残值（%）",

        # ---- Sidebar: MC runs ----
        "mc_runs_label": "蒙特卡洛模拟次数",
        "mc_runs_help":  "次数越多，分布图越平滑，刷新越慢。",

        # ---- Hero strip ----
        "hero_title":          "方案分析 — {deal_id}",
        "hero_npv":            "净现值（NPV）",
        "hero_irr":            "内部收益率（IRR）",
        "hero_payback":        "投资回收期",
        "hero_cust_save":      "客户首年净节省",
        "hero_verdict":        "评估结论",
        "payback_over":        "> 合同期",
        "data_warn_expander":  "⚠️ 数据质量提示",

        # ---- Tabs ----
        "tab_cashflow": "📈 现金流",
        "tab_cost":     "💼 成本结构",
        "tab_savings":  "🔍 节省归因",
        "tab_risk":     "⚠️ 风险与敏感性",

        # ---- Cashflow tab table ----
        "cf_year": "**年份**",
        "cf_fee":  "**服务费收入**",
        "cf_net":  "**净现金流**",
        "cf_cum":  "**累计现金流**",

        # ---- Chart strings ----
        "chart_cf_title":    "惠普纳现金流",
        "chart_cf_x":        "年份",
        "chart_cf_net":      "净现金流",
        "chart_cf_cum":      "累计现金流",

        "chart_capex_title":  "资本支出明细 — 合计 {total}",
        "chart_capex_labels": ["硬件", "安装", "铺管", "备用金"],

        "chart_tco_title":  "{N} 年总拥有成本对比",
        "chart_tco_x":      ["维持现状", "LED 换装", "惠普纳 LaaS"],
        "chart_tco_y":      "{currency}（合同期合计）",

        "chart_wf_title":   "年度节省归因（第1年）",
        "chart_wf_y":       "{currency}/年",
        "chart_wf_labels":  ["功率降低", "自适应调光", "减少巡检",
                              "减少故障工单", "降低故障率", "太阳能电网补偿", "合计"],

        "chart_tornado_title": "龙卷风图 — 净现值敏感性分析（基准：{base}）",
        "chart_tornado_x":     "净现值变化量（{currency}）",
        "chart_tornado_low":   "低端",
        "chart_tornado_high":  "高端",

        "chart_mc_title": "净现值分布（{n:,} 次模拟）",
        "chart_mc_x":     "净现值（{currency}）",
        "chart_mc_y":     "频次",

        # ---- Cost stack summary table ----
        "tbl_metric":         "指标",
        "tbl_value":          "数值",
        "tbl_total_capex":    "总资本支出",
        "tbl_fee_y1":         "首年年服务费",
        "tbl_cust_vs_sq":     "客户相对维持现状的节省",
        "tbl_cust_vs_led":    "客户相对 LED 换装的节省",
        "tbl_savings_share":  "惠普纳隐含节省分成",

        # ---- Savings attribution table ----
        "tbl_mechanism":     "节省机制",
        "tbl_annual_saving": "年节省额（{currency}）",
        "tbl_pct":           "占比",
        "row_wattage":       "功率降低",
        "row_dimming":       "自适应调光",
        "row_inspection":    "减少巡检",
        "row_ticket":        "减少故障工单",
        "row_failure":       "降低故障率",
        "row_solar":         "太阳能电网补偿",
        "row_total":         "**合计**",

        # ---- Risk tab ----
        "tornado_header": "龙卷风图 — 单因素敏感性分析",
        "mc_header":      "蒙特卡洛模拟 — 净现值不确定性分布",
        "mc_caption":     "NPV 区间：{npv_range}  |  P(NPV > 0)：{prob:.0%}  |  变动参数：{params}",
        "pb_caption":     "回收期区间：{pb_range}  |  P(回收期 ≤ {yrs}年)：{prob:.0%}",
        "irr_caption":    "IRR 区间：{irr_range}",

        # ---- Spinners ----
        "spinner_model": "正在运行模型…",
        "spinner_mc":    "正在运行蒙特卡洛模拟…",
    },
}

# Active language — set by the app before calling t()
_lang = "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in _STRINGS else "en"


def t(key: str, **kwargs: Any) -> Any:
    """Look up a translation string and optionally format it."""
    val = _STRINGS[_lang].get(key) or _STRINGS["en"].get(key, key)
    if kwargs and isinstance(val, str):
        return val.format(**kwargs)
    return val
