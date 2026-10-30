"""Offline, versioned O4 equivalence evaluation; contains no remote mode."""
import argparse
import json

from ..o4.common import O4Error
from ..o4.evaluation_v2_rescore import rescore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", action="append", required=True, help="sealed fixed experiment; repeat for multiple runs")
    parser.add_argument("--output", required=True, help="new directory outside the source experiments")
    args = parser.parse_args(argv)
    try:
        result = rescore(args.experiment, args.output)
    except (O4Error, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
