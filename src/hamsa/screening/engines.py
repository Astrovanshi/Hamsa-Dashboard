"""Transparent discovery-engine calculations over point-in-time inputs.

The module never selects observations or decides universe membership. Callers
must supply already validated, point-in-time, mainboard-eligible observations.
Qualitative evidence remains human reviewed; an engine status is a research
flag and is never an investment recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
from math import isfinite
from typing import Mapping, Sequence


class EvaluationState(StrEnum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    UNPROVEN = "unproven"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    metric: str
    value: Decimal | None
    period_start: date
    period_end: date
    observation_id: str
    source_document_id: str
    quality_status: str = "observed"
    reporting_scope: str = "consolidated"
    canonical_unit: str = "INR"

    def __post_init__(self) -> None:
        if not self.metric or not self.observation_id or not self.source_document_id:
            raise ValueError("metric points require metric, observation, and source identifiers")
        if self.period_start > self.period_end:
            raise ValueError("metric period_start must not be after period_end")
        if self.quality_status == "observed" and self.value is None:
            raise ValueError("observed metric points require a value")
        if self.reporting_scope not in ("standalone", "consolidated", "not_applicable"):
            raise ValueError("unsupported financial reporting scope")
        if not self.canonical_unit:
            raise ValueError("financial metric point requires its canonical unit")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("metric value must be finite")


@dataclass(frozen=True, slots=True)
class CompanyInput:
    issuer_entity_id: str
    business_class: str
    metrics: tuple[MetricPoint, ...]
    source_observation_ids: tuple[str, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    evidence: Mapping[str, bool | None] = field(default_factory=dict)
    evidence_observation_ids: tuple[str, ...] = ()
    evidence_document_ids: tuple[str, ...] = ()
    evidence_source_document_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    reporting_scope: str = "consolidated"


@dataclass(frozen=True, slots=True)
class EngineResult:
    engine: str
    issuer_entity_id: str
    state: EvaluationState
    calculation_expression: str
    inputs: Mapping[str, str | int | float | None]
    source_observation_ids: tuple[str, ...]
    source_document_ids: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class EngineThresholds:
    sales_cagr_min: Decimal = Decimal("0.12")
    pat_cagr_min: Decimal = Decimal("0.12")
    # Financial schema percentages are stored in percentage points, so 12% is 12.
    roce_min: Decimal = Decimal("12")
    earnings_sales_growth_min: Decimal = Decimal("0.20")
    earnings_pat_growth_min: Decimal = Decimal("0.25")
    cash_cfo_pat_min: Decimal = Decimal("0.8")
    # No approved numerical definition of "unusual" was supplied for this
    # engine. Those thresholds remain unset until the user configures them.
    unusual_volume_multiple: Decimal | None = None
    unusual_delivery_percentage_points: Decimal | None = None

    def __post_init__(self) -> None:
        required = (self.sales_cagr_min, self.pat_cagr_min, self.roce_min,
                    self.earnings_sales_growth_min, self.earnings_pat_growth_min,
                    self.cash_cfo_pat_min)
        optional = (self.unusual_volume_multiple, self.unusual_delivery_percentage_points)
        if any(not item.is_finite() or item < 0 for item in required):
            raise ValueError("configured discovery thresholds must be finite and non-negative")
        if any(item is not None and (not item.is_finite() or item < 0) for item in optional):
            raise ValueError("optional liquidity thresholds must be finite and non-negative")


def _unsupported_financial_class(company: CompanyInput, engine: str) -> EngineResult | None:
    if company.business_class == "financial":
        return EngineResult(engine, company.issuer_entity_id, EvaluationState.BLOCKED,
            "financial_sector_profile_required", {"business_class": "financial"},
            company.source_observation_ids, company.source_document_ids,
            "No approved financial-sector threshold profile is configured; industrial criteria were not applied.")
    if company.business_class != "industrial":
        return EngineResult(engine, company.issuer_entity_id, EvaluationState.BLOCKED,
            "approved_business_class_required", {"business_class": company.business_class},
            company.source_observation_ids, company.source_document_ids,
            "An approved financial or industrial classification is required.")
    return None


def _metric_points(company: CompanyInput, metric: str, *, annual: bool | None = None,
                   observed_only: bool = True) -> list[MetricPoint]:
    result = [p for p in company.metrics if p.metric == metric and p.reporting_scope == company.reporting_scope
              and (not observed_only or (p.quality_status == "observed" and p.value is not None))]
    if annual is not None:
        result = [p for p in result if (p.period_end - p.period_start).days >= 300] if annual else [
            p for p in result if 60 <= (p.period_end - p.period_start).days <= 120
        ]
    return sorted(result, key=lambda p: (p.period_end, p.period_start, p.observation_id))


def _unique_annual(points: Sequence[MetricPoint]) -> list[MetricPoint] | None:
    by_year: dict[int, list[MetricPoint]] = {}
    for point in points:
        by_year.setdefault(point.period_end.year, []).append(point)
    if any(
        len(items) != 1 or items[0].quality_status != "observed" or items[0].value is None
        for items in by_year.values()
    ):
        return None
    return [by_year[year][0] for year in sorted(by_year)]


def _year_growth(points: Sequence[MetricPoint], *, years: int) -> Decimal | None:
    if len(points) < years + 1:
        return None
    selected = points[-(years + 1):]
    if selected[-1].period_end.year - selected[0].period_end.year != years:
        return None
    if len({point.period_end.year for point in selected}) != years + 1:
        return None
    if len({point.canonical_unit for point in selected}) != 1:
        return None
    start, end = selected[0].value, selected[-1].value
    assert start is not None and end is not None
    if start <= 0 or end < 0:
        return None
    try:
        # Decimal fractional powers are not supported consistently; float is
        # used for the calculation and immediately represented as Decimal.
        result = Decimal(str((float(end / start) ** (1 / years)) - 1))
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return result if result.is_finite() else None


def _result(engine: str, company: CompanyInput, state: EvaluationState, expression: str,
            inputs: Mapping[str, str | int | float | None], points: Sequence[MetricPoint], explanation: str) -> EngineResult:
    metrics = {point.metric for point in points}
    relevant = [point for point in company.metrics if point.metric in metrics
                and point.reporting_scope == company.reporting_scope]
    quality_states: dict[str, dict[str, int]] = {}
    for point in relevant:
        counts = quality_states.setdefault(point.metric, {})
        counts[point.quality_status] = counts.get(point.quality_status, 0) + 1
    recorded_inputs = dict(inputs)
    recorded_inputs["input_quality_states"] = json.dumps(quality_states, sort_keys=True)
    observed = list(dict.fromkeys((*[p.observation_id for p in relevant], *company.evidence_observation_ids)))
    categorized_evidence = tuple(source_id for ids in company.evidence_source_document_ids.values() for source_id in ids)
    sources = list(dict.fromkeys((*[p.source_document_id for p in relevant], *company.evidence_document_ids, *categorized_evidence)))
    return EngineResult(engine, company.issuer_entity_id, state, expression, recorded_inputs, tuple(observed), tuple(sources), explanation)


def evaluate_compounders(company: CompanyInput, thresholds: EngineThresholds = EngineThresholds()) -> EngineResult:
    blocked = _unsupported_financial_class(company, "compounders")
    if blocked:
        return blocked
    sales_rows, pat_rows, roce_rows = (
        _metric_points(company, name, annual=True, observed_only=False) for name in ("revenue", "pat", "roce")
    )
    sales, pat, roce = (_unique_annual(rows) for rows in (sales_rows, pat_rows, roce_rows))
    sales, pat, roce = sales or [], pat or [], roce or []
    quarters = _metric_points(company, "revenue", annual=False, observed_only=False)
    sales_cagr, pat_cagr = _year_growth(sales, years=3), _year_growth(pat, years=3)
    periods = sorted({(p.period_start, p.period_end) for p in quarters})
    recent_periods = periods[-4:]
    positive_q_growth = None
    if len(recent_periods) == 4:
        positive_q_growth = 0
        known_growth = True
        for start, end in recent_periods:
            current = [p for p in quarters if (p.period_start,p.period_end)==(start,end)]
            prior = [p for p in quarters if p.period_start.month == start.month
                     and p.period_start.day == start.day and p.period_start.year == start.year - 1
                     and p.period_end.month == end.month and p.period_end.day == end.day
                     and p.period_end.year == end.year - 1]
            if (len(current)!=1 or len(prior)!=1 or current[0].quality_status!="observed"
                    or prior[0].quality_status!="observed" or current[0].value is None or prior[0].value is None
                    or current[0].canonical_unit != prior[0].canonical_unit):
                known_growth = False
                break
            positive_q_growth += int(current[0].value > prior[0].value)
        if not known_growth:
            positive_q_growth = None
    latest_roce = roce[-1].value if roce and roce[-1].canonical_unit == "PERCENT" else None
    improving_roce = (
        len(roce) >= 2
        and roce[-1].period_end.year - roce[-2].period_end.year == 1
        and len({p.canonical_unit for p in roce[-2:]}) == 1
        and roce[-1].canonical_unit == "PERCENT"
        and roce[-1].value is not None
        and roce[-2].value is not None
        and roce[-1].value > roce[-2].value
    )
    roce_known = latest_roce is not None and (latest_roce > thresholds.roce_min or len(roce) >= 2)
    enough = sales_cagr is not None and pat_cagr is not None and roce_known and positive_q_growth is not None
    checks = [sales_cagr is not None and sales_cagr > thresholds.sales_cagr_min,
              pat_cagr is not None and pat_cagr > thresholds.pat_cagr_min,
              (latest_roce is not None and latest_roce > thresholds.roce_min) or improving_roce,
              positive_q_growth is not None and positive_q_growth >= 3]
    state = EvaluationState.UNPROVEN if not enough else (EvaluationState.TRIGGERED if all(checks) else EvaluationState.NOT_TRIGGERED)
    points = sales_rows + pat_rows + roce_rows + quarters
    return _result("compounders", company, state,
        f"3y sales CAGR > {thresholds.sales_cagr_min} AND 3y PAT CAGR > {thresholds.pat_cagr_min} AND (ROCE > {thresholds.roce_min} percentage points OR improving) AND positive sales growth in >=3/4 latest YoY quarters",
        {"sales_cagr_3y": str(sales_cagr) if sales_cagr is not None else None,
         "pat_cagr_3y": str(pat_cagr) if pat_cagr is not None else None,
         "latest_roce": str(latest_roce) if latest_roce is not None else None,
         "roce_improving": improving_roce if len(roce) >= 2 else None,
         "positive_sales_growth_quarters": positive_q_growth,
         "sales_cagr_threshold": str(thresholds.sales_cagr_min), "pat_cagr_threshold": str(thresholds.pat_cagr_min),
         "roce_threshold": str(thresholds.roce_min)}, points,
        "Insufficient periods or missing/invalid metrics remain unproven; all input periods must already be point-in-time eligible.")


def evaluate_earnings_inflection(company: CompanyInput, thresholds: EngineThresholds = EngineThresholds()) -> EngineResult:
    blocked = _unsupported_financial_class(company, "earnings_inflection")
    if blocked:
        return blocked
    revenues = _metric_points(company, "revenue", annual=False, observed_only=False)
    pats = _metric_points(company, "pat", annual=False, observed_only=False)
    margins = _metric_points(company, "operating_margin", annual=False, observed_only=False)
    latest_period_end = max((p.period_end for p in revenues + pats + margins), default=None)
    latest_revenue_rows = [p for p in revenues if p.period_end == latest_period_end] if latest_period_end else []
    latest_revenue = latest_revenue_rows[0] if len(latest_revenue_rows)==1 and latest_revenue_rows[0].quality_status=="observed" else None
    def current_prior(points: list[MetricPoint], current: MetricPoint | None) -> tuple[MetricPoint, MetricPoint] | None:
        if len(points) < 2 or current is None:
            return None
        current_points = [p for p in points if (p.period_start, p.period_end) == (current.period_start, current.period_end)]
        if len(current_points) != 1 or current_points[0].quality_status != "observed" or current_points[0].value is None:
            return None
        latest = current_points[0]
        comparable = [p for p in points if p.period_start.month == latest.period_start.month
                      and p.period_start.day == latest.period_start.day
                      and p.period_start.year == latest.period_start.year - 1
                      and p.period_end.month == latest.period_end.month
                      and p.period_end.day == latest.period_end.day
                      and p.period_end.year == latest.period_end.year - 1]
        if len(comparable) != 1 or comparable[0].quality_status != "observed" or comparable[0].value is None:
            return None
        if latest.canonical_unit != comparable[0].canonical_unit:
            return None
        return latest, comparable[0]
    rev_pair, pat_pair = current_prior(revenues, latest_revenue), current_prior(pats, latest_revenue)
    margin_pair = current_prior(margins, latest_revenue)
    def growth(pair):
        if pair is None or pair[1].value == 0 or pair[1].value is None or pair[0].value is None:
            return None
        return (pair[0].value - pair[1].value) / abs(pair[1].value)
    revenue_growth, pat_growth = growth(rev_pair), growth(pat_pair)
    loss_to_profit = bool(pat_pair and pat_pair[1].value is not None and pat_pair[0].value is not None
                          and pat_pair[1].value <= 0 < pat_pair[0].value)
    margin_improving = bool(margin_pair and margin_pair[0].value is not None and margin_pair[1].value is not None
                            and margin_pair[0].value > margin_pair[1].value)
    enough = revenue_growth is not None and pat_growth is not None and margin_pair is not None
    positive = revenue_growth is not None and revenue_growth > thresholds.earnings_sales_growth_min and (loss_to_profit or (pat_growth is not None and pat_growth > thresholds.earnings_pat_growth_min)) and margin_improving
    points = revenues + pats + margins
    return _result("earnings_inflection", company,
        EvaluationState.UNPROVEN if not enough else (EvaluationState.TRIGGERED if positive else EvaluationState.NOT_TRIGGERED),
        f"YoY quarterly sales growth > {thresholds.earnings_sales_growth_min} AND (PAT growth > {thresholds.earnings_pat_growth_min} OR loss-to-profit) AND same-quarter YoY operating margin improvement",
        {"sales_growth_yoy": str(revenue_growth) if revenue_growth is not None else None,
         "pat_growth_yoy": str(pat_growth) if pat_growth is not None else None,
         "loss_to_profit": loss_to_profit if pat_pair else None,
         "operating_margin_improving": margin_improving if margin_pair else None,
         "one_offs_and_base_effects_review_required": True,
         "sales_growth_threshold": str(thresholds.earnings_sales_growth_min),
         "pat_growth_threshold": str(thresholds.earnings_pat_growth_min)}, points,
        "One-offs and base effects require explicit review; no adjustment is inferred by the engine.")


def evaluate_capex_conversion(company: CompanyInput) -> EngineResult:
    blocked = _unsupported_financial_class(company, "capex_conversion")
    if blocked:
        return blocked
    capex_rows = _metric_points(company, "capex", annual=True, observed_only=False)
    cwip_rows = _metric_points(company, "cwip", annual=True, observed_only=False)
    gross_block_rows = _metric_points(company, "gross_block", annual=True, observed_only=False)
    capex = _unique_annual(capex_rows) or []
    cwip = _unique_annual(cwip_rows) or []
    gross_block = _unique_annual(gross_block_rows) or []
    trends = {}
    for metric, rows in (("capex", capex), ("cwip", cwip), ("gross_block", gross_block)):
        trends[metric] = bool(
            len(rows) >= 2
            and rows[-1].period_end.year - rows[-2].period_end.year == 1
            and rows[-1].value is not None
            and rows[-2].value is not None
            and rows[-1].canonical_unit == rows[-2].canonical_unit
            and rows[-1].value > rows[-2].value
        )
    deployment = capex + cwip + gross_block
    rising = any(trends.values())
    gates = ("commissioning", "demand", "customer_evidence")
    missing_gates = [key for key in gates if company.evidence.get(key) is not True
                     or not company.evidence_source_document_ids.get(key)]
    enough = bool(deployment)
    state = EvaluationState.UNPROVEN if (not enough or missing_gates or not rising) else EvaluationState.TRIGGERED
    points = capex_rows + cwip_rows + gross_block_rows
    return _result("capex_conversion", company, state,
        "rising capex/CWIP/gross block AND source-backed commissioning/trial/qualification AND demand/customer evidence",
        {"investment_metric_trends": json.dumps(trends,sort_keys=True),
         "investment_trend_rising": rising if deployment else None,
         "missing_evidence_gates": missing_gates,
         "negative_fcf_or_low_roce_is_automatic_rejection": False}, points,
        "The engine does not reject capex-heavy businesses because of current ROCE or FCF. Narrative evidence gates need cited human review.")


def evaluate_cash_quality(company: CompanyInput, thresholds: EngineThresholds = EngineThresholds()) -> EngineResult:
    blocked = _unsupported_financial_class(company, "cash_quality")
    if blocked:
        return blocked
    cfo_rows, pat_rows, fcf_rows = (
        _metric_points(company, name, annual=True, observed_only=False) for name in ("cfo", "pat", "fcf")
    )
    cfo, pat, fcf = (_unique_annual(rows) or [] for rows in (cfo_rows, pat_rows, fcf_rows))
    all_years = sorted({p.period_end.year for p in cfo_rows + pat_rows + fcf_rows})
    common_years = all_years[-3:]
    cfo_by_year = {p.period_end.year: p for p in cfo}
    pat_by_year = {p.period_end.year: p for p in pat}
    complete_years = (
        len(common_years) == 3
        and common_years[-1] - common_years[0] == 2
        and all(y in cfo_by_year and y in pat_by_year for y in common_years)
    )
    units_match = complete_years and len({cfo_by_year[y].canonical_unit for y in common_years}
        | {pat_by_year[y].canonical_unit for y in common_years}) == 1
    cfo_sum = sum((cfo_by_year[y].value for y in common_years), Decimal(0)) if complete_years and units_match else None
    pat_sum = sum((pat_by_year[y].value for y in common_years), Decimal(0)) if complete_years and units_match else None
    ratio = cfo_sum / pat_sum if cfo_sum is not None and pat_sum not in (None, Decimal(0)) and pat_sum > 0 else None
    fcf_by_year = {p.period_end.year: p for p in fcf}
    fcf_years = common_years
    fcf_complete = complete_years and all(y in fcf_by_year for y in common_years)
    positive_fcf_count = sum(1 for y in common_years if y in fcf_by_year and fcf_by_year[y].value is not None and fcf_by_year[y].value > 0)
    documented_expansion = (company.evidence.get("documented_expansion") is True
                            and bool(company.evidence_source_document_ids.get("documented_expansion")))
    enough = ratio is not None and fcf_complete and all(fcf_by_year[y].canonical_unit == cfo_by_year[y].canonical_unit for y in common_years)
    passed = ratio is not None and ratio >= thresholds.cash_cfo_pat_min and (positive_fcf_count >= 2 or documented_expansion)
    points = cfo_rows + pat_rows + fcf_rows
    return _result("cash_quality", company,
        EvaluationState.UNPROVEN if not enough else (EvaluationState.TRIGGERED if passed else EvaluationState.NOT_TRIGGERED),
        f"3y cumulative CFO/PAT >= {thresholds.cash_cfo_pat_min} AND (positive FCF in >=2/3 years OR documented expansion explains negative FCF)",
        {"cfo_pat_ratio_3y": str(ratio) if ratio is not None else None,
         "positive_fcf_years_of_three": positive_fcf_count if fcf_complete else None,
         "documented_expansion": documented_expansion,
         "receivables_and_inventory_review_required": True,
         "cfo_pat_threshold": str(thresholds.cash_cfo_pat_min)}, points,
        "PAT/CFO divergence, receivables, inventory, and any expansion explanation remain visible research checks.")


def evaluate_extreme_sell_side_liquidity(company: CompanyInput, *, volume_multiple: Decimal | None,
        delivery_percentage_point_change: Decimal | None, forced_selling_evidence: bool | None,
        absorption_capacity_evidence: bool | None,
        forced_selling_source_document_ids: tuple[str, ...] = (),
        absorption_capacity_source_document_ids: tuple[str, ...] = (),
        volume_source_observation_ids: tuple[str, ...] = (),
        volume_source_document_ids: tuple[str, ...] = (),
        delivery_source_observation_ids: tuple[str, ...] = (),
        delivery_source_document_ids: tuple[str, ...] = (),
        turnover_multiple: Decimal | None = None,
        avg_turnover_20d_inr: Decimal | None = None,
        delivery_percentage: Decimal | None = None,
        session_return_pct: Decimal | None = None,
        drawdown_from_window_high_pct: Decimal | None = None,
        close_range_position: Decimal | None = None,
        unadjusted_corporate_action_in_window: bool = False,
        thresholds: EngineThresholds = EngineThresholds()) -> EngineResult:
    """Liquidity monitor; price declines never qualify without seller evidence."""
    if company.business_class not in ("financial", "industrial"):
        return _unsupported_financial_class(company, "extreme_sell_side_liquidity") or EngineResult(
            "extreme_sell_side_liquidity", company.issuer_entity_id, EvaluationState.UNPROVEN,
            "approved_business_class_required", {}, (), (), "Approved business classification required.")
    unusual_volume = (volume_multiple >= thresholds.unusual_volume_multiple
                      if volume_multiple is not None and thresholds.unusual_volume_multiple is not None else None)
    elevated_delivery = (delivery_percentage_point_change >= thresholds.unusual_delivery_percentage_points
                        if delivery_percentage_point_change is not None and thresholds.unusual_delivery_percentage_points is not None else None)
    volume_gate = (unusual_volume is True and bool(volume_source_observation_ids) and bool(volume_source_document_ids))
    delivery_gate = (elevated_delivery is True and bool(delivery_source_observation_ids) and bool(delivery_source_document_ids))
    if (forced_selling_evidence is True and bool(forced_selling_source_document_ids)
            and absorption_capacity_evidence is True and bool(absorption_capacity_source_document_ids)
            and (volume_gate or delivery_gate)):
        state = EvaluationState.TRIGGERED
    elif forced_selling_evidence is False:
        state = EvaluationState.NOT_TRIGGERED
    else:
        state = EvaluationState.UNPROVEN
    recorded_inputs: dict[str, str | int | float | bool | None] = {
        "volume_multiple": str(volume_multiple) if volume_multiple is not None else None,
        "volume_threshold": str(thresholds.unusual_volume_multiple) if thresholds.unusual_volume_multiple is not None else None,
        "delivery_percentage_point_change": str(delivery_percentage_point_change) if delivery_percentage_point_change is not None else None,
        "delivery_threshold_percentage_points": str(thresholds.unusual_delivery_percentage_points) if thresholds.unusual_delivery_percentage_points is not None else None,
        "unusual_volume": unusual_volume,
        "elevated_delivery": elevated_delivery,
        "forced_selling_evidence": forced_selling_evidence,
        "absorption_capacity_evidence": absorption_capacity_evidence,
        "forced_selling_source_document_ids": json.dumps(forced_selling_source_document_ids),
        "absorption_capacity_source_document_ids": json.dumps(absorption_capacity_source_document_ids),
        "volume_source_observation_ids": json.dumps(volume_source_observation_ids),
        "delivery_source_observation_ids": json.dumps(delivery_source_observation_ids),
        "falling_price_alone_sufficient": False,
    }
    if turnover_multiple is not None:
        recorded_inputs["turnover_multiple"] = str(turnover_multiple)
    if avg_turnover_20d_inr is not None:
        recorded_inputs["avg_turnover_20d_inr"] = str(avg_turnover_20d_inr)
    if delivery_percentage is not None:
        recorded_inputs["delivery_percentage"] = str(delivery_percentage)
    if session_return_pct is not None:
        recorded_inputs["session_return_pct"] = str(session_return_pct)
    if drawdown_from_window_high_pct is not None:
        recorded_inputs["drawdown_from_window_high_pct"] = str(drawdown_from_window_high_pct)
    if close_range_position is not None:
        recorded_inputs["close_range_position"] = str(close_range_position)
    if unadjusted_corporate_action_in_window:
        recorded_inputs["unadjusted_corporate_action_in_window"] = True
    return EngineResult("extreme_sell_side_liquidity", company.issuer_entity_id, state,
        "volume multiple >= explicitly configured threshold OR venue-specific delivery percentage-point change >= explicitly configured threshold; AND separately evidenced forced/structural selling AND absorption capacity",
        recorded_inputs,
        tuple(dict.fromkeys((*volume_source_observation_ids, *delivery_source_observation_ids))),
        tuple(dict.fromkeys((*forced_selling_source_document_ids, *absorption_capacity_source_document_ids,
                             *volume_source_document_ids, *delivery_source_document_ids))),
        "Block/bulk, ownership, lock-in, pledge and absorption evidence must be separately sourced; delivery remains venue-specific.")


def evaluate_company(
    company: CompanyInput,
    thresholds: EngineThresholds = EngineThresholds(),
    *,
    volume_multiple: Decimal | None = None,
    delivery_percentage_point_change: Decimal | None = None,
    forced_selling_evidence: bool | None = None,
    absorption_capacity_evidence: bool | None = None,
    forced_selling_source_document_ids: tuple[str, ...] = (),
    absorption_capacity_source_document_ids: tuple[str, ...] = (),
    volume_source_observation_ids: tuple[str, ...] = (),
    volume_source_document_ids: tuple[str, ...] = (),
    delivery_source_observation_ids: tuple[str, ...] = (),
    delivery_source_document_ids: tuple[str, ...] = (),
    turnover_multiple: Decimal | None = None,
    avg_turnover_20d_inr: Decimal | None = None,
    delivery_percentage: Decimal | None = None,
    session_return_pct: Decimal | None = None,
    drawdown_from_window_high_pct: Decimal | None = None,
    close_range_position: Decimal | None = None,
    unadjusted_corporate_action_in_window: bool = False,
) -> tuple[EngineResult, ...]:
    if forced_selling_evidence is None and "forced_selling" in company.evidence:
        forced_selling_evidence = company.evidence.get("forced_selling")
    if absorption_capacity_evidence is None and "absorption_capacity" in company.evidence:
        absorption_capacity_evidence = company.evidence.get("absorption_capacity")
    if not forced_selling_source_document_ids:
        forced_selling_source_document_ids = tuple(company.evidence_source_document_ids.get("forced_selling", ()))
    if not absorption_capacity_source_document_ids:
        absorption_capacity_source_document_ids = tuple(company.evidence_source_document_ids.get("absorption_capacity", ()))
    return (
        evaluate_compounders(company, thresholds),
        evaluate_earnings_inflection(company, thresholds),
        evaluate_capex_conversion(company),
        evaluate_cash_quality(company, thresholds),
        evaluate_extreme_sell_side_liquidity(
            company,
            volume_multiple=volume_multiple,
            delivery_percentage_point_change=delivery_percentage_point_change,
            forced_selling_evidence=forced_selling_evidence,
            absorption_capacity_evidence=absorption_capacity_evidence,
            forced_selling_source_document_ids=forced_selling_source_document_ids,
            absorption_capacity_source_document_ids=absorption_capacity_source_document_ids,
            volume_source_observation_ids=volume_source_observation_ids,
            volume_source_document_ids=volume_source_document_ids,
            delivery_source_observation_ids=delivery_source_observation_ids,
            delivery_source_document_ids=delivery_source_document_ids,
            turnover_multiple=turnover_multiple,
            avg_turnover_20d_inr=avg_turnover_20d_inr,
            delivery_percentage=delivery_percentage,
            session_return_pct=session_return_pct,
            drawdown_from_window_high_pct=drawdown_from_window_high_pct,
            close_range_position=close_range_position,
            unadjusted_corporate_action_in_window=unadjusted_corporate_action_in_window,
            thresholds=thresholds,
        ),
    )
