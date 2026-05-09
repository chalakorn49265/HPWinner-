"""Survey routing (J/H/I/K) and B/C validation helpers.

Aligned with agent-skills/questionnaire-to-client-dashboard/survey-routing.md
and workflow-checklist.md. Parsing is defensive for mixed Chinese + numeric text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RouteStory(str, Enum):
    GENERIC = "generic"
    EMC_INCUMBENT = "emc_incumbent"
    LAAS_STYLE = "laas_style"
    EMC_AND_LAAS = "emc_and_laas"


@dataclass(frozen=True)
class RouteResult:
    story: RouteStory
    emc_incumbent: bool
    laas_emphasis: bool
    summary: str


def load_answers(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parent.parent
    path = root / "data" / "chongqing_answers.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run: python3 read_questionnaire_input.py "
            f"--input questionnaire_01_filled_chongqing_sales_rep.xlsx "
            f"--sheet both --answers-only --compact > data/chongqing_answers.json"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


def extract_numbers(text: Any) -> list[float]:
    """Pull decimal/comma integers from free-form survey text."""
    s = _norm(text)
    if not s:
        return []
    # Normalize Chinese comma and full-width digits optionally later
    s = s.replace(",", "")
    # Match integers and decimals (e.g. 2450000, 0.82, 3.5)
    parts = re.findall(r"\d+(?:\.\d+)?", s)
    out: list[float] = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            continue
    return out


def first_money_like(text: Any) -> float | None:
    nums = extract_numbers(text)
    if not nums:
        return None
    # Prefer first plausible annual/large figure; survey often leads with 约2,450,000
    return nums[0]


def parse_horizon_years(text: Any) -> tuple[float | None, float | None]:
    """Return (default_guess, max_hint) from H10-style strings like '5–8年'."""
    s = _norm(text)
    if not s:
        return None, None
    s = s.replace("–", "-").replace("—", "-")
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (lo + hi) / 2, hi
    nums = extract_numbers(s)
    if nums:
        return nums[0], nums[0]
    return None, None


def parse_tariff_kw(text: Any) -> float | None:
    nums = extract_numbers(text)
    if not nums:
        return None
    # C4 often ~0.82 CNY/kWh — take first small decimal if present
    for n in nums:
        if n < 50:  # avoid grabbing years or lamp counts
            return n
    return nums[0]


def j1_implies_emc_incumbent(j1: Any) -> bool:
    s = _norm(j1)
    if not s:
        return False
    if any(x in s for x in ("全覆盖", "仅部分")):
        return True
    if any(x in s for x in ("无", "未知", "没有", "不含")) and "部分" not in s:
        return False
    return False


def laas_signals(i2: Any, h10: Any) -> bool:
    a, b = _norm(i2), _norm(h10)
    combo = a + b
    if not combo.strip():
        return False
    if "LaaS" in combo or "laas" in combo.lower():
        return True
    if "租赁" in combo:
        return True
    if "年" in b and re.search(r"\d", b):
        return True
    if any(x in a for x in ("使用权", "所有权", "未决", "有条件接受", "接受")):
        return True
    return False


def route_dashboard(answers: dict[str, Any]) -> RouteResult:
    j1 = answers.get("J1")
    i2 = answers.get("I2")
    h10 = answers.get("H10")

    emc = j1_implies_emc_incumbent(j1)
    laas = laas_signals(i2, h10)

    if emc and laas:
        story = RouteStory.EMC_AND_LAAS
        summary = (
            "Routing: incumbent EMC-style arrangements (J-block) plus LaaS / ownership "
            "appetite (H/I). Show EMC disclosure and LaaS-oriented copy."
        )
    elif emc:
        story = RouteStory.EMC_INCUMBENT
        summary = (
            "Routing: incumbent EMC / outsourced arrangement (J1–J6). Emphasize baseline "
            "electricity payer (J4) and overlap risk."
        )
    elif laas:
        story = RouteStory.LAAS_STYLE
        summary = (
            "Routing: lease / LaaS-style emphasis from H/I (term H10, usership I2). "
            "Use feasible-envelope framing (no modeled IRR here)."
        )
    else:
        story = RouteStory.GENERIC
        summary = "Routing: generic retrofit / economics narrative."

    return RouteResult(
        story=story,
        emc_incumbent=emc,
        laas_emphasis=laas,
        summary=summary,
    )


_PREFIX_ORDER = (
    "INT",
    "A",
    "B",
    "C",
    "D",
    "E",
    "J",
    "G",
    "H",
    "I",
    "K",
)


def _prefix_key(qid: str) -> tuple[int, str]:
    qid = str(qid).strip()
    for i, p in enumerate(_PREFIX_ORDER):
        if qid.startswith(p) and (len(qid) == len(p) or qid[len(p)].isdigit()):
            return (i, qid)
    return (len(_PREFIX_ORDER), qid)


def group_fixed_facts(answers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group answer IDs into layers for UI expanders."""
    grouped: dict[str, dict[str, Any]] = {p: {} for p in _PREFIX_ORDER}
    grouped["Other"] = {}
    for k, v in answers.items():
        if k == "说明/Note":
            grouped["Other"][k] = v
            continue
        pk = str(k).strip()
        placed = False
        for p in _PREFIX_ORDER:
            if pk.startswith(p) and (len(pk) == len(p) or pk[len(p)].isdigit()):
                grouped[p][pk] = v
                placed = True
                break
        if not placed:
            grouped["Other"][pk] = v
    # Stable sort inside groups
    for d in grouped.values():
        keys = sorted(d.keys(), key=lambda x: _prefix_key(x)[1])
        ordered = {k: d[k] for k in keys}
        d.clear()
        d.update(ordered)
    return grouped


def collect_validation_warnings(answers: dict[str, Any]) -> list[str]:
    """B1 vs B2+B3+B4 and C4 vs TOU band (C4b–C4d) soft checks."""
    warnings: list[str] = []

    b1 = first_money_like(answers.get("B1"))
    b2 = first_money_like(answers.get("B2"))
    b3 = first_money_like(answers.get("B3"))
    b4 = first_money_like(answers.get("B4"))

    if answers.get("B1") in (None, "") and b1 is None:
        warnings.append(
            "B1 not provided — cannot reconcile total spend vs B2+B3+B4 (see acquisition Definitions)."
        )

    parts = [b2, b3, b4]
    if all(x is not None for x in parts) and b1 is not None:
        s = sum(x for x in parts if x is not None)
        # Loose tolerance for rounding / narrative estimates
        if abs(b1 - s) / max(b1, 1.0) > 0.25:
            warnings.append(
                f"B1 ({b1:,.0f}) vs B2+B3+B4 parts ({s:,.0f}) differ materially — reconcile definitions."
            )
    elif b2 is not None and b3 is not None and b1 is not None:
        s = b2 + b3
        if abs(b1 - s) / max(b1, 1.0) > 0.25:
            warnings.append(
                f"B1 ({b1:,.0f}) vs B2+B3 ({s:,.0f}) differ materially — confirm whether B4 belongs in the same sum."
            )

    c4 = parse_tariff_kw(answers.get("C4"))
    band = []
    for key in ("C4b", "C4c", "C4d"):
        t = parse_tariff_kw(answers.get(key))
        if t is not None:
            band.append(t)
    if c4 is not None and len(band) >= 2:
        lo, hi = min(band), max(band)
        if c4 < lo - 0.05 or c4 > hi + 0.05:
            warnings.append(
                f"C4 blended ({c4}) sits outside C4b–C4d band [{lo}, {hi}] — verify blended vs TOU split."
            )

    return warnings
