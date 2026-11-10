"""Parsers for publicly downloadable official NSE/BSE EOD files.

Only end-of-day files are accepted. The functions return source field values
plus exact archive-member/CSV-line locators; identity resolution remains an
explicit ingestion step.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence
from zipfile import BadZipFile, ZipFile


def _decimal(value: str, field: str) -> str:
    value = (value or "").strip()
    if value in {"", "-", "--"}:
        return ""
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field} value {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"non-finite {field} value")
    return str(parsed)


def _optional_integer(value: str) -> str:
    value = (value or "").strip()
    if value in {"", "-", "--"}:
        return ""
    if not value.isdigit():
        raise ValueError(f"invalid integer quantity {value!r}")
    return value


def _read_csv_bytes(content: bytes, *, encoding: str = "utf-8-sig") -> tuple[list[dict[str, str]], list[int]]:
    import io

    reader = csv.DictReader(io.StringIO(content.decode(encoding), newline=""), strict=True)
    if not reader.fieldnames:
        raise ValueError("missing CSV header")
    fields = [name.strip() for name in reader.fieldnames]
    if len(fields) != len(set(fields)):
        raise ValueError("duplicate CSV header")
    rows, lines = [], []
    for row in reader:
        if None in row:
            raise ValueError(f"extra CSV fields at line {reader.line_num}")
        rows.append({key.strip(): (value or "").strip() for key, value in row.items()})
        lines.append(reader.line_num)
    return rows, lines


def parse_nse_udiff(path: Path, *, allowed_series: set[str], isin_allowlist: set[str] | None = None) -> tuple[list[dict[str, str]], list[int], int]:
    """Parse NSE CM UDiFF bhavcopy; non-allowlisted series are counted out of scope."""
    try:
        with ZipFile(path) as archive:
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(csv_members) != 1:
                raise ValueError(f"expected one CSV member in NSE UDiFF ZIP, found {len(csv_members)}")
            member = csv_members[0]
            raw, lines = _read_csv_bytes(archive.read(member))
    except BadZipFile as exc:
        raise ValueError("malformed NSE UDiFF ZIP archive") from exc
    required = {"TradDt", "Sgmt", "FinInstrmTp", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs",
                "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal"}
    if not raw or not required.issubset(raw[0]):
        raise ValueError(f"NSE UDiFF header missing: {', '.join(sorted(required - set(raw[0] if raw else [])))}")
    rows: list[dict[str, str]] = []
    excluded = 0
    for row, line in zip(raw, lines):
        if (row["Sgmt"] != "CM" or row["FinInstrmTp"] != "STK" or row["SctySrs"] not in allowed_series
                or (isin_allowlist is not None and row["ISIN"].upper() not in isin_allowlist)):
            excluded += 1
            continue
        try:
            trade_day = datetime.strptime(row["TradDt"], "%Y-%m-%d").date().isoformat()
            values = {"trade_date": trade_day, "exchange": "NSE", "instrument_id": row["FinInstrmId"],
                      "symbol": row["TckrSymb"], "isin": row["ISIN"], "series": row["SctySrs"],
                      "open": _decimal(row["OpnPric"], "open"), "high": _decimal(row["HghPric"], "high"),
                      "low": _decimal(row["LwPric"], "low"), "close": _decimal(row["ClsPric"], "close"),
                      "volume": row["TtlTradgVol"], "turnover": _decimal(row["TtlTrfVal"], "turnover"),
                      "price_unit": "INR_PER_SHARE", "volume_unit": "SHARES", "turnover_unit": "INR",
                      "_source_locator": f"zip:{member}:csv:line:{line}"}
        except (ValueError, KeyError) as exc:
            values = {"_parse_error": str(exc), "_source_locator": f"zip:{member}:csv:line:{line}"}
        if "_parse_error" not in values and (not values["isin"] or not values["instrument_id"] or not values["symbol"]):
            values["isin"] = values["isin"] or ""
        rows.append(values)
    return rows, list(range(1, len(rows) + 1)), excluded


def parse_nse_delivery(path: Path, *, symbols_allowlist: set[str] | None = None) -> tuple[list[dict[str, str]], list[int], int]:
    raw_bytes = path.read_bytes()
    rows, lines = _read_csv_bytes(raw_bytes)
    # NSE full bhavdata headers intentionally include leading spaces.
    required = {"SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"NSE delivery header missing: {', '.join(sorted(required - set(rows[0] if rows else [])))}")
    result = []
    result_lines = []
    excluded = 0
    for row, line in zip(rows, lines):
        if symbols_allowlist is not None and row.get("SYMBOL", "").upper() not in symbols_allowlist:
            excluded += 1
            continue
        try:
            parsed = {"trade_date": datetime.strptime(row["DATE1"], "%d-%b-%Y").date().isoformat(),
                      "exchange": "NSE", "symbol": row["SYMBOL"], "series": row["SERIES"],
                      "volume": _optional_integer(row["TTL_TRD_QNTY"]), "delivery_quantity": _optional_integer(row["DELIV_QTY"]),
                      "delivery_percentage": _decimal(row["DELIV_PER"], "delivery percentage")}
        except (ValueError, KeyError) as exc:
            parsed = {"_parse_error": str(exc)}
        parsed["_source_locator"] = f"csv:line:{line}"
        result.append(parsed)
        result_lines.append(line)
    return result, result_lines, excluded


def parse_bse_stock_prices(path: Path, *, listing_mapping: Mapping[str, str] | Sequence[Mapping[str, str]] | None) -> tuple[list[dict[str, str]], list[int]]:
    """Parse BSE per-scrip stock-history export with an explicit code-to-ISIN map.

    The CSV itself has no scrip code, symbol or ISIN. A mapping must be passed
    from an independently reviewed BSE listing lookup/security master.
    """
    rows, lines = _read_csv_bytes(path.read_bytes())
    required = {"Date", "Open Price", "High Price", "Low Price", "Close Price", "No.of Shares", "Total Turnover (Rs.)"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"BSE stock-history header missing: {', '.join(sorted(required - set(rows[0] if rows else [])))}")
    mapping: dict[str, str] | None = None
    mapping_error: str | None = None
    if listing_mapping is None:
        mapping_error = "missing BSE listing mapping"
    elif isinstance(listing_mapping, Mapping):
        mapping = dict(listing_mapping)
    elif isinstance(listing_mapping, Sequence) and not isinstance(listing_mapping, (str, bytes)):
        candidates = [dict(item) for item in listing_mapping if isinstance(item, Mapping)]
        if len(candidates) != len(listing_mapping):
            mapping_error = "invalid or incomplete BSE listing mapping collection"
        fingerprints = {tuple(sorted((key, str(value)) for key, value in item.items())) for item in candidates}
        if mapping_error is None and len(fingerprints) > 1:
            mapping_error = "ambiguous or conflicting BSE listing mappings"
        elif mapping_error is None and candidates:
            mapping = candidates[0]
        elif mapping_error is None:
            mapping_error = "missing BSE listing mapping"
    else:
        mapping_error = "invalid BSE listing mapping type"
    required_mapping = {"instrument_id", "symbol", "isin", "effective_from", "evidence_reference"}
    if mapping_error is None and mapping is not None:
        missing = required_mapping - set(mapping)
        if missing:
            mapping_error = f"BSE listing mapping missing fields: {', '.join(sorted(missing))}"
        elif not all(str(mapping[key]).strip() for key in required_mapping):
            mapping_error = "BSE listing mapping contains blank required values"
        else:
            from hamsa.domain.security import is_valid_isin
            if not is_valid_isin(str(mapping["isin"])):
                mapping_error = "BSE listing mapping has an invalid ISIN"
            try:
                date.fromisoformat(str(mapping["effective_from"]))
            except ValueError:
                mapping_error = "BSE listing mapping has an invalid effective_from date"
    output = []
    for row, line in zip(rows, lines):
        try:
            if mapping_error:
                raise ValueError(mapping_error)
            assert mapping is not None
            parsed_date = datetime.strptime(row["Date"], "%d-%B-%Y").date()
            parsed = {"trade_date": parsed_date.isoformat(), "exchange": "BSE",
                      "instrument_id": mapping["instrument_id"], "symbol": mapping["symbol"],
                      "isin": mapping["isin"], "series": "EQ",
                      "open": _decimal(row["Open Price"], "open"), "high": _decimal(row["High Price"], "high"),
                      "low": _decimal(row["Low Price"], "low"), "close": _decimal(row["Close Price"], "close"),
                      "volume": _optional_integer(row["No.of Shares"]), "turnover": _decimal(row["Total Turnover (Rs.)"], "turnover"),
                      "price_unit": "INR_PER_SHARE", "volume_unit": "SHARES", "turnover_unit": "INR",
                      "delivery_quantity": _optional_integer(row.get("Deliverable Quantity", "")),
                      "delivery_percentage": _decimal(row.get("% Deli. Qty to Traded Qty", ""), "delivery percentage"),
                      "_mapping_valid": True}
        except (ValueError, KeyError) as exc:
            parsed = {"_parse_error": str(exc)}
        evidence = str(mapping.get("evidence_reference", "unresolved")) if mapping else "unresolved"
        parsed["_source_locator"] = f"csv:line:{line};listing-map:{evidence}"
        output.append(parsed)
    return output, lines
