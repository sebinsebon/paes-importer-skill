"""Explicit adoption into a fresh run, with verified legacy and current runtimes.

No schema migration or content retranscription is performed. Failed staging is
retained for inspection; the source archive and original runtime are immutable.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

from lab import artifact_path, digest, json_digest, no_links, read, relative_path


def _resume(runtime, staging, label):
    try:
        checked = subprocess.run([sys.executable, '-B', str(runtime/'scripts/importer.py'),
                                  'resume', '--run', str(staging)],
                                 capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(label+' resume timed out; staging retained at '+str(staging)) from exc
    if checked.returncode:
        raise ValueError(label+' resume rejected checkpoint; staging retained at '+str(staging)+': '+checked.stderr[-2000:])
    result = json.loads(checked.stdout)
    if not isinstance(result, dict):
        raise ValueError(label+' resume returned an invalid status')
    return result


def _verify_runtime(root):
    root = no_links(root)
    manifest = read(root/'release.json')
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Runtime release needs a nonempty file manifest')
    names = set()
    for record in files:
        name = relative_path(record['path'])
        if name in names or digest(artifact_path(root, name)) != record.get('sha256'):
            raise ValueError('Runtime manifest failed verification: '+name)
        names.add(name)
    if not {'scripts/importer.py', 'shared/scripts/pipeline.py'}.issubset(names):
        raise ValueError('Runtime manifest omits recovery implementation')
    # Adoption supports the documented portable protocol family only. File
    # verification proves integrity against the supplied manifests, not authorship.
    if (not re.fullmatch(r'1\.\d+\.\d+-portable', manifest.get('version', '')) or
            manifest.get('protocol_version') != '0.4.0'):
        raise ValueError('Incompatible runtime family/protocol; explicit migration required')
    return manifest


def _extract(source, staging):
    with zipfile.ZipFile(source) as archive:
        seen = set()
        roots = set()
        for info in archive.infolist():
            name = info.filename[:-1] if info.is_dir() else info.filename
            relative_path(name)
            normalized = name.casefold()
            if normalized in seen or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Checkpoint has duplicate or linked entries')
            seen.add(normalized)
            roots.add(name.split('/')[0])
        if len(roots) != 1:
            raise ValueError('Checkpoint must contain one run directory')
        root = next(iter(roots))
        for info in archive.infolist():
            parts = info.filename.rstrip('/').split('/')[1:]
            if not parts:
                continue
            path = artifact_path(staging, '/'.join(parts))
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as reader, path.open('xb') as writer:
                    shutil.copyfileobj(reader, writer)
    return root


def _bind_sources(staging, folder):
    sources = read(folder/'sources.json')
    registry = read(folder/'sources.local.json')
    if not sources or set(registry) != {s['id'] for s in sources}:
        raise ValueError('Source registry differs from frozen sources')
    checkpoint = staging/'checkpoint-manifest.json'
    manifest = read(checkpoint) if checkpoint.is_file() else None
    if manifest is not None:
        from checkpoint_export import PROTOCOL
        run = read(folder/'run.json')
        if (manifest.get('protocol') != PROTOCOL or manifest.get('sources') != registry or
                manifest.get('run_id') != run.get('id') or
                manifest.get('release_sha256') != run.get('release_sha256')):
            raise ValueError('Invalid portable checkpoint registry/protocol')
        inventory = manifest.get('files')
        physical = {p.relative_to(staging).as_posix() for p in staging.rglob('*')
                    if p.is_file() and p != checkpoint}
        if not isinstance(inventory, dict) or set(inventory) != physical:
            raise ValueError('Checkpoint inventory does not cover its physical files')
        for name, expected in inventory.items():
            path = artifact_path(staging, name)
            if not path.is_file() or digest(path) != expected:
                raise ValueError('Checkpoint file hash mismatch: '+name)
        archived = {sid: artifact_path(staging, value) for sid, value in registry.items()}
    else:
        # Older detached checkpoints have absolute host paths. Discover original
        # PDFs by the frozen hashes, never a private folder layout or source ID.
        pdfs = [p for p in staging.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf']
        hashes = {p: digest(p) for p in pdfs}
        archived = {}
        for source in sources:
            matches = [p for p, value in hashes.items() if value == source['sha256']]
            if not matches:
                raise ValueError('Checkpoint omits original source PDF: '+source['id'])
            archived[source['id']] = sorted(matches)[0]
    portable = {}
    for source in sources:
        path = archived[source['id']]
        if not path.is_file() or digest(path) != source['sha256']:
            raise ValueError('Missing or altered source: '+source['id'])
        portable[source['id']] = path.relative_to(staging).as_posix()
    # Legacy resume needs absolute paths, but only to files within staging.
    (folder/'sources.local.json').write_text(json.dumps({sid: str(archived[sid]) for sid in portable})+'\n', encoding='utf-8')
    return portable


def adopt(checkpoint, legacy_bundle, output_run, new_release):
    source = no_links(checkpoint)
    if not source.is_file():
        raise ValueError('Checkpoint archive does not exist')
    legacy = no_links(legacy_bundle)
    new_release = no_links(new_release)
    if new_release.name != 'release.json':
        raise ValueError('Current release must be the runtime release.json manifest')
    current = new_release.parent
    old_manifest = _verify_runtime(legacy)
    new_manifest = _verify_runtime(current)
    if old_manifest['protocol_version'] != new_manifest['protocol_version']:
        raise ValueError('Adoption requires compatible protocols')
    from runtime_environment import external_path
    target = external_path(output_run)
    if (target.exists() or target == Path(target.anchor) or
            target.is_relative_to(legacy) or target.is_relative_to(current)):
        raise ValueError('Adoption requires a NEW external output directory')
    staging = no_links(target.parent/(target.name+'.adoption-'+uuid.uuid4().hex))
    staging.mkdir(parents=True, exist_ok=False)
    root = _extract(source, staging)
    folder = staging/'.work/base'
    run = read(folder/'run.json')
    if (run.get('id') != root or run.get('release_sha256') != digest(legacy/'release.json') or
            run.get('protocol_version') != old_manifest['protocol_version'] or
            run.get('status') not in ('awaiting_ai', 'awaiting_route', 'awaiting_mapping') or
            json_digest(run.get('config')) != run.get('config_hash')):
        raise ValueError('Checkpoint identity, configuration, runtime or editable state mismatch')
    old_run_bytes = (folder/'run.json').read_bytes()
    portable = _bind_sources(staging, folder)
    # The actual pinned importer recovers journals, validates its contract, frozen
    # map/route and accepted questions. It may have fewer than a full exam accepted.
    result = _resume(legacy, staging, 'Legacy')
    candidate_path = folder/'candidate.json'
    candidate_before = candidate_path.read_bytes() if candidate_path.exists() else None
    accepted = result.get('accepted_question_ids', [])
    if not isinstance(accepted, list) or len(set(accepted)) != len(accepted):
        raise ValueError('Legacy resume returned invalid accepted question IDs')
    candidate = read(candidate_path) if candidate_before is not None else None
    questions = {q['id']: q for q in candidate.get('questions', [])} if candidate else {}
    if not set(accepted).issubset(questions):
        raise ValueError('Accepted questions are absent from candidate')
    snapshot = {qid: json_digest(questions[qid]) for qid in accepted}
    run = read(folder/'run.json')
    run.update(release_sha256=digest(new_release), output_dir=str(target))
    (folder/'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (folder/'sources.local.json').write_text(json.dumps(portable, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    current_result = _resume(current, staging, 'Current')
    if (set(current_result.get('accepted_question_ids', [])) != set(accepted) or
            (candidate_before is not None and candidate_path.read_bytes() != candidate_before)):
        raise ValueError('Current runtime changed accepted state/content; explicit migration required')
    versions = folder/'versions'
    versions.mkdir(exist_ok=True)
    (versions/('pre-adoption-run-'+uuid.uuid4().hex+'.json')).write_bytes(old_run_bytes)
    if candidate_before is not None and candidate_path.read_bytes() != candidate_before:
        raise ValueError('Adoption changed accepted candidate bytes')
    record = {'protocol': 'explicit-adoption-2', 'original_run_id': root,
              'old_checkpoint_sha256': digest(source), 'old_release_sha256': digest(legacy/'release.json'),
              'new_release_sha256': digest(new_release), 'accepted_question_ids': accepted,
              'accepted_content_sha256': snapshot, 'candidate_sha256_before_after':
              hashlib.sha256(candidate_before).hexdigest() if candidate_before is not None else None,
              'legacy_resume': 'passed', 'current_resume': 'passed', 'migration': None,
              'changes': ['run output location and release pin', 'verified portable source locations']}
    (folder/('adoption-'+uuid.uuid4().hex+'.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # Atomic rename fails instead of merging into another directory on Windows.
    if target.exists():
        raise ValueError('Output directory was created concurrently')
    staging.rename(target)
    return {'output_run': str(target), 'adoption': record,
            'next': 'Resume using the current verified runtime; accepted content is preserved and reviews remain pending as recorded.'}
