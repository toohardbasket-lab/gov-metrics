"""Reusable loader for the Productivity Commission's Report on Government Services (RoGS).

Each RoGS section is published as a CSV dataset and an Excel workbook. This module:

1. finds today's files (`discover`): the newest year folder on the RoGS front page, its data-downloads
   page, and the one link whose file name contains each requested slug. If the newest year's page does
   not have the section yet, the previous year is tried and the result says so (`fell_back_from`).
2. reads the CSV (`parse_dataset`) and selects rows by exact matches on named columns (`select`). There
   must be exactly one row for each year and selection: none, or two, is a refusal.
3. reads the same figures from the workbook (`read_workbook`), finding the sheet by the table number and
   the rows by their labels, and requires every selected figure to agree (`cross_check`).
4. keeps history (`merge_history`): each edition carries only the last five or ten years, so rows already
   stored for years the new edition no longer carries are kept unchanged, years in both come from the new
   edition, and a map records which edition each stored period last came from.

Cell codes: `..` not applicable, `na` not available, `np` not published, `–` or `-` nil or rounded to
zero. They are kept as codes (the en dash is written as a plain `-`), never turned into numbers. The
metric decides what a code means. An empty cell, or text that is neither a number nor a code, is refused.

Every function raises ScrapeError on anything unexpected; callers write nothing in that case.
No figure is typed here: every value comes from the downloaded bytes.
"""
import csv
import io
import re
from collections import namedtuple
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

from abs_series import ScrapeError

FRONT_URL = "https://www.pc.gov.au/ongoing/report-on-government-services/"
ALLOWED_HOSTS = {"www.pc.gov.au", "assets.pc.gov.au"}

# The jurisdiction columns of a RoGS CSV, in order. "Total" exists in some sections and is not required.
JURISDICTIONS = ["NSW", "Vic", "Qld", "WA", "SA", "Tas", "ACT", "NT", "Aust"]
CODES = {"..", "na", "np", "-"}
NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")
YEAR_RE = re.compile(r"\d{4}(-\d{2})?")

Discovery = namedtuple("Discovery", "edition files fell_back_from")  # files: {slug: url}


# ---------------------------------------------------------------- discovery

def _links(html_bytes):
    html = html_bytes.decode("utf-8", errors="replace")
    return [m.group(1).strip() for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html, re.I)]


def newest_editions(front_html):
    """Every year that has a /<year>/data-downloads/ link on the RoGS front page, newest first."""
    years = {int(m.group(1)) for href in _links(front_html)
             for m in [re.search(r"/report-on-government-services/(\d{4})/data-downloads/?$", href.split("#")[0].split("?")[0])] if m}
    if not years:
        raise ScrapeError("no /<year>/data-downloads/ link was found on the RoGS front page")
    return sorted(years, reverse=True)


def _pick(links, base, slug, page):
    found = []
    for href in links:
        name = urlparse(href.split("#")[0]).path.rsplit("/", 1)[-1]
        if slug in name:
            full = urljoin(base, href)
            if full not in found:
                found.append(full)
    if not found:
        return None
    if len(found) > 1:
        raise ScrapeError(f"more than one link on {page} has {slug!r} in its file name: {found}")
    u = urlparse(found[0])
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ScrapeError(f"the link {found[0]} is not an https address on {sorted(ALLOWED_HOSTS)}")
    return found[0]


def discover(fetcher, slugs, front_url=FRONT_URL, log=print):
    """Finds the file for every slug (for example 'section18-housing-dataset'). Takes the newest year; if
    that year's page lacks one of the slugs, falls back to the previous year and says so. Refuses if no
    year has all of them or if any slug matches more than one link. Returns a Discovery."""
    editions = newest_editions(fetcher(front_url, "text/html"))
    newest = editions[0]
    for k, year in enumerate(editions[:2]):
        page = urljoin(front_url, f"{year}/data-downloads/")
        links = _links(fetcher(page, "text/html"))
        files = {slug: _pick(links, page, slug, page) for slug in slugs}
        missing = [s for s, u in files.items() if u is None]
        if not missing:
            if k:
                log(f"The {newest} edition's data-downloads page has no file for {', '.join(slugs)} yet; using the {year} edition instead.")
            return Discovery(str(year), files, str(newest) if k else None)
        if k == 0:
            log(f"The {year} data-downloads page has no link for {', '.join(missing)}.")
    raise ScrapeError(f"no link for {', '.join(slugs)} on the data-downloads pages of the {editions[0]} or the previous edition")


# ---------------------------------------------------------------- the CSV

class Dataset:
    def __init__(self, header, rows):
        self.header, self.rows = header, rows


def normalise_cell(text):
    """A cell as the loader keeps it: a number as written, or a code ('–' becomes '-'). Anything else
    (an empty cell, thousands separators, words) is refused."""
    t = str(text).strip().replace("–", "-").replace("−", "-")
    if t in CODES or NUMBER_RE.fullmatch(t):
        return t
    raise ScrapeError(f"the cell {text!r} is neither a number nor one of the codes {sorted(CODES)}")


def is_code(text):
    return text in CODES


def parse_dataset(raw, label="the RoGS CSV"):
    """Reads a RoGS CSV. Requires Table_Number, Year, Measure, Unit and every jurisdiction column."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ScrapeError(f"{label} is empty") from None
    need = ["Table_Number", "Year", "Measure", "Unit", *JURISDICTIONS]
    missing = [c for c in need if c not in header]
    if missing:
        raise ScrapeError(f"{label} lacks the columns {missing}; it has {header}")
    if len(set(header)) != len(header):
        raise ScrapeError(f"{label} has a repeated column name")
    rows = []
    for n, r in enumerate(reader, start=2):
        if not r:
            continue
        if len(r) != len(header):
            raise ScrapeError(f"{label}: line {n} has {len(r)} fields; the header has {len(header)}")
        rows.append(dict(zip(header, r)))
    if not rows:
        raise ScrapeError(f"{label} has no rows")
    return Dataset(header, rows)


def years_of(ds, where):
    """The years of the rows that match `where` (exact matches), sorted."""
    return sorted({r["Year"] for r in ds.rows if all(r.get(k) == v for k, v in where.items())})


def select(ds, where, years, columns=JURISDICTIONS, label="the RoGS CSV"):
    """One selection: the rows whose columns equal `where` exactly, one per year in `years`. Returns
    {year: {column: cell}} with cells normalised (numbers as written, codes as codes). Refuses if a year
    has no matching row, if it has more than one, or if a cell is empty or unreadable."""
    for k in where:
        if k not in ds.header:
            raise ScrapeError(f"{label} has no column {k!r}")
    for c in columns:
        if c not in ds.header:
            raise ScrapeError(f"{label} has no column {c!r}")
    out = {}
    for year in years:
        hits = [r for r in ds.rows if r["Year"] == year and all(r[k] == v for k, v in where.items())]
        if len(hits) != 1:
            raise ScrapeError(f"{label}: {len(hits)} rows match {where} for the year {year}; expected exactly one")
        row = hits[0]
        try:
            out[year] = {c: normalise_cell(row[c]) for c in columns}
        except ScrapeError as e:
            raise ScrapeError(f"{label}: {where}, {year}: {e}") from None
    return out


def units_of(ds, where, years):
    """The Unit text of the selected rows (must be one)."""
    units = {r["Unit"] for r in ds.rows if r["Year"] in years and all(r[k] == v for k, v in where.items())}
    if len(units) != 1:
        raise ScrapeError(f"the rows matching {where} have {len(units)} different units: {sorted(units)}")
    return units.pop()


# ---------------------------------------------------------------- the workbook

FOOTNOTE_RE = re.compile(r"(?:[\s ]*\((?:[a-z]{1,2}|\d{1,2})\)[\s,]*)+$")


def clean_label(value):
    """A workbook label without its footnote marks: 'NSW\\xa0(c)' -> 'NSW', 'Public housing\\xa0(i), (j)' -> 'Public housing'."""
    if value is None:
        return ""
    return FOOTNOTE_RE.sub("", re.sub(r"\s+", " ", str(value).replace(" ", " ")).strip()).strip()


def read_workbook(raw, table_number, label="the RoGS workbook", group=None, unit_in_path=False):
    """Reads the sheet for `table_number` (the sheet whose name is 'Table <number>') into a list of
    (path, year, {column: cell}). `path` is the tuple of row labels above the figure. The row labels are in
    the first columns, then Unit, then one column per jurisdiction headed by its name (with footnote marks).
    The year is found in either of the two layouts the Commission uses:
      - the year is the figure row's own label (the last label column), as in housing: the path is the
        labels above it;
      - the year is a label row of its own (for example '2024-25' above its figures): the year is then
        left out of the path, and the figure row's own label is the last element of the path.
    group: some sheets hold two sets of jurisdiction columns side by side, each under a heading above the
    header row (for example '50th percentile' and '90th percentile'). Name the heading to read that set;
    without it, a repeated jurisdiction column is refused.
    unit_in_path: add the row's Unit to the end of the path, for sheets where two rows differ only by unit
    (a count and a per cent)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ScrapeError(f"{label} could not be opened as an Excel file: {e}") from None
    try:
        want = f"table {table_number}".lower()
        names = [n for n in wb.sheetnames if re.sub(r"\s+", " ", n).strip().lower() == want]
        if len(names) != 1:
            raise ScrapeError(f"{label} has {len(names)} sheets named 'Table {table_number}'; it has {wb.sheetnames[:8]}...")
        ws = wb[names[0]]
        ws.reset_dimensions()  # some workbooks declare the sheet as one cell (A1); read what is really there
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    head = [i for i, r in enumerate(rows[:10]) if r and "Unit" in [clean_label(v) for v in r]]
    if len(head) != 1:
        raise ScrapeError(f"{label}: expected one header row with 'Unit' near the top of sheet {names[0]}, found {len(head)}")
    h = rows[head[0]]
    labels = [clean_label(v) for v in h]
    unit_col = labels.index("Unit")
    # headings above the header row, to the right of Unit, mark column groups; a group runs to the next heading
    starts = sorted((j, clean_label(v)) for r in rows[: head[0]] for j, v in enumerate(r) if j > unit_col and clean_label(v) != "")
    span = (unit_col + 1, len(h))
    if group is not None:
        mine = [k for k, (_, g) in enumerate(starts) if g == group]
        if len(mine) != 1:
            raise ScrapeError(f"{label}: sheet {names[0]} has {len(mine)} column headings {group!r} above the header row; it has {[g for _, g in starts]}")
        span = (starts[mine[0]][0], starts[mine[0] + 1][0] if mine[0] + 1 < len(starts) else len(h))
    cols = {}
    for j, name in enumerate(labels):
        if span[0] <= j < span[1] and j > unit_col and name in JURISDICTIONS:
            if name in cols:
                raise ScrapeError(f"{label}: the column {name} appears twice in sheet {names[0]}")
            cols[name] = j
    absent = [c for c in JURISDICTIONS if c not in cols]
    if absent:
        raise ScrapeError(f"{label}: sheet {names[0]} has no column for {absent}")
    current = [None] * unit_col
    year_level, block_year = None, None  # a year label row: the level it sits at, and the year
    out, seen_data = [], False
    for k, r in enumerate(rows[head[0] + 1:], start=head[0] + 2):
        r = list(r) + [None] * (len(h) - len(r))
        if all(v is None or str(v).strip() == "" for v in r):
            if seen_data:
                break  # the blank row after the last figure: what follows are notes
            continue
        lab = [i for i in range(unit_col) if r[i] is not None and str(r[i]).strip() != ""]
        has_unit = r[unit_col] is not None and str(r[unit_col]).strip() != ""
        if not has_unit:
            if lab:  # a label row: it sets its level and clears the deeper ones
                i = lab[0]
                text = clean_label(r[i])
                if year_level is not None and i <= year_level:
                    year_level, block_year = None, None
                if YEAR_RE.fullmatch(text):
                    year_level, block_year = i, text
                    current[i] = None  # the year is not part of the path
                else:
                    current[i] = text
                for d in range(i + 1, unit_col):
                    current[d] = None
            continue
        if len(lab) != 1:
            raise ScrapeError(f"{label}: sheet {names[0]} row {k} has a figure but {len(lab)} label cells; expected one")
        own = clean_label(r[lab[0]])
        if YEAR_RE.fullmatch(own):  # the year is the row's own label
            year = own
            path = tuple(c for c in current[: lab[0]] if c)
        else:  # the year is a label row above; the row's own label ends the path
            if block_year is None:
                raise ScrapeError(f"{label}: sheet {names[0]} row {k} has {own!r} where a year was expected, and no year row above it")
            year = block_year
            path = tuple(c for c in current[: lab[0]] if c) + (own,)
        if unit_in_path:
            path = path + (clean_label(r[unit_col]),)
        cells = {}
        for c, j in cols.items():
            v = r[j]
            if v is None or str(v).strip() == "":
                cells[c] = ""  # kept empty; a selected empty cell is refused by cross_check
            elif isinstance(v, bool):
                raise ScrapeError(f"{label}: sheet {names[0]} row {k} column {c} holds a true/false value")
            elif isinstance(v, (int, float)):
                cells[c] = format(Decimal(repr(v)), "f") if isinstance(v, float) else str(v)
            else:
                cells[c] = str(v).strip()
        out.append((path, year, cells))
        seen_data = True
    if not out:
        raise ScrapeError(f"{label}: sheet {names[0]} holds no figures")
    return out


def description_path(where):
    """The workbook's row labels for a CSV selection: its Description1, Description2... values that are
    not empty, in order. (Description columns the workbook shows as the table title are not used for
    selection; the caller selects only on the ones that are row labels.)"""
    keys = sorted((k for k in where if re.fullmatch(r"Description\d+", k)), key=lambda k: int(k[11:]))
    return tuple(where[k] for k in keys if where[k] != "")


def _same(a, b):
    if a == b:
        return True
    try:
        return Decimal(a) == Decimal(b)
    except InvalidOperation:
        return False


def cross_check(selected, workbook_rows, path, label="the RoGS workbook", columns=JURISDICTIONS):
    """Every selected figure ({year: {column: cell}}) must equal the workbook's figure for the row with
    the label path `path` in the same year and column. The workbook must hold every selected year for
    that path (it may hold more). Returns the number of figures compared. Refuses on any difference."""
    mine = {y: cells for p, y, cells in workbook_rows if p == tuple(path)}
    dup = [y for p, y, _ in workbook_rows if p == tuple(path)]
    if len(dup) != len(set(dup)):
        raise ScrapeError(f"{label}: the labels {list(path)} appear more than once for a year")
    if not set(selected) <= set(mine):
        raise ScrapeError(f"{label}: for {list(path)} the workbook has the years {sorted(mine)} but the CSV selection has {sorted(selected)}")
    bad, n = [], 0
    for y in sorted(selected):
        for c in columns:
            n += 1
            try:
                w = normalise_cell(mine[y][c])
            except ScrapeError:
                bad.append(f"{y} {c}: the workbook cell is {mine[y][c]!r}")
                continue
            if not _same(selected[y][c], w):
                bad.append(f"{y} {c}: CSV {selected[y][c]}, workbook {w}")
    if bad:
        shown = "; ".join(bad[:10]) + (f"; and {len(bad) - 10} more" if len(bad) > 10 else "")
        raise ScrapeError(f"{label}: the CSV and the workbook disagree for {list(path)} in {len(bad)} figure(s): {shown}")
    return n


# ---------------------------------------------------------------- keeping history

def merge_history(old_rows, new_rows, carried, edition, old_editions=None):
    """Keeps what the new edition no longer carries.

    old_rows: rows already stored, each a dict with at least 'period'. new_rows: rows from the new edition.
    carried: the set of periods the new edition carries. Stored rows for periods NOT in `carried` are kept
    unchanged and put first; every period in `carried` comes from new_rows (the checker's revision test then
    decides whether a changed figure is accepted). Returns (rows, editions) where editions maps each stored
    period to the edition it last came from: `edition` for carried periods, the old map's value for kept ones.
    A kept period with no entry in old_editions is refused (its source would be unknown)."""
    old_editions = old_editions or {}
    kept = [r for r in old_rows if r["period"] not in carried]
    editions = {}
    for r in kept:
        p = r["period"]
        if p not in old_editions:
            raise ScrapeError(f"the stored period {p} is not carried by the {edition} edition and the manifest does not say which edition it came from")
        editions[p] = old_editions[p]
    for p in carried:
        editions[p] = edition
    return kept + list(new_rows), dict(sorted(editions.items()))
