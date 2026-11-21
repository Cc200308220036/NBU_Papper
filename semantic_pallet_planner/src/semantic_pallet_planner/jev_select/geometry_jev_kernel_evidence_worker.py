"""Read-only v17 verification with closed, byte-checked historical imports."""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path


class HistoricalImports(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Own every historical package import; never fall through to other finders."""
    prefix = 'semantic_pallet_planner'

    def __init__(self, root, files):
        self.root = Path(root).resolve()
        self.files = files
        if any(n == self.prefix or n.startswith(self.prefix + '.') for n in sys.modules):
            raise ImportError('historical_import_already_loaded')

    def location(self, fullname):
        relative = fullname.split('.')[1:]
        stem = '/'.join(relative)
        for name, package in ((stem + '/__init__.py' if stem else '__init__.py', True),
                              (stem + '.py', False)):
            if name in self.files:
                path = self.root / name
                if path.resolve() != path or not path.is_relative_to(self.root):
                    raise ImportError('historical_import_origin_mismatch')
                return path, name, package
        raise ImportError('historical_import_not_in_manifest: ' + fullname)

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.prefix and not fullname.startswith(self.prefix + '.'):
            return None
        origin, _, package = self.location(fullname)
        # A package may not redirect its children to another search location.
        if fullname != self.prefix:
            parent_name = fullname.rsplit('.', 1)[0]
            parent_path, _, _ = self.location(parent_name)
            if list(path or []) != [str(parent_path.parent)]:
                raise ImportError('historical_import_search_path_mismatch')
        return importlib.util.spec_from_file_location(
            fullname, origin, loader=self,
            submodule_search_locations=[str(origin.parent)] if package else None)

    def get_resource_reader(self, fullname):
        # Historical contracts use importlib.resources for their local Schemas.
        # This reader serves the same isolated directory; it never loads code.
        path, _, package = self.location(fullname)
        if package:
            return importlib.machinery.SourceFileLoader(fullname, str(path)).get_resource_reader(fullname)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, name, package = self.location(module.__name__)
        if module.__spec__.origin != str(path) or module.__file__ != str(path):
            raise ImportError('historical_import_origin_mismatch')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.files[name]:
            raise ImportError('historical_import_bytes_mismatch')
        # Compile the checked bytes directly: no pyc, alternate loader or lookup.
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        if module.__file__ != str(path) or module.__spec__.origin != str(path):
            raise ImportError('historical_import_origin_mismatch')
        if package and list(module.__path__) != [str(path.parent)]:
            raise ImportError('historical_import_search_path_mismatch')


def main():
    root, manifest_path, receipt_path, monitor_path = sys.argv[1:]
    files = json.loads(Path(manifest_path).read_bytes())
    finder = HistoricalImports(root, files)
    sys.meta_path.insert(0, finder)
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
