from datetime import date
from decimal import Decimal
import unittest

from hamsa.screening.engines import (
    CompanyInput, EngineThresholds, EvaluationState, MetricPoint, evaluate_capex_conversion,
    evaluate_cash_quality, evaluate_company, evaluate_compounders, evaluate_earnings_inflection,
    evaluate_extreme_sell_side_liquidity,
)


def point(metric, value, start, end, suffix):
    return MetricPoint(metric, Decimal(str(value)), date.fromisoformat(start), date.fromisoformat(end),
                       f"obs-{suffix}", f"doc-{suffix}", canonical_unit="PERCENT" if metric in ("roce", "operating_margin") else "INR")


def industrial(metrics=(), *, evidence=None, **kwargs):
    return CompanyInput("issuer-1", "industrial", tuple(metrics), evidence=evidence or {}, **kwargs)


class DiscoveryEngineTests(unittest.TestCase):
    def test_compounder_uses_cagr_roe_and_four_actual_yoy_comparisons(self):
        rows = []
        for year, revenue, pat, roce in [(2021, 100, 10, 9), (2022, 125, 13, 10), (2023, 150, 16, 12), (2024, 190, 22, 13)]:
            rows.extend([point("revenue", revenue, f"{year}-04-01", f"{year+1}-03-31", f"r{year}"),
                         point("pat", pat, f"{year}-04-01", f"{year+1}-03-31", f"p{year}"),
                         point("roce", roce, f"{year}-04-01", f"{year+1}-03-31", f"c{year}")])
        # Four current quarters and their matching prior-year periods.
        for year in (2024, 2025):
            for q, (sm, sd, em, ed) in enumerate(((4, 1, 6, 30), (7, 1, 9, 30), (10, 1, 12, 31), (1, 1, 3, 31))):
                actual_year = year + (q == 3)
                prior_start = date(actual_year, sm, sd)
                prior_end = date(actual_year, em, ed)
                value = (100 + q * 10) if year == 2024 else (125 + q * 12)
                rows.append(point("revenue", value, prior_start.isoformat(), prior_end.isoformat(), f"q{year}-{q}"))
        result = evaluate_compounders(industrial(rows))
        self.assertEqual(result.state, EvaluationState.TRIGGERED)
        self.assertIn("sales_cagr_3y", result.inputs)
        self.assertEqual(len(result.source_observation_ids), len(set(result.source_observation_ids)))

    def test_compounder_does_not_treat_matching_periods_as_positive_growth(self):
        rows = []
        for year in range(2021, 2025):
            rows.extend([point("revenue", 100, f"{year}-04-01", f"{year+1}-03-31", f"r{year}"),
                         point("pat", 10, f"{year}-04-01", f"{year+1}-03-31", f"p{year}"),
                         point("roce", 13, f"{year}-04-01", f"{year+1}-03-31", f"c{year}")])
        for year in (2024, 2025):
            for q, (start, end) in enumerate((("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31"), ("01-01", "03-31"))):
                actual = year + (q == 3)
                val = 100 if year == 2024 else 90
                rows.append(point("revenue", val, f"{actual}-{start}", f"{actual}-{end}", f"q{year}-{q}"))
        self.assertEqual(evaluate_compounders(industrial(rows)).inputs["positive_sales_growth_quarters"], 0)

    def test_earnings_inflection_yoy_growth_margin_and_review_flags(self):
        rows = [point("revenue", 100, "2024-04-01", "2024-06-30", "r1"),
                point("revenue", 125, "2025-04-01", "2025-06-30", "r2"),
                point("pat", 10, "2024-04-01", "2024-06-30", "p1"),
                point("pat", 13, "2025-04-01", "2025-06-30", "p2"),
                point("operating_margin", 12, "2024-04-01", "2024-06-30", "m1"),
                point("operating_margin", 13, "2025-04-01", "2025-06-30", "m2")]
        result = evaluate_earnings_inflection(industrial(rows))
        self.assertEqual(result.state, EvaluationState.TRIGGERED)
        self.assertTrue(result.inputs["one_offs_and_base_effects_review_required"])

    def test_financial_company_never_uses_industrial_thresholds(self):
        result = evaluate_compounders(CompanyInput("bank", "financial", ()))
        self.assertEqual(result.state, EvaluationState.BLOCKED)
        self.assertIn("financial_sector_profile_required", result.calculation_expression)

    def test_capex_conversion_requires_demand_and_commissioning_evidence_but_not_roce_fcf(self):
        rows = [point("capex", 100, "2023-04-01", "2024-03-31", "c1"),
                point("capex", 150, "2024-04-01", "2025-03-31", "c2"),
                point("fcf", -100, "2024-04-01", "2025-03-31", "f1"),
                point("roce", 4, "2024-04-01", "2025-03-31", "rc1")]
        self.assertEqual(evaluate_capex_conversion(industrial(rows)).state, EvaluationState.UNPROVEN)
        qualified = industrial(rows, evidence={"commissioning": True, "demand": True, "customer_evidence": True},
            evidence_source_document_ids={
                "commissioning": ("doc-commissioning",),
                "demand": ("doc-demand",),
                "customer_evidence": ("doc-customer",),
            })
        result = evaluate_capex_conversion(qualified)
        self.assertEqual(result.state, EvaluationState.TRIGGERED)
        self.assertFalse(result.inputs["negative_fcf_or_low_roce_is_automatic_rejection"])

    def test_cash_quality_requires_complete_three_years_and_explicit_threshold(self):
        rows = []
        for year in range(2022, 2025):
            rows.extend([point("cfo", 100, f"{year}-04-01", f"{year+1}-03-31", f"c{year}"),
                         point("pat", 100, f"{year}-04-01", f"{year+1}-03-31", f"p{year}"),
                         point("fcf", 10 if year > 2022 else -10, f"{year}-04-01", f"{year+1}-03-31", f"f{year}")])
        self.assertEqual(evaluate_cash_quality(industrial(rows)).state, EvaluationState.TRIGGERED)
        self.assertEqual(evaluate_cash_quality(industrial(rows[:2])).state, EvaluationState.UNPROVEN)
        custom = EngineThresholds(cash_cfo_pat_min=Decimal("1.1"))
        self.assertEqual(evaluate_cash_quality(industrial(rows), custom).state, EvaluationState.NOT_TRIGGERED)

    def test_extreme_liquidity_never_triggers_from_price_or_volume_without_selling_evidence(self):
        result = evaluate_extreme_sell_side_liquidity(industrial(), volume_multiple=Decimal("5"),
            delivery_percentage_point_change=Decimal("70"), forced_selling_evidence=None,
            absorption_capacity_evidence=None)
        self.assertEqual(result.state, EvaluationState.UNPROVEN)
        self.assertFalse(result.inputs["falling_price_alone_sufficient"])
        forced = evaluate_extreme_sell_side_liquidity(industrial(), volume_multiple=Decimal("5"),
            delivery_percentage_point_change=None, forced_selling_evidence=True,
            absorption_capacity_evidence=True,
            forced_selling_source_document_ids=("doc-seller",),
            absorption_capacity_source_document_ids=("doc-absorption",),
            volume_source_observation_ids=("obs-volume",),
            volume_source_document_ids=("doc-volume",),
            thresholds=EngineThresholds(unusual_volume_multiple=Decimal("3")))
        self.assertEqual(forced.state, EvaluationState.TRIGGERED)

    def test_capex_evidence_without_citations_does_not_trigger(self):
        rows = [point("capex", 100, "2023-04-01", "2024-03-31", "c1"),
                point("capex", 150, "2024-04-01", "2025-03-31", "c2")]
        company = industrial(rows, evidence={"commissioning": True, "demand": True, "customer_evidence": True})
        self.assertEqual(evaluate_capex_conversion(company).state, EvaluationState.UNPROVEN)

    def test_extreme_liquidity_requires_configured_threshold_and_source_evidence(self):
        kwargs = dict(volume_multiple=Decimal("9"), delivery_percentage_point_change=None,
            forced_selling_evidence=True, absorption_capacity_evidence=True,
            forced_selling_source_document_ids=("doc-seller",),
            absorption_capacity_source_document_ids=("doc-absorption",),
            volume_source_observation_ids=("obs-volume",), volume_source_document_ids=("doc-volume",))
        self.assertEqual(evaluate_extreme_sell_side_liquidity(industrial(), **kwargs).state, EvaluationState.UNPROVEN)
        configured = evaluate_extreme_sell_side_liquidity(industrial(), **kwargs,
            thresholds=EngineThresholds(unusual_volume_multiple=Decimal("3")))
        self.assertEqual(configured.state, EvaluationState.TRIGGERED)
        no_citation = evaluate_extreme_sell_side_liquidity(industrial(), **{**kwargs,
            "forced_selling_source_document_ids": (), "volume_source_document_ids": ()},
            thresholds=EngineThresholds(unusual_volume_multiple=Decimal("3")))
        self.assertEqual(no_citation.state, EvaluationState.UNPROVEN)

    def test_missing_invalid_and_nonfinite_inputs_do_not_pass(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            point("pat", Decimal("NaN"), "2024-01-01", "2024-12-31", "nan")
        result = evaluate_cash_quality(industrial([point("pat", 0, "2024-01-01", "2024-12-31", "p0")]))
        self.assertEqual(result.state, EvaluationState.UNPROVEN)

    def test_conflicted_or_stale_latest_period_fails_closed_across_engines(self):
        # Earnings inflection must not trigger if latest PAT or operating margin is conflicted/stale.
        inflection_rows = [
            point("revenue", 100, "2024-04-01", "2024-06-30", "r1"),
            point("revenue", 125, "2025-04-01", "2025-06-30", "r2"),
            point("pat", 10, "2024-04-01", "2024-06-30", "p1"),
            MetricPoint("pat", Decimal("13"), date(2025, 4, 1), date(2025, 6, 30),
                        "obs-p2-conflict", "doc-p2", quality_status="conflicted", canonical_unit="INR"),
            point("operating_margin", 12, "2024-04-01", "2024-06-30", "m1"),
            point("operating_margin", 13, "2025-04-01", "2025-06-30", "m2"),
        ]
        self.assertEqual(evaluate_earnings_inflection(industrial(inflection_rows)).state, EvaluationState.UNPROVEN)

        # Annual engines must not silently drop a conflicted latest year to evaluate an older window.
        cash_rows = []
        for year in range(2021, 2024):
            cash_rows.extend([
                point("cfo", 100, f"{year}-04-01", f"{year+1}-03-31", f"c{year}"),
                point("pat", 100, f"{year}-04-01", f"{year+1}-03-31", f"p{year}"),
                point("fcf", 20, f"{year}-04-01", f"{year+1}-03-31", f"f{year}"),
            ])
        cash_rows.append(MetricPoint("cfo", Decimal("100"), date(2024, 4, 1), date(2025, 3, 31),
                                     "obs-c2024-conflict", "doc-c2024", quality_status="conflicted", canonical_unit="INR"))
        self.assertEqual(evaluate_cash_quality(industrial(cash_rows)).state, EvaluationState.UNPROVEN)

    def test_evaluate_company_forwards_evidence_and_liquidity_inputs(self):
        company = industrial(
            evidence={"forced_selling": True, "absorption_capacity": True},
            evidence_source_document_ids={
                "forced_selling": ("doc-seller",),
                "absorption_capacity": ("doc-absorption",),
            },
        )
        results = evaluate_company(
            company,
            EngineThresholds(unusual_volume_multiple=Decimal("3")),
            volume_multiple=Decimal("4.5"),
            volume_source_observation_ids=("obs-vol-1",),
            volume_source_document_ids=("doc-vol-1",),
        )
        self.assertEqual(len(results), 5)
        liq = next(r for r in results if r.engine == "extreme_sell_side_liquidity")
        self.assertEqual(liq.state, EvaluationState.TRIGGERED)
        self.assertIn("doc-seller", liq.source_document_ids)
        self.assertIn("obs-vol-1", liq.source_observation_ids)


if __name__ == "__main__":
    unittest.main()
