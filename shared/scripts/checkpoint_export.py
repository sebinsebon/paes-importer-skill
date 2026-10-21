"""Portable recovery archives; historical files in the original run are untouched."""
from __future__ import annotations

import json
import os
import uuid
import zipfile
from pathlib import Path

from checkpoints import recover, state_lock
from lab import artifact_path, digest, inside, no_links, read, relative_path

PROTOCOL = 'recovery-checkpoint-1'


def resolve_sources(folder):
    """Resolve legacy absolute paths or portable paths relative to the run root."""
    folder = Path(folder)
    root = no_links(folder.parent.parent)
    paths = read(folder/'sources.local.json')
    sources = read(folder/'sources.json')
    if set(paths) != {s['id'] for s in sources}:
        raise ValueError('Local source registry differs from frozen sources')
    resolved = {}
    for source in sources:
        value = paths[source['id']]
        if not isinstance(value, str):
            raise ValueError('Source registry paths must be strings')
        path = Path(value)
        if not path.is_absolute():
            path = artifact_path(root, value)
        path = no_links(path)
        if not path.is_file() or digest(path) != source['sha256']:
            raise ValueError('Source changed: missing or altered source: '+source['id'])
        resolved[source['id']] = str(path)
    return resolved


def _references(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str):
            yield value['path']
        for item in value.values():
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _review_paths(folder, document, value):
    """Probe receipts use paths relative to their self-contained nested subrun."""
    base = document.parent
    while base != folder:
        if (base/'candidate.json').is_file() and (base/'reviews').is_dir():
            break
        base = base.parent
    for reference in _references(value):
        if reference.startswith('reviews/'):
            yield artifact_path(base, reference, 'reviews').relative_to(folder).as_posix()


def export_checkpoint(folder, output_zip):
    folder = inside(folder)
    with state_lock(folder):
        recover(folder)
        return _export(folder, output_zip)


def _export(folder, output_zip):
    from runtime_environment import external_path
    output_zip = external_path(output_zip)
    if output_zip.exists():
        raise ValueError('Checkpoint export must use a new filename')
    root = folder.parent.parent
    if output_zip.is_relative_to(root):
        raise ValueError('Write the archive outside the run being exported')
    sources = resolve_sources(folder)
    run = read(folder/'run.json')
    relative_path(run['id'])
    # Retain state, attempts, raw responses and audit history. Only unreferenced
    # review snapshots, host caches, temporary files and lock markers are omitted.
    selected = {}
    for path in sorted(folder.rglob('*')):
        no_links(path)
        if not path.is_file():
            continue
        rel = path.relative_to(folder).as_posix()
        parts = rel.split('/')
        if (parts[0] == 'reviews' or any(part in ('.runtime', 'tmp', 'cache') for part in parts) or
                path.name.endswith(('.lock', '.tmp'))):
            continue
        selected[rel] = path
    # Follow review/capture records recursively, including screenshots and source
    # previews. References in old audit records remain reproducible as well.
    queue = []
    for rel, path in selected.items():
        if path.suffix == '.json':
            try:
                data = read(path)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Transport repair deliberately retains the original response,
                # which can contain Markdown fences or invalid JSON bytes.
                if 'raw' not in rel.split('/'):
                    raise
                continue
            queue.extend(_review_paths(folder, path, data))
    while queue:
        rel = queue.pop()
        if rel in selected:
            continue
        path = artifact_path(folder, rel)
        if not path.is_file():
            raise ValueError('Referenced review artifact is missing: '+rel)
        selected[rel] = path
        if path.suffix == '.json':
            queue.extend(_review_paths(folder, path, read(path)))
    source_registry = {sid: 'sources/'+digest(path)+'.pdf' for sid, path in sources.items()}
    local_bytes = (json.dumps(source_registry, ensure_ascii=False, indent=2)+'\n').encode()
    manifest = {'protocol': PROTOCOL, 'run_id': run['id'],
                'release_sha256': run['release_sha256'], 'sources': source_registry,
                'files': {}, 'omission_policy': 'Unreferenced review snapshots and host temporary/cache/lock files only; original history is not deleted.'}
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary = external_path(output_zip.with_name(output_zip.name+'.'+uuid.uuid4().hex+'.tmp'))
    import hashlib
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for rel, path in sorted(selected.items()):
                name = '.work/base/'+rel
                payload = local_bytes if rel == 'sources.local.json' else path.read_bytes()
                archive.writestr(run['id']+'/'+name, payload)
                manifest['files'][name] = hashlib.sha256(payload).hexdigest()
            for sid, path in sources.items():
                name = source_registry[sid]
                if name not in manifest['files']:
                    archive.write(path, run['id']+'/'+name)
                    manifest['files'][name] = digest(path)
            archive.writestr(run['id']+'/checkpoint-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        # Atomic publication without replacing an existing archive.
        if output_zip.exists():
            raise ValueError('Checkpoint filename was created concurrently')
        os.link(temporary, output_zip)
    finally:
        temporary.unlink(missing_ok=True)
    return {'checkpoint': str(output_zip), 'sha256': digest(output_zip),
            'files': len(manifest['files']), 'sources': len(sources), 'self_contained': True}
