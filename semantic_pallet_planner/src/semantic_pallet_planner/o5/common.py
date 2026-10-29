"""O5-owned serialization, atomic storage and single-writer locks."""
import contextlib
import fcntl
import hashlib
import json
import os
import socket
import tempfile
from pathlib import Path

VERSION = 'o5_direct_memory_v1'
ROOT = Path(__file__).resolve().parents[4]


class O5Error(ValueError):
    def __init__(self, code, detail=''):
        self.code = code
        super().__init__(code + (': ' + detail if detail else ''))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    def reject(value):
        raise O5Error('NON_FINITE_JSON', value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise O5Error('RUN_BUSY') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def new_directory(path):
    path = Path(path).resolve()
    forbidden = ('semantic_pallet_dataset_v1', 'raw', 'ReMe-main', 'GOPT-main', 'PackLab-main')
    if any(path == ROOT / n or path.is_relative_to(ROOT / n) for n in forbidden):
        raise O5Error('PROTECTED_OUTPUT')
    if path.is_relative_to(ROOT):
        output_root = ROOT/'semantic_pallet_planner/outputs'
        report_root = ROOT/'report/analysis'
        allowed = any(path.parent == base and 'O5_' in path.name for base in (output_root, report_root))
        if not allowed:
            raise O5Error('PROTECTED_OUTPUT', 'use a new direct O5 output/report directory')
    path.mkdir(parents=True, exist_ok=False)
    return path


@contextlib.contextmanager
def offline_guard():
    """Process-local CLI guard; imports do not modify global networking behavior."""
    original_connect = socket.socket.connect
    original_connection = socket.create_connection
    def reject(*args, **kwargs):
        raise O5Error('NETWORK_FORBIDDEN_IN_S1')
    socket.socket.connect = reject
    socket.create_connection = reject
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_connection
