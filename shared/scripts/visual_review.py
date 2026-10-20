"""Bind source/result previews to the exact content being cotejado."""
import time
from lab import artifact_path, configure_workspace, digest, inside, read, write
from pipeline import content_hash, solution_hash

PROTOCOL = 'source-result-1'


def required(folder):
    return read(folder/'run.json')['config'].get('visual_review_protocol') == PROTOCOL


def create_review(folder):
    from source_review import build_review
    candidate = read(folder/'candidate.json')
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
        result = build_review(folder/'candidate.json', read(folder/'sources.local.json'), output,
                              workspace=folder, context=context,
                              requirements=requirements)
    finally:
        configure_workspace(folder.parent.parent)
    record = {'protocol': PROTOCOL, 'run_id': candidate['run']['id'],
              'questions': {q['id']: {'content_sha256': content_hash(q, candidate, folder),
                                      'solution_sha256': solution_hash(q, candidate, folder)} for q in candidate['questions']},
              'files': [{'path': p.relative_to(folder).as_posix(), 'sha256': digest(p)}
                        for p in sorted(output.rglob('*')) if p.is_file()]}
    path = output/'render-review.json'
    write(path, record)
    reference = {'path': path.relative_to(folder).as_posix(), 'sha256': digest(path)}
    write(folder/'render-reviews.json', {qid: reference for qid in record['questions']})
    return {**result, 'render_review': reference,
            'next': 'Open the HTML and inspect every question and crop against its sources; then record-check. Generating a preview does not review it.'}


def validate_review(folder, reference, question, candidate, cache=None):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('Run review and inspect source/result before recording cotejo')
    path = artifact_path(folder, reference['path'], 'reviews')
    if not path.is_file() or digest(path) != reference['sha256']:
        raise ValueError('Altered render review record')
    key = (reference['path'], reference['sha256'])
    cache = cache if cache is not None else {}
    if key not in cache:
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
    if observation['mode'] == 'images':
        from capture_review import validate_capture
        validate_capture(folder, observation.get('capture_receipt'), reference, question['id'])
    return True
