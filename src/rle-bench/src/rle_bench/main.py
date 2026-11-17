"""Generate the five CPU tasks from an immutable RLE-Bench revision."""
import argparse
import logging
from pathlib import Path
import subprocess

from .adapter import RLEBenchAdapter, TASKS, UPSTREAM_COMMIT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("datasets/rle-bench-cpu"))
    parser.add_argument("--source-dir", type=Path,
                        help=f"Clean local checkout at {UPSTREAM_COMMIT}; otherwise fetch the pinned revision")
    parser.add_argument("--limit", type=int, help="Generate the first N selected tasks")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing generated tasks")
    parser.add_argument("--task-ids", nargs="+", help="CPU task IDs or native selectors")
    parser.add_argument("--list", action="store_true", help="List available CPU task IDs")
    args = parser.parse_args()
    if args.list:
        print("\n".join(task.task_id for task in TASKS))
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        RLEBenchAdapter(args.output_dir, limit=args.limit, overwrite=args.overwrite,
                        task_ids=args.task_ids, source_dir=args.source_dir).run()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
