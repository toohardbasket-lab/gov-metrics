#!/usr/bin/env python3
"""The weekly "what changed" report.

    python3 scrapers/report.py --before <folder> --after <folder> --status <status.json> --out <report.md>

Compares the metrics/ and shared/ folders of two copies of the project (before and after the
scrapers ran) and writes a short Markdown report in plain language. It does not use git.
It also prints the summary line, and always exits 0 unless the report itself cannot be written.

Options:
  --today YYYY-MM-DD       pretend today is this date (used by the tests)
  --changed-flag <file>    write "true" or "false": did any tracked data file change?

What counts as a change (for the flag and the "What to do" line): any file under metrics/ or
shared/ that was added, removed or altered, EXCEPT data.lock.json and anything inside a sources
folder (the downloaded files and their manifest). A downloaded file can come back with different
bytes but the same figures: the ABS, for example, sends the same rows in a different order from
one day to the next. That is listed in the Sources section but does not open a pull request. When
the figures do change, the new downloads are committed along with them.

The summary counts include the shared price index. "Problems" are: scrapers that failed,
data files that could not be read, data points that were removed, a status file that could not
be read, and target dates that could not be read.

Targets: a metric.yml may carry a list called "targets". Entries that have a "due" date
(YYYY-MM-DD) and a "label" are checked. Entries without "due" (the ledger rows the page draws)
are ignored. This program has no YAML library available, so it reads only the simple layout
described in metrics/README.md: "key: value" lines, or one {key: value, ...} line per item.

Revision tolerance: each series in metric.yml declares "revision: {max_abs: 500, max_pct: 1,
pct_floor: 5000}" (max_pct and pct_floor are optional). The report reads it from that one-line
form only; the same rule as the validator (scripts/validate.mjs) then marks each revised figure
that is over the tolerance with "**LARGE:** ". A revision written over several lines is valid for
the validator but cannot be read here: the report then says so and marks nothing for that series.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

HEADER = "date,period,series,jurisdiction,value,unit,status"
CPI_HEADER = "date,index,base"
MAX_SHOWN = 15
TARGET_DAYS = 90
IGNORED_NAMES = {"data.lock.json"}


# ---------------------------------------------------------------- reading files

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_lines(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def load_table(path, header, key_cols, value_cols):
    """Reads a small CSV. Returns (rows, error). rows maps a key tuple to a dict of the value columns."""
    path = Path(path)
    if not path.exists():
        return {}, None
    try:
        lines = read_lines(path)
        if not lines or lines[0].strip() != header:
            return {}, f"{path.name} has an unexpected header"
        cols = header.split(",")
        rows = {}
        for n, line in enumerate(lines[1:], start=2):
            if line.strip() == "":
                continue
            cells = [c.strip() for c in line.split(",")]
            if len(cells) != len(cols):
                return {}, f"{path.name} line {n} has {len(cells)} fields, expected {len(cols)}"
            rec = dict(zip(cols, cells))
            rows[tuple(rec[c] for c in key_cols)] = {c: rec[c] for c in value_cols}
        return rows, None
    except (OSError, UnicodeDecodeError) as e:
        return {}, f"{path.name} could not be read ({e})"


def load_data(root, slug):
    return load_table(Path(root) / "metrics" / slug / "data.csv", HEADER,
                      ["series", "jurisdiction", "date"], ["period", "value", "unit", "status"])


def load_cpi(root):
    return load_table(Path(root) / "shared" / "cpi_june.csv", CPI_HEADER, ["date"], ["index", "base"])


def metric_slugs(root):
    base = Path(root) / "metrics"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and ((p / "metric.yml").exists() or (p / "data.csv").exists()))


# ---------------------------------------------------------------- a very small reader for metric.yml

def _clean_scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return re.sub(r"\s+#.*$", "", v).strip()


def top_scalar(text, key):
    m = re.search(r"^%s:[ \t]+(.+)$" % re.escape(key), text, re.M)
    return _clean_scalar(m.group(1)) if m else None


def top_list(text, key):
    """The items of a top-level list such as `targets:` or `series:`, as dicts of simple values.

    Understands the layout used in this project: the key at the left edge, the items indented
    beneath it, each item starting with "- " and its other keys lined up under the first one.
    Anything nested deeper than an item's own keys is ignored.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^%s:\s*(#.*)?$" % re.escape(key), line):
            start = i + 1
            break
    if start is None:
        return []
    items, cur, item_indent = [], None, None
    for line in lines[start:]:
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break  # the next top-level key
        body = line.strip()
        first = False
        if body.startswith("- ") or body == "-":
            if item_indent is None:
                item_indent = indent
            if indent != item_indent:
                continue  # a list nested inside an item
            cur = {}
            items.append(cur)
            body = body[1:].strip()
            if body.startswith("{") and body.endswith("}"):
                for part in body[1:-1].split(","):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        cur[k.strip()] = _clean_scalar(v)
                continue
            first = True
        if cur is None or (not first and indent != item_indent + 2):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$", body)
        if m and m.group(2):
            cur[m.group(1)] = _clean_scalar(m.group(2))
    return items


REVISION_KEYS = ("max_abs", "max_pct", "pct_floor")


def parse_revision(text):
    """Reads "{max_abs: 500, max_pct: 1, pct_floor: 5000}" into a dict of Decimals, or None if it
    is not exactly that form (a one-line map of the three known keys, max_abs required and above zero)."""
    if not text:
        return None
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    out = {}
    for part in text[1:-1].split(","):
        if ":" not in part:
            return None
        k, v = part.split(":", 1)
        k, d = k.strip(), to_decimal(v.strip())
        if k not in REVISION_KEYS or d is None or not d.is_finite() or k in out:
            return None
        out[k] = d
    if "max_abs" not in out or out["max_abs"] <= 0:
        return None
    if "max_pct" in out and out["max_pct"] <= 0:
        return None
    if "pct_floor" in out and out["pct_floor"] < 0:
        return None
    return out


def revision_breach(old, new, rev):
    """True if changing a figure from the text `old` to the text `new` breaks the tolerance `rev`.
    The same rule as revisionBreach in scripts/validate.mjs."""
    a, b = to_decimal(old), to_decimal(new)
    if rev is not None and old != new and (a is None or b is None) and (old in ("..", "na", "np", "-") or new in ("..", "na", "np", "-")):
        return True  # a figure that becomes a code, or a code that changes, is always a revision to check (as in scripts/validate.mjs)
    if rev is None or a is None or b is None or a == b:
        return False
    change = abs(b - a)
    sign_limit = rev["pct_floor"] if "pct_floor" in rev else rev["max_abs"]
    if a * b < 0 and abs(a) >= sign_limit and abs(b) >= sign_limit:
        return True
    if change <= rev["max_abs"]:
        return False
    if "max_pct" not in rev:
        return True
    floor = rev.get("pct_floor", Decimal(0))
    if abs(a) < floor:
        return True
    if a == 0:
        return True
    return change / abs(a) * 100 > rev["max_pct"]


def read_definition(root, slug):
    path = Path(root) / "metrics" / slug / "metric.yml"
    if not path.exists():
        return {"title": slug, "labels": {}, "targets": [], "revisions": {}}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {"title": slug, "labels": {}, "targets": [], "revisions": {}}
    series = top_list(text, "series")
    labels = {s.get("id"): s.get("label") for s in series if s.get("id") and s.get("label")}
    revisions = {s["id"]: parse_revision(s.get("revision")) for s in series if s.get("id")}
    return {"title": top_scalar(text, "title") or slug, "labels": labels, "targets": top_list(text, "targets"),
            "revisions": revisions}


# ---------------------------------------------------------------- comparing

def to_decimal(s):
    try:
        return Decimal(s)
    except (InvalidOperation, TypeError):
        return None


def diff_tables(before, after):
    """Returns (new keys, revised [(key, old, new)], removed keys), each sorted."""
    new = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    revised = []
    for k in sorted(k for k in after if k in before):
        if before[k] != after[k]:
            revised.append((k, before[k], after[k]))
    return new, revised, removed


def fmt_value(s, unit):
    d = to_decimal(s)
    if d is None:
        return s
    if unit == "aud_million":
        return ("-" if d < 0 else "") + f"${abs(d):,}m"
    if unit == "pct_gdp":
        return f"{d}% of GDP"
    if unit == "pct":
        return f"{d}%"
    return f"{d} {unit}".strip()


def fmt_diff(old, new, unit):
    a, b = to_decimal(old), to_decimal(new)
    if a is None or b is None:
        return None
    d = b - a
    sign = "+" if d > 0 else "-" if d < 0 else ""
    d = abs(d)
    if unit == "aud_million":
        return f"{sign}${d:,}m"
    if unit in ("pct_gdp", "pct"):
        return f"{sign}{d} percentage points"
    return f"{sign}{d}"


def numeric_change(rec_old, rec_new):
    a, b = to_decimal(rec_old.get("value", rec_old.get("index"))), to_decimal(rec_new.get("value", rec_new.get("index")))
    return abs(b - a) if a is not None and b is not None else Decimal(0)


def trees_differ(before, after):
    """True if any tracked data file differs between the two copies (see the module note)."""
    def files(root):
        out = {}
        for sub in ("metrics", "shared"):
            base = Path(root) / sub
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*")):
                if "sources" in p.relative_to(base).parts:
                    continue
                if p.is_file() and p.name not in IGNORED_NAMES and "__pycache__" not in p.parts:
                    out[p.relative_to(root).as_posix()] = p
        return out

    fb, fa = files(before), files(after)
    if set(fb) != set(fa):
        return True
    for rel, pa in fa.items():
        pb = fb[rel]
        if pa.name == "manifest.json":
            if _manifest_view(pb) != _manifest_view(pa):
                return True
        elif pa.read_bytes() != pb.read_bytes():
            return True
    return False


def _manifest_view(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Path(path).read_bytes()
    if isinstance(data, dict):
        return {k: ({kk: vv for kk, vv in v.items() if kk != "retrieved"} if isinstance(v, dict) else v) for k, v in data.items()}
    return data


# ---------------------------------------------------------------- writing sections

def series_name(defn, series):
    label = defn["labels"].get(series)
    return f"{label} ({series})" if label else series


def describe_change(old, new, unit):
    parts = []
    if old.get("value") != new.get("value"):
        text = f"{fmt_value(old['value'], unit)} became {fmt_value(new['value'], new.get('unit', unit))}"
        d = fmt_diff(old["value"], new["value"], new.get("unit", unit))
        if d is not None:
            text += f" (difference {d})"
        parts.append(text)
    for col in ("period", "unit", "status"):
        if old.get(col) != new.get(col):
            parts.append(f"{col} changed from {old.get(col)} to {new.get(col)}")
    return "; ".join(parts)


def section_for_table(metric_title, new, revised, removed, before, after, defn, out_new, out_rev, out_rem, kind="data"):
    """Adds lines for one metric to the three lists. Keys are (series, jurisdiction, date)."""
    def group(keys):
        g = {}
        for k in keys:
            g.setdefault((k[0], k[1]), []).append(k)
        return g

    for (series, jur), keys in sorted(group(new).items()):
        out_new.append(f"**{metric_title}: {series_name(defn, series)}, {jur}**")
        shown = keys if len(keys) <= MAX_SHOWN else keys[-MAX_SHOWN:]
        if len(keys) > MAX_SHOWN:
            out_new.append(f"- {len(keys)} new data points from {keys[0][2]} to {keys[-1][2]}. The latest {MAX_SHOWN} are listed.")
        for k in shown:
            r = after[k]
            out_new.append(f"- {k[2]} ({r['period']}): {fmt_value(r['value'], r['unit'])}, {r['status']}")
        out_new.append("")

    rev_groups = {}
    for item in revised:
        rev_groups.setdefault((item[0][0], item[0][1]), []).append(item)
    revisions = defn.get("revisions")  # None for files with no series list, such as the price index
    for (series, jur), items in sorted(rev_groups.items()):
        out_rev.append(f"**{metric_title}: {series_name(defn, series)}, {jur}**")
        tolerance = (revisions or {}).get(series)
        if revisions is not None and tolerance is None:
            out_rev.append("- The allowed revision for this series could not be read from metric.yml, so no figure below is marked LARGE. "
                           "The checks (npm run validate) still apply.")

        def is_large(it):
            return revision_breach(it[1].get("value"), it[2].get("value"), tolerance)

        if len(items) > MAX_SHOWN:
            big = max(items, key=lambda it: numeric_change(it[1], it[2]))
            unit = big[2]["unit"]
            n_large = sum(1 for it in items if is_large(it))
            out_rev.append(f"- {len(items)} figures changed. The largest change is {big[0][2]}: {describe_change(big[1], big[2], unit)}. The first {MAX_SHOWN} are listed.")
            if n_large:
                out_rev.append(f"- **LARGE:** {n_large} of these changed by more than the allowed revision. They are listed first.")
                items = sorted(items, key=lambda it: not is_large(it))
            items = items[:MAX_SHOWN]
        for k, old, new in items:
            mark = "**LARGE:** " if is_large((k, old, new)) else ""
            out_rev.append(f"- {mark}{k[2]} ({new['period']}): {describe_change(old, new, new['unit'])}")
        out_rev.append("")

    for (series, jur), keys in sorted(group(removed).items()):
        out_rem.append(f"**{metric_title}: {series_name(defn, series)}, {jur}**")
        for k in keys[:30]:
            r = before[k]
            out_rem.append(f"- {k[2]} ({r['period']}): {fmt_value(r['value'], r['unit'])} is no longer in the file")
        if len(keys) > 30:
            out_rem.append(f"- and {len(keys) - 30} more")
        out_rem.append("")


def source_lines(before, after):
    """One line per downloaded source file: unchanged, changed, new or removed."""
    lines = []
    manifests = set()
    for root in (before, after):
        root = Path(root)
        for m in sorted(root.glob("metrics/*/sources/manifest.json")) + sorted(root.glob("shared/sources/manifest.json")):
            manifests.add(m.relative_to(root).parent.as_posix())
    changed = 0
    for d in sorted(manifests):
        names = set()
        for root in (before, after):
            mp = Path(root) / d / "manifest.json"
            if mp.exists():
                try:
                    entries = json.loads(mp.read_text(encoding="utf-8"))
                    # an entry with a "path" refers to another metric's file (a copied series), and an entry with
                    # "editions" is a scraper's note of which edition each stored year came from; neither is a
                    # download kept in this folder, so neither has a line here
                    names |= {k for k, v in entries.items() if not (isinstance(v, dict) and ("path" in v or "editions" in v))}
                except (OSError, ValueError, AttributeError):
                    pass
        for name in sorted(names):
            pb, pa = Path(before) / d / name, Path(after) / d / name
            sb = sha256_file(pb) if pb.exists() else None
            sa = sha256_file(pa) if pa.exists() else None
            rel = f"{d}/{name}"
            if sb == sa and sa is not None:
                lines.append(f"- `{rel}`: unchanged")
            elif sb is None and sa is not None:
                changed += 1
                lines.append(f"- `{rel}`: new file (checksum {sa[:12]})")
            elif sa is None and sb is not None:
                changed += 1
                lines.append(f"- `{rel}`: REMOVED (it was there before)")
            elif sa is None and sb is None:
                lines.append(f"- `{rel}`: listed in the manifest but not found in either copy")
            else:
                changed += 1
                lines.append(f"- `{rel}`: CHANGED, the downloaded file is different (checksum {sb[:12]} before, {sa[:12]} now)")
    return lines, changed


def read_status(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data, None
    except (OSError, ValueError) as e:
        return {}, f"The status file could not be read ({e}). It is not known whether the scrapers worked."


def targets_due(after, today):
    """Returns (lines, problems)."""
    found, problems = [], []
    for slug in metric_slugs(after):
        d = read_definition(after, slug)
        for t in d["targets"]:
            if not t.get("due"):
                continue
            label = t.get("label", "(no label)")
            try:
                due = datetime.strptime(t["due"], "%Y-%m-%d").date()
            except ValueError:
                problems.append(f"- {d['title']}: the due date \"{t['due']}\" for \"{label}\" is not a real date (use YYYY-MM-DD).")
                continue
            days = (due - today).days
            if days <= TARGET_DAYS:
                when = f"overdue by {-days} day{'s' if days != -1 else ''}" if days < 0 else "due today" if days == 0 else f"due in {days} day{'s' if days != 1 else ''}"
                found.append((due, f"- {d['title']}: {label}, {t['due']} ({when})"))
    return [l for _, l in sorted(found)], problems


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---------------------------------------------------------------- the report

def build_report(before, after, status_path, today):
    problems = 0
    n_new = n_rev = n_rem = 0
    out_new, out_rev, out_rem, notes = [], [], [], []

    slugs = sorted(set(metric_slugs(before)) | set(metric_slugs(after)))
    for slug in slugs:
        b_rows, b_err = load_data(before, slug)
        a_rows, a_err = load_data(after, slug)
        for err in (b_err, a_err):
            if err:
                problems += 1
                notes.append(f"- metrics/{slug}: {err}. This metric could not be compared.")
        if b_err or a_err:
            continue
        defn = read_definition(after if slug in metric_slugs(after) else before, slug)
        new, revised, removed = diff_tables(b_rows, a_rows)
        n_new += len(new)
        n_rev += len(revised)
        n_rem += len(removed)
        section_for_table(defn["title"], new, revised, removed, b_rows, a_rows, defn, out_new, out_rev, out_rem)

    # shared price index
    cb, cb_err = load_cpi(before)
    ca, ca_err = load_cpi(after)
    out_cpi = []
    cpi_changed = False
    if cb_err or ca_err:
        problems += 1
        out_cpi.append(f"- shared/cpi_june.csv: {cb_err or ca_err}. It could not be compared.")
    else:
        new, revised, removed = diff_tables(cb, ca)
        n_new += len(new)
        n_rev += len(revised)
        n_rem += len(removed)
        cpi_changed = bool(new or revised or removed)
        lines_new, lines_rev, lines_rem = [], [], []
        # reuse the writer with a fixed series name, a fixed jurisdiction and a made-up unit
        wrap = lambda d: {("June quarter index", "Australia", k[0]): {"period": k[0][:4], "value": v["index"], "unit": "index points", "status": "actual"} for k, v in d.items()}
        wb, wa = wrap(cb), wrap(ca)
        n2, r2, d2 = diff_tables(wb, wa)
        section_for_table("Consumer Price Index", n2, r2, d2, wb, wa, {"labels": {}}, lines_new, lines_rev, lines_rem)
        for title, lines in (("New June price index figures", lines_new), ("Revised June price index figures", lines_rev)):
            if lines:
                out_cpi.append(f"{title}:")
                out_cpi.extend(lines)
        if lines_rem:
            out_cpi.append("REMOVED June price index figures (this should never happen):")
            out_cpi.extend(lines_rem)
        if cpi_changed:
            out_cpi.append("**A changed price index changes every inflation-adjusted figure on the site.**")
            out_cpi.append("")
    for name in ("governments.csv", "events.csv"):
        pb, pa = Path(before) / "shared" / name, Path(after) / "shared" / name
        tb = pb.read_bytes().replace(b"\r\n", b"\n") if pb.exists() else None
        ta = pa.read_bytes().replace(b"\r\n", b"\n") if pa.exists() else None
        if tb != ta:
            out_cpi.append(f"- shared/{name} changed. The scrapers do not write this file, so check who changed it.")
    problems += n_rem

    # sources and scrapers
    status, status_err = read_status(status_path)
    src_lines, src_changed = source_lines(before, after)
    failed = {n: s for n, s in status.items() if isinstance(s, dict) and not s.get("ok")}
    problems += len(failed) + (1 if status_err else 0)
    out_src = list(src_lines)
    if status:
        worked = [n for n in status if n not in failed]
        out_src.append("")
        out_src.append(f"Scrapers that worked: {', '.join(worked) if worked else 'none'}.")
    if status_err:
        out_src.append("")
        out_src.append(status_err)
    for n, s in failed.items():
        out_src.append("")
        out_src.append(f"**Scraper failed: {n}** (exit code {s.get('exit_code')}). Nothing from this scraper was saved. The last lines it printed:")
        out_src.append("")
        out_src.append("```")
        out_src.append((s.get("output_tail") or "(no output)").rstrip())
        out_src.append("```")

    # targets
    tgt_lines, tgt_problems = targets_due(after, today)
    problems += len(tgt_problems)
    tgt_lines = tgt_lines + tgt_problems

    changed = trees_differ(before, after)

    summary = f"{plural(n_new, 'new data point')}, {plural(n_rev, 'revised figure')}, {plural(problems, 'problem')}"

    def body(lines):
        text = "\n".join(lines).strip("\n")
        return text if text else "None"

    removed_text = body(out_rem)
    if out_rem:
        removed_text = ("**WARNING: data points have been removed from the files. This should never happen. "
                        "Do not merge until you know why.**\n\n" + removed_text)

    if n_rem or failed:
        todo = "Do not merge yet. " if n_rem else ""
        if n_rem:
            todo += "Find out why data points were removed. "
        if failed:
            todo += "A source could not be read; see the Sources section. "
        if changed:
            todo += "Otherwise, review the figures above against the source."
    elif changed:
        todo = "Review the figures above against the source, then merge this pull request."
    elif src_changed:
        todo = ("Nothing to do. A downloaded source file came back with different bytes, but the "
                "figures read from it are the same, so nothing on the site changes.")
    else:
        todo = "Nothing to do."

    md = [
        f"# Weekly data update, {today.isoformat()}",
        "",
        f"**{summary}**",
        "",
        "## New data points",
        "",
        body(out_new),
        "",
        "## Revised history",
        "",
        body(out_rev),
        "",
        "## Removed data points",
        "",
        removed_text,
        "",
        "## Sources",
        "",
        body(out_src),
        "",
        "## Shared files",
        "",
        body(out_cpi),
        "",
        f"## Targets due within {TARGET_DAYS} days",
        "",
        body(tgt_lines),
        "",
        "## What to do",
        "",
        todo.strip(),
        "",
    ]
    if notes:
        md.insert(md.index("## New data points"), "## Files that could not be read\n\n" + "\n".join(notes) + "\n")
    return "\n".join(md), summary, changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the weekly what-changed report.")
    ap.add_argument("--before", required=True, help="copy of the project before the scrapers ran")
    ap.add_argument("--after", required=True, help="copy of the project after the scrapers ran")
    ap.add_argument("--status", required=True, help="JSON file written by run_all.py")
    ap.add_argument("--out", required=True, help="where to write the Markdown report")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    ap.add_argument("--changed-flag", help="file to write true or false to")
    args = ap.parse_args(argv)
    try:
        today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    except ValueError:
        print("ERROR: --today must look like 2026-11-17", file=sys.stderr)
        return 2
    md, summary, changed = build_report(args.before, args.after, args.status, today)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    if args.changed_flag:
        Path(args.changed_flag).write_text("true\n" if changed else "false\n", encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
