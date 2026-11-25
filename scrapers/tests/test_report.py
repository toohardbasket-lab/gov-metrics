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


# The same toy metric with a revision tolerance on each series, written the way metric.yml writes it.
METRIC_YML_REV = METRIC_YML.replace(
    "    frequency: annual\n",
    "    frequency: annual\n    revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}\n",
).replace(
    "    label: Share of GDP\n",
    "    label: Share of GDP\n    # a comment line between the keys\n    revision: {max_abs: 0.5}   # per cent of GDP\n",
)
assert METRIC_YML_REV.count("revision:") == 2


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
              targets="", source=b"source bytes", retrieved="2026-11-10", drop=(), yml=METRIC_YML):
    data = [HEADER] + [r for r in rows(years, gross, pct) if not any(r.startswith(d) for d in drop)]
    write(root, "metrics/toy/data.csv", "\n".join(data) + "\n")
    write(root, "metrics/toy/metric.yml", yml % targets)
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


def test_large_revisions_are_marked():
    before = {"yml": METRIC_YML_REV, "years": (2021, 2022, 2023), "gross": {2021: "100000", 2022: "100000", 2023: "100000"}}
    after = {"yml": METRIC_YML_REV, "years": (2021, 2022, 2023),
             # 2021: +400 (under max_abs), 2022: +5000 (over 500 and over 1 per cent), 2023 unchanged
             "gross": {2021: "100400", 2022: "105000", 2023: "100000"},
             # 2021: +0.2 (within 0.5), 2023: +1.0 (over 0.5)
             "pct": {2021: "20.3", 2022: "20.2", 2023: "21.3"}}
    md, flag = run_report(before, after)
    check_style(md)
    rev = section(md, "Revised history")
    lines = [l for l in rev.split("\n") if l.startswith("- ")]
    assert any(l.startswith("- **LARGE:** 2022-06-30") and "$100,000m became $105,000m" in l for l in lines), rev
    assert any(l.startswith("- **LARGE:** 2023-06-30") and "20.3% of GDP became 21.3% of GDP" in l for l in lines), rev
    assert any(l.startswith("- 2021-06-30") and "$100,000m became $100,400m" in l for l in lines), rev
    assert any(l.startswith("- 2021-06-30") and "20.1% of GDP became 20.3% of GDP" in l for l in lines), rev
    assert rev.count("**LARGE:**") == 2, rev
    assert "could not be read" not in rev, rev


def test_sign_change_between_large_figures_is_marked():
    before = {"yml": METRIC_YML_REV, "gross": {2021: "-39958"}}
    after = {"yml": METRIC_YML_REV, "gross": {2021: "39958"}}
    md, flag = run_report(before, after)
    assert "- **LARGE:** 2021-06-30" in section(md, "Revised history")


def test_no_large_mark_when_tolerance_cannot_be_read():
    # the toy metric without a revision key, and one written over several lines
    before, after = {"gross": {2021: "100000"}}, {"gross": {2021: "999999"}}
    md, flag = run_report(before, after)
    rev = section(md, "Revised history")
    assert "could not be read from metric.yml" in rev, rev
    assert not any(l.startswith("- **LARGE:**") for l in rev.split("\n")), rev
    multi = METRIC_YML_REV.replace("revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}", "revision:\n      max_abs: 500")
    md, flag = run_report({"yml": multi, "gross": {2021: "100000"}}, {"yml": multi, "gross": {2021: "999999"}})
    rev = section(md, "Revised history")
    assert "could not be read from metric.yml" in rev, rev
    assert not any(l.startswith("- **LARGE:** 2021") for l in rev.split("\n")), rev


def test_parse_revision():
    d = report.parse_revision("{max_abs: 500, max_pct: 1, pct_floor: 5000}")
    assert d == {"max_abs": 500, "max_pct": 1, "pct_floor": 5000}
    assert report.parse_revision("{max_abs: 0.5}") == {"max_abs": 0.5}
    for bad in (None, "", "500", "{max_pct: 1}", "{max_abs: x}", "{max_abs: 5, speed: 1}", "{max_abs: 0}", "{max_abs: 5, max_abs: 6}"):
        assert report.parse_revision(bad) is None, bad


def test_a_figure_that_becomes_a_code_is_a_large_revision_and_the_edition_note_is_not_a_download():
    rev = report.parse_revision("{max_abs: 1, max_pct: 2, pct_floor: 100}")
    assert report.revision_breach("1234", "na", rev) and report.revision_breach("..", "5", rev) and report.revision_breach("na", "np", rev)
    assert not report.revision_breach("..", "..", rev) and not report.revision_breach("1000", "1010", rev) and report.revision_breach("1000", "1030", rev)
    with tempfile.TemporaryDirectory() as tmp:
        for side in ("before", "after"):
            d = Path(tmp) / side / "metrics/toy/sources"
            d.mkdir(parents=True)
            (d / "manifest.json").write_text(json.dumps({"rogs-editions": {"editions": {"2025": "2026"}}}))
        lines, changed = report.source_lines(Path(tmp) / "before", Path(tmp) / "after")
        assert lines == [] and changed == 0, lines


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
    assert [n for n, _ in run_all.REGISTRY] == ["cpi_june", "commonwealth_debt", "budget_balance", "unemployment_rate", "inflation", "wages_and_prices", "rents", "social_housing", "new_homes", "hospital_waits", "homelessness", "bulk_billing"]
    # the scraper that copies the inflation page's figures must come after the inflation scraper
    names = [n for n, _ in run_all.REGISTRY]
    assert run_all.DEPENDS_ON == {"wages_and_prices": "inflation", "new_homes": "social_housing"} and names.index("inflation") < names.index("wages_and_prices")
    # the scraper that copies the social housing page's population must come after the social housing scraper
    assert names.index("social_housing") < names.index("new_homes")
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


def _run_all_with(registry, depends, scripts):
    """Runs run_all.main on throwaway scripts; returns (status dict, text printed order is not needed)."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in scripts.items():
            (Path(tmp) / name).write_text(body)
        old = (run_all.HERE, run_all.REGISTRY, run_all.DEPENDS_ON)
        try:
            run_all.HERE, run_all.REGISTRY, run_all.DEPENDS_ON = Path(tmp), registry, depends
            status = Path(tmp) / "status.json"
            assert run_all.main(["--status", str(status), "--root", tmp]) == 0
        finally:
            run_all.HERE, run_all.REGISTRY, run_all.DEPENDS_ON = old
        return json.loads(status.read_text())


def test_run_all_skips_a_scraper_whose_dependency_failed():
    scripts = {"first.py": "import sys\nsys.exit(1)\n", "second.py": "open('ran.txt', 'w').write('x')\n", "ok.py": "pass\n"}
    s = _run_all_with([("first", "first.py"), ("second", "second.py"), ("other", "ok.py")], {"second": "first"}, scripts)
    assert s["first"]["ok"] is False
    assert s["second"]["ok"] is False and s["second"]["skipped"] is True and "Skipped" in s["second"]["output_tail"] and "first" in s["second"]["output_tail"]
    assert s["other"]["ok"] is True                      # an unrelated scraper still runs
    # the weekly report lists the skipped scraper as failed, so the weekly job raises an issue
    md, _ = run_report({}, {}, status=s)
    src = section(md, "Sources")
    assert "**Scraper failed: second**" in src and "Skipped" in src, src


def test_run_all_runs_a_scraper_whose_dependency_worked():
    scripts = {"first.py": "pass\n", "second.py": "print('ran')\n"}
    s = _run_all_with([("first", "first.py"), ("second", "second.py")], {"second": "first"}, scripts)
    assert s["first"]["ok"] is True and s["second"] == {"ok": True, "exit_code": 0, "output_tail": "ran"}


def test_a_manifest_reference_to_another_metrics_file_has_no_source_line():
    with tempfile.TemporaryDirectory() as tmp:
        b, a = Path(tmp) / "before", Path(tmp) / "after"
        for root in (b, a):
            make_tree(root)
            d = root / "metrics" / "toy" / "sources"
            m = json.loads((d / "manifest.json").read_text())
            m["copied-from-other"] = {"path": "metrics/other/data.csv", "sha256": "0" * 64, "bytes": 1, "retrieved": "2026-11-24"}
            (d / "manifest.json").write_text(json.dumps(m))
        lines, changed = report.source_lines(b, a)
        assert changed == 0 and not any("copied-from-other" in l for l in lines), lines


def test_percent_unit_is_formatted_and_tolerance_read():
    assert report.fmt_value("4.9", "pct") == "4.9%"
    assert report.fmt_diff("4.3", "4.9", "pct") == "+0.6 percentage points"
    assert report.fmt_diff("4.9", "4.3", "pct") == "-0.6 percentage points"
    rev = report.parse_revision("{max_abs: 0.3}")
    assert report.revision_breach("4.3", "4.5", rev) is False
    assert report.revision_breach("4.3", "4.6", rev) is False  # exactly 0.3 passes
    assert report.revision_breach("4.3", "4.9", rev) is True
    # the real metric.yml can be read by the report's small reader
    repo = HERE.parent.parent
    d = report.read_definition(repo, "unemployment-rate")
    assert d["revisions"]["unemployment_rate"] == {"max_abs": report.Decimal("0.3")}, d["revisions"]
    assert d["labels"]["unemployment_rate"] == "Unemployment rate"


def test_unemployment_metric_revision_and_source_change_in_a_report():
    import shutil
    repo = HERE.parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        for side in ("before", "after"):
            shutil.copytree(repo / "metrics" / "unemployment-rate", Path(tmp) / side / "metrics" / "unemployment-rate")
            (Path(tmp) / side / "shared").mkdir(parents=True)
        status = Path(tmp) / "status.json"
        status.write_text(json.dumps({"unemployment_rate": {"ok": True, "exit_code": 0, "output_tail": ""}}))
        # only the downloaded file's bytes change: listed, but not a data change
        src = Path(tmp) / "after" / "metrics" / "unemployment-rate" / "sources" / "abs-lf-M13.3.1599.20.AUS.M.csv"
        src.write_bytes(src.read_bytes() + b"\n")
        md, summary, changed = report.build_report(Path(tmp) / "before", Path(tmp) / "after", status, TODAY)
        assert changed is False and "CHANGED" in md
        # a past month moves by 0.5 (over the 0.3 allowed), another by 0.2 (within it)
        data = Path(tmp) / "after" / "metrics" / "unemployment-rate" / "data.csv"
        lines = data.read_text().split("\n")
        for i, l in enumerate(lines):
            c = l.split(",")
            if c[0] == "2000-06-30":
                c[4] = str(round(float(c[4]) + 0.5, 1))
                lines[i] = ",".join(c)
            if c[0] == "2001-06-30":
                c[4] = str(round(float(c[4]) + 0.2, 1))
                lines[i] = ",".join(c)
        data.write_text("\n".join(lines))
        md, summary, changed = report.build_report(Path(tmp) / "before", Path(tmp) / "after", status, TODAY)
        rev = section(md, "Revised history")
        assert changed is True and "2 revised figures" in summary, summary
        assert rev.count("**LARGE:**") == 1 and "+0.5 percentage points" in rev and "+0.2 percentage points" in rev, rev


def test_inflation_metric_labels_tolerances_and_a_new_quarter_in_a_report():
    """Three series of two frequencies, labels with commas, and a comment between the keys: the report's
    small reader must still find each label and tolerance, and the quarterly rows must report like any other."""
    import shutil
    repo = HERE.parent.parent
    d = report.read_definition(repo, "inflation")
    assert d["labels"]["headline_quarterly"] == "Inflation, quarterly CPI", d["labels"]
    assert d["labels"]["trimmed_mean_quarterly"] == "Underlying inflation (trimmed mean)"
    assert d["revisions"]["headline_quarterly"] == {"max_abs": report.Decimal("0.1")}, d["revisions"]
    assert d["revisions"]["headline_monthly"] == {"max_abs": report.Decimal("0.1")}
    assert d["revisions"]["trimmed_mean_quarterly"] == {"max_abs": report.Decimal("0.3")}
    with tempfile.TemporaryDirectory() as tmp:
        for side in ("before", "after"):
            shutil.copytree(repo / "metrics" / "inflation", Path(tmp) / side / "metrics" / "inflation")
            (Path(tmp) / side / "shared").mkdir(parents=True)
        status = Path(tmp) / "status.json"
        status.write_text(json.dumps({"inflation": {"ok": True, "exit_code": 0, "output_tail": ""}}))
        data = Path(tmp) / "after" / "metrics" / "inflation" / "data.csv"
        lines = data.read_text().split("\n")
        for i, l in enumerate(lines):
            c = l.split(",")
            if c[0] == "2000-06-30" and c[2] == "headline_quarterly":
                c[4] = str(round(float(c[4]) + 0.2, 1))      # over its 0.1
                lines[i] = ",".join(c)
            if c[0] == "2000-06-30" and c[2] == "trimmed_mean_quarterly":
                c[4] = str(round(float(c[4]) + 0.2, 1))      # within its 0.3
                lines[i] = ",".join(c)
        lines = [l for l in lines if l != ""] + ["2026-12-31,2026-Q4,headline_quarterly,Australia,3.8,pct,actual", ""]
        data.write_text("\n".join(lines))
        md, summary, changed = report.build_report(Path(tmp) / "before", Path(tmp) / "after", status, TODAY)
        new, rev = section(md, "New data points"), section(md, "Revised history")
        assert changed is True and "1 new data point" in summary and "2 revised figures" in summary, summary
        assert "Inflation, quarterly CPI (headline_quarterly), Australia" in new and "2026-12-31 (2026-Q4): 3.8%, actual" in new, new
        assert rev.count("**LARGE:**") == 1 and "(headline_quarterly)" in rev and rev.count("+0.2 percentage points") == 2, rev
        head_q, head_t = rev.index("(headline_quarterly)"), rev.index("(trimmed_mean_quarterly)")
        assert head_q < rev.index("**LARGE:**") < head_t, rev      # the LARGE line is under the headline heading, not the trimmed mean


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
