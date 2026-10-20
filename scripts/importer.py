"""Portable deterministic PAESSED M1 tools. The host AI reads and interprets PDFs."""
from __future__ import annotations
import argparse
import copy
import json
import os
import re
import shutil
import sys
sys.dont_write_bytecode = True
import time
import unicodedata
import uuid
from functools import wraps
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared/scripts'))
from lab import (artifact_path, configure_workspace, digest, event, inside, json_digest,
                 no_links, now, publication_path, read, relative_path, write)
from package_io import inspect_package, pack, validate
from pdf_assets import apply_crops, prepare_catalog, source_record
from direct_gate import validate_direct_input
from output_policy import require_official_final
from evidence import field_paths, validate_citations, validate_geometry, validate_mapping, validate_source_fields
from quality import summarize, require_publishable
from content_inventory import validate_inventory_record, validate_inventory, with_solution_inventory as observed_inventory
import visual_review
import pipeline as engine
from policy import select_mode

CHECKS = ('stem', 'options', 'assets_math', 'answer', 'explanation', 'consistency')
CAPABILITIES = ('pdf_visual', 'crop', 'execute', 'zip', 'validate')
PROTOCOL = '0.4.0'


def candidate_operation(function):
    @wraps(function)
    def locked(folder, *args, **kwargs):
        from checkpoints import state_lock
        with state_lock(inside(folder)):
            return function(folder, *args, **kwargs)
    return locked


def slug(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    value = re.sub(r'[^a-zA-Z0-9]+', '-', value).strip('-').lower()[:100]
    return value or 'm1-ensayo'


def known_folder(kind):
    home = Path.home()
    if sys.platform == 'win32':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            name = 'Personal' if kind == 'documents' else '{374DE290-123F-4565-9164-39C4925E467B}'
            try:
                value, _ = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                value = str(home / ('Documents' if kind == 'documents' else 'Downloads'))
            return Path(os.path.expandvars(value))
    name = 'XDG_DOCUMENTS_DIR' if kind == 'documents' else 'XDG_DOWNLOAD_DIR'
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'user-dirs.dirs'
    if config.is_file():
        for line in config.read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'\s*' + name + r'="([^"\n]+)"\s*', line)
            if match:
                return Path(match[1].replace('$HOME', str(home)))
    return home / ('Documents' if kind == 'documents' else 'Downloads')


def output_root(destination, custom):
    if destination == 'custom':
        if not custom or not Path(custom).is_absolute():
            raise ValueError('Custom output-root must be an absolute path')
        return no_links(custom)
    if custom:
        raise ValueError('Use --destination custom with --output-root')
    return no_links(known_folder(destination) / 'EnsayosPaessedOutput')


def require_capabilities(record):
    if any(record.get(k) is not True for k in CAPABILITIES) or not record.get('observation'):
        raise ValueError('Need observed PDF visuals, crops, execution, validation and ZIP capabilities')
    visual = record.get('result_visual', {})
    if not isinstance(visual,dict) or visual.get('mode') not in ('html','images','unavailable') or not visual.get('observation'):
        raise ValueError('Observe result_visual mode html/images/unavailable and its limitation/tool')
    if visual['mode'] != 'unavailable' and not visual.get('tool'):
        raise ValueError('Identify the actual rendered-result inspection tool')


def base_folder(value):
    folder = Path(value).absolute()
    if (folder / '.work/base/run.json').is_file():
        folder = folder / '.work/base'
    if folder.name != 'base' or folder.parent.name != '.work':
        raise ValueError('Expected an output run or its .work/base directory')
    configure_workspace(folder.parent.parent)
    return inside(folder)


def prepare(args):
    capabilities = read(args.capabilities)
    require_capabilities(capabilities)
    exam = Path(args.exam).resolve(strict=True)
    solution = Path(args.solution).resolve(strict=True) if args.solution else None
    if solution == exam:
        raise ValueError('An embedded key uses the exam source; do not repeat --solution')
    title = args.title or exam.stem
    exam_id = slug(title)
    if not exam_id.startswith('m1-'):
        exam_id = 'm1-' + exam_id
    rid = args.run_id or time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid):
        raise ValueError('Unsafe run-id')
    destination = output_root(args.destination, args.output_root) / exam_id / rid
    configure_workspace(destination)
    engine.verify_release()
    if destination.exists():
        raise ValueError('Output already exists; use resume or a new run-id')
    folder = inside(destination / '.work/base')
    folder.mkdir(parents=True)
    temporary = inside(destination / '.work/tmp')
    temporary.mkdir()
    from runtime_environment import process_environment
    os.environ.update(process_environment(destination/'.work', create=True))
    config = {'host': args.host, 'model': args.model, 'effort': args.effort, 'batch_size': 5,
              'capabilities': capabilities, 'max_retries': 3,
              'suggested_save_location': getattr(args, 'suggested_save_location', None),
              'visual_review_protocol': visual_review.PROTOCOL, 'source_fields_protocol': 'source-fields-1'}
    run = {'id': rid, 'pipeline': 'pdf-direct', 'variant': 'direct', 'protocol_version': PROTOCOL,
           'purpose': 'portable-import', 'eligible': False, 'status': 'preparing',
           'cli': args.client or args.host, 'host': args.host, 'model': args.model,
           'session_id': args.session_id, 'started_at': now(), 'output_dir': str(destination),
           'config': config, 'config_hash': json_digest(config), 'exam_id': exam_id, 'title': title,
           'release_sha256': digest(ROOT / 'release.json')}
    write(folder / 'run.json', run)
    try:
        paths = {'exam': str(exam)}
        if solution:
            paths['solution'] = str(solution)
        sources = [source_record(sid, p, 'exam' if sid == 'exam' else 'solution') for sid, p in paths.items()]
        write(folder / 'sources.local.json', paths)
        write(folder / 'sources.json', sources)
        prepare_catalog(sources, paths, folder, scale=args.scale)
        write(folder / 'direct-input.template.json', {
            'mode': 'unavailable', 'input_kind': 'pdf', 'reader': '',
            'visual_content_understood': False, 'capability_observation': '', 'limitations': [],
            'sources': [{'source_id': s['id'], 'sha256': s['sha256'], 'pages_read': []} for s in sources]})
        run['status'] = 'awaiting_mapping'
        write(folder / 'run.json', run)
    except Exception:
        run['status'] = 'failed_preparation'
        write(folder / 'run.json', run)
        raise
    return {'run': str(folder), 'output': str(destination), 'next': 'Read source pages, then map'}


def verify_pre_mapping(folder):
    run = read(folder / 'run.json')
    if digest(ROOT / 'release.json') != run['release_sha256'] or json_digest(run['config']) != run['config_hash']:
        raise ValueError('Frozen implementation/configuration changed')
    engine.verify_release()
    paths = read(folder / 'sources.local.json')
    for source in read(folder / 'sources.json'):
        if digest(paths[source['id']]) != source['sha256']:
            raise ValueError('Source changed before question mapping')


@candidate_operation
def map_questions(folder, selection_file):
    verify_pre_mapping(folder)
    run = read(folder / 'run.json')
    if run['status'] != 'awaiting_mapping' or (folder / 'selection.json').exists():
        raise ValueError('Question map is already frozen or preparation failed')
    selection = read(selection_file)
    expected = selection.get('expected_questions', [])
    if not expected or len({q['id'] for q in expected}) != len(expected):
        raise ValueError('Expected questions must be nonempty and unique')
    pages = next(s['page_count'] for s in read(folder / 'sources.json') if s['id'] == 'exam')
    numbers = set()
    for q in expected:
        if (q.get('source_id') != 'exam' or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', q['id'])
                or not isinstance(q.get('number'), str) or not q['number']
                or type(q.get('page')) is not int or not 1 <= q['page'] <= pages or q['number'] in numbers):
            raise ValueError('Invalid question identity, number, exam source or physical page')
        labels = q.get('option_labels')
        if labels is None and q.get('mapping_pending') is not True:
            raise ValueError('Observe option_labels or declare mapping_pending explicitly')
        if labels is not None and (not isinstance(labels, list) or len(labels) < 2 or
                len(set(labels)) != len(labels) or any(not isinstance(x, str) or not re.fullmatch('[A-Z]', x) for x in labels)):
            raise ValueError('Observed option_labels must be distinct A..Z labels')
        if visual_review.required(folder) and not q.get('mapping_pending'):
            validate_inventory_record(q, read(folder/'catalog.json'))
            if run['config'].get('source_fields_protocol') == 'source-fields-1':
                validate_source_fields(q, read(folder/'catalog.json'))
                for item in q['content_inventory']:
                    if item['field'] == 'explanation':
                        raise ValueError('Observe explanation inventory in its frozen answer-key entry')
                    if item['type']=='table' and item.get('representation','editable')=='editable' and not (item.get('shape') or item.get('shapes')):
                        raise ValueError('Observe editable table shape before transcription')
        for region in q.get('regions', []):
            page = next((p for p in read(folder/'catalog.json')['pages'] if p['source_id'] == 'exam' and p['page'] == region.get('page')), None)
            if not page:
                raise ValueError('Mapped region page missing from catalog')
            __import__('lab').bbox(region['bbox'], page['width'], page['height'])
        for dimension, regions in q.get('field_regions', {}).items():
            if dimension not in CHECKS or not isinstance(regions, list) or not regions:
                raise ValueError('Invalid mapped field_regions')
            for region in regions:
                page = next((p for p in read(folder/'catalog.json')['pages'] if p['source_id'] == 'exam' and p['page'] == region.get('page')), None)
                if not page:
                    raise ValueError('Mapped field region outside catalog')
                __import__('lab').bbox(region['bbox'], page['width'], page['height'])
        numbers.add(q['number'])
    if selection.get('observed_question_count') != len(expected) or not selection.get('observation'):
        raise ValueError('Record observed total question count and mapping observation')
    suite = {'id': run['exam_id'], 'title': selection.get('title', run['title']), 'scope': 'full',
             'expected_questions': expected, 'observation': selection['observation']}
    write(folder / 'selection.json', suite)
    run.update(selection_hash=json_digest(suite), suite_sha256=digest(folder / 'selection.json'),
               status='awaiting_route')
    write(folder / 'run.json', run)
    candidate = engine.initial_candidate(run, suite, read(folder / 'sources.json'))
    catalog = read(folder / 'catalog.json')
    candidate.update(assets=catalog['assets'], evidence=catalog['evidence'])
    write(folder / 'candidate.json', candidate)
    return {'questions': len(expected)}


def validate_key(record, candidate):
    sources = {s['id']: s for s in candidate['sources']}
    exam = sources['exam']
    if record.get('exam_sha256') != exam['sha256']:
        raise ValueError('Answer key is bound to another exam')
    match = record.get('match', {})
    if match.get('status') != 'matched' or not match.get('reason') or not match.get('evidence'):
        raise ValueError('Resolve ambiguous/incompatible key; do not apply it')
    def cite(item):
        source = sources.get(item.get('source_id'))
        if (not source or type(item.get('page')) is not int or not 1 <= item['page'] <= source['page_count']
                or not item.get('observation')):
            raise ValueError('Key correspondence needs source/page/observation')
        if 'pages' in item:
            pages = item['pages']
            if (not isinstance(pages, list) or not pages or
                    any(type(p) is not int or not 1 <= p <= source['page_count'] for p in pages) or
                    len(set(pages)) != len(pages) or item['page'] not in pages):
                raise ValueError('Key pages must include its primary page and valid distinct physical pages')
    for item in match['evidence']:
        cite(item)
    allowed = {q['id'] for q in candidate['questions']}
    entries = record.get('entries', [])
    if len({e['question_id'] for e in entries}) != len(entries):
        raise ValueError('Duplicate answer-key entry')
    for entry in entries:
        if entry['question_id'] not in allowed or not re.fullmatch('[A-Z]', entry.get('label', '')):
            raise ValueError('Invalid answer-key question or label')
        cite(entry)
        if 'has_explanation' in entry and type(entry['has_explanation']) is not bool:
            raise ValueError('has_explanation must be boolean')
        if entry.get('has_explanation'):
            inventory = entry.get('content_inventory')
            if not isinstance(inventory,list):
                raise ValueError('Observe solution content_inventory explicitly before transcribing development')
            allowed_pages = entry.get('pages',[entry['page']])
            if any(not isinstance(item,dict) or item.get('field')!='explanation' or item.get('source_id',entry['source_id']) != entry['source_id'] or
                   any(r.get('page') not in allowed_pages for r in item.get('regions',[])) for item in inventory):
                raise ValueError('Explanation inventory must follow its own frozen solution source/pages')
    return {e['question_id']: e for e in entries}


@candidate_operation
def route(folder, key_file, subagents, experimental, review_ids=None):
    engine.verify_resume(folder)
    run, candidate = read(folder / 'run.json'), read(folder / 'candidate.json')
    if run['status'] != 'awaiting_route':
        raise ValueError('Processing route is already frozen')
    key = read(key_file) if key_file else None
    entries = validate_key(key, candidate) if key else {}
    mapping = {q['id']:q for q in read(folder/'selection.json')['expected_questions']}
    for qid,entry in entries.items():
        validate_inventory_record(observed_inventory(mapping[qid],entry), read(folder/'catalog.json'))
    decision = select_mode(run['host'], [q['id'] for q in candidate['questions']], entries,
                           subagents, experimental, review_ids=review_ids)
    if decision['status'] == 'needs_consent':
        return decision
    record = {**decision, 'experimental_consent': experimental, 'answer_key': key}
    write(folder / 'route.json', record)
    if key:
        write(folder / 'answer-key-map.json', key)
    run.update(route_hash=json_digest(record), status='awaiting_ai')
    candidate['run'].update(processing_mode=decision['processing_mode'], review_mode=decision['review_mode'],
                            host=run['host'], answer_key_sha256=json_digest(key) if key else None)
    write(folder / 'candidate.json', candidate)
    write(folder / 'run.json', run)
    return decision


def ensure_editable(folder):
    run = read(folder / 'run.json')
    if run['status'] != 'awaiting_ai' or (folder / 'final.json').exists() or (folder.parent.parent / 'final.json').exists():
        raise ValueError('Preserve completed/failed runs; use a new run')


@candidate_operation
def repair_mapping(folder, response_file):
    """Correct source observations, preserving identity, content and prior bytes."""
    ensure_editable(folder)
    decision = copy.deepcopy(frozen_route(folder))
    response = read(response_file)
    if not isinstance(response.get('reason'), str) or not response['reason'].strip():
        raise ValueError('Mapping repair needs a source-based reason')
    selection, candidate, run = (read(folder/name) for name in ('selection.json','candidate.json','run.json'))
    catalog = read(folder/'catalog.json')
    mapped = {q['id']: q for q in selection['expected_questions']}
    changed = set()
    for replacement in response.get('questions', []):
        qid = replacement.get('id')
        if qid not in mapped or qid in changed:
            raise ValueError('Unknown or duplicate mapping repair question')
        old = mapped[qid]
        editable = {'content_inventory','source_fields','regions','field_regions','mapping_pending'}
        if {k:v for k,v in old.items() if k not in editable} != {k:v for k,v in replacement.items() if k not in editable}:
            raise ValueError('Mapping repair cannot change question identity or option labels')
        validate_source_fields(replacement, catalog)
        validate_inventory_record(replacement, catalog)
        if any(i['field']=='explanation' for i in replacement['content_inventory']):
            raise ValueError('Repair explanation inventory in solution_entries')
        mapped[qid] = replacement
        changed.add(qid)
    key = decision.get('answer_key')
    entries = {e['question_id']: e for e in (key or {}).get('entries', [])}
    seen = set()
    for replacement in response.get('solution_entries', []):
        qid = replacement.get('question_id')
        if qid not in entries or qid in seen:
            raise ValueError('Unknown or duplicate solution repair question')
        old = entries[qid]
        if {k:v for k,v in old.items() if k not in ('content_inventory','observation')} != {k:v for k,v in replacement.items() if k not in ('content_inventory','observation')}:
            raise ValueError('Solution repair only changes observed inventory; preserve frozen key/source')
        entries[qid] = replacement
        seen.add(qid); changed.add(qid)
    if not changed:
        raise ValueError('Mapping repair needs questions or solution_entries')
    selection['expected_questions'] = [mapped[q['id']] for q in selection['expected_questions']]
    if key:
        key['entries'] = [entries[e['question_id']] for e in key['entries']]
        validate_key(key, candidate)
    for qid in changed:
        validate_inventory_record(observed_inventory(mapped[qid], entries.get(qid)), catalog)
    from checkpoints import commit, json_bytes
    stamp = str(time.time_ns())
    original = (folder/'candidate.json').read_bytes()
    selection_bytes = json_bytes(selection)
    run.update(selection_hash=json_digest(selection), suite_sha256=__import__('hashlib').sha256(selection_bytes).hexdigest(),
               route_hash=json_digest(decision))
    candidate['run'].update(suite_sha256=run['suite_sha256'], answer_key_sha256=json_digest(key) if key else None)
    updates = {'candidate.json':json_bytes(candidate), 'selection.json':selection_bytes,
               'run.json':json_bytes(run), 'route.json':json_bytes(decision),
               'reports/mapping/repair-'+stamp+'.json':json_bytes(response)}
    if key: updates['answer-key-map.json'] = json_bytes(key)
    for name in ('self-checks.json','render-reviews.json'):
        if (folder/name).exists():
            current = read(folder/name)
            updates[name] = json_bytes({qid:v for qid,v in current.items() if qid not in changed})
    # Back up every changed file in the same recoverable transaction.
    for name in list(updates):
        if (folder/name).exists():
            updates['versions/mapping-'+stamp+'/'+name] = (folder/name).read_bytes()
    commit(folder, updates, original)
    return {'mapping_repaired':sorted(changed), 'content_preserved':True,
            'next':'Inspect the corrected source map; repair rejected content and renew affected visual cotejos.'}


def progress(folder):
    """Small continuation summary; never launches an agent or repeats accepted work."""
    candidate = read(folder/'candidate.json')
    checks = read(folder/'self-checks.json') if (folder/'self-checks.json').exists() else {}
    selection = {q['id']:q for q in read(folder/'selection.json')['expected_questions']}
    key = read(folder/'answer-key-map.json') if (folder/'answer-key-map.json').exists() else {}
    keys = {e['question_id']:e for e in key.get('entries',[])}
    accepted, pending, reviews = [], [], []
    reasons = {}
    for path in sorted((folder/'reports/ingest').glob('*.json')):
        attempt = read(path)
        for row in attempt.get('rejected',[]): reasons[row['question_id']] = row['reason']
        for qid in attempt.get('accepted',[]) + attempt.get('unchanged',[]): reasons.pop(qid, None)
    review_cache = {}
    for q in candidate['questions']:
        qid = q['id']
        try:
            if 'NOT_PROCESSED' in q['issues'] or not q['options']:
                raise ValueError('No accepted transcription')
            validate_inventory(q, observed_inventory(selection[qid],keys.get(qid)), candidate)
            validate_mapping({'questions':[q]}, {'expected_questions':[selection[qid]]})
            if any(b['type']=='unresolved' for b in __import__('lab').question_blocks(q)):
                raise ValueError('Source content remains unresolved')
            accepted.append(qid)
        except ValueError as error:
            pending.append(qid); reasons.setdefault(qid,str(error)); continue
        entry = checks.get(qid)
        try:
            if not entry: raise ValueError('No source cotejo')
            record = read(folder/'reports/self-checks'/entry['report'])
            check_record(folder, {**record,'questions':[entry['row']]}, candidate, review_cache)
            if not all(c['status']=='pass' for c in entry['row']['checks'].values()):
                raise ValueError('Source cotejo is not complete')
        except (ValueError, OSError, KeyError): reviews.append(qid)
    deferred = read(folder/'route.json').get('pending_question_ids', [])
    solution_pending = [q['id'] for q in candidate['questions'] if q['id'] in accepted and q['id'] not in deferred and
                        (q['answer']['status']=='missing' or q['explanation']['status']=='missing')]
    return {'accepted_question_ids':accepted, 'pending_question_ids':pending,
            'pending_solution_ids':solution_pending, 'pending_review_ids':reviews,
            'deferred_question_ids':deferred,
            'rejections':[{'question_id':qid,'reason':reason} for qid,reason in reasons.items()],
            'next':'batch-plan --pending-only' if pending else 'Complete missing solutions or review pending questions' if solution_pending or reviews else 'validate, then pack',
            'continuation':'The host agent continues while its session permits; resume does not execute AI.'}


def source_text(folder, source_id, pages):
    """Native text for selected physical pages; never infer formulas or answers."""
    source = next((s for s in read(folder/'sources.json') if s['id']==source_id), None)
    if source is None or not pages or any(p < 1 or p > source['page_count'] for p in pages):
        raise ValueError('Select existing source and physical pages')
    path = read(folder/'sources.local.json')[source_id]
    if digest(path) != source['sha256']: raise ValueError('Source PDF changed')
    import pypdfium2 as pdfium
    result = []
    with pdfium.PdfDocument(path) as pdf:
        for number in sorted(set(pages)):
            page = pdf[number-1]
            try:
                text = page.get_textpage()
                try: value = text.get_text_range()
                finally: text.close()
            finally: page.close()
            result.append({'page':number,'text':value})
    return {'source_id':source_id,'sha256':source['sha256'],'pages':result,
            'limitation':'Native extraction only: visually verify association, reading order, tables, accents and mathematical layout; never ingest this as verified content.'}


@candidate_operation
def adapt_draft(folder, draft_file):
    ensure_editable(folder)
    frozen_route(folder)
    from draft_adapter import adapt
    return adapt(folder, draft_file)


def frozen_route(folder):
    engine.verify_resume(folder)
    run, decision = read(folder / 'run.json'), read(folder / 'route.json')
    if json_digest(decision) != run.get('route_hash'):
        raise ValueError('Processing route changed')
    if decision['answer_key'] and read(folder / 'answer-key-map.json') != decision['answer_key']:
        raise ValueError('Answer-key provenance changed')
    return decision


@candidate_operation
def ingest(folder, response_file):
    ensure_editable(folder)
    frozen_route(folder)
    response = read(response_file)
    try:
        result = ingest_response(folder, response_file)
    except (ValueError, KeyError, TypeError) as error:
        rejected = getattr(error, 'rejected', [])
        archive(folder, 'ingest', {'response':response, 'accepted':[], 'unchanged':[],
                                  'rejected':rejected, 'error':str(error)})
        raise
    name = archive(folder, 'ingest', {'response':response, **result})
    return {**result, 'attempt_report':'reports/ingest/'+name}


def ingest_response(folder, response_file):
    ensure_editable(folder)
    decision = frozen_route(folder)
    raw_response_bytes = Path(response_file).read_bytes()
    response = json.loads(raw_response_bytes.decode('utf-8-sig'))
    candidate = read(folder/'candidate.json')
    key = validate_key(decision['answer_key'], candidate) if decision['answer_key'] else {}
    explanations = response.get('explanation_provenance', {})
    allowed = {q['id'] for q in candidate['questions']}
    questions = response.get('questions', [])
    if (not isinstance(questions, list) or not questions or any(not isinstance(q, dict) or q.get('id') not in allowed for q in questions) or
            len({q['id'] for q in questions}) != len(questions)):
        raise ValueError('AI batch must have unique questions inside frozen selection')
    if not isinstance(explanations, dict) or not set(explanations).issubset(allowed):
        raise ValueError('Unknown explanation question')
    prepared = []
    rejected = []
    mapping = {q['id']: q for q in read(folder/'selection.json')['expected_questions']}
    for raw_question in questions:
        q = copy.deepcopy(raw_question)
        try:
            inventory = observed_inventory(mapping[q['id']], key.get(q['id']))
            validate_inventory_record(inventory, read(folder/'catalog.json'))
            validate_inventory(q, inventory, candidate)
            if q['id'] in key:
                label = key[q['id']]['label']
                if label not in {o['label'] for o in q['options']}:
                    raise ValueError('Key answer does not exist among question alternatives')
                q['answer'] = {'label':label, 'status':'provisional', 'origin':'answer-key',
                               'source_ref':'.work/base/answer-key-map.json#'+q['id']}
            elif q['id'] in decision['pending_question_ids']:
                if q['answer']['label'] is not None or q['explanation']['blocks']:
                    raise ValueError('Experimental solving declined: keep uncovered answers/explanations missing')
            elif q['answer']['origin'] == 'answer-key':
                raise ValueError('Answer-key origin requires a frozen matching entry')
            if q['explanation']['blocks']:
                provenance = explanations.get(q['id'])
                if not provenance or provenance.get('origin') not in ('model','solution'):
                    raise ValueError('Every explanation needs model/solution provenance')
                if key.get(q['id'], {}).get('has_explanation') and provenance['origin'] != 'solution':
                    raise ValueError('Transcribe the existing solution; do not generate a replacement explanation')
                if provenance['origin'] == 'solution':
                    if q['id'] not in key or not key[q['id']].get('has_explanation'):
                        raise ValueError('No source justification recorded for this question')
                    if provenance.get('source_id') != key[q['id']]['source_id'] or provenance.get('page') != key[q['id']]['page']:
                        raise ValueError('Solution explanation source/page mismatch')
                    pages = provenance.setdefault('pages',key[q['id']].get('pages',[key[q['id']]['page']]))
                    if not isinstance(pages,list) or not pages or set(pages) != set(key[q['id']].get('pages',[key[q['id']]['page']])):
                        raise ValueError('Explanation pages must preserve frozen solution coverage')
            prepared.append(q)
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'question_id':q['id'],'reason':str(exc)})
    if not prepared:
        error = ValueError('No questions accepted: '+'; '.join(r['reason'] for r in rejected))
        error.rejected = rejected
        raise error
    response = {**response, 'questions':prepared, 'curriculum_provenance':{qid:r for qid,r in response.get('curriculum_provenance',{}).items() if qid in {q['id'] for q in prepared}}}
    staged = folder/'requests'/('ingest-'+str(time.time_ns())+'.json')
    write(staged,response)
    try:
        result = engine.ingest(folder, staged, raw_response_bytes=raw_response_bytes, explanation_provenance=explanations)
    except ValueError as error:
        error.rejected = rejected + getattr(error, 'rejected', [])
        raise
    finally:
        staged.unlink(missing_ok=True)
    result['rejected'] = rejected + result['rejected']
    return result


def record_usage(folder, response_file):
    """Record provider receipts without estimating missing measurements."""
    frozen_route(folder)
    response = read(response_file)
    if response.get('run_id') != read(folder/'run.json')['id']:
        raise ValueError('Usage belongs to a different run')
    incoming = response.get('events')
    if not isinstance(incoming,list) or not incoming:
        raise ValueError('Usage needs nonempty individual provider events')
    stored = read(folder/'usage-events.json') if (folder/'usage-events.json').exists() else []
    by_id = {e['event_id']:e for e in stored}
    from metrics import aggregate_usage
    for receipt in incoming:
        if not isinstance(receipt,dict) or not isinstance(receipt.get('usage_source'),str) or receipt['usage_source'] in ('','unavailable'):
            raise ValueError('Usage requires actual provider receipt source')
        aggregate_usage([receipt])
        prior = by_id.get(receipt['event_id'])
        if prior is not None and prior != receipt:
            raise ValueError('Conflicting usage receipt for existing event_id')
        by_id[receipt['event_id']] = receipt
    values = list(by_id.values())
    total = aggregate_usage(values)
    write(folder/'usage-events.json',values)
    write(folder/'usage-summary.json',total)
    return {'usage':total,'attestation':'provider receipts reported by host; not authenticated by this script'}


def final_usage(folder):
    from metrics import aggregate_usage
    records = read(folder/'usage-events.json') if (folder/'usage-events.json').exists() else []
    total = aggregate_usage(records)
    before, after = total['input_tokens'],total['output_tokens']
    return {**total,'total_tokens':before+after if before is not None and after is not None else None,
            'cost_usd':total['cost'] if total['currency']=='USD' else None,
            'source':'provider_receipts' if records else 'unavailable', 'scope':'production_only'}


def publication_usage(folder, independent):
    production = final_usage(folder)
    if not independent:
        return {'production':production, 'verification':None, 'combined':production}
    path = folder.parent/'verification/metrics.json'
    if not path.is_file():
        raise ValueError('Independent publication requires its measured/unknown verification summary')
    metrics = read(path)
    verification = metrics['verification_usage']
    fields = ('input_tokens','output_tokens','total_tokens','cost_usd','duration_seconds')
    combined = {key:production.get(key)+verification[key]
                if production.get(key) is not None and verification.get(key) is not None else None
                for key in fields}
    return {'production':production, 'verification':verification,
            'verification_metrics_sha256':digest(path),
            'combined':{**combined, 'scope':'production_and_verification',
                        'accounting':'disjoint_declared_scopes; duration sums calls, not wall time',
                        'attestation':'host measurements; missing values remain unknown'}}


@candidate_operation
def record_input(folder, response_file):
    ensure_editable(folder)
    frozen_route(folder)
    candidate = read(folder / 'candidate.json')
    ledger = read(response_file)
    proposed = copy.deepcopy(candidate)
    proposed['run'].update(input_mode=ledger.get('mode'), all_pages_read=True)
    temporary = folder / 'requests' / ('reading-' + str(time.time_ns()))
    temporary.mkdir(parents=True)
    write(temporary / 'direct-input.json', ledger)
    validate_direct_input(proposed, temporary)
    archive(folder, 'reading', ledger)
    write(folder / 'direct-input.json', ledger)
    write(folder / 'candidate.json', proposed)
    return {'reading_recorded': True, 'attestation': 'host declaration, not proof of comprehension'}


def archive(folder, kind, record):
    name = kind + '-' + str(time.time_ns()) + '.json'
    write(folder / 'reports' / kind / name, record)
    return name


def check_template(folder, question_ids=None):
    candidate = read(folder / 'candidate.json')
    previews = read(folder/'render-reviews.json') if (folder/'render-reviews.json').exists() else {}
    return {'run_id': candidate['run']['id'], 'independent': False,
            'session_id': read(folder / 'run.json')['session_id'],
            'protocol': 'source-cotejo-0.2',
            'questions': [{'id': q['id'], 'content_sha256': engine.content_hash(q, candidate, folder),
                           'solution_sha256': engine.solution_hash(q, candidate, folder),
                           **({'render_review': previews.get(q['id'])} if visual_review.required(folder) else {}),
                           'visual_observation': {'mode':'unavailable','tool':'','observation':''},
                           'checks': {k: {'status': 'unresolved', 'reason': '', 'field_paths': field_paths(q)[k], 'evidence': []} for k in CHECKS}}
                          for q in candidate['questions'] if question_ids is None or q['id'] in question_ids]}


def check_record(folder, record, candidate, review_cache=None):
    run = read(folder / 'run.json')
    if (record.get('run_id') != run['id'] or record.get('independent') is not False
            or record.get('session_id') != run['session_id']):
        raise ValueError('Self-check must identify this producing session and declare independent=false')
    by_id = {q['id']: q for q in candidate['questions']}
    rows = record.get('questions', [])
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Self-check rows must be nonempty and unique')
    resources = {a['id']: a for a in candidate['assets'] + candidate['evidence']}
    selection = {q['id']: q for q in read(folder/'selection.json')['expected_questions']}
    key_path = folder/'answer-key-map.json'
    keys = {e['question_id']: e for e in read(key_path)['entries']} if key_path.exists() else {}
    provenance = read(folder/'explanation-provenance.json') if (folder/'explanation-provenance.json').exists() else {}
    if candidate['schema_version'] == '0.2.0' and record.get('protocol') != 'source-cotejo-0.2':
        raise ValueError('Source cotejo 0.2 protocol required')
    review_cache = {} if review_cache is None else review_cache
    for row in rows:
        q = by_id.get(row['id'])
        if (not q or row.get('content_sha256') != engine.content_hash(q, candidate, folder)
                or row.get('solution_sha256') != engine.solution_hash(q, candidate, folder)):
            raise ValueError('Stale self-check question/solution')
        if visual_review.required(folder):
            visual_review.validate_review(folder, row.get('render_review'), q, candidate, review_cache)
            observed = visual_review.validate_observation(folder, row.get('visual_observation'), row.get('render_review'), q, candidate, review_cache)
            if not observed and any(row.get('checks',{}).get(k,{}).get('status')=='pass' for k in ('stem','options','assets_math','consistency')):
                raise ValueError('Rendered result unavailable: keep visual checks unresolved')
        if set(row.get('checks', {})) != set(CHECKS):
            raise ValueError('Self-check needs all six dimensions')
        for dimension, check in row['checks'].items():
            if check.get('status') not in ('pass', 'fail', 'unresolved') or not check.get('reason') or not check.get('evidence'):
                raise ValueError('Self-check needs pass/unresolved, reason and visual evidence')
            for citation in check['evidence']:
                resource = resources.get(citation.get('id'))
                if (not resource or resource['sha256'] != citation.get('sha256')
                        or not citation.get('observation')
                        or digest(artifact_path(folder, resource['path'])) != citation['sha256']):
                    raise ValueError('Unknown, altered or unjustified self-check evidence')
            if candidate['schema_version'] == '0.2.0':
                validate_citations(q, dimension, check, candidate, folder, selection.get(q['id']), keys.get(q['id']), provenance.get(q['id']))
    return rows


@candidate_operation
def record_check(folder, response_file):
    ensure_editable(folder)
    frozen_route(folder)
    candidate = read(folder / 'candidate.json')
    record = read(response_file)
    rows = check_record(folder, record, candidate)
    current = read(folder / 'self-checks.json') if (folder / 'self-checks.json').exists() else {}
    name = archive(folder, 'self-checks', record)
    for row in rows:
        current[row['id']] = {'report': name, 'row': row}
    write(folder / 'self-checks.json', current)
    return {'self_checked': len(rows), 'independent': False}


def validate_for_pack(folder):
    if read(folder / 'run.json')['status'] in ('failed', 'failed_preparation'):
        raise ValueError('Failed runs cannot publish')
    decision = frozen_route(folder)
    candidate = read(folder / 'candidate.json')
    engine.validate_run_contract(folder / 'candidate.json')
    require_official_final(candidate)
    for field in ('processing_mode', 'review_mode'):
        if candidate['run'].get(field) != decision[field]:
            raise ValueError('Candidate changed selected mode')
    expected_key_hash = json_digest(decision['answer_key']) if decision['answer_key'] else None
    if candidate['run'].get('answer_key_sha256') != expected_key_hash:
        raise ValueError('Candidate changed answer-key identity')
    validate_direct_input(candidate, folder)
    validation_result = validate(candidate, folder)
    validate_geometry(candidate, read(folder/'catalog.json'))
    if candidate['schema_version'] == '0.2.0': validate_mapping(candidate,read(folder/'selection.json'))
    key = validate_key(decision['answer_key'], candidate) if decision['answer_key'] else {}
    provenance = read(folder / 'explanation-provenance.json') if (folder / 'explanation-provenance.json').exists() else {}
    checks = read(folder / 'self-checks.json') if (folder / 'self-checks.json').exists() else {}
    curriculum_ledger = read(folder/'curriculum-ledger.json') if (folder/'curriculum-ledger.json').exists() else {}
    mapped = {q['id']:q for q in read(folder/'selection.json')['expected_questions']}
    checked_reports = {}
    for q in candidate['questions']:
        validate_inventory(q, observed_inventory(mapped[q['id']], key.get(q['id'])), candidate)
        if candidate['schema_version'] == '0.2.0':
            from curriculum import curriculum_hash, prepare_ledger, validate_question_curriculum
            classified = validate_question_curriculum(q)
            entry = curriculum_ledger.get(q['id'], {})
            if classified:
                if entry.get('curriculum_sha256') != curriculum_hash(q, engine.content_hash(q,candidate,folder)):
                    raise ValueError(q['id']+': Stale or absent curriculum evidence ledger')
                prepare_ledger(candidate, {'questions':[q], 'curriculum_provenance':{q['id']:entry}}, engine.content_hash, folder, curriculum_ledger)
            observed_labels = mapped[q['id']].get('option_labels')
            if observed_labels is not None and [o['label'] for o in q['options']] != observed_labels:
                raise ValueError(q['id']+': options differ from frozen observed labels')
        if q['id'] in key:
            if (q['answer']['label'] != key[q['id']]['label'] or q['answer']['origin'] != 'answer-key'
                    or q['answer']['source_ref'] != '.work/base/answer-key-map.json#' + q['id']):
                raise ValueError('Candidate changed mapped answer-key response')
        elif q['answer']['origin'] == 'answer-key':
            raise ValueError('Unknown key answer')
        if q['id'] in decision['pending_question_ids'] and (q['answer']['label'] is not None or q['explanation']['blocks']):
            raise ValueError('Solving declined for this question')
        if q['fidelity']['status'] != 'pending' or q['answer']['status'] == 'verified' or q['explanation']['status'] == 'verified':
            raise ValueError('Base/self-check cannot claim independent verified status')
        if q['explanation']['blocks'] and provenance.get(q['id'], {}).get('origin') not in ('model', 'solution'):
            raise ValueError('Missing explanation provenance')
        entry = checks.get(q['id'])
        if not entry:
            raise ValueError('Every question needs its own documented source cotejo')
        if entry['report'] not in checked_reports:
            archived = read(folder / 'reports/self-checks' / entry['report'])
            active = [row for row in archived['questions']
                      if checks.get(row['id'], {}).get('report') == entry['report']]
            checked_reports[entry['report']] = check_record(folder, {**archived, 'questions': active}, candidate)
        bound = checked_reports[entry['report']]
        if entry['row'] not in bound:
            raise ValueError('Self-check archive binding mismatch')
    result = summarize(candidate, checks)
    # These rows have just passed check_record, including source association,
    # hashes and rendered-result evidence. Status flags alone never confer Gold.
    result['gold_eligible'] = bool(candidate['questions']) and result['publication_eligibility'] == 'complete' and visual_review.required(folder) and all(
        all(c['status'] == 'pass' for c in checks[q['id']]['row']['checks'].values()) and
        checks[q['id']]['row'].get('visual_observation', {}).get('mode') in ('html','images')
        for q in candidate['questions'])
    result['gold_basis'] = 'Visual fidelity to exam and available solution; not independent mathematical correctness'
    for q in candidate['questions']:
        if mapped[q['id']].get('mapping_pending'):
            result['gold_eligible'] = False
            result['issues'].append({'question_id':q['id'],'field':'options','code':'MAPPING_PENDING','severity':'warning'})
            if result['publication_eligibility'] != 'blocked': result['publication_eligibility'] = 'partial'
    write(folder/'quality-report.json', result)
    require_publishable(result)
    if decision['processing_mode'] == 'answer-key' and result['publication_eligibility'] != 'complete':
        raise ValueError('Complete answer-key import has pending source cotejos/content; repair before publication. Preserve the run as incomplete.')
    decision = {**decision, 'quality': result, 'validation': validation_result}
    return candidate, decision


@candidate_operation
def publish_base(folder):
    candidate, decision = validate_for_pack(folder)
    if decision['independent_question_ids']:
        raise ValueError('Independent route needs baseline and verification before publication')
    candidate['run']['quality'] = decision['quality']
    output = publication_path(folder)
    used = {b['asset_id'] for q in candidate['questions'] for b in __import__('lab').question_blocks(q) if b['type'] == 'image'}
    for resource in candidate['assets']:
        if resource['id'] in used:
            target = inside(output / resource['path']); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact_path(folder, resource['path']), target)
    candidate['assets'] = [a for a in candidate['assets'] if a['id'] in used]
    candidate['evidence'] = []
    write(output / 'candidate.json', candidate)
    result = pack(output / 'candidate.json')
    return finish_publication(folder, output, result, decision)


def finish_publication(folder, output, result, decision):
    run = read(folder / 'run.json')
    target = inside(output / (run['exam_id'] + '.zip'))
    Path(result['zip']).rename(target)
    companion = inside(output / (run['exam_id'] + '.paessed'))
    Path(result['paessed']).rename(companion)
    result.update(zip=str(target), paessed=str(companion))
    final = read(output / 'final.json')
    metadata = {**run, 'id': final['run']['id'], 'status': 'packaged', 'finished_at': now(),
                'processing_mode': decision['processing_mode'], 'review_mode': decision['review_mode'],
                'final_sha256': digest(output / 'final.json'), 'package_sha256': digest(target),
                 'usage': final_usage(folder),
                'usage_scopes': publication_usage(folder, bool(decision['independent_question_ids'])),
                'summary': {'questions': result['questions'],
                            'answers_from_key': sum(q['answer']['origin'] == 'answer-key' for q in final['questions']),
                            'answers_from_model': sum(q['answer']['origin'] == 'model' for q in final['questions']),
                            'answers_missing': sum(q['answer']['status'] == 'missing' for q in final['questions']),
                            'answers_verified_by_ai': sum(q['answer']['status'] == 'verified' for q in final['questions']),
                            'independent_questions': len(decision['independent_question_ids']),
                            'accuracy': None,
                            'quality': final['run'].get('quality', decision.get('quality', summarize(final))),
                             'note': 'Structural validation and AI review are not ground truth'}}
    if (output / 'run.json').exists():
        metadata['verification'] = read(output / 'run.json')
    if not decision['independent_question_ids']:
        run.update(status='packaged', finished_at=metadata['finished_at'], final_sha256=metadata['final_sha256'])
        write(folder / 'run.json', run)
    write(output / 'run.json', metadata)
    result['summary'] = metadata['summary']
    return result


@candidate_operation
def baseline(folder):
    candidate, decision = validate_for_pack(folder)
    if not decision['independent_question_ids']:
        raise ValueError('This route publishes directly; no independent baseline needed')
    candidate['run']['quality'] = decision['quality']
    write(folder/'candidate.json',candidate)
    result = pack(folder / 'candidate.json')
    run = read(folder / 'run.json')
    run.update(status='packaged', finished_at=now(), final_sha256=digest(folder / 'final.json'),
               independent_question_ids=decision['independent_question_ids'])
    write(folder / 'run.json', run)
    return result


def verify_command(args):
    import verify
    if args.action == 'prepare':
        parent = base_folder(args.run)
        decision = frozen_route(parent)
        if not decision['independent_question_ids']:
            raise ValueError('No independent work selected')
        validate_for_pack(parent)
        run = read(parent / 'run.json')
        if args.session_id in ('unknown', '', run['session_id']):
            raise ValueError('Independent coordinator session required')
        return {'verification': verify.prepare(parent, run['id'] + '-review', 10, run['model'],
                                              run['config']['effort'], args.session_id,
                                              parent.parent.parent)}
    folder = Path(args.run).absolute()
    if (folder / '.work/verification/run.json').is_file():
        folder = folder / '.work/verification'
    if folder.name != 'verification' or folder.parent.name != '.work':
        raise ValueError('Expected .work/verification')
    configure_workspace(folder.parent.parent)
    if args.action == 'commit-reading':
        return verify.commit_reading(folder, args.batch, args.response)
    if args.action == 'check':
        return {'reports': len(verify.load_reports(folder)[2])}
    if args.action == 'decisions':
        verify.decisions(folder)
        return {'template': str(folder / 'decisions-template.json')}
    if args.action == 'add-evidence':
        return verify.add_evidence(folder, args.batch, read(args.requests))
    parent = base_folder(folder.parent / 'base')
    decision = frozen_route(parent)
    validate_for_pack(parent)
    result = verify.consolidate(folder, args.decisions)
    return finish_publication(parent, folder.parent.parent, result, decision)


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--exam', required=True); p.add_argument('--solution')
    p.add_argument('--destination', choices=['documents', 'downloads', 'custom'], default='documents')
    p.add_argument('--output-root'); p.add_argument('--title'); p.add_argument('--run-id')
    p.add_argument('--suggested-save-location')
    p.add_argument('--host', choices=['cli', 'web'], required=True); p.add_argument('--client')
    p.add_argument('--model', default='unknown'); p.add_argument('--effort', default='unknown')
    p.add_argument('--session-id', required=True); p.add_argument('--capabilities', required=True)
    p.add_argument('--scale', type=float, default=1.5)
    p = sub.add_parser('inspect'); p.add_argument('--package', required=True)
    p = sub.add_parser('adapt-draft'); p.add_argument('--run', required=True); p.add_argument('--draft', required=True)
    p = sub.add_parser('verify')
    p.add_argument('action', choices=['prepare', 'check', 'decisions', 'consolidate', 'add-evidence', 'commit-reading'])
    p.add_argument('--run', required=True); p.add_argument('--session-id', default='unknown')
    p.add_argument('--decisions'); p.add_argument('--batch'); p.add_argument('--requests'); p.add_argument('--response')
    for name in ('map', 'repair-map', 'source-text', 'route', 'ingest', 'record-input', 'record-usage', 'batch-plan', 'review', 'capture-review', 'check-template', 'record-check', 'crops',
                 'validate', 'pack', 'baseline', 'resume', 'fail'):
        p = sub.add_parser(name); p.add_argument('--run', required=True)
        if name == 'map': p.add_argument('--selection', required=True)
        if name == 'source-text':
            p.add_argument('--source-id', required=True)
            p.add_argument('--page', type=int, action='append', required=True)
        if name in ('ingest', 'repair-map', 'record-input', 'record-check', 'record-usage'): p.add_argument('--response', required=True)
        if name == 'route':
            p.add_argument('--answer-key'); p.add_argument('--subagents', action='store_true')
            p.add_argument('--experimental', choices=['yes', 'no'])
            review = p.add_mutually_exclusive_group()
            review.add_argument('--review-question', action='append', default=[])
            review.add_argument('--review-all', action='store_true')
        if name == 'crops': p.add_argument('--requests', required=True)
        if name == 'capture-review':
            p.add_argument('--executable-path')
            p.add_argument('--transport', choices=['auto','file','memory'], default='auto')
        if name == 'check-template': p.add_argument('--question', action='append')
        if name == 'batch-plan':
            p.add_argument('--batch-size',type=int,default=5); p.add_argument('--max-characters',type=int,default=24000)
            p.add_argument('--pending-only', action='store_true')
        if name == 'fail': p.add_argument('--reason', required=True)
    args = parser.parse_args()
    stage_started = time.perf_counter()
    folder = None
    try:
        if args.command == 'prepare': result = prepare(args)
        elif args.command == 'inspect': result = inspect_package(args.package)
        elif args.command == 'verify': result = verify_command(args)
        else:
            folder = base_folder(args.run)
            if args.command == 'map': result = map_questions(folder, args.selection)
            elif args.command == 'repair-map': result = repair_mapping(folder, args.response)
            elif args.command == 'source-text': result = source_text(folder,args.source_id,args.page)
            elif args.command == 'route':
                review_ids = [q['id'] for q in read(folder/'candidate.json')['questions']] if args.review_all else args.review_question or None
                result = route(folder, args.answer_key, args.subagents, args.experimental, review_ids)
            elif args.command == 'ingest': result = ingest(folder, args.response)
            elif args.command == 'adapt-draft': result = adapt_draft(folder, args.draft)
            elif args.command == 'record-input': result = record_input(folder, args.response)
            elif args.command == 'record-usage': result = record_usage(folder,args.response)
            elif args.command == 'batch-plan':
                frozen_route(folder)
                from batch_plan import plan_batches
                remaining = progress(folder) if args.pending_only else None
                result = plan_batches(read(folder/'candidate.json'),args.batch_size,args.max_characters,
                                      selection=read(folder/'selection.json'), route=read(folder/'route.json'),
                                      question_ids=remaining['pending_question_ids']+remaining['pending_solution_ids'] if remaining else None)
            elif args.command == 'check-template':
                if args.question and not set(args.question).issubset(q['id'] for q in read(folder/'candidate.json')['questions']):
                    raise ValueError('Unknown check-template question')
                result = check_template(folder,args.question)
            elif args.command == 'capture-review':
                ensure_editable(folder)
                frozen_route(folder)
                references = read(folder/'render-reviews.json')
                if not references: raise ValueError('Generate review before capture-review')
                from capture_review import capture_review
                result = capture_review(folder, next(iter(references.values())), executable_path=args.executable_path, transport=args.transport)
            elif args.command == 'review':
                with __import__('checkpoints').state_lock(folder):
                    ensure_editable(folder)
                    frozen_route(folder)
                    result = visual_review.create_review(folder)
            elif args.command == 'record-check': result = record_check(folder, args.response)
            elif args.command == 'crops':
                ensure_editable(folder)
                frozen_route(folder)
                additions = apply_crops(folder, read(args.requests)); engine.sync_assets(folder)
                ids = {a['id'] for a in additions}
                result = {'assets':additions, 'warnings':[w for w in read(folder/'catalog.json').get('warnings',[]) if w.get('asset_id') in ids]}
            elif args.command == 'validate': result = validate_for_pack(folder)[1]
            elif args.command == 'pack': result = publish_base(folder)
            elif args.command == 'baseline': result = baseline(folder)
            elif args.command == 'fail':
                run = read(folder / 'run.json'); run.update(status='failed', reason=args.reason)
                write(folder / 'run.json', run); result = {'status': 'failed', 'reason': args.reason}
            else:
                run = read(folder / 'run.json')
                if run['status'] == 'awaiting_mapping':
                    verify_pre_mapping(folder); result = {'status': run['status']}
                else:
                    result = engine.verify_resume(folder)
                    if (folder / 'route.json').exists(): frozen_route(folder)
                    if run['status'] == 'awaiting_ai': result.update(progress(folder))
        if args.command == 'prepare': folder = Path(result['run'])
        if folder is not None:
            event(folder,'command_'+args.command,duration_seconds=time.perf_counter()-stage_started,outcome='completed')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
        if folder is not None and (folder/'run.json').exists():
            event(folder,'command_'+args.command,duration_seconds=time.perf_counter()-stage_started,outcome='failed')
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
