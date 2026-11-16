#!/usr/bin/env python3
"""June quarter price index scraper.

Downloads the quarterly Consumer Price Index (all groups, weighted average of
eight capital cities, original series) from the ABS Data API, saves the raw
response, and writes shared/cpi_june.csv with one row per June quarter.

Run from anywhere:  python3 scrapers/cpi_june.py

If any check fails (a June quarter is missing, a value is unreadable, the series
is not the one expected) nothing is written and the exit code is 1.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/1.10001.10.50.Q?startPeriod=1970-Q1"
ACCEPT = "application/vnd.sdmx.data+csv"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gov-metrics-scraper"
RAW_NAME = "abs-cpi-1.10001.10.50.Q.csv"
FIRST_YEAR = 1971  # the debt tables start at 1970-71, which ends on 30 June 1971

# The ABS key 1.10001.10.50.Q means: measure 1 (index numbers), index 10001
# (all groups CPI), TSEST 10 (original), region 50 (weighted average of eight
# capital cities), frequency Q (quarterly). These columns must be constant.
EXPECTED = {"MEASURE": "1", "INDEX": "10001", "TSEST": "10", "REGION": "50", "FREQ": "Q"}


class ScrapeError(Exception):
    """Something is wrong with the source or the data. Nothing gets written."""


def fetch(url=URL):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})
        except requests.RequestException as e:
            last = e
            time.sleep(2)
            continue
        if r.status_code != 200:
            raise ScrapeError(f"{url} answered HTTP {r.status_code}")
        return r.content
    raise ScrapeError(f"{url} could not be downloaded: {last}")


def parse_cpi(raw: bytes):
    """Returns ([(date, index_text)], base_text) for the June quarters 1971 to the latest.

    index_text is exactly the text the ABS printed (for example '98.43').
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"the response is not text: {e}") from None
    reader = csv.DictReader(io.StringIO(text))
    need = {"TIME_PERIOD", "OBS_VALUE", "BASE_PERIOD", *EXPECTED}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise ScrapeError(f"the response lacks the expected columns {sorted(need)}; got {reader.fieldnames}")
    seen = set()
    june = {}
    bases = set()
    for line_no, row in enumerate(reader, start=2):
        for col, want in EXPECTED.items():
            if row[col] != want:
                raise ScrapeError(f"line {line_no}: {col} is {row[col]!r}, expected {want!r}. This is not the series asked for.")
        period = row["TIME_PERIOD"]
        m = re.fullmatch(r"(\d{4})-Q([1-4])", period)
        if not m:
            raise ScrapeError(f"line {line_no}: unexpected period {period!r}")
        if period in seen:
            raise ScrapeError(f"line {line_no}: period {period} appears twice")
        seen.add(period)
        bases.add(row["BASE_PERIOD"])
        if m.group(2) != "2":
            continue
        year = int(m.group(1))
        value = row["OBS_VALUE"].strip()
        if not re.fullmatch(r"\d+(\.\d+)?", value) or float(value) <= 0:
            raise ScrapeError(f"line {line_no}: {period} has an unreadable index value {value!r}")
        if year >= FIRST_YEAR:
            june[year] = value
    if len(bases) != 1:
        raise ScrapeError(f"the file has more than one base period code: {sorted(bases)}")
    base_code = bases.pop()
    if not re.fullmatch(r"[A-Za-z0-9.\- ]+", base_code):
        raise ScrapeError(f"base period code looks odd: {base_code!r}")
    if not june:
        raise ScrapeError("no June quarters found")
    first, last = min(june), max(june)
    if first != FIRST_YEAR:
        raise ScrapeError(f"first June quarter is {first}, expected {FIRST_YEAR}")
    missing = [y for y in range(first, last + 1) if y not in june]
    if missing:
        raise ScrapeError(f"missing June quarters: {missing}")
    # The ABS gives the base only as a code. It is passed on as given, not decoded.
    base_text = f"base period {base_code} as coded by the ABS"
    return [(f"{y}-06-30", june[y]) for y in sorted(june)], base_text


def write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(root=ROOT, fetcher=fetch, log=print):
    root = Path(root)
    log(f"Downloading {URL}")
    raw = fetcher()
    retrieved = datetime.now(timezone.utc).date().isoformat()
    rows, base_text = parse_cpi(raw)
    log(f"June quarters {rows[0][0][:4]} to {rows[-1][0][:4]}: {len(rows)} rows, none missing. Base: {base_text}")

    sources = root / "shared" / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest[RAW_NAME] = {"url": URL, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    write_atomic(sources / RAW_NAME, raw)
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "index", "base"])
    for date, value in rows:
        w.writerow([date, value, base_text])
    write_atomic(root / "shared" / "cpi_june.csv", buf.getvalue().encode("utf-8"))
    log(f"Wrote shared/cpi_june.csv, saved the raw response and the manifest.")
    return rows, base_text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download the ABS CPI and write the June quarter file.")
    ap.add_argument("--root", default=str(ROOT), help="project folder to write into (default: this project)")
    args = ap.parse_args(argv)
    try:
        run(root=args.root)
    except ScrapeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
