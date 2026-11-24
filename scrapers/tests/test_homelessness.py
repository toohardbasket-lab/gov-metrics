#!/usr/bin/env python3
"""Tests for scrapers/homelessness.py. Plain asserts; pytest also finds them. No network. Fixtures (trimmed copies of
the real RoGS 2026 section 19 files; built by claude/make_hl_fixtures.py from the downloads):
  rogs-homelessness-trimmed.csv   table 19A.2 (the Total rows for 2011, 2016 and 2021: rate, number and proportion, and the
                                  severely-crowded rows as decoys), table 19A.10 (2022-23 to 2024-25: total clients, and the
                                  accommodation and other-services rows) and table 19A.11 (2022-23 to 2024-25), every column
  rogs-homelessness-trimmed.xlsx  sheets 'Table 19A.2', 'Table 19A.10', 'Table 19A.11' in the real layout (all years)
  rogs-front.html                 the RoGS front page links
The scraper's FIRST_YEAR is set to 2022 so the trimmed CSV gives a three-year run of service figures."""
import csv
import io
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import abs_series as a  # noqa: E402
import homelessness as hl  # noqa: E402
import rogs  # noqa: E402

FX = HERE / "fixtures"
CSV = (FX / "rogs-homelessness-trimmed.csv").read_bytes()
XLSX = (FX / "rogs-homelessness-trimmed.xlsx").read_bytes()
FRONT = (FX / "rogs-front.html").read_bytes()
CSV_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-partg-section19-homelessness-services-dataset.csv?VersionId=oou7gCfLtIUjLTYmqVgZgevEBezJo44g"
XLSX_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-partg-section19-homelessness-services-data-tables.xlsx?VersionId=8l3O8_q4Kf08VTCrI2wlAS5Mv1SinIHQ"
P2026 = rogs.FRONT_URL + "2026/data-downloads/"
D2026 = f'<html><a href="{CSV_URL}">dataset</a><a href="{XLSX_URL}">tables</a><a href="https://assets.pc.gov.au/2026-01/rogs-2026-partg-section19-homelessness-services-report.pdf">pdf</a></html>'.encode()
hl.FIRST_YEAR = 2022
quiet = lambda m: None  # noqa: E731


def raises(fn, *a_, **kw):
    try:
        fn(*a_, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError("expected ScrapeError")


def fetcher(csv_=CSV, xlsx=XLSX):
    table = {rogs.FRONT_URL: FRONT, P2026: D2026, CSV_URL: csv_, XLSX_URL: xlsx}

    def f(url, accept="*/*"):
        if url not in table:
            raise AssertionError(f"unexpected download {url}")
        return table[url]
    return f


def run_in(root, **kw):
    return hl.run(root=root, fetcher=fetcher(**kw), log=quiet)


def rows_of(root):
    return list(csv.DictReader(io.StringIO((Path(root) / "metrics/homelessness/data.csv").read_text())))


def write_csv(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(rows)
    return buf.getvalue().encode("utf-8")


def edit_csv(raw, where, year, column, value, nth=0):
    """Changes one figure in the CSV: the rows whose columns equal `where` in the given year."""
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    head = rows[0]
    hits = [r for r in rows[1:] if r[head.index("Year")] == year and all(r[head.index(k)] == v for k, v in where.items())]
    hits[nth][head.index(column)] = value
    return write_csv(rows)


def change_xlsx(raw, sheet, labels, year, column, value):
    """Changes one figure in the workbook: the figure row whose own label starts with labels[-1], under the label row that starts
    with labels[0] when there are two labels, in the block of `year` (a label row of its own above its figures)."""
    import openpyxl
    clean = lambda v: str(v).replace("\xa0", " ").strip()  # noqa: E731
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb[sheet]
    header = next(r for r in ws.iter_rows(min_row=1, max_row=8) if any(c.value == "Unit" for c in r))
    unit_col = next(c.column for c in header if c.value == "Unit")
    col = next(c.column for c in header if c.value and clean(c.value).startswith(column))
    block, parent = None, None  # the year of the block, and the last label row above the figure (the year row may come before or after it)
    for r in ws.iter_rows(min_row=1):
        lab = [clean(c.value) for c in r[: unit_col - 1] if c.value is not None]
        has_unit = r[unit_col - 1].value is not None
        if not lab:
            continue
        if not has_unit and any(re.fullmatch(r"\d{4}(-\d{2})?( \(\w\))?", t) for t in lab):
            block = re.match(r"\d{4}(-\d{2})?", next(t for t in lab if re.match(r"\d{4}", t))).group(0)
            continue
        if not has_unit:
            parent = lab[0]
            continue
        if block == year and lab[-1].split(" (")[0] == labels[-1] and (len(labels) == 1 or (parent or "").startswith(labels[0].split(" (")[0][:20])):
            ws.cell(r[0].row, col).value = value
            break
    else:
        raise AssertionError("cell not found")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


RATE = {"Table_Number": "19A.2", "Description3": "Rate per 10000 people in the population", "Description4": "Total"}
NUMBER = {"Table_Number": "19A.2", "Description3": "Number", "Description4": "Total"}
CLIENTS = {"Table_Number": "19A.10", "Description1": "Total clients"}
UNMET = {"Table_Number": "19A.10", "Description1": "Accommodation services", "Description3": "Proportion of clients with unmet need"}
ACCOM = {"Table_Number": "19A.11", "Description1": "Accommodation services"}


# ---------------------------------------------------------------- a full run

def test_a_full_run_selects_each_series_dates_it_and_stores_codes_as_published():
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root)
        rows = rows_of(root)
        assert len(rows) == (2 * 3 + 5 * 3) * 9  # two Census series x 3 Censuses, five service series x 3 years, nine jurisdictions
        get = lambda s, j, p: next(r for r in rows if (r["series"], r["jurisdiction"], r["period"]) == (s, j, p))  # noqa: E731
        # each series, Australia, latest period, with its unit and date
        for sid, per, want, unit, date in [
            ("census_homeless_rate", "2021", "48.2", "rate", "2021-08-10"),
            ("census_homeless_number", "2021", "122494", "count", "2021-08-10"),
            ("clients", "2024-25", "288970", "count", "2025-06-30"),
            ("unmet_accommodation_pct", "2024-25", "33.2", "pct", "2025-06-30"),
            ("unassisted_accommodation_daily", "2024-25", "232.0", "per_day", "2025-06-30"),
            ("unassisted_other_daily", "2024-25", "79.4", "per_day", "2025-06-30"),
            ("unassisted_no_need_daily", "2024-25", "41.7", "per_day", "2025-06-30"),
        ]:
            r = get(sid, "Australia", per)
            assert (r["value"], r["unit"], r["date"], r["status"]) == (want, unit, date, "actual"), (sid, r)
        # the Census nights, from the map
        assert {r["date"] for r in rows if r["series"] == "census_homeless_rate"} == {"2011-08-09", "2016-08-09", "2021-08-10"}
        assert {r["period"] for r in rows if r["series"] == "census_homeless_rate"} == {"2011", "2016", "2021"}
        # the other rows of the same table are not selected: the proportion (100.0) and the crowded-dwellings rows
        assert all(r["value"] != "100.0" for r in rows)
        assert get("census_homeless_rate", "Australia", "2016")["value"] == "49.8"
        assert get("census_homeless_rate", "Northern Territory", "2021")["value"] == "563.6"
        assert get("clients", "Victoria", "2024-25")["value"] == "105126"
        assert get("unmet_accommodation_pct", "New South Wales", "2024-25")["value"] == "46.6"
        # the Commission prints a true zero as a plain 0 in the one-decimal table; it is stored as published
        assert get("unassisted_no_need_daily", "South Australia", "2024-25")["value"] == "0"
        assert out["checked"] == {"census_homeless_rate": 27, "census_homeless_number": 27, **{s: 27 for s in hl.SERIES if hl.SERIES[s]["kind"] == "service"}}
        assert out["codes"] == []
        man = json.loads((Path(root) / "metrics/homelessness/sources/manifest.json").read_text())
        assert man["rogs-editions"] == {"editions": {"2011": "2026", "2016": "2026", "2021": "2026", "2022-23": "2026", "2023-24": "2026", "2024-25": "2026"}}
        assert man["rogs-2026-partg-section19-homelessness-services-data-tables.xlsx"]["url"] == XLSX_URL
        assert (Path(root) / "metrics/homelessness/sources/rogs-2026-partg-section19-homelessness-services-dataset.csv").read_bytes() == CSV  # byte for byte


def test_a_second_run_is_byte_identical():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        files = lambda: {p.name: p.read_bytes() for p in (Path(root) / "metrics/homelessness").rglob("*") if p.is_file()}  # noqa: E731
        one = files()
        run_in(root)
        assert files() == one


# ---------------------------------------------------------------- the Census dates

def test_each_census_night_comes_from_the_map_and_an_unknown_census_is_refused():
    assert hl.census_date("2011") == "2011-08-09" and hl.census_date("2016") == "2016-08-09" and hl.census_date("2021") == "2021-08-10"
    assert "not in CENSUS_NIGHT" in raises(hl.census_date, "2026")
    assert "not a Census year" in raises(hl.census_date, "2021-22")
    saved = dict(hl.CENSUS_NIGHT)
    try:
        del hl.CENSUS_NIGHT["2021"]
        with tempfile.TemporaryDirectory() as root:
            msg = raises(run_in, root)
            assert "Census year 2021 is not in CENSUS_NIGHT" in msg
            assert not (Path(root) / "metrics").exists()
    finally:
        hl.CENSUS_NIGHT.clear()
        hl.CENSUS_NIGHT.update(saved)


def test_a_new_census_in_the_csv_stops_the_update_until_its_date_is_added():
    # a 2026 Census arrives in a later edition: the rows exist but the map has no date for them
    rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
    head = rows[0]
    extra = [list(r) for r in rows[1:] if r[head.index("Table_Number")] == "19A.2" and r[head.index("Year")] == "2021"]
    for r in extra:
        r[head.index("Year")] = "2026"
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=write_csv(rows + extra))
        assert "Census year 2026 is not in CENSUS_NIGHT" in msg
        assert not (Path(root) / "metrics").exists()
        hl.CENSUS_NIGHT["2026"] = "2026-08-11"
        try:
            # with the date added, the run goes on (and then stops on the workbook, which has no 2026)
            assert "2026" in raises(run_in, root, csv_=write_csv(rows + extra)) and "workbook" in raises(run_in, root, csv_=write_csv(rows + extra))
        finally:
            del hl.CENSUS_NIGHT["2026"]


def test_a_missing_census_is_refused():
    rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
    head = rows[0]
    gap = [rows[0]] + [r for r in rows[1:] if not (r[head.index("Table_Number")] == "19A.2" and r[head.index("Year")] == "2016")]
    with tempfile.TemporaryDirectory() as root:
        assert "not 5 years apart" in raises(run_in, root, csv_=write_csv(gap))
        assert not (Path(root) / "metrics").exists()


# ---------------------------------------------------------------- refusals

def test_the_run_refuses_and_writes_nothing_when_the_workbook_disagrees():
    with tempfile.TemporaryDirectory() as root:
        cases = [
            ("Table 19A.2", ("Rate per 10,000 people in the population", "Total"), "2021", "Aust", 48.3, "census_homeless_rate", "2021 Aust: CSV 48.2, workbook 48.3"),
            ("Table 19A.2", ("Number", "Total"), "2016", "NT", 13718, "census_homeless_number", "2016 NT: CSV 13717, workbook 13718"),
            ("Table 19A.10", ("Total clients",), "2024-25", "Aust", 288971, "clients", "2024-25 Aust: CSV 288970, workbook 288971"),
            ("Table 19A.10", ("Accommodation services", "Proportion of clients with unmet need"), "2024-25", "Aust", 33.3, "unmet_accommodation_pct", "2024-25 Aust: CSV 33.2, workbook 33.3"),
            ("Table 19A.11", ("Average daily unassisted requests", "Accommodation services"), "2024-25", "Aust", 232.1, "unassisted_accommodation_daily", "2024-25 Aust: CSV 232.0, workbook 232.1"),
            ("Table 19A.11", ("Average daily unassisted requests", "No service need identified"), "2024-25", "SA", 0.1, "unassisted_no_need_daily", "2024-25 SA: CSV 0, workbook 0.1"),
        ]
        for sheet, labels, year, col, val, sid, want in cases:
            bad = change_xlsx(XLSX, sheet, labels, year, col, val)
            msg = raises(run_in, root, xlsx=bad)
            assert sid in msg and want in msg, (sid, msg)
            assert not (Path(root) / "metrics").exists()


def test_a_code_in_a_cell_must_agree_between_the_csv_and_the_workbook_and_other_text_is_refused():
    with tempfile.TemporaryDirectory() as root:
        # the CSV says na and the workbook has a number
        msg = raises(run_in, root, csv_=edit_csv(CSV, CLIENTS, "2024-25", "Tas", "na"))
        assert "2024-25 Tas: CSV na, workbook 6323" in msg
        # the CSV has a number and the workbook says np
        bad = change_xlsx(XLSX, "Table 19A.10", ("Total clients",), "2024-25", "SA", "np")
        assert "workbook np" in raises(run_in, root, xlsx=bad)
        # a code in the CSV that the workbook shares is stored as a code
        both_csv = edit_csv(CSV, CLIENTS, "2024-25", "Tas", "np")
        both_xlsx = change_xlsx(XLSX, "Table 19A.10", ("Total clients",), "2024-25", "Tas", "np")
        run_in(root, csv_=both_csv, xlsx=both_xlsx)
        assert next(r for r in rows_of(root) if (r["series"], r["jurisdiction"], r["period"]) == ("clients", "Tasmania", "2024-25"))["value"] == "np"
    with tempfile.TemporaryDirectory() as root:
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=edit_csv(CSV, CLIENTS, "2024-25", "Tas", "n/a"))
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=edit_csv(CSV, CLIENTS, "2024-25", "Tas", ""))
        assert not (Path(root) / "metrics").exists()


def test_the_number_of_decimal_places_is_checked_and_a_plain_zero_is_the_one_exception():
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=edit_csv(CSV, RATE, "2021", "Aust", "48"))
        assert "census_homeless_rate" in msg and "'48'" in msg and "1 decimal place" in msg
        msg = raises(run_in, root, csv_=edit_csv(CSV, NUMBER, "2021", "Aust", "122494.0"))
        assert "census_homeless_number" in msg and "0 decimal place" in msg
        msg = raises(run_in, root, csv_=edit_csv(CSV, ACCOM, "2024-25", "Aust", "232"))
        assert "unassisted_accommodation_daily" in msg and "1 decimal place" in msg
        msg = raises(run_in, root, csv_=edit_csv(CSV, UNMET, "2024-25", "Aust", "33.25"))
        assert "unmet_accommodation_pct" in msg
        assert not (Path(root) / "metrics").exists()
    assert hl.check_places("x", {"2024-25": {"SA": "0", "Aust": "41.7"}}, 1) is None  # a true zero is printed as 0
    assert "x" in raises(hl.check_places, "x", {"2024-25": {"Aust": "41"}}, 1)
    assert "x" in raises(hl.check_places, "x", {"2024-25": {"Aust": "41.0"}}, 0)


def test_a_missing_or_doubled_selection_or_a_year_gap_is_refused():
    with tempfile.TemporaryDirectory() as root:
        rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
        head = rows[0]
        # a selection that matches nothing (the Measure text changed)
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"Unmet need"', b'"Unmet needs"'))
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"Rate per 10000 people in the population"', b'"Rate per 100000 people in the population"'))
        # the unit is part of the selection
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"rate"', b'"ratio"'))
        # a duplicate row: two rows for one year and selection
        dup = next(r for r in rows[1:] if all(r[head.index(k)] == v for k, v in CLIENTS.items()) and r[head.index("Year")] == "2024-25")
        assert "2 rows match" in raises(run_in, root, csv_=write_csv(rows + [dup]))
        # a missing year in the middle of a service series
        gap = [rows[0]] + [r for r in rows[1:] if not (r[head.index("Year")] == "2023-24" and r[head.index("Table_Number")] == "19A.11" and r[head.index("Description1")] == "Services other than accommodation")]
        assert "not consecutive" in raises(run_in, root, csv_=write_csv(gap))
        # the services series must cover the same years
        short = [rows[0]] + [r for r in rows[1:] if not (r[head.index("Year")] == "2022-23" and r[head.index("Table_Number")] == "19A.11" and r[head.index("Description1")] == "No service need identified")]
        assert "do not cover the same years" in raises(run_in, root, csv_=write_csv(short))
        assert not (Path(root) / "metrics").exists()


def test_a_service_year_is_dated_30_june_of_its_second_year():
    assert hl.date_of("service", "2024-25") == "2025-06-30"
    assert hl.date_of("census", "2021") == "2021-08-10"
    assert "not two consecutive years" in raises(hl.date_of, "service", "2015-17")


# ---------------------------------------------------------------- history

def test_rows_for_periods_the_new_edition_drops_are_kept_and_revisions_come_from_the_new_edition():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/homelessness/data.csv"
        text = path.read_text()
        extra = "\n".join(f"2022-06-30,2021-22,{s},Australia,1,{hl.SERIES[s]['unit']},actual" for s in hl.SERIES if hl.SERIES[s]["kind"] == "service") + "\n"
        text = text.replace("2025-06-30,2024-25,clients,Australia,288970,count,actual", "2025-06-30,2024-25,clients,Australia,1,count,actual") + extra
        path.write_text(text)
        mp = Path(root) / "metrics/homelessness/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"]["editions"]["2021-22"] = "2025"
        mp.write_text(json.dumps(man))
        run_in(root)
        rows = rows_of(root)
        kept = [r for r in rows if r["period"] == "2021-22"]
        assert len(kept) == 5 and all(r["value"] == "1" for r in kept)  # unchanged
        assert next(r for r in rows if r["series"] == "clients" and r["jurisdiction"] == "Australia" and r["period"] == "2024-25")["value"] == "288970"
        assert json.loads(mp.read_text())["rogs-editions"]["editions"]["2021-22"] == "2025"
        # without the manifest's note for a kept period the run refuses and writes nothing
        man["rogs-editions"] = {"editions": {"2021": "2026"}}
        mp.write_text(json.dumps(man))
        before = path.read_bytes()
        assert "does not say which edition" in raises(run_in, root)
        assert path.read_bytes() == before


def test_rows_never_fall():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/homelessness/data.csv"
        path.write_text(path.read_text() + "2020-06-30,2019-20,clients,Australia,5,count,actual\n")
        mp = Path(root) / "metrics/homelessness/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"]["editions"]["2019-20"] = "2025"
        mp.write_text(json.dumps(man))
        run_in(root)  # a kept older year is fine
        assert any(r["period"] == "2019-20" for r in rows_of(root))


def test_main_returns_1_and_says_nothing_was_written_on_a_failure():
    orig = hl.run
    try:
        hl.run = lambda **kw: (_ for _ in ()).throw(a.ScrapeError("boom"))
        assert hl.main(["--root", "/nonexistent"]) == 1
    finally:
        hl.run = orig


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"pass {name}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
