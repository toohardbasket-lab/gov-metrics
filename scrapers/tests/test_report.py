#!/usr/bin/env python3
"""Tests for scrapers/report.py and scrapers/run_all.py. Plain asserts, no pytest needed.

Run from the project folder:  python3 scrapers/tests/test_report.py

Each test builds a small "before" and "after" copy of a project in a temporary folder,
runs the report on them and checks what it says. No network, no git.
"""
import json
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import report  # noqa: E402
import run_all  # noqa: E402

TODAY = date(2026, 11, 17)
HEADER = "date,period,series,jurisdiction,value,unit,status"
OK_STATUS = {"cpi_june": {"ok": True, "exit_code": 0, "output_tail": "fine"},
             "commonwealth_debt": {"ok": True, "exit_code": 0, "output_tail": "fine"}}

METRIC_YML = """slug: toy
title: Toy metric
series:
  - id: gross
    label: Gross thing
    frequency: annual
  - id: pct
    label: Share of GDP
targets:
  - label: Old ledger row without a date
    text: "No target: here"
%s"""


def rows(years, gross=None, pct=None):
    """Data rows for two series. gross and pct are dicts year -> value text."""
    gross = gross or {}
    pct = pct or {}
    out = []
    for y in years:
        out.append(f"{y}-06-30,{y - 1}-{str(y)[2:]},gross,Commonwealth,{gross.get(y, 1000 + y - 2020)},aud_million,actual")
    for y in years:
        out.append(f"{y}-06-30,{y - 1}-{str(y)[2:]},pct,Commonwealth,{pct.get(y, 20 + (y - 2020) / 10)},pct_gdp,actual")
    return out


def cpi_rows(years, overrides=None):
    overrides = overrides or {}
    return ["date,index,base"] + [f"{y}-06-30,{overrides.get(y, 90 + (y - 2020))},base period 25" for y in years]


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def make_tree(root, years=(2021, 2022, 2023), gross=None, pct=None, cpi_years=(2021, 2022, 2023), cpi_over=None,
              targets="", source=b"source bytes", retrieved="2026-11-10", drop=()):
    data = [HEADER] + [r for r in rows(years, gross, pct) if not any(r.startswith(d) for d in drop)]
    write(root, "metrics/toy/data.csv", "\n".join(data) + "\n")
    write(root, "metrics/toy/metric.yml", METRIC_YML % targets)
    (Path(root) / "metrics/toy/sources").mkdir(parents=True, exist_ok=True)
    (Path(root) / "metrics/toy/sources/file.docx").write_bytes(source)
    write(root, "metrics/toy/sources/manifest.json", json.dumps({"file.docx": {"url": "https://x", "retrieved": retrieved, "sha256": "abc", "bytes": len(source)}}))
    write(root, "shared/cpi_june.csv", "\n".join(cpi_rows(cpi_years, cpi_over)) + "\n")
    write(root, "shared/events.csv", "date,label\n2020-04-01,COVID-19\n")
    write(root, "shared/governments.csv", "sworn_in,party,note\n2022-05-23,Labor,Albanese\n")
    (Path(root) / "shared/sources").mkdir(parents=True, exist_ok=True)
    (Path(root) / "shared/sources/abs.csv").write_bytes(b"abs bytes")
    write(root, "shared/sources/manifest.json", json.dumps({"abs.csv": {"url": "https://y", "retrieved": retrieved, "sha256": "def", "bytes": 9}}))


def run_report(before_kwargs, after_kwargs, status=None, today=TODAY):
    with tempfile.TemporaryDirectory() as tmp:
        b, a = Path(tmp) / "before", Path(tmp) / "after"
        make_tree(b, **before_kwargs)
        make_tree(a, **after_kwargs)
        sp = Path(tmp) / "status.json"
        sp.write_text(json.dumps(OK_STATUS if status is None else status), encoding="utf-8")
        out, flag = Path(tmp) / "report.md", Path(tmp) / "flag.txt"
        code = report.main(["--before", str(b), "--after", str(a), "--status", str(sp), "--out", str(out),
                            "--today", today.isoformat(), "--changed-flag", str(flag)])
        assert code == 0, code
        return out.read_text(encoding="utf-8"), flag.read_text().strip()


def section(md, title):
    parts = md.split("## ")
    for p in parts:
        if p.startswith(title):
            return p.split("\n", 1)[1].strip()
    raise AssertionError(f"no section {title!r} in\n{md}")


def check_style(md):
    assert "—" not in md and "–" not in md, "the report must not contain dashes like the em dash"


# ---------------------------------------------------------------- the cases

def test_no_change():
    md, flag = run_report({}, {})
    check_style(md)
    assert "**0 new data points, 0 revised figures, 0 problems**" in md, md
    for title in ("New data points", "Revised history", "Removed data points", "Shared files", "Targets due within 90 days"):
        assert section(md, title) == "None", (title, section(md, title))
    assert section(md, "What to do") == "Nothing to do."
    assert "unchanged" in section(md, "Sources") and "CHANGED" not in section(md, "Sources")
    assert flag == "false"


def test_retrieved_date_alone_is_not_a_change():
    md, flag = run_report({"retrieved": "2026-11-10"}, {"retrieved": "2026-11-17"})
    assert flag == "false", flag
    assert section(md, "What to do") == "Nothing to do."


def test_one_new_year():
    md, flag = run_report({}, {"years": (2021, 2022, 2023, 2024), "cpi_years": (2021, 2022, 2023, 2024)})
    check_style(md)
    # two series in the toy metric plus the price index
    assert "**3 new data points, 0 revised figures, 0 problems**" in md, md
    new = section(md, "New data points")
    assert "Toy metric: Gross thing (gross), Commonwealth" in new
    assert "2024-06-30 (2023-24): $1,004m, actual" in new, new
    assert "2024-06-30 (2023-24): 20.4% of GDP, actual" in new, new
    assert section(md, "Revised history") == "None"
    assert "Review the figures above against the source, then merge this pull request." in section(md, "What to do")
    assert "June quarter index" in section(md, "Shared files")
    assert flag == "true"


def test_three_revised_values():
    md, flag = run_report({}, {"gross": {2022: "1500"}, "pct": {2021: "21.5", 2023: "23.0"}})
    check_style(md)
    assert "**0 new data points, 3 revised figures, 0 problems**" in md
    rev = section(md, "Revised history")
    assert "2022-06-30 (2021-22): $1,002m became $1,500m (difference +$498m)" in rev, rev
    assert "2021-06-30 (2020-21): 20.1% of GDP became 21.5% of GDP (difference +1.4 percentage points)" in rev, rev
    assert "2023-06-30 (2022-23): 20.3% of GDP became 23.0% of GDP (difference +2.7 percentage points)" in rev, rev
    assert section(md, "New data points") == "None"
    assert flag == "true"


def test_more_than_fifteen_revisions_are_summarised():
    years = tuple(range(2000, 2030))
    over = {y: str(5000 + y) for y in years}
    over[2010] = "99999"  # the largest change
    md, flag = run_report({"years": years, "cpi_years": ()}, {"years": years, "gross": over, "cpi_years": ()})
    rev = section(md, "Revised history")
    assert "30 figures changed. The largest change is 2010-06-30" in rev, rev
    assert "The first 15 are listed." in rev
    listed = [l for l in rev.split("\n") if l.startswith("- 20") and "became" in l]
    assert len(listed) == 15, len(listed)


def test_removed_row():
    md, flag = run_report({}, {"drop": ("2023-06-30,",)}, status=None)
    check_style(md)
    assert "2 problems" in md.split("\n")[2], md.split("\n")[2]
    rem = section(md, "Removed data points")
    assert "WARNING" in rem and "should never happen" in rem
    assert "2023-06-30 (2022-23): $1,003m is no longer in the file" in rem, rem
    assert "Do not merge yet." in section(md, "What to do")
    assert flag == "true"


def test_failed_scraper():
    status = {"cpi_june": {"ok": True, "exit_code": 0, "output_tail": "fine"},
              "commonwealth_debt": {"ok": False, "exit_code": 1, "output_tail": "ERROR: the table was not found\nNothing was written."}}
    md, flag = run_report({}, {}, status=status)
    check_style(md)
    assert "**0 new data points, 0 revised figures, 1 problem**" in md, md
    src = section(md, "Sources")
    assert "**Scraper failed: commonwealth_debt**" in src
    assert "```\nERROR: the table was not found\nNothing was written.\n```" in src, src
    assert "Scrapers that worked: cpi_june." in src
    assert "A source could not be read" in section(md, "What to do")
    assert section(md, "What to do") != "Nothing to do."
    assert flag == "false"


def test_unreadable_status_file_is_a_problem():
    with tempfile.TemporaryDirectory() as tmp:
        b, a = Path(tmp) / "b", Path(tmp) / "a"
        make_tree(b)
        make_tree(a)
        out = Path(tmp) / "r.md"
        report.main(["--before", str(b), "--after", str(a), "--status", str(Path(tmp) / "missing.json"), "--out", str(out), "--today", "2026-11-17"])
        md = out.read_text(encoding="utf-8")
        assert "1 problem" in md and "status file could not be read" in md, md


def test_targets_due():
    targets = ("  - label: Soon target\n    due: 2026-12-17\n"
               "  - label: Far target\n    due: 2027-06-05\n"
               "  - label: Late target\n    due: 2026-11-01\n"
               "  - {label: Flow target, due: 2026-12-01}\n")
    md, flag = run_report({}, {"targets": targets})
    check_style(md)
    t = section(md, "Targets due within 90 days")
    assert "Toy metric: Soon target, 2026-12-17 (due in 30 days)" in t, t
    assert "Toy metric: Late target, 2026-11-01 (overdue by 16 days)" in t, t
    assert "Toy metric: Flow target, 2026-12-01 (due in 14 days)" in t, t
    assert "Far target" not in t, t
    assert "Old ledger row" not in t
    # the order is by due date
    assert t.index("Late target") < t.index("Flow target") < t.index("Soon target")
    # and with no targets that have a due date, the section says None
    md2, _ = run_report({}, {})
    assert section(md2, "Targets due within 90 days") == "None"


def test_target_with_bad_date_is_a_problem():
    md, _ = run_report({}, {"targets": "  - label: Broken\n    due: 2026-02-30\n"})
    assert "1 problem" in md and "not a real date" in section(md, "Targets due within 90 days"), md


def test_changed_source_file_and_price_index_revision():
    md, flag = run_report({}, {"source": b"new source bytes", "cpi_over": {2022: "95.5"}})
    src = section(md, "Sources")
    assert "metrics/toy/sources/file.docx`: CHANGED" in src, src
    assert "shared/sources/abs.csv`: unchanged" in src, src
    shared = section(md, "Shared files")
    assert "June quarter index" in shared and "became" in shared, shared
    assert "changes every inflation-adjusted figure" in shared
    assert "**0 new data points, 1 revised figure, 0 problems**" in md
    assert flag == "true"


def test_source_change_alone_does_not_set_the_flag():
    # A re-download with different bytes but the same figures (the ABS reorders its rows from
    # one day to the next) must be listed, but must not open a pull request.
    md, flag = run_report({}, {"source": b"different"})
    assert flag == "false"
    assert "metrics/toy/sources/file.docx`: CHANGED" in section(md, "Sources")
    todo = section(md, "What to do")
    assert "Nothing to do" in todo and "same" in todo, todo
    assert "merge" not in todo, todo


def test_run_all_registry_and_status():
    assert [n for n, _ in run_all.REGISTRY] == ["cpi_june", "commonwealth_debt"]
    # a script that fails and a script that works, run without touching the network
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.py"
        bad = Path(tmp) / "bad.py"
        good.write_text("import sys\nprint('hello')\nsys.exit(0)\n")
        bad.write_text("import sys\nfor i in range(50): print('line', i)\nsys.exit(3)\n")
        old_here, old_reg = run_all.HERE, run_all.REGISTRY
        try:
            run_all.HERE = Path(tmp)
            run_all.REGISTRY = [("bad", "bad.py"), ("good", "good.py")]
            status = Path(tmp) / "s" / "status.json"
            assert run_all.main(["--status", str(status), "--root", tmp]) == 0
        finally:
            run_all.HERE, run_all.REGISTRY = old_here, old_reg
        s = json.loads(status.read_text())
        assert s["bad"]["ok"] is False and s["bad"]["exit_code"] == 3
        assert s["bad"]["output_tail"].split("\n")[-1] == "line 49" and len(s["bad"]["output_tail"].split("\n")) == 30
        assert s["good"] == {"ok": True, "exit_code": 0, "output_tail": "hello"}, s["good"]


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
