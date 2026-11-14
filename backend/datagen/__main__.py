"""Command line: ``python -m datagen --mode starter|full [options]``.

Examples (PowerShell, from backend/)::

    .\\.venv\\Scripts\\python.exe -m datagen --mode starter
    .\\.venv\\Scripts\\python.exe -m datagen --mode full --check-reproducibility
    .\\.venv\\Scripts\\python.exe -m datagen --mode starter --no-load
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from app.core.config import get_settings
from datagen.loader import load_dataset
from datagen.pipeline import OUTPUT_ROOT, compare_runs, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m datagen", description=__doc__)
    parser.add_argument("--mode", choices=("starter", "full"), default="starter")
    parser.add_argument("--seed", type=int, default=None, help="override the configured seed")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUTPUT_ROOT,
        help="output root (a <mode> folder is created inside)",
    )
    parser.add_argument("--no-load", action="store_true", help="do not load into the database")
    parser.add_argument("--db-url", default=None, help="target database (default: from .env)")
    parser.add_argument(
        "--check-reproducibility",
        action="store_true",
        help="generate a second time and compare row counts and SHA-256",
    )
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    ds, manifest = run(args.mode, seed=args.seed, out_root=args.out)
    out = args.out / args.mode
    print(f"[{args.mode}] generated in {time.perf_counter() - t0:.1f}s -> {out}")
    for table, n in manifest["tables"].items():
        print(f"  {table:<26}{n:>9,}")
    for kind, info in manifest["anomalies"].items():
        print(
            f"  anomaly {kind:<40} events={info['events']:<4} "
            f"ground-truth rows={info['ground_truth_rows']}"
        )
    failed = [c for c in ds.baseline_checks + ds.checks if not c.passed]
    print(
        f"  validation: {len(ds.baseline_checks) + len(ds.checks) - len(failed)} passed, "
        f"{len(failed)} failed"
    )

    if args.check_reproducibility:
        with tempfile.TemporaryDirectory() as tmp:
            _, second = run(args.mode, seed=args.seed, out_root=Path(tmp))
        result = compare_runs(manifest, second)
        (out / "reproducibility.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"  reproducibility: identical={result['identical']} "
            f"files={result['files_compared']} rows={result['rows_compared']:,}"
        )
        if not result["identical"]:
            return 1

    if not args.no_load:
        url = args.db_url or get_settings().database_url()
        t1 = time.perf_counter()
        counts = load_dataset(ds.tables, url)
        print(
            f"  loaded {sum(counts.values()):,} rows into the database "
            f"in {time.perf_counter() - t1:.1f}s"
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
