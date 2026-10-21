"""Bind source/result previews to the exact content being cotejado."""
import hashlib
import json
import time
from pathlib import Path
from lab import artifact_path, configure_workspace, digest, inside, read, write
from pipeline import content_hash, solution_hash

PROTOCOL = 'source-result-1'


def required(folder):
    return read(folder/'run.json')['config'].get('visual_review_protocol') == PROTOCOL


def select_questions(candidate, question_ids=None):
    known = {q['id'] for q in candidate['questions']}
    requested = known if question_ids is None else set(question_ids)
    if requested - known:
        raise ValueError('Unknown question IDs: ' + ', '.join(sorted(requested - known)))
    return [q for q in candidate['questions'] if q['id'] in requested]


def dependency_hash(folder, question, cache=None):
    """Bind only this question's mapping/provenance plus the current renderer."""
    qid = question['id']
    payload = {}
    cache = cache if cache is not None else {}
    for filename in ('selection.json', 'answer-key-map.json', 'explanation-provenance.json'):
        if not (folder/filename).exists():
            continue
        key = ('dependency-file', filename)
        if key not in cache:
            cache[key] = read(folder/filename)
        data = cache[key]
        if filename == 'selection.json':
            payload[filename] = next((q for q in data['expected_questions'] if q['id'] == qid), None)
        elif filename == 'answer-key-map.json':
            payload[filename] = next((q for q in data['entries'] if q['question_id'] == qid), None)
        else:
            payload[filename] = data.get(qid)
    if ('renderer',) not in cache:
        import pypdfium2 as pdfium
        root = Path(__file__).resolve().parents[2]
        cache[('renderer',)] = {name: digest(root/name) for name in
            ('viewer/block-renderer.js', 'viewer/block-renderer.css', 'viewer/vendor/katex/dist/katex.min.js',
             'viewer/vendor/katex/dist/katex.min.css', 'shared/scripts/source_review.py',
             'shared/scripts/pdf_assets.py')}
        cache[('renderer',)]['pdfium_version'] = str(pdfium.PDFIUM_INFO)
        cache[('renderer',)]['pypdfium_version'] = str(pdfium.PYPDFIUM_INFO)
        cache[('renderer',)]['katex_tree'] = {
            path.relative_to(root).as_posix():digest(path)
            for path in sorted((root/'viewer/vendor/katex').rglob('*')) if path.is_file()}
    payload['renderer'] = cache[('renderer',)]
    if (folder/'sources.json').exists():
        if ('sources',) not in cache:
            cache[('sources',)] = read(folder/'sources.json')
        source_ids = {question['source_id']} | {entry['source_id'] for entry in payload.values()
            if isinstance(entry, dict) and entry.get('source_id')}
        payload['sources'] = [s for s in cache[('sources',)] if s['id'] in source_ids]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def question_binding(folder, question, candidate, cache=None):
    return {'content_sha256': content_hash(question, candidate, folder),
            'solution_sha256': solution_hash(question, candidate, folder),
            'dependencies_sha256': dependency_hash(folder, question, cache)}


def create_review(folder, question_ids=None, pending=False):
    from source_review import build_review
    candidate = read(folder/'candidate.json')
    selected = select_questions(candidate, question_ids)
    references = read(folder/'render-reviews.json') if (folder/'render-reviews.json').exists() else {}
    changed = []
    cache = {}
    for question in selected:
        try:
            validate_review(folder, references.get(question['id']), question, candidate, cache)
        except (ValueError, KeyError, OSError):
            changed.append(question)
    selected = changed
    if not selected:
        return {'questions': 0, 'pages_rendered': 0, 'reused': [q['id'] for q in select_questions(candidate, question_ids)],
                'render_reviews': references, 'review_status': 'pending', 'certification': 'not_performed'}
    mapping = {q['id']: q for q in read(folder/'selection.json')['expected_questions']}
    requirements = {qid: list(q.get('content_inventory', [])) for qid, q in mapping.items()}
    context = {q['id']: [] for q in candidate['questions']}
    for filename, entries in [('answer-key-map.json', 'entries'), ('explanation-provenance.json', None)]:
        if not (folder/filename).exists():
            continue
        data = read(folder/filename)
        rows = [(e['question_id'], e) for e in data[entries]] if entries else data.items()
        for qid, entry in rows:
            if entries and entry.get('source_id'):
                requirements[qid].extend({**item, 'source_id': entry['source_id']}
                                         for item in entry.get('content_inventory', []))
            if entry.get('source_id') and entry.get('page'):
                for page in entry.get('pages', [entry['page']]):
                    context[qid].append({'source_id': entry['source_id'], 'page': page})
    output = inside(folder/'reviews'/('review-' + str(time.time_ns())))
    try:
        from checkpoint_export import resolve_sources
        result = build_review(folder/'candidate.json', resolve_sources(folder), output,
                              workspace=folder, context=context,
                              requirements=requirements, question_ids=[q['id'] for q in selected],
                              page_cache=folder/'cache/review-pages')
    finally:
        configure_workspace(folder.parent.parent)
    record = {'protocol': PROTOCOL, 'run_id': candidate['run']['id'],
              'questions': {q['id']: question_binding(folder, q, candidate, cache) for q in selected},
              'files': [{'path': p.relative_to(folder).as_posix(), 'sha256': digest(p)}
                        for p in sorted(output.rglob('*')) if p.is_file()]}
    path = output/'render-review.json'
    write(path, record)
    reference = {'path': path.relative_to(folder).as_posix(), 'sha256': digest(path)}
    references.update({qid: reference for qid in record['questions']})
    write(folder/'render-reviews.json', references)
    return {**result, 'render_review': reference,
            'next': 'Open the HTML and inspect every question and crop against its sources; then record-check. Generating a preview does not review it.'}


def validate_review(folder, reference, question, candidate, cache=None):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('Run review and inspect source/result before recording cotejo')
    path = artifact_path(folder, reference['path'], 'reviews')
    key = (reference['path'], reference['sha256'])
    cache = cache if cache is not None else {}
    if key not in cache:
        if not path.is_file() or digest(path) != reference['sha256']:
            raise ValueError('Altered render review record')
        record = read(path)
        if record.get('protocol') != PROTOCOL or record.get('run_id') != candidate['run']['id']:
            raise ValueError('Render review belongs to another protocol/run')
        files = record.get('files')
        if not isinstance(files, list) or not files:
            raise ValueError('Render review needs its source/result artifact inventory')
        for item in files:
            file = artifact_path(folder, item['path'], 'reviews')
            if file.parent != path.parent and path.parent not in file.parents:
                raise ValueError('Render review file outside its snapshot')
            if not file.is_file() or digest(file) != item['sha256']:
                raise ValueError('Altered source/result preview; regenerate review')
        if (path.parent/'index.html').relative_to(folder).as_posix() not in {f['path'] for f in files}:
            raise ValueError('Render review needs its HTML preview')
        cache[key] = record
    expected = {'content_sha256': content_hash(question, candidate, folder),
                'solution_sha256': solution_hash(question, candidate, folder)}
    expected['dependencies_sha256'] = dependency_hash(folder, question, cache)
    if cache[key]['questions'].get(question['id']) != expected:
        raise ValueError(question['id'] + ': Stale render review; regenerate review for changed content/assets')


def validate_observation(folder, observation, reference, question, candidate, cache=None):
    """Validate an attributed observation, not whether a model comprehended the render."""
    validate_review(folder, reference, question, candidate, cache)
    if not isinstance(observation, dict) or observation.get('mode') not in ('html', 'images', 'unavailable'):
        raise ValueError('Visual observation needs mode html, images or unavailable')
    if any(not isinstance(observation.get(key), str) or not observation[key].strip()
           for key in ('tool', 'observation')):
        raise ValueError('Visual observation needs a tool and a concrete observation or limitation')
    if observation['mode'] == 'unavailable':
        return False
    from capture_review import validate_capture
    validate_capture(folder, observation.get('capture_receipt'), reference, question['id'], cache=cache)
    return True
