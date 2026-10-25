"""No-network deterministic headroom audit; never changes the sealed corpus."""
import argparse
from collections import defaultdict
from pathlib import Path

from semantic_pallet_planner.o4.common import read, write
from semantic_pallet_planner.o4.research.episode import compile_source
from semantic_pallet_planner.o4.research.metrics import compilation_metrics
from semantic_pallet_planner.o4.research.data import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.corpus)
    verify(root)
    data = read(root / "private/input_snapshot.json")
    groups = defaultdict(list)
    for case in data["fixed"]:
        for backend in ("public_parser", "normalized_parser"):
            response, status, _ = compile_source(case["request"], backend)
            metrics = compilation_metrics(case["request"], response, case["reference_policy"], case["candidates"])
            groups[(case["split"], case["track"], backend)].append({"case_id": case["case_id"], "status": status, **metrics})
    result = {"status": "PASS", "real_api_calls": 0,
              "purpose": "identify deterministic baseline headroom before paying for a model study",
              "groups": [{"split": split, "track": track, "backend": backend, "cases": len(rows),
                          "semantic_correct": sum(r["semantic_equal"] for r in rows),
                          "unsupported": sum(r["status"] == "unsupported_construct" for r in rows),
                          "semantic_headroom_cases": sum(not r["semantic_equal"] for r in rows)}
                         for (split, track, backend), rows in sorted(groups.items())]}
    write(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
