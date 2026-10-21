"""Validate and package the experiment contract; no AI or implied verification."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import uuid
import zipfile
import subprocess
from functools import lru_cache
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator
from lab import ROOT, artifact_path, bbox, digest, inside, json_digest, question_blocks, read, relative_path, write

SCHEMA = ROOT / 'shared/schemas/final.schema.json'
MAX_BYTES = 256 * 1024 * 1024

# These detect serialization syntax, not mathematical meaning or source fidelity.
RAW_LATEX = re.compile(r'\\(?:[A-Za-z]+|[()\[\]_%{}^,;!: $&|#\\])')
INLINE_DOLLARS = re.compile(r'(?<!\\)\$([^$\n]+)(?<!\\)\$(?!\d)')
MONETARY_PREFIX = re.compile(r'\$\s*\d+(?:[ .]\d{3})*(?:[.,]\d+)?(?=\s*(?:[A-Za-zÁÉÍÓÚáéíóúÑñ¿¡]|[,.;:]|$))')
TABLE_SEPARATOR_CELL = re.compile(r':?-{3,}:?')


def markdown_table(text):
    previous_columns = None
    for line in text.splitlines():
        cells = re.split(r'(?<!\\)\|', line.strip())
        if len(cells) < 2:
            previous_columns = None
            continue
        if not cells[0].strip(): cells.pop(0)
        if cells and not cells[-1].strip(): cells.pop()
        cells = [cell.strip() for cell in cells]
        if len(cells) < 2 or not all(cells):
            previous_columns = None
            continue
        if all(TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in cells):
            return True
        if previous_columns == len(cells):
            return True
        previous_columns = len(cells)
    return False


def located_blocks(q):
    def walk(blocks, path):
        for index, block in enumerate(blocks):
            at = f'{path}[{index}]'
            yield at, block
            if block['type'] == 'table':
                for row_index, row in enumerate(block['rows']):
                    for cell_index, cell in enumerate(row):
                        yield from walk(cell, f'{at}.rows[{row_index}][{cell_index}]')
    yield from walk(q['stem'], 'stem')
    for index, option in enumerate(q['options']):
        yield from walk(option['blocks'], f'options[{index}].blocks')
    yield from walk(q['explanation']['blocks'], 'explanation.blocks')


def validate_structured_content(q):
    errors = []
    for at, block in located_blocks(q):
        if block['type'] == 'text':
            text = block['text']
            if not text.strip():
                errors.append(f'{q["id"]}/{at}: EMPTY_CONTENT')
            if markdown_table(text):
                errors.append(f'{q["id"]}/{at}: MARKDOWN_TABLE_IN_TEXT; correct using table.rows')
            if RAW_LATEX.search(text) or '$$' in text or INLINE_DOLLARS.search(MONETARY_PREFIX.sub('', text)):
                errors.append(f'{q["id"]}/{at}: LATEX_IN_TEXT; correct using math.latex/display')
        elif block['type'] == 'math':
            latex = block['latex'].strip()
            if not latex:
                errors.append(f'{q["id"]}/{at}: EMPTY_CONTENT')
            if latex.startswith(('$', r'\(', r'\[')) or latex.endswith(('$', r'\)', r'\]')):
                errors.append(f'{q["id"]}/{at}: MATH_DELIMITERS; math.latex must omit delimiters')
    # Quality gates for deterministic corruption observed in real M1 imports.
    # Source fidelity still requires manual/AI visual comparison.
    for at, block in located_blocks(q):
        if block['type'] == 'math' and not re.search(r'\\begin\{(?:aligned|align|cases|array|matrix|pmatrix|bmatrix)\}', block['latex']) and re.search(r'(?<!\\)\\\\(?=(?:vec|sqrt|frac|dfrac|tfrac|left|right|cdot|times|text|mathrm|begin|end|sum|int|sin|cos|tan|log|ln|pi|pm|leq|geq|neq|approx|infty)\b)', block['latex']):
            errors.append(f'{q["id"]}/{at}: DOUBLE_ESCAPED_LATEX_COMMAND; use one backslash before a KaTeX command')
    for option in q['options']:
        blocks = option['blocks']
        if len(blocks) == 1 and blocks[0]['type'] == 'text':
            content = blocks[0]['text'].strip()
            if re.fullmatch(r'(?:gr[aá]fico|imagen|figura|diagrama)\s+de\s+(?:la\s+)?alternativa\s+' + re.escape(option['label']), content, re.IGNORECASE):
                errors.append(f'{q["id"]}/option-{option["label"]}: VISUAL_OPTION_PLACEHOLDER; attach the actual option image')
    if len(q['options']) >= 2 and all(
            len(o['blocks']) == 1 and o['blocks'][0]['type'] == 'text' and
            re.fullmatch(r'\s*0{3}\s*', o['blocks'][0]['text']) for o in q['options']):
        errors.append(f'{q["id"]}: TRUNCATED_NUMERIC_OPTIONS; check missing monetary prefixes/digits against the PDF')
    if errors:
        raise ValueError('; '.join(errors))

@lru_cache(maxsize=2048)
def renderable_math(formulas):
    if not formulas:
        return
    result=subprocess.run(['node',str(ROOT/'shared/scripts/check_math.cjs')],input=json.dumps([{'latex': latex, 'display': display} for latex, display in formulas]),
                          capture_output=True,text=True,encoding='utf-8',timeout=30,cwd=ROOT)
    if result.returncode:
        raise ValueError('KaTeX formula error: '+result.stderr[:600])


def unique(records, key, name):
    ids = [r[key] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f'Duplicate {name}')
    return {r[key]: r for r in records}


def validate(data, root=None, blob_reader=None, *, validation_context=None):
    """Validate completely; an optional cache belongs to one immutable operation.

    Call without a shared context for the final pre-commit validation so resource
    bytes and schema are checked afresh at the publication boundary.
    """
    version = data.get('schema_version')
    if version not in ('0.1.0', '0.2.0'):
        raise ValueError('Unsupported final schema_version')
    schema = SCHEMA if version == '0.2.0' else SCHEMA.with_name('final-0.1.schema.json')
    context = validation_context if validation_context is not None else {}
    validators = context.setdefault('schema_validators', {})
    schema_key = str(schema)
    if schema_key not in validators:
        validators[schema_key] = Draft202012Validator(read(schema))
    errors = sorted(validators[schema_key].iter_errors(data), key=lambda e: str(e.path))
    if errors:
        raise ValueError('; '.join(f'{list(e.path)}: {e.message}' for e in errors[:6]))
    sources = unique(data['sources'], 'id', 'source IDs')
    questions = unique(data['questions'], 'id', 'question IDs')
    expected = unique(data['exam']['expected_questions'], 'id', 'expected IDs')
    assets = unique(data['assets'], 'id', 'asset IDs')
    unique(data['evidence'], 'id', 'evidence IDs')
    unique(data['assets']+data['evidence'], 'id', 'resource IDs')
    if set(questions) != set(expected):
        raise ValueError(f'Question coverage mismatch: missing={sorted(set(expected)-set(questions))}, extra={sorted(set(questions)-set(expected))}')
    identity = set()
    paths = set()
    warnings = []
    for collection in ('assets', 'evidence'):
        for resource in data[collection]:
            path = relative_path(resource['path'], collection)
            if path.casefold() in paths:
                raise ValueError(f'Duplicate resource path: {path}')
            paths.add(path.casefold())
            if not path.endswith('.png'):
                raise ValueError('Only PNG resources are supported')
            source = sources.get(resource['source_id'])
            if not source or resource['page'] > source['page_count']:
                raise ValueError(f'Invalid resource source/page: {resource["id"]}')
            bbox(resource['bbox'])
            if root is not None or blob_reader is not None:
                cache_key = (str(Path(root).resolve()) if root is not None else id(blob_reader), path, resource['sha256'])
                checked = context.setdefault('checked_resources', set())
                if cache_key not in checked:
                    content = blob_reader(path) if blob_reader else artifact_path(root, path, collection).read_bytes()
                    if hashlib.sha256(content).hexdigest() != resource['sha256']:
                        raise ValueError(f'Hash mismatch: {path}')
                    if not content.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError(f'Invalid PNG: {path}')
                    checked.add(cache_key)
    for q in data['questions']:
        validate_structured_content(q)
        if version == '0.2.0':
            from curriculum import validate_question_curriculum
            validate_question_curriculum(q)
        source = sources.get(q['source_id'])
        if not source or source['role'] != 'exam':
            raise ValueError(f'Invalid question source: {q["id"]}')
        if (q['source_id'], q['number']) in identity:
            raise ValueError(f'Duplicate source/number: {q["id"]}')
        identity.add((q['source_id'], q['number']))
        if any(q[k] != expected[q['id']][k] for k in ('source_id', 'number')):
            raise ValueError(f'Question differs from frozen selection: {q["id"]}')
        for region in q['regions']:
            bbox(region['bbox'])
            if region['page'] > source['page_count']:
                raise ValueError(f'Question page outside PDF: {q["id"]}')
        labels = [o['label'] for o in q['options']]
        if len(labels) != len(set(labels)):
            raise ValueError(f'Duplicate option label: {q["id"]}')
        content = list(question_blocks(q))
        unresolved = any(b['type'] == 'unresolved' for b in content)
        for at, block in located_blocks(q):
            if block['type'] == 'image':
                resource = assets.get(block['asset_id'])
                if not resource or (resource['source_id'] != q['source_id'] and
                        (not at.startswith('explanation.') or sources[resource['source_id']]['role'] != 'solution')):
                    raise ValueError(f'Missing or wrong-source image: {q["id"]}/{block["asset_id"]}')
            if block['type'] == 'math' and (block['latex'].startswith('$') or block['latex'].endswith('$')):
                raise ValueError(f'LaTeX must not have dollar delimiters: {q["id"]}')
            if block['type'] == 'table' and len({len(row) for row in block['rows']}) != 1:
                raise ValueError(f'Nonrectangular table: {q["id"]}')
        if (len(labels) < 2 or not q['regions']) and not unresolved:
            raise ValueError(f'Question needs regions and at least two options, or explicit unresolved: {q["id"]}')
        answer = q['answer']
        if answer['label'] is not None and answer['label'] not in labels:
            raise ValueError(f'Answer label does not exist: {q["id"]}')
        if (answer['status'] == 'missing') != (answer['label'] is None):
            raise ValueError(f'Answer status/label conflict: {q["id"]}')
        if (answer['origin'] == 'none') != (answer['status'] == 'missing'):
            raise ValueError(f'Answer origin/status conflict: {q["id"]}')
        if (q['explanation']['status'] == 'missing') != (not q['explanation']['blocks']):
            raise ValueError(f'Explanation status/content conflict: {q["id"]}')
        if q['fidelity']['status'] == 'reviewed' and (unresolved or not q['fidelity']['review_ref']):
            raise ValueError(f'Reviewed fidelity requires reference and resolved content: {q["id"]}')
        if answer['status'] == 'verified' and (not answer['source_ref'] or q['fidelity']['status'] != 'reviewed'):
            raise ValueError(f'Verified answer requires provenance and fidelity: {q["id"]}')
        if q['explanation']['status'] == 'verified' and answer['status'] != 'verified':
            raise ValueError(f'Verified explanation requires verified answer: {q["id"]}')
        if unresolved or q['fidelity']['status'] != 'reviewed' or answer['status'] != 'verified':
            warnings.append(f'{q["id"]}: revisión o resolución pendiente')
    renderable_math(tuple(sorted({(b['latex'], b['display']) for q in data['questions'] for b in question_blocks(q) if b['type']=='math'})))
    result=subprocess.run(['node',str(ROOT/'shared/scripts/check_final.cjs')],input=json.dumps(data),
                          capture_output=True,text=True,encoding='utf-8',timeout=30,cwd=ROOT)
    if result.returncode:
        raise ValueError('Viewer contract: '+result.stderr[:600])
    from quality import summarize
    return {'valid': True, 'questions': len(questions), 'assets': len(assets), 'warnings': warnings, 'quality': summarize(data),
            'semantic_correctness': 'not_proven_by_structural_validation'}


def pack(file, include_evidence=False):
    file = inside(file)
    original = read(file)
    validate(original, file.parent)
    data = copy.deepcopy(original)
    used = {b['asset_id'] for q in data['questions'] for b in question_blocks(q) if b['type'] == 'image'}
    data['assets'] = [r for r in data['assets'] if r['id'] in used]
    if not include_evidence:
        data['evidence'] = []
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    files = {'final.json': raw}
    for r in data['assets'] + data['evidence']:
        files[r['path']] = artifact_path(file.parent, r['path']).read_bytes()
    manifest = {'format': 'paessed-package', 'schema_version': '0.1.0', 'files': [
        {'path': name, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
        for name, content in sorted(files.items())]}
    files['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    zip_path = inside(file.parent / 'package.zip')
    paessed_path = inside(file.parent / 'package.paessed')
    if zip_path.exists() or paessed_path.exists():
        raise ValueError('Package already exists; use a new run/version directory')
    # Verify the exact in-memory archive before publishing it.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    payload = buf.getvalue()
    inspect_package(io.BytesIO(payload))
    # Stage everything before publication; final.json is the commit point.
    token=uuid.uuid4().hex
    staged_zip=inside(file.parent/f'package-{token}.zip.tmp')
    staged_paessed=inside(file.parent/f'package-{token}.paessed.tmp')
    staged_final=inside(file.parent/f'final-{token}.json.tmp')
    published=[]
    try:
        staged_zip.write_bytes(payload);staged_paessed.write_bytes(payload)
        write(staged_final,data)
        for temporary,destination in ((staged_zip,zip_path),(staged_paessed,paessed_path)):
            os.replace(temporary,destination);published.append(destination)
        os.replace(staged_final,file.parent/'final.json')
    except Exception:
        for destination in published:destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary in (staged_zip,staged_paessed,staged_final):temporary.unlink(missing_ok=True)
    return {'zip': str(zip_path), 'paessed': str(paessed_path), 'bytes': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest(), 'questions': len(data['questions'])}


def inspect_package(path):
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        names = [e.filename for e in entries]
        if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_BYTES:
            raise ValueError('Package exceeds local size limits')
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError('Duplicate archive path')
        for e in entries:
            # JSZip exports explicit empty directories. Match the browser reader:
            # validate their paths, then exclude them from the file inventory.
            relative_path(e.filename[:-1] if e.is_dir() else e.filename)
            if e.is_dir() and (not e.filename.startswith(('assets/', 'evidence/')) or e.file_size):
                raise ValueError(f'Unexpected or nonempty archive directory: {e.filename}')
            if (e.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive contains a symlink')
        names = [e.filename for e in entries if not e.is_dir()]
        if not {'final.json', 'manifest.json'}.issubset(names):
            raise ValueError('Missing final.json or manifest.json at archive root')
        manifest = json.loads(z.read('manifest.json'))
        if manifest.get('format') != 'paessed-package' or manifest.get('schema_version') != '0.1.0':
            raise ValueError('Unsupported package manifest')
        indexed = unique(manifest['files'], 'path', 'manifest paths')
        if set(indexed) != set(names) - {'manifest.json'}:
            raise ValueError('Manifest file inventory mismatch')
        for name, record in indexed.items():
            blob = z.read(name)
            if len(blob) != record['bytes'] or hashlib.sha256(blob).hexdigest() != record['sha256']:
                raise ValueError(f'Manifest integrity failure: {name}')
        data = json.loads(z.read('final.json'))
        result = validate(data, blob_reader=z.read)
        expected_files = {'final.json', 'manifest.json'} | {r['path'] for r in data['assets'] + data['evidence']}
        if set(names) != expected_files:
            raise ValueError('Unexpected or missing file in package')
        if isinstance(path,(str,Path)):
            if Path(path).stat().st_size>272*1024*1024:raise ValueError('Archive exceeds viewer size limit')
            payload=Path(path).read_bytes()
        else:
            position=path.tell();path.seek(0);payload=path.read(272*1024*1024+1);path.seek(position)
        if len(payload)>272*1024*1024:raise ValueError('Archive exceeds viewer size limit')
        parity=subprocess.run(['node',str(ROOT/'shared/scripts/check_package.cjs')],input=payload,
                              capture_output=True,timeout=60,cwd=ROOT)
        if parity.returncode:
            raise ValueError('Viewer package: '+parity.stderr.decode('utf-8',errors='replace')[:600])
        return {**result, 'pipeline': data['pipeline'], 'run_id': data['run']['id'], 'files': len(names)}
