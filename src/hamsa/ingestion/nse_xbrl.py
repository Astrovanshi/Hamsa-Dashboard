"""NSE XBRL financial-results acquisition, parsing, normalization, and ingestion.

Supports both post-2024 SEBI Integrated Filing XBRL (`INTEGRATED_FILING_INDAS_*`,
`_NBFC_INDAS_*`, `_BANKING_*`, `_NONINDAS_*`) and pre-2025 NSE Corporate Financial
Results XBRL (`INDAS_*`, `NONINDAS_*`).

Preserves:
- Immutable raw XML bytes and SHA-256 archive provenance.
- Point-in-time publication date and reliable IST broadcast/creation timestamp.
- Standalone vs. consolidated reporting scope.
- Exact period_start and period_end (distinguishing quarterly 60..120d,
  cumulative 6m/9m YTD 150..300d, and annual 330..380d).
- As-reported facts vs. derived facts (operating_margin, ebit, ebitda, fcf,
  roce, and YTD-derived quarters) with explicit formula_version and
  observation_lineage_input references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Iterable, Sequence
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from hamsa.domain.financials import (
    AsReportedStatus,
    FinancialObservationRevision,
    PublicationPrecision,
    QualityStatus,
)
from hamsa.domain.security import is_valid_isin
from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.ingestion.source_registry import register_local_exchange_source
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


PARSER_VERSION = "nse-xbrl-v1"

METRIC_DEFINITIONS: dict[str, tuple[str, str, str]] = {
    "revenue": ("INR", "currency", "Revenue from operations"),
    "other_income": ("INR", "currency", "Other income"),
    "ebit": ("INR", "currency", "Earnings before interest and tax"),
    "ebitda": ("INR", "currency", "Earnings before interest, tax, depreciation, and amortisation"),
    "operating_margin": ("PERCENT", "percentage", "Operating EBITDA margin (percentage points)"),
    "interest": ("INR", "currency", "Finance costs / interest expended"),
    "depreciation": ("INR", "currency", "Depreciation, depletion, and amortisation expense"),
    "pbt": ("INR", "currency", "Profit before tax"),
    "pat": ("INR", "currency", "Profit after tax for the period"),
    "eps": ("INR_PER_SHARE", "price", "Basic earnings per share"),
    "total_assets": ("INR", "currency", "Total assets"),
    "net_worth": ("INR", "currency", "Total equity / net worth"),
    "borrowings": ("INR", "currency", "Total borrowings (non-current + current)"),
    "cash_and_equivalents": ("INR", "currency", "Cash and cash equivalents"),
    "receivables": ("INR", "currency", "Trade receivables"),
    "inventory": ("INR", "currency", "Inventories"),
    "trade_payables": ("INR", "currency", "Trade payables"),
    "gross_block": ("INR", "currency", "Property, plant, and equipment (net/carrying)"),
    "cwip": ("INR", "currency", "Capital work in progress"),
    "cfo": ("INR", "currency", "Cash flows from operating activities"),
    "capex": ("INR", "currency", "Purchase of PPE and intangible assets"),
    "fcf": ("INR", "currency", "Free cash flow (CFO minus capex)"),
    "investing_cash_flow": ("INR", "currency", "Cash flows from investing activities"),
    "financing_cash_flow": ("INR", "currency", "Cash flows from financing activities"),
    "roce": ("PERCENT", "percentage", "Return on capital employed (percentage points)"),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, text/plain, */*",
}


@dataclass(frozen=True, slots=True)
class ExtractedFact:
    metric: str
    value: Decimal
    canonical_unit: str
    period_start: date
    period_end: date
    reporting_scope: str
    locator: str
    formula_version: str | None = None
    lineage_input_keys: tuple[tuple[str, date, date], ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedXbrlFiling:
    symbol: str | None
    isin: str | None
    company_name: str | None
    reporting_scope: str
    audited: bool
    level_of_rounding: str | None
    type_of_company: str | None
    class_of_security: str | None
    facts: tuple[ExtractedFact, ...]


@dataclass(frozen=True, slots=True)
class NseXbrlFilingMetadata:
    symbol: str
    company_name: str | None
    source_identifier: str
    xbrl_url: str
    period_start: date | None
    period_end: date
    reporting_scope: str
    audited: bool
    is_revision: bool
    publication_date: date
    published_at: datetime | None


@dataclass(slots=True)
class XbrlIngestionSummary:
    filings_processed: int = 0
    filings_succeeded: int = 0
    filings_duplicated: int = 0
    filings_quarantined: int = 0
    filings_failed: int = 0
    observations_accepted: int = 0
    observations_revised: int = 0
    quarters_derived_from_ytd: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "filings_processed": self.filings_processed,
            "filings_succeeded": self.filings_succeeded,
            "filings_duplicated": self.filings_duplicated,
            "filings_quarantined": self.filings_quarantined,
            "filings_failed": self.filings_failed,
            "observations_accepted": self.observations_accepted,
            "observations_revised": self.observations_revised,
            "quarters_derived_from_ytd": self.quarters_derived_from_ytd,
            "errors": list(self.errors),
        }


def _parse_iso_or_dmy_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_nse_broadcast_timestamp(raw: str | None, *, fallback_date: date) -> tuple[date, datetime | None]:
    """Parse NSE's IST broadcast/creation timestamp (`DD-Mon-YYYY HH:MM:SS`)."""
    if not raw or not raw.strip() or raw.strip() in {"-", "--"}:
        return fallback_date, None
    text = raw.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%B-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=MARKET_TIMEZONE)
            return dt.date(), dt
        except ValueError:
            continue
    parsed_date = _parse_iso_or_dmy_date(text)
    if parsed_date is not None:
        return parsed_date, None
    return fallback_date, None


def _dec(raw: str | None) -> Decimal | None:
    if raw is None or not raw.strip():
        return None
    try:
        val = Decimal(raw.strip())
    except InvalidOperation:
        return None
    return val if val.is_finite() else None


def _first_present(mapping: dict[str, str], keys: Sequence[str]) -> tuple[str | None, Decimal | None]:
    for key in keys:
        if key in mapping:
            val = _dec(mapping[key])
            if val is not None:
                return key, val
    return None, None


def parse_nse_xbrl_bytes(
    xml_bytes: bytes,
    *,
    fallback_symbol: str | None = None,
    fallback_scope: str | None = None,
) -> ParsedXbrlFiling:
    """Parse an NSE Ind-AS / Integrated Filing / Banking XBRL XML document."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"malformed XBRL XML: {exc}") from exc

    contexts: dict[str, dict[str, object]] = {}
    facts_by_ctx: dict[str, dict[str, str]] = {}

    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == "context":
            cid = el.attrib.get("id", "").strip()
            if not cid:
                continue
            start = end = instant = None
            has_segment = False
            for child in el.iter():
                clocal = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if clocal == "startDate" and child.text:
                    start = _parse_iso_or_dmy_date(child.text)
                elif clocal == "endDate" and child.text:
                    end = _parse_iso_or_dmy_date(child.text)
                elif clocal == "instant" and child.text:
                    instant = _parse_iso_or_dmy_date(child.text)
                elif clocal in ("segment", "scenario"):
                    has_segment = True
            if not has_segment:
                contexts[cid] = {"start": start, "end": end, "instant": instant}
            continue

        ctx_ref = el.attrib.get("contextRef", "").strip()
        if ctx_ref and el.text and el.text.strip():
            facts_by_ctx.setdefault(ctx_ref, {})[local] = el.text.strip()

    oned = facts_by_ctx.get("OneD", {})
    fourd = facts_by_ctx.get("FourD", {})
    onei = facts_by_ctx.get("OneI", {})
    meta = {**fourd, **oned}

    symbol = (meta.get("Symbol") or fallback_symbol or "").strip().upper() or None
    raw_isin = (meta.get("ISIN") or "").strip().upper()
    isin = raw_isin if is_valid_isin(raw_isin) else None
    company_name = (meta.get("NameOfTheCompany") or "").strip() or None
    nature = (meta.get("NatureOfReportStandaloneConsolidated") or fallback_scope or "Consolidated").strip().lower()
    reporting_scope = "consolidated" if nature.startswith("con") else "standalone"
    audited_text = (meta.get("WhetherResultsAreAuditedOrUnaudited") or "").strip().lower()
    audited = audited_text == "audited"
    rounding = (meta.get("LevelOfRounding") or meta.get("LevelOfRoundingUsedInFinancialStatements") or "").strip() or None
    type_of_company = (meta.get("TypeOfCompany") or "").strip() or None
    class_of_security = (meta.get("ClassOfSecurity") or "").strip() or None

    extracted: list[ExtractedFact] = []
    seen_keys: set[tuple[str, date, date]] = set()

    def add_fact(fact: ExtractedFact) -> None:
        key = (fact.metric, fact.period_start, fact.period_end)
        if key not in seen_keys:
            seen_keys.add(key)
            extracted.append(fact)

    def resolve_duration(ctx_id: str, ctx_facts: dict[str, str]) -> tuple[date, date] | None:
        s = _parse_iso_or_dmy_date(ctx_facts.get("DateOfStartOfReportingPeriod"))
        e = _parse_iso_or_dmy_date(ctx_facts.get("DateOfEndOfReportingPeriod"))
        if s is None and ctx_id in contexts:
            s = contexts[ctx_id].get("start")  # type: ignore[assignment]
        if e is None and ctx_id in contexts:
            e = contexts[ctx_id].get("end")  # type: ignore[assignment]
        if s is not None and e is not None and s <= e:
            return s, e
        return None

    # Process FourD first (when it represents a distinct YTD/Annual period), then OneD
    duration_spans: dict[str, tuple[date, date]] = {}
    for ctx_id, ctx_facts in (("FourD", fourd), ("OneD", oned)):
        if not ctx_facts:
            continue
        span = resolve_duration(ctx_id, ctx_facts)
        if span is None:
            continue
        duration_spans[ctx_id] = span
        p_start, p_end = span

        rev_tag, rev_val = _first_present(ctx_facts, (
            "RevenueFromOperations", "InterestEarned", "TotalRevenueFromOperations",
        ))
        oi_tag, oi_val = _first_present(ctx_facts, ("OtherIncome",))
        int_tag, int_val = _first_present(ctx_facts, ("FinanceCosts", "InterestExpended"))
        dep_tag, dep_val = _first_present(ctx_facts, (
            "DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense",
        ))
        pbt_tag, pbt_val = _first_present(ctx_facts, ("ProfitBeforeTax",))
        pbt_ex_tag, pbt_ex_val = _first_present(ctx_facts, (
            "ProfitBeforeExceptionalItemsAndTax", "OperatingProfitBeforeProvisionsAndContingencies", "ProfitBeforeTax",
        ))
        pat_tag, pat_val = _first_present(ctx_facts, (
            "ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod",
        ))
        eps_tag, eps_val = _first_present(ctx_facts, (
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations",
            "BasicEPS",
        ))

        if rev_val is not None and rev_tag:
            add_fact(ExtractedFact("revenue", rev_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{rev_tag}"))
        if oi_val is not None and oi_tag:
            add_fact(ExtractedFact("other_income", oi_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{oi_tag}"))
        if int_val is not None and int_tag:
            add_fact(ExtractedFact("interest", int_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{int_tag}"))
        if dep_val is not None and dep_tag:
            add_fact(ExtractedFact("depreciation", dep_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{dep_tag}"))
        if pbt_val is not None and pbt_tag:
            add_fact(ExtractedFact("pbt", pbt_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{pbt_tag}"))
        if pat_val is not None and pat_tag:
            add_fact(ExtractedFact("pat", pat_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{pat_tag}"))
        if eps_val is not None and eps_tag:
            add_fact(ExtractedFact("eps", eps_val, "INR_PER_SHARE", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{eps_tag}"))

        # Derived EBIT, EBITDA, and Operating Margin (with lineage to reported inputs)
        if pbt_val is not None and int_val is not None:
            base_pbt = pbt_ex_val if pbt_ex_val is not None else pbt_val
            ebit_val = base_pbt + int_val
            ebit_inputs: list[tuple[str, date, date]] = [("pbt", p_start, p_end), ("interest", p_start, p_end)]
            add_fact(ExtractedFact(
                "ebit", ebit_val, "INR", p_start, p_end, reporting_scope,
                f"xbrl:{ctx_id}:{pbt_ex_tag or pbt_tag}+{int_tag}",
                formula_version="xbrl-ebit-pbt-plus-interest-v1",
                lineage_input_keys=tuple(ebit_inputs),
            ))
            if dep_val is not None:
                op_ebitda = ebit_val + dep_val - (oi_val or Decimal("0"))
                ebitda_inputs: list[tuple[str, date, date]] = [
                    ("pbt", p_start, p_end), ("interest", p_start, p_end), ("depreciation", p_start, p_end),
                ]
                if oi_val is not None:
                    ebitda_inputs.append(("other_income", p_start, p_end))
                add_fact(ExtractedFact(
                    "ebitda", op_ebitda, "INR", p_start, p_end, reporting_scope,
                    f"xbrl:{ctx_id}:OperatingEBITDA",
                    formula_version="xbrl-operating-ebitda-v1",
                    lineage_input_keys=tuple(ebitda_inputs),
                ))
                if rev_val is not None and rev_val > 0:
                    opm_pct = (op_ebitda / rev_val) * Decimal("100")
                    if opm_pct.is_finite():
                        add_fact(ExtractedFact(
                            "operating_margin", opm_pct, "PERCENT", p_start, p_end, reporting_scope,
                            f"xbrl:{ctx_id}:OperatingMarginPct",
                            formula_version="xbrl-operating-margin-ebitda-pct-v1",
                            lineage_input_keys=(("revenue", p_start, p_end), ("ebitda", p_start, p_end)),
                        ))

        # Cash flow lines (typically in FourD)
        cfo_tag, cfo_val = _first_present(ctx_facts, ("CashFlowsFromUsedInOperatingActivities",))
        capex_ppe_tag, capex_ppe_val = _first_present(ctx_facts, (
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        ))
        _, capex_int_val = _first_present(ctx_facts, (
            "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        ))
        inv_cf_tag, inv_cf_val = _first_present(ctx_facts, ("CashFlowsFromUsedInInvestingActivities",))
        fin_cf_tag, fin_cf_val = _first_present(ctx_facts, ("CashFlowsFromUsedInFinancingActivities",))

        if cfo_val is not None and cfo_tag:
            add_fact(ExtractedFact("cfo", cfo_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{cfo_tag}"))
        capex_total = None
        if capex_ppe_val is not None:
            capex_total = abs(capex_ppe_val) + (abs(capex_int_val) if capex_int_val is not None and capex_int_val > 0 else Decimal("0"))
            add_fact(ExtractedFact(
                "capex", capex_total, "INR", p_start, p_end, reporting_scope,
                f"xbrl:{ctx_id}:{capex_ppe_tag}",
            ))
        if inv_cf_val is not None and inv_cf_tag:
            add_fact(ExtractedFact("investing_cash_flow", inv_cf_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{inv_cf_tag}"))
        if fin_cf_val is not None and fin_cf_tag:
            add_fact(ExtractedFact("financing_cash_flow", fin_cf_val, "INR", p_start, p_end, reporting_scope, f"xbrl:{ctx_id}:{fin_cf_tag}"))
        if cfo_val is not None and capex_total is not None:
            fcf_val = cfo_val - capex_total
            add_fact(ExtractedFact(
                "fcf", fcf_val, "INR", p_start, p_end, reporting_scope,
                f"xbrl:{ctx_id}:FreeCashFlow",
                formula_version="xbrl-fcf-cfo-minus-capex-v1",
                lineage_input_keys=(("cfo", p_start, p_end), ("capex", p_start, p_end)),
            ))

    # Balance Sheet (OneI)
    if onei:
        bs_span = duration_spans.get("FourD") or duration_spans.get("OneD")
        if bs_span is not None:
            bs_start, bs_end = bs_span
            assets_tag, assets_val = _first_present(onei, ("Assets", "EquityAndLiabilities"))
            eq_tag, eq_val = _first_present(onei, ("Equity", "EquityAttributableToOwnersOfParent", "ShareholdersFunds"))
            ppe_tag, ppe_val = _first_present(onei, ("PropertyPlantAndEquipment", "FixedAssets"))
            cwip_tag, cwip_val = _first_present(onei, ("CapitalWorkInProgress",))
            rec_tag, rec_val = _first_present(onei, ("TradeReceivablesCurrent", "TradeReceivables"))
            inv_tag, inv_val = _first_present(onei, ("Inventories",))
            pay_tag, pay_val = _first_present(onei, ("TradePayablesCurrent", "TradePayables"))
            cash_tag, cash_val = _first_present(onei, ("CashAndCashEquivalents", "CashAndCashEquivalentsCashFlowStatement"))
            _, b_nc = _first_present(onei, ("BorrowingsNoncurrent",))
            _, b_c = _first_present(onei, ("BorrowingsCurrent",))
            b_single_tag, b_single = _first_present(onei, ("Borrowings",))

            if assets_val is not None and assets_tag:
                add_fact(ExtractedFact("total_assets", assets_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{assets_tag}"))
            if eq_val is not None and eq_tag:
                add_fact(ExtractedFact("net_worth", eq_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{eq_tag}"))
            if ppe_val is not None and ppe_tag:
                add_fact(ExtractedFact("gross_block", ppe_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{ppe_tag}"))
            if cwip_val is not None and cwip_tag:
                add_fact(ExtractedFact("cwip", cwip_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{cwip_tag}"))
            if rec_val is not None and rec_tag:
                add_fact(ExtractedFact("receivables", rec_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{rec_tag}"))
            if inv_val is not None and inv_tag:
                add_fact(ExtractedFact("inventory", inv_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{inv_tag}"))
            if pay_val is not None and pay_tag:
                add_fact(ExtractedFact("trade_payables", pay_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{pay_tag}"))
            if cash_val is not None and cash_tag:
                add_fact(ExtractedFact("cash_and_equivalents", cash_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{cash_tag}"))

            borrowings_val: Decimal | None = None
            if b_nc is not None or b_c is not None:
                borrowings_val = (b_nc or Decimal("0")) + (b_c or Decimal("0"))
                add_fact(ExtractedFact(
                    "borrowings", borrowings_val, "INR", bs_start, bs_end, reporting_scope,
                    "xbrl:OneI:BorrowingsNoncurrent+BorrowingsCurrent",
                ))
            elif b_single is not None and b_single_tag:
                borrowings_val = b_single
                add_fact(ExtractedFact("borrowings", borrowings_val, "INR", bs_start, bs_end, reporting_scope, f"xbrl:OneI:{b_single_tag}"))

            # Derived ROCE for annual periods (>=300 days)
            if (bs_end - bs_start).days >= 300 and eq_val is not None:
                cap_employed = eq_val + (borrowings_val or Decimal("0"))
                ebit_match = next(
                    (f for f in extracted if f.metric == "ebit" and f.period_start == bs_start and f.period_end == bs_end),
                    None,
                )
                if ebit_match is not None and cap_employed > 0:
                    roce_pct = (ebit_match.value / cap_employed) * Decimal("100")
                    if roce_pct.is_finite():
                        roce_inputs: list[tuple[str, date, date]] = [
                            ("ebit", bs_start, bs_end), ("net_worth", bs_start, bs_end),
                        ]
                        if borrowings_val is not None:
                            roce_inputs.append(("borrowings", bs_start, bs_end))
                        add_fact(ExtractedFact(
                            "roce", roce_pct, "PERCENT", bs_start, bs_end, reporting_scope,
                            "xbrl:OneI+FourD:ROCE",
                            formula_version="xbrl-roce-ebit-over-capital-employed-pct-v1",
                            lineage_input_keys=tuple(roce_inputs),
                        ))

    return ParsedXbrlFiling(
        symbol=symbol,
        isin=isin,
        company_name=company_name,
        reporting_scope=reporting_scope,
        audited=audited,
        level_of_rounding=rounding,
        type_of_company=type_of_company,
        class_of_security=class_of_security,
        facts=tuple(extracted),
    )


def ensure_financial_metrics(repository: DuckDBRepository) -> None:
    """Register all standard HAMSA financial metric definitions idempotently."""
    con = repository._connection
    for metric, (unit, dimension, description) in METRIC_DEFINITIONS.items():
        con.execute(
            "INSERT INTO financial_metric_definition VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
            [metric, unit, dimension, description, PARSER_VERSION],
        )


def _resolve_issuer_entity_for_xbrl(
    repository: DuckDBRepository,
    *,
    isin: str | None,
    symbol: str | None,
    period_end: date,
) -> tuple[str | None, str]:
    con = repository._connection
    resolved_isin = isin.strip().upper() if isin and is_valid_isin(isin) else None
    if resolved_isin is None and symbol:
        # Pre-2025 INDAS XBRL files do not embed <ISIN>; resolve via approved
        # effective NSE listing revision for that symbol and period_end, then
        # verify its approved ISIN mapping.
        rows = con.execute(
            """SELECT DISTINCT i.identifier_value
               FROM exchange_listing l
               JOIN exchange_listing_revision lr USING(listing_id)
               JOIN exchange_listing_revision_review lrr
                 ON lrr.listing_revision_id=lr.listing_revision_id
                AND lrr.review_status='approved'
                AND NOT EXISTS (
                  SELECT 1 FROM exchange_listing_revision_review n
                  WHERE n.supersedes_review_id=lrr.listing_revision_review_id
                )
               JOIN security_identifier_revision i ON i.security_id=l.security_id AND i.identifier_type='ISIN'
               JOIN security_identifier_revision_review ir
                 ON ir.identifier_revision_id=i.identifier_revision_id
                AND ir.review_status='approved'
                AND NOT EXISTS (
                  SELECT 1 FROM security_identifier_revision_review s
                  WHERE s.supersedes_review_id=ir.review_id
                )
               WHERE l.exchange='NSE' AND upper(lr.symbol)=?
                 AND lr.effective_from<=? AND (lr.effective_to IS NULL OR lr.effective_to>=?)
                 AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
            [symbol.strip().upper(), period_end, period_end, period_end, period_end],
        ).fetchall()
        if len(rows) == 1:
            resolved_isin = str(rows[0][0]).upper()
        else:
            return None, "missing_or_ambiguous_listing_to_isin_mapping"
    if not resolved_isin:
        return None, "missing_or_invalid_isin"

    mappings = con.execute(
        """SELECT DISTINCT e.issuer_entity_id
           FROM security_identifier_revision i
           JOIN security_identifier_revision_review r
             ON r.identifier_revision_id=i.identifier_revision_id
            AND r.review_status='approved'
            AND NOT EXISTS (
              SELECT 1 FROM security_identifier_revision_review s
              WHERE s.supersedes_review_id=r.review_id
            )
           JOIN equity_security e USING(security_id)
           WHERE i.identifier_type='ISIN' AND i.identifier_value=?
             AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
        [resolved_isin, period_end, period_end],
    ).fetchall()
    if len(mappings) != 1:
        return None, "unresolved_financial_subject"
    return str(mappings[0][0]), "resolved"


def ingest_local_xbrl_file(
    repository: DuckDBRepository,
    source_path: Path,
    *,
    archive_root: Path,
    source_identifier: str,
    source_document_date: date,
    publication_date: date,
    published_at: datetime | None,
    fallback_symbol: str | None = None,
    fallback_scope: str | None = None,
    parser_version: str = PARSER_VERSION,
    retention_authorized: bool = True,
    source_url: str | None = None,
) -> tuple[int, int, int]:
    """Archive, parse, and persist one local NSE XBRL filing into DuckDB.

    Returns (accepted_observations, revised_observations, quarantined_count).
    """
    ensure_financial_metrics(repository)
    registered = register_local_exchange_source(
        repository,
        source_path,
        archive_root=archive_root,
        exchange="NSE",
        dataset="nse_xbrl_financial_results",
        source_identifier=source_identifier,
        source_document_date=source_document_date,
        publication_date=publication_date,
        published_at=published_at,
        source_as_of_date=source_document_date,
        parser_version=parser_version,
        retention_authorized=retention_authorized,
        source_locator=source_url or source_path.name,
        source_metadata={
            "format": "SEBI_NSE_XBRL_XML",
            "source_url": source_url,
            "fallback_symbol": fallback_symbol,
            "fallback_scope": fallback_scope,
        },
    )
    con = repository._connection
    prior_success = con.execute(
        """SELECT 1 FROM source_document_processing_revision
           WHERE source_document_id=? AND parser_version=? AND status='succeeded' LIMIT 1""",
        [registered.source_document_id, parser_version],
    ).fetchone()
    if prior_success is not None:
        return 0, 0, 0

    now = datetime.now().astimezone()
    latest_proc = con.execute(
        """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
           WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""",
        [registered.source_document_id],
    ).fetchone()
    attempt = latest_proc[1] + 1 if latest_proc else 1
    proc_id = "proc-" + sha256(
        f"{registered.source_document_id}|{parser_version}|{attempt}".encode("utf-8")
    ).hexdigest()[:32]

    with repository._transaction():
        con.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,
                status,accepted_count,rejected_count,quarantined_count,supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,'started',0,0,0,?)""",
            [proc_id, registered.source_document_id, parser_version, attempt, now,
             latest_proc[0] if latest_proc else None],
        )

    try:
        parsed = parse_nse_xbrl_bytes(
            source_path.read_bytes(),
            fallback_symbol=fallback_symbol,
            fallback_scope=fallback_scope,
        )
    except Exception as exc:
        with repository._transaction():
            con.execute(
                """UPDATE source_document_processing_revision
                   SET completed_at=?,status='failed',rejected_count=1,error_summary=?
                   WHERE processing_revision_id=?""",
                [datetime.now().astimezone(), str(exc)[:1000], proc_id],
            )
        raise

    subject_id, reason = _resolve_issuer_entity_for_xbrl(
        repository,
        isin=parsed.isin,
        symbol=parsed.symbol or fallback_symbol,
        period_end=source_document_date,
    )
    if subject_id is None or not parsed.facts:
        q_reason = reason if subject_id is None else "empty_xbrl_financial_facts"
        qid = "q-" + sha256(f"{registered.source_document_id}|{parser_version}|{q_reason}".encode("utf-8")).hexdigest()[:32]
        with repository._transaction():
            con.execute(
                """INSERT INTO observation_quarantine
                   (quarantine_id,source_document_id,source_locator,reason_code,detail,quarantined_at)
                   VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                [qid, registered.source_document_id, "$", q_reason,
                 f"symbol={parsed.symbol}, isin={parsed.isin}, facts={len(parsed.facts)}", now],
            )
            con.execute(
                """UPDATE source_document_processing_revision
                   SET completed_at=?,status='succeeded',accepted_count=0,rejected_count=0,quarantined_count=1
                   WHERE processing_revision_id=?""",
                [datetime.now().astimezone(), proc_id],
            )
        return 0, 0, 1

    accepted = revised = 0
    obs_id_by_key: dict[tuple[str, date, date], str] = {}
    # Insert reported facts first so derived facts in the same filing can link to their observation IDs
    ordered_facts = sorted(parsed.facts, key=lambda f: (f.formula_version is not None, f.metric))

    with repository._transaction():
        for fact in ordered_facts:
            existing = con.execute(
                """SELECT current.observation_id,current.revision_number,current.canonical_value,current.source_document_id
                   FROM financial_observation_revision current
                   WHERE current.subject_entity_id=? AND current.metric=? AND current.period_start=?
                     AND current.period_end=? AND current.reporting_scope=?
                     AND NOT EXISTS (
                       SELECT 1 FROM financial_observation_revision child
                       WHERE child.supersedes_observation_id=current.observation_id
                     )
                   ORDER BY current.revision_number DESC LIMIT 1""",
                [subject_id, fact.metric, fact.period_start, fact.period_end, fact.reporting_scope],
            ).fetchall()

            parent_obs_id = None
            rev_num = 1
            status = AsReportedStatus.ORIGINAL
            if existing:
                prior_obs_id, prior_rev_num, prior_val, prior_doc_id = existing[0]
                if prior_doc_id == registered.source_document_id:
                    obs_id_by_key[(fact.metric, fact.period_start, fact.period_end)] = str(prior_obs_id)
                    continue
                if prior_val is not None and Decimal(str(prior_val)) == fact.value:
                    # Identical restated/re-reported value in a subsequent filing:
                    # retain existing active observation ID for lineage without
                    # creating a redundant restatement revision.
                    obs_id_by_key[(fact.metric, fact.period_start, fact.period_end)] = str(prior_obs_id)
                    continue
                parent_obs_id = str(prior_obs_id)
                rev_num = int(prior_rev_num) + 1
                status = AsReportedStatus.RESTATEMENT

            obs_id = "fin-" + sha256(
                f"{registered.source_document_id}|{parser_version}|{fact.metric}|{fact.period_start.isoformat()}|{fact.period_end.isoformat()}|{fact.reporting_scope}".encode("utf-8")
            ).hexdigest()[:32]

            lineage_inputs: list[tuple[str, str]] = []
            if fact.formula_version is not None:
                for dep_key in fact.lineage_input_keys:
                    if dep_key in obs_id_by_key:
                        lineage_inputs.append((obs_id_by_key[dep_key], "financial"))
                if not lineage_inputs:
                    continue

            obs = FinancialObservationRevision(
                observation_id=obs_id,
                subject_id=subject_id,
                metric=fact.metric,
                raw_value=fact.value,
                raw_unit=fact.canonical_unit,
                canonical_value=fact.value,
                canonical_unit=fact.canonical_unit,
                period_start=fact.period_start,
                period_end=fact.period_end,
                source_document_date=source_document_date,
                publication_date=publication_date,
                publication_precision=PublicationPrecision.TIMESTAMP if published_at else PublicationPrecision.DATE_ONLY,
                published_at=published_at,
                ingestion_timestamp=now,
                revision_number=rev_num,
                source_document_id=registered.source_document_id,
                as_reported_status=status,
                quality_status=QualityStatus.OBSERVED,
                reporting_scope=fact.reporting_scope,
                source_locator=fact.locator,
                parser_version=parser_version,
                extraction_timestamp=now,
                supersedes_observation_id=parent_obs_id,
                formula_version=fact.formula_version,
            )
            repository.append_financial_observation(
                obs,
                lineage_inputs=lineage_inputs,
                extraction_revision_id=proc_id,
            )
            obs_id_by_key[(fact.metric, fact.period_start, fact.period_end)] = obs_id
            accepted += int(parent_obs_id is None)
            revised += int(parent_obs_id is not None)

        con.execute(
            """UPDATE source_document_processing_revision
               SET completed_at=?,status='succeeded',accepted_count=?,rejected_count=0,quarantined_count=0
               WHERE processing_revision_id=?""",
            [datetime.now().astimezone(), accepted + revised, proc_id],
        )
    return accepted, revised, 0


def discover_nse_xbrl_filings_for_symbol(
    symbol: str,
    *,
    min_period_end: date = date(2022, 3, 31),
    timeout: int = 20,
) -> list[NseXbrlFilingMetadata]:
    """Query NSE's public filing indices (Integrated Filings + Legacy Results) for one symbol."""
    clean_symbol = symbol.strip().upper()
    discovered: dict[str, NseXbrlFilingMetadata] = {}

    def fetch_json(url: str):
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # 1. Post-2024 Integrated Filings (Financials)
    q_sym = urllib.parse.quote(clean_symbol)
    int_url = (
        f"https://www.nseindia.com/api/integrated-filing-results"
        f"?index=equities&type=Integrated%20Filing-%20Financials&symbol={q_sym}&page=1&size=50"
    )
    try:
        int_payload = fetch_json(int_url)
        rows = int_payload.get("data", []) if isinstance(int_payload, dict) else []
    except Exception:
        rows = []

    for row in rows:
        xbrl_url = str(row.get("xbrl") or "").strip()
        if not xbrl_url or not xbrl_url.lower().endswith(".xml"):
            continue
        p_end = _parse_iso_or_dmy_date(str(row.get("qe_Date") or ""))
        if p_end is None or p_end < min_period_end:
            continue
        bcast_raw = str(row.get("broadcast_Date") or row.get("creation_Date") or "")
        pub_date, pub_at = parse_nse_broadcast_timestamp(bcast_raw, fallback_date=p_end)
        scope = "consolidated" if str(row.get("consolidated") or "").strip().lower().startswith("con") else "standalone"
        audited = str(row.get("audited") or "").strip().lower() == "audited"
        is_rev = str(row.get("type_Sub") or "").strip().lower() != "original"
        seq_id = str(row.get("seq_Id") or Path(urllib.parse.urlparse(xbrl_url).path).stem)
        source_id = f"NSE-IF-{clean_symbol}-{seq_id}"
        discovered[xbrl_url] = NseXbrlFilingMetadata(
            symbol=clean_symbol,
            company_name=str(row.get("cmName") or "").strip() or None,
            source_identifier=source_id,
            xbrl_url=xbrl_url,
            period_start=None,
            period_end=p_end,
            reporting_scope=scope,
            audited=audited,
            is_revision=is_rev,
            publication_date=pub_date,
            published_at=pub_at,
        )

    # 2. Pre-2025 Corporate Financial Results (Annual + Quarterly)
    for period_param in ("Annual", "Quarterly"):
        old_url = (
            f"https://www.nseindia.com/api/corporates-financial-results"
            f"?index=equities&symbol={q_sym}&period={period_param}"
        )
        try:
            old_rows = fetch_json(old_url)
            if not isinstance(old_rows, list):
                old_rows = []
        except Exception:
            old_rows = []

        for row in old_rows:
            xbrl_url = str(row.get("xbrl") or "").strip()
            if not xbrl_url or xbrl_url == "-" or not xbrl_url.lower().endswith(".xml"):
                continue
            p_end = _parse_iso_or_dmy_date(str(row.get("toDate") or ""))
            p_start = _parse_iso_or_dmy_date(str(row.get("fromDate") or ""))
            if p_end is None or p_end < min_period_end:
                continue
            # Keep pre-2025 annuals back to min_period_end, and quarterlies from 2024-01-01 onwards
            if period_param == "Quarterly" and p_end < date(2024, 3, 31) and p_end.month != 3:
                continue
            if xbrl_url in discovered:
                continue
            bcast_raw = str(row.get("broadCastDate") or row.get("filingDate") or "")
            pub_date, pub_at = parse_nse_broadcast_timestamp(bcast_raw, fallback_date=p_end)
            cons_raw = str(row.get("consolidated") or "").strip().lower()
            scope = "consolidated" if cons_raw == "consolidated" else "standalone"
            audited = str(row.get("audited") or "").strip().lower() == "audited"
            seq_num = str(row.get("seqNumber") or Path(urllib.parse.urlparse(xbrl_url).path).stem)
            source_id = f"NSE-CFR-{clean_symbol}-{seq_num}"
            discovered[xbrl_url] = NseXbrlFilingMetadata(
                symbol=clean_symbol,
                company_name=str(row.get("companyName") or "").strip() or None,
                source_identifier=source_id,
                xbrl_url=xbrl_url,
                period_start=p_start,
                period_end=p_end,
                reporting_scope=scope,
                audited=audited,
                is_revision=False,
                publication_date=pub_date,
                published_at=pub_at,
            )

    return sorted(
        discovered.values(),
        key=lambda m: (
            m.period_end,
            m.publication_date,
            m.published_at.timestamp() if m.published_at else 0.0,
            m.source_identifier,
        ),
    )


def fetch_and_ingest_symbols(
    repository: DuckDBRepository,
    symbols: Iterable[str],
    *,
    download_cache_dir: Path,
    archive_root: Path,
    min_period_end: date = date(2022, 3, 31),
    preferred_scope: str | None = None,
    delay_seconds: float = 0.25,
) -> XbrlIngestionSummary:
    """Discover, cache, archive, and ingest NSE XBRL filings for a batch of symbols."""
    download_cache_dir.mkdir(parents=True, exist_ok=True)
    archive_root.mkdir(parents=True, exist_ok=True)
    summary = XbrlIngestionSummary()

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        try:
            filings = discover_nse_xbrl_filings_for_symbol(symbol, min_period_end=min_period_end)
        except Exception as exc:
            summary.filings_failed += 1
            summary.errors.append(f"{symbol}: discovery failed: {exc}")
            continue

        if preferred_scope in ("consolidated", "standalone"):
            scoped = [f for f in filings if f.reporting_scope == preferred_scope]
            # Fall back to standalone if a company has no consolidated filings
            filings = scoped if scoped else filings

        for meta in filings:
            summary.filings_processed += 1
            filename = Path(urllib.parse.urlparse(meta.xbrl_url).path).name
            cached_path = download_cache_dir / symbol / filename
            cached_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path = cached_path.with_suffix(".meta.json")

            try:
                if not cached_path.is_file():
                    req = urllib.request.Request(meta.xbrl_url, headers=_HEADERS)
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        xml_bytes = resp.read()
                    cached_path.write_bytes(xml_bytes)
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)
                sidecar_path.write_text(
                    json.dumps({
                        "symbol": meta.symbol,
                        "company_name": meta.company_name,
                        "source_identifier": meta.source_identifier,
                        "xbrl_url": meta.xbrl_url,
                        "period_start": meta.period_start.isoformat() if meta.period_start else None,
                        "period_end": meta.period_end.isoformat(),
                        "reporting_scope": meta.reporting_scope,
                        "audited": meta.audited,
                        "is_revision": meta.is_revision,
                        "publication_date": meta.publication_date.isoformat(),
                        "published_at": meta.published_at.isoformat() if meta.published_at else None,
                    }, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                acc, rev, quar = ingest_local_xbrl_file(
                    repository,
                    cached_path,
                    archive_root=archive_root,
                    source_identifier=meta.source_identifier,
                    source_document_date=meta.period_end,
                    publication_date=meta.publication_date,
                    published_at=meta.published_at,
                    fallback_symbol=meta.symbol,
                    fallback_scope=meta.reporting_scope,
                    retention_authorized=True,
                    source_url=meta.xbrl_url,
                )
                if quar > 0:
                    summary.filings_quarantined += 1
                elif acc == 0 and rev == 0:
                    summary.filings_duplicated += 1
                else:
                    summary.filings_succeeded += 1
                    summary.observations_accepted += acc
                    summary.observations_revised += rev
            except urllib.error.HTTPError as exc:
                summary.filings_failed += 1
                summary.errors.append(f"{symbol} ({meta.source_identifier}): HTTP {exc.code}")
            except Exception as exc:
                summary.filings_failed += 1
                summary.errors.append(f"{symbol} ({meta.source_identifier}): {exc}")

    return summary
