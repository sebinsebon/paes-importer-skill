"""Shared helpers. Runtime writes stay in the explicitly selected workspace."""
from __future__ import annotations

import hashlib
import json
import math
import re
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = None
UPSTREAM = ROOT  # Compatibility alias for this bundle, not an external checkout.


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def no_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError(f'Linked output path: {item}')
    return path.resolve()


def configure_workspace(path):
    global WORKSPACE
    from runtime_environment import external_path
    WORKSPACE = external_path(path)
    if WORKSPACE == Path(WORKSPACE.anchor):
        raise ValueError('A filesystem root cannot be an output workspace')
    return WORKSPACE


def inside(path):
    if WORKSPACE is None:
        raise ValueError('Configure the explicit output workspace first')
    path = no_links(path)
    if path == ROOT or path.is_relative_to(ROOT):
        raise ValueError('Runtime installation is read-only; select an external workspace')
    if not path.is_relative_to(WORKSPACE):
        raise ValueError(f'Destination leaves selected workspace: {path}')
    return path


def write(path, value):
    path = inside(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = inside(path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp'))
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def relative_path(value, prefix=None):
    if not isinstance(value, str) or not value or len(value)>1024 or re.search(r'[\\:\x00-\x1f\x7f<>"|?*]',value):
        raise ValueError(f'Unsafe relative path: {value!r}')
    parts = value.split('/')
    if any(p in ('', '.', '..') for p in parts) or PurePosixPath(value).is_absolute():
        raise ValueError(f'Unsafe relative path: {value!r}')
    if any(p.endswith(('.', ' ')) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',p,re.I) for p in parts):
        raise ValueError(f'Unsafe relative path: {value!r}')
    if prefix and parts[0] != prefix:
        raise ValueError(f'Expected path under {prefix}/: {value}')
    return value


def artifact_path(root, value, prefix=None):
    relative_path(value, prefix)
    root = Path(root).resolve()
    path = root / value
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'Path leaves artifact root: {value}')
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError(f'Linked resource: {value}')
    return path


def bbox(box, width=None, height=None):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError('bbox must have four coordinates')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in box):
        raise ValueError('bbox coordinates must be finite numbers')
    x0, y0, x1, y1 = box
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        raise ValueError(f'Invalid bbox: {box}')
    if width is not None and (x1 > width + .01 or y1 > height + .01):
        raise ValueError(f'bbox exceeds page: {box}')
    return list(box)


def blocks_in(blocks):
    for block in blocks:
        yield block
        if block.get('type') == 'table':
            for row in block['rows']:
                for cell in row:
                    yield from blocks_in(cell)


def question_blocks(q):
    yield from blocks_in(q['stem'])
    for option in q['options']:
        yield from blocks_in(option['blocks'])
    yield from blocks_in(q['explanation']['blocks'])


def event(run_dir, stage, **fields):
    path = inside(Path(run_dir) / 'events.jsonl')
    kind = fields.pop('kind', 'measured' if 'duration_seconds' in fields else 'info')
    metrics = ('duration_seconds','model_calls','input_tokens','output_tokens','cost_usd','human_minutes','retries')
    if kind not in ('info', 'measured'):
        raise ValueError('event kind must be info or measured')
    if kind == 'info' and any(k in fields for k in metrics):
        raise ValueError('Informational events cannot carry measured totals')
    if kind == 'measured':
        for key in metrics:
            value = fields.setdefault(key, None)
            if value is not None and (isinstance(value, bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0):
                raise ValueError(f'Invalid measurement: {key}')
            if key in ('model_calls','input_tokens','output_tokens','retries') and value is not None and type(value) is not int:
                raise ValueError(f'Measurement must be an integer: {key}')
    line = json.dumps({'timestamp': now(), 'stage': stage, 'kind': kind, **fields}, ensure_ascii=False, allow_nan=False) + '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(line)


def output_path(path):
    return inside(path)


def reserve_output(path, stage):
    path = output_path(path)
    if stage == 'verification':
        if not (path / '.work/base/run.json').is_file():
            raise ValueError('Verification needs a completed base')
        if any(p.name != '.work' for p in path.iterdir()):
            raise ValueError('Output already contains artifacts')
    elif path.exists():
        raise ValueError('Output already exists; choose a new run')
    folder = inside(path / '.work' / stage)
    folder.mkdir(parents=True, exist_ok=False)
    temporary = inside(path / '.work/tmp')
    temporary.mkdir(exist_ok=True)
    from runtime_environment import process_environment
    os.environ.update(process_environment(path/'.work', create=True))
    return folder


def publication_path(folder):
    folder = inside(folder)
    output = output_path(read(folder / 'run.json')['output_dir'])
    if folder.parent != output / '.work':
        raise ValueError('Run state and publication destination disagree')
    if any(p.name != '.work' for p in output.iterdir()):
        raise ValueError('Preserve existing published artifacts; use a new run')
    return output
