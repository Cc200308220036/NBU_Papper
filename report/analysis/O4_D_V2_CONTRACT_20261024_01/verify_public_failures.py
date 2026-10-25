"""Read-only regression of historical failures; writes only this report folder."""
from collections import Counter
import hashlib
from pathlib import Path

from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import canonical, read, write
from semantic_pallet_planner.o4.remote_v2.protocol import ProtocolError, parse_response, repair_context


def main():
    counts = Counter()
    rows = []
    for name in ("EXP_O4_D_COMPILE_SMOKE_REAL_20261023_01", "EXP_O4_D_ORDERS_REAL_20261023_01"):
        for path in sorted((WORKSPACE / "semantic_pallet_planner/outputs" / name / "responses").glob("D*.json")):
            record = read(path)
            if record["status"] not in ("invalid_ast", "invalid_binding"):
                continue
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            try:
                parse_response(record["attempts"][-1]["payload"], record["envelope"]["public_request"])
            except ProtocolError as exc:
                diagnostic = repair_context(exc, record["attempts"][-1]["payload"])
            else:
                raise AssertionError(f"Historical invalid response unexpectedly accepted: {path}")
            counts[diagnostic["issues"][0]["reason"]] += 1
            assert hashlib.sha256(path.read_bytes()).hexdigest() == before
            rows.append({"path": str(path.relative_to(WORKSPACE)), "sha256": before,
                         "original_status": record["status"], "issues": diagnostic["issues"]})
    assert len(rows) == 247 and counts["invalid_selector_value"] == 237
    result = {"status": "PASS", "checked": len(rows), "reasons": dict(counts),
              "real_api_calls": 0, "original_results_changed": False,
              "model_repairs_measured": False, "rows": rows}
    write(Path(__file__).parent / "failure_regression.json", result)
    print(canonical({key: value for key, value in result.items() if key != "rows"}))


if __name__ == "__main__":
    main()
