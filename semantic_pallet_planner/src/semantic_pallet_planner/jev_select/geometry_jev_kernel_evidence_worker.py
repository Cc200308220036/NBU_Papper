"""Read-only v17 verifier process. Only invoked after package byte verification.

No credential loader, freezer, runner, monitor assessment or solver is called.
The historical contract validates its own identities and durable records.
"""
import sys
from pathlib import Path


def main():
    root, receipt_path, monitor_path = sys.argv[1:]
    # Remove the current package directory; only the verified historical package
    # can supply semantic_pallet_planner imports in this process.
    sys.path[0] = str(Path(root).parent)
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    from semantic_pallet_planner.jev_select.ledger import read
    from semantic_pallet_planner.jev_select.packaging_geometry_protocol import (
        read_reference, validate_real_kernel_receipt)
    receipt = read(receipt_path)
    validate_schema('geometry_real_kernel_receipt_v3', receipt)
    acceptance = read_reference(receipt['acceptance_plan'])
    validate_real_kernel_receipt(receipt, acceptance, read(monitor_path))
    print('GP5_V17_EVIDENCE_VALID')


if __name__ == '__main__':
    main()
