"""Reusable helpers for reading one series from the ABS.

Two kinds of source are handled:

1. The ABS Data API (SDMX CSV). `parse_sdmx_series` checks that every dimension column holds
   the one expected code, then returns the series as (period, value text) pairs.
2. The ABS time series spreadsheets (the "Table 1" style .xlsx files). `parse_spreadsheet_series`
   finds one column by its series ID (for example A84423050A) and returns its months.

`cross_check` compares the two, month by month, after rounding both the same way.

Every function raises ScrapeError on anything unexpected. Callers must catch it and write nothing.
No figure is typed here: every value comes from the downloaded bytes.

Rounding: the ABS API gives long decimals (6.64467408) and a DECIMALS column saying how many the
ABS publishes (1). The value is rounded to that many places with Python's Decimal and ROUND_HALF_UP,
so a figure that sits exactly on a half rounds up, as the ABS publishes it.
"""
import calendar
import csv
import io
import re
import time
from collections import namedtuple
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

import requests

ACCEPT_SDMX = "application/vnd.sdmx.data+csv"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gov-metrics-scraper"
MONTH_RE = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
QUARTER_RE = re.compile(r"(\d{4})-Q([1-4])")
PERIOD_RES = {"M": MONTH_RE, "Q": QUARTER_RE}
VALUE_RE = re.compile(r"-?\d+(\.\d+)?")


class ScrapeError(Exception):
    """Something is wrong with the source or the data. Nothing gets written."""


# What parse_sdmx_series returns: pairs is [(period, rounded value text)] sorted by period;
# decimals maps each period to the DECIMALS figure of its row; raw_values maps each period to the
# API's own OBS_VALUE text.
SdmxSeries = namedtuple("SdmxSeries", "pairs decimals raw_values")


# ---------------------------------------------------------------- downloading

def fetch(url, accept="*/*"):
    """Downloads a URL and returns its bytes. Three attempts for network errors; any answer other
    than HTTP 200 is an immediate refusal (the same pattern as cpi_june.py)."""
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": USER_AGENT, "Accept": accept})
        except requests.RequestException as e:
            last = e
            time.sleep(2)
            continue
        if r.status_code != 200:
            raise ScrapeError(f"{url} answered HTTP {r.status_code}")
        return r.content
    raise ScrapeError(f"{url} could not be downloaded: {last}")


# ---------------------------------------------------------------- small helpers

def round_half_up(text, decimals):
    """Rounds the number written in `text` to `decimals` places (ROUND_HALF_UP). Returns the text,
    keeping trailing zeros (4.0 stays "4.0")."""
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ScrapeError(f"unreadable number {text!r}") from None
    if not d.is_finite():
        raise ScrapeError(f"unreadable number {text!r}")
    if not isinstance(decimals, int) or not 0 <= decimals <= 6:
        raise ScrapeError(f"unexpected number of decimal places {decimals!r}")
    q = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)  # never "-0.0"
    return format(q, "f")


def month_end(period):
    """'1978-02' -> '1978-02-28' (the last day of the month, leap years included)."""
    m = MONTH_RE.fullmatch(period)
    if not m:
        raise ScrapeError(f"unexpected month label {period!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"


def next_month(period):
    y, mo = int(period[:4]), int(period[5:7])
    return f"{y + 1:04d}-01" if mo == 12 else f"{y:04d}-{mo + 1:02d}"


def quarter_end(period):
    """'1950-Q1' -> '1950-03-31' (the last day of the quarter)."""
    m = QUARTER_RE.fullmatch(period)
    if not m:
        raise ScrapeError(f"unexpected quarter label {period!r}")
    y, q = int(m.group(1)), int(m.group(2))
    return month_end(f"{y:04d}-{q * 3:02d}")


def next_quarter(period):
    y, q = int(period[:4]), int(period[6])
    return f"{y + 1:04d}-Q1" if q == 4 else f"{y:04d}-Q{q + 1}"


def previous_quarter(period, n=1):
    """The quarter n quarters before `period` ('2026-Q3', 4 -> '2025-Q3')."""
    if not QUARTER_RE.fullmatch(period):
        raise ScrapeError(f"unexpected quarter label {period!r}")
    total = int(period[:4]) * 4 + int(period[6]) - 1 - n
    return f"{total // 4:04d}-Q{total % 4 + 1}"


def require_no_missing_quarters(periods, label):
    """Raises if a quarter is missing between the first and the last of `periods`."""
    ordered = sorted(periods)
    if not ordered:
        raise ScrapeError(f"{label}: no quarters found")
    have = set(ordered)
    missing = []
    p = ordered[0]
    while p < ordered[-1]:
        p = next_quarter(p)
        if p not in have:
            missing.append(p)
    if missing:
        shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
        raise ScrapeError(f"{label}: missing quarters {shown}")


def require_no_missing_months(periods, label):
    """Raises if a month is missing between the first and the last of `periods`."""
    ordered = sorted(periods)
    if not ordered:
        raise ScrapeError(f"{label}: no months found")
    have = set(ordered)
    missing = []
    p = ordered[0]
    while p < ordered[-1]:
        p = next_month(p)
        if p not in have:
            missing.append(p)
    if missing:
        shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
        raise ScrapeError(f"{label}: missing months {shown}")


# ---------------------------------------------------------------- the Data API

def parse_sdmx_series(raw, expected, label="the ABS Data API response", freq="M", blank_decimals=None):
    """Reads one series from an SDMX CSV response.

    `expected` maps each dimension column (and any other column that must be constant, such as
    UNIT_MEASURE) to its one allowed text, for example {"MEASURE": "M13", "SEX": "3"}. A value
    that is a callable is called with the cell text and must return true.

    Refuses on: a response that is not text; missing columns; any unexpected code; a month label
    that is not YYYY-MM; a duplicate month; a missing month inside the series; an unreadable
    value or DECIMALS.

    `freq` is "M" (periods like 2026-09, the default) or "Q" (periods like 2026-Q3).

    `blank_decimals` says what to do when the DECIMALS cell is empty (the ABS CPI dataflows leave it
    empty; the Labour Force one fills it). None (the default) refuses, as before. An integer N
    accepts the figure only if the API's own text already has at most N decimal places, and writes
    it with exactly N (so "4" becomes "4.0"); a figure with more places is refused, never rounded.
    The text "raw" keeps the API's text unchanged (for an index that is used in sums).
    """
    if freq not in PERIOD_RES:
        raise ScrapeError(f"unknown frequency {freq!r}")
    period_re = PERIOD_RES[freq]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    reader = csv.DictReader(io.StringIO(text))
    need = {"TIME_PERIOD", "OBS_VALUE", "DECIMALS", *expected}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        missing = sorted(need - set(reader.fieldnames or []))
        raise ScrapeError(f"{label} lacks the expected columns {missing}; got {reader.fieldnames}")
    raw_values, decimals = {}, {}
    for line_no, row in enumerate(reader, start=2):
        if None in row or any(v is None for v in row.values()):
            raise ScrapeError(f"line {line_no}: the row has the wrong number of fields")
        for col, want in expected.items():
            ok = want(row[col]) if callable(want) else row[col] == want
            if not ok:
                shown = "a different value" if callable(want) else repr(want)
                raise ScrapeError(f"line {line_no}: {col} is {row[col]!r}, expected {shown}. This is not the series asked for.")
        period = row["TIME_PERIOD"]
        if not period_re.fullmatch(period):
            raise ScrapeError(f"line {line_no}: unexpected period {period!r}")
        if period in raw_values:
            raise ScrapeError(f"line {line_no}: period {period} appears twice")
        value = row["OBS_VALUE"].strip()
        if not VALUE_RE.fullmatch(value):
            raise ScrapeError(f"line {line_no}: {period} has an unreadable value {value!r}")
        dec = row["DECIMALS"].strip()
        if dec == "" and blank_decimals is not None:
            if blank_decimals == "raw":
                dec = None
            else:
                places = len(value.split(".")[1]) if "." in value else 0
                if places > blank_decimals:
                    raise ScrapeError(f"line {line_no}: {period} has the figure {value!r} with {places} decimal places and an empty DECIMALS cell; "
                                      f"at most {blank_decimals} are accepted, and nothing is rounded without a DECIMALS figure")
                dec = str(blank_decimals)
        elif not re.fullmatch(r"[0-6]", dec):
            raise ScrapeError(f"line {line_no}: {period} has an unreadable DECIMALS {dec!r}")
        raw_values[period] = value
        decimals[period] = None if dec is None else int(dec)
    (require_no_missing_months if freq == "M" else require_no_missing_quarters)(raw_values.keys(), label)
    pairs = [(p, raw_values[p] if decimals[p] is None else round_half_up(raw_values[p], decimals[p])) for p in sorted(raw_values)]
    return SdmxSeries(pairs, decimals, raw_values)


# ---------------------------------------------------------------- the spreadsheet

def find_link(html_bytes, page_url, ending):
    """Finds the one link on an ABS page whose address ends in `ending` (for example
    '/62020001.xlsx') and returns it as a full address on www.abs.gov.au."""
    try:
        html = html_bytes.decode("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover
        raise ScrapeError(f"the page could not be read: {e}") from None
    found = []
    for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html, re.I):
        href = m.group(1).strip()
        if href.split("#")[0].split("?")[0].endswith(ending):
            full = urljoin(page_url, href)
            if full not in found:
                found.append(full)
    if not found:
        raise ScrapeError(f"no link ending in {ending} was found on {page_url}")
    if len(found) > 1:
        raise ScrapeError(f"more than one link ending in {ending} on {page_url}: {found}")
    u = urlparse(found[0])
    if u.scheme != "https" or u.hostname != "www.abs.gov.au":
        raise ScrapeError(f"the link {found[0]} is not an https address on www.abs.gov.au")
    return found[0]


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip() if s is not None else ""


def parse_spreadsheet_series(raw, series_id, sheet="Data1", expected_meta=None, label="the ABS spreadsheet"):
    """Reads the column with series ID `series_id` from an ABS time series spreadsheet.

    The sheet has a description on row 1, labelled rows (Unit, Series Type, ... Series ID) in column
    A, and one row per month beneath the Series ID row, dated the first of the month.
    `expected_meta` maps text found in column A (for example "Series Type") to the text the column
    must hold, and the key "description" stands for row 1. Whitespace is ignored when comparing.

    Returns {period: number text}, where the number text is the repr of the number in the file.
    A month with an empty cell is left out. Refuses if the sheet or the column is not found, the
    column is found more than once, a month is not a date, a month appears twice, or a value is
    not a number.
    """
    import openpyxl  # imported here so the other helpers work without it

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ScrapeError(f"{label} could not be opened as an Excel file: {e}") from None
    try:
        if sheet not in wb.sheetnames:
            raise ScrapeError(f"{label} has no sheet {sheet!r}; it has {wb.sheetnames}")
        rows = list(wb[sheet].iter_rows(values_only=True))
    finally:
        wb.close()
    id_rows = [i for i, r in enumerate(rows[:30]) if r and _norm(r[0]) == "Series ID"]
    if len(id_rows) != 1:
        raise ScrapeError(f"{label}: expected one 'Series ID' row in the first 30 rows of {sheet}, found {len(id_rows)}")
    id_row = id_rows[0]
    cols = [j for j, v in enumerate(rows[id_row]) if _norm(v) == series_id]
    if len(cols) != 1:
        raise ScrapeError(f"{label}: series ID {series_id} appears {len(cols)} times in {sheet}; expected once")
    col = cols[0]
    labelled = {_norm(r[0]): r for r in rows[:id_row] if r and r[0] is not None}
    for key, want in (expected_meta or {}).items():
        if key == "description":
            got = rows[0][col] if len(rows[0]) > col else None
        else:
            r = labelled.get(key)
            got = r[col] if r is not None and len(r) > col else None
        if _norm(got) != _norm(want):
            raise ScrapeError(f"{label}: column {series_id} has {key} {_norm(got)!r}, expected {_norm(want)!r}. This is not the series asked for.")
    values = {}
    for k, r in enumerate(rows[id_row + 1:], start=id_row + 2):
        if r is None or all(v is None for v in r):
            continue
        d = r[0]
        if not isinstance(d, datetime) or d.day != 1:
            raise ScrapeError(f"{label}: row {k} has {d!r} where the first day of a month was expected")
        period = f"{d.year:04d}-{d.month:02d}"
        if period in values:
            raise ScrapeError(f"{label}: month {period} appears twice")
        v = r[col] if len(r) > col else None
        if v is None or v == "":
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ScrapeError(f"{label}: row {k} ({period}) has an unreadable value {v!r}")
        text = repr(v) if not isinstance(v, str) else v.strip()
        if not VALUE_RE.fullmatch(text):
            raise ScrapeError(f"{label}: row {k} ({period}) has an unreadable value {v!r}")
        values[period] = text
    if not values:
        raise ScrapeError(f"{label}: column {series_id} holds no values")
    require_no_missing_months(values.keys(), f"{label} column {series_id}")
    return values


def find_series_id_by_header(raw, must_contain, sheet="Data1", label="the ABS spreadsheet"):
    """Finds the one column of an ABS time series spreadsheet whose row 1 header contains every
    text in `must_contain` (whitespace is ignored when comparing) and returns its series ID from
    the 'Series ID' row. Refuses if no column, or more than one column, matches."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ScrapeError(f"{label} could not be opened as an Excel file: {e}") from None
    try:
        if sheet not in wb.sheetnames:
            raise ScrapeError(f"{label} has no sheet {sheet!r}; it has {wb.sheetnames}")
        rows = list(wb[sheet].iter_rows(values_only=True))
    finally:
        wb.close()
    id_rows = [i for i, r in enumerate(rows[:30]) if r and _norm(r[0]) == "Series ID"]
    if len(id_rows) != 1:
        raise ScrapeError(f"{label}: expected one 'Series ID' row in the first 30 rows of {sheet}, found {len(id_rows)}")
    needles = [_norm(t) for t in must_contain]
    cols = [j for j, h in enumerate(rows[0]) if all(n in _norm(h) for n in needles)]
    if len(cols) != 1:
        raise ScrapeError(f"{label}: {len(cols)} columns have a header containing {must_contain}; expected exactly one")
    sid = _norm(rows[id_rows[0]][cols[0]]) if len(rows[id_rows[0]]) > cols[0] else ""
    if not sid:
        raise ScrapeError(f"{label}: the column found for {must_contain} has no series ID")
    return sid


# ---------------------------------------------------------------- the second-source check

def cross_check(series, sheet_values, log=print):
    """Compares the API series with a spreadsheet column. Both are rounded the same way (the API
    row's DECIMALS). Every month in both must agree, and the latest month must be the same in both.
    Returns (months compared, first month compared, last month compared)."""
    api = dict(series.pairs)
    sheet_latest, api_latest = max(sheet_values), max(api)
    if sheet_latest != api_latest:
        raise ScrapeError(f"the latest month differs: the API ends at {api_latest}, the spreadsheet at {sheet_latest}")
    common = sorted(set(api) & set(sheet_values))
    if not common:
        raise ScrapeError("the API and the spreadsheet have no month in common")
    bad = []
    for p in common:
        s = round_half_up(sheet_values[p], series.decimals[p])
        if s != api[p]:
            bad.append(f"{p}: API {api[p]} (from {series.raw_values[p]}), spreadsheet {s} (from {sheet_values[p]})")
    if bad:
        shown = "; ".join(bad[:10]) + (f"; and {len(bad) - 10} more" if len(bad) > 10 else "")
        raise ScrapeError(f"the API and the spreadsheet disagree in {len(bad)} month(s): {shown}")
    log(f"Cross-check: {len(common)} months agree ({common[0]} to {common[-1]}); the latest month is {api_latest} in both.")
    return len(common), common[0], common[-1]
