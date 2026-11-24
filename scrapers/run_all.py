#!/usr/bin/env python3
"""Runs every scraper, one after another, and records how each one went.

Run from anywhere:  python3 scrapers/run_all.py --status /tmp/status.json

Each scraper runs as its own program. If one fails, the others still run. The status file
(JSON) records, for each scraper, whether it worked (ok), its exit code and the last 30 lines
of what it printed. scrapers/report.py reads that file.

The exit code is 0 even when a scraper failed, because the weekly report carries the failure.
It is non-zero only if this program itself breaks (for example the status file cannot be written).

To add a scraper, add a line to REGISTRY. A scraper that depends on another one's output goes after it
and is listed in DEPENDS_ON; if the earlier one failed, the later one is skipped and reported as failed.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# (name used in the report, script file). They run in this order.
REGISTRY = [
    ("cpi_june", "cpi_june.py"),
    ("commonwealth_debt", "commonwealth_debt.py"),
    ("unemployment_rate", "unemployment_rate.py"),
    ("inflation", "inflation.py"),
    ("wages_and_prices", "wages_and_prices.py"),  # copies the inflation page's figures: must run after inflation
    ("rents", "rents.py"),  # downloads everything it needs itself: no dependency on another scraper
    ("social_housing", "social_housing.py"),  # RoGS section 18 and ABS population; downloads everything itself
]

# A scraper that copies another scraper's output. If the one it depends on failed in this run, it is
# not run (its copy could be stale) and is reported as failed, so the weekly job raises an issue.
DEPENDS_ON = {"wages_and_prices": "inflation"}

TAIL_LINES = 30
TIMEOUT_SECONDS = 900


def tail(text, n=TAIL_LINES):
    lines = text.replace("\r\n", "\n").rstrip("\n").split("\n") if text else []
    return "\n".join(lines[-n:])


def run_one(name, script, root):
    cmd = [sys.executable, str(HERE / script), "--root", str(root)]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS, cwd=str(root))
        return {"ok": p.returncode == 0, "exit_code": p.returncode, "output_tail": tail(p.stdout)}
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return {"ok": False, "exit_code": -1,
                "output_tail": tail(out + f"\nStopped: no answer after {TIMEOUT_SECONDS} seconds.")}
    except OSError as e:
        return {"ok": False, "exit_code": -1, "output_tail": f"Could not start {script}: {e}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run every scraper and write a status file.")
    ap.add_argument("--status", required=True, help="where to write the JSON status file")
    ap.add_argument("--root", default=str(ROOT), help="project folder the scrapers write into (default: this project)")
    args = ap.parse_args(argv)

    status = {}
    for name, script in REGISTRY:
        needs = DEPENDS_ON.get(name)
        if needs is not None and not status.get(needs, {}).get("ok", False):
            status[name] = {"ok": False, "exit_code": -2, "skipped": True,
                            "output_tail": f"Skipped: the {needs} scraper did not succeed in this run, and {name} copies its figures. Nothing was written."}
            print(f"  {name}: SKIPPED because {needs} did not succeed", flush=True)
            continue
        print(f"Running {name} ...", flush=True)
        status[name] = run_one(name, script, args.root)
        print(f"  {name}: {'ok' if status[name]['ok'] else 'FAILED'} (exit code {status[name]['exit_code']})", flush=True)

    out = Path(args.status)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    failed = [n for n, s in status.items() if not s["ok"]]
    print(f"{len(status) - len(failed)} of {len(status)} scrapers worked. Status written to {out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
