"""Deterministic lossless batch planning; character budgets are not token estimates."""
import copy
import hashlib
import json
from curriculum import catalog_hash
from pipeline import content_hash

def blocks_with_children(blocks):
    for block in blocks:
        yield block
        if block['type'] == 'table':
            for row in block['rows']:
                for cell in row:
                    yield from blocks_with_children(cell)

def plan_batches(candidate, max_questions=5, max_characters=24000, *, selection=None, route=None, question_ids=None,
                 source_index=None, include_context=False, asset_candidates=None, failure_counts=None):
    if type(max_questions) is not int or not 1 <= max_questions <= 10:
        raise ValueError('max_questions must be 1..10')
    if type(max_characters) is not int or max_characters < 1:
        raise ValueError('max_characters must be a positive integer')
    questions = candidate['questions']
    ids = [q['id'] for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate question ID')
    assets = {a['id']: a for a in candidate.get('assets', [])}
    sources = {s['id']: s for s in candidate['sources']}
    mapping = {q['id']: q for q in (selection or {}).get('expected_questions', [])}
    keys = {e['question_id']: e for e in ((route or {}).get('answer_key') or {}).get('entries', [])}
    if selection is not None and set(mapping) != set(ids):
        raise ValueError('Batch plan requires exact frozen selection coverage')
    selected = set(ids if question_ids is None else question_ids)
    if not selected.issubset(ids):
        raise ValueError('Batch selection outside mapped questions')
    index = []
    page_index = {}
    for question in questions:
        if question['id'] not in selected:
            continue
        blocks = list(blocks_with_children(question['stem']))
        for option in question['options']:
            blocks.extend(blocks_with_children(option['blocks']))
        blocks.extend(blocks_with_children(question['explanation']['blocks']))
        used = sorted({b['asset_id'] for b in blocks if b['type'] == 'image'})
        if any(aid not in assets for aid in used):
            raise ValueError('Question references a missing asset')
        if question['source_id'] not in sources:
            raise ValueError('Question references a missing source')
        observed = mapping.get(question['id'], {})
        inventory = observed.get('content_inventory', [])
        regions = observed.get('regions') or [r for values in observed.get('source_fields', {}).values() for r in values]
        pages = {(question['source_id'], r['page']) for r in regions or question['regions']}
        context_scope = 'frozen_source_map' if regions else 'question_regions' if pages else 'full_source_fallback'
        if not pages:
            if selection is not None:
                if not observed.get('mapping_pending'):
                    raise ValueError(question['id']+': map source regions before batch planning')
                pages = {(question['source_id'], observed['page'])}
                context_scope = 'mapping_pending'
            else:
                pages = {(question['source_id'], page) for page in range(1, sources[question['source_id']]['page_count'] + 1)}
        key = keys.get(question['id'])
        if key:
            pages.update((key['source_id'], p) for p in key.get('pages', [key['page']]))
        pages.update((assets[aid]['source_id'], assets[aid]['page']) for aid in used)
        for sid, page in pages:
            if sid not in sources or type(page) is not int or not 1 <= page <= sources[sid]['page_count']:
                raise ValueError('Question page is outside source')
            page_index.setdefault((sid, page), []).append(question['id'])
        tables = [b for b in blocks if b['type'] == 'table']
        cells = sum(len(row) for table in tables for row in table['rows'])
        math_characters = sum(len(b['latex']) for b in blocks if b['type'] == 'math')
        complexity = len(used) * 3 + len(tables) * 3 + cells // 8 + math_characters // 300 + max(0, len(pages) - 1) * 2
        solution_inventory = [{**item,'source_id':item.get('source_id',key['source_id'])}
                              for item in (key or {}).get('content_inventory', [])]
        observed_complexity = sum(i['count'] * 3 for i in inventory+solution_inventory if i['type'] in ('image','table'))
        complexity = max(complexity, observed_complexity + max(0, len(pages)-1)*2)
        cap = 1 if complexity >= 8 else min(2, max_questions) if complexity >= 3 else max_questions
        failures = (failure_counts or {}).get(question['id'],0)
        if type(failures) is not int or failures < 0: raise ValueError('Failure counts must be nonnegative integers')
        if failures: cap = min(cap,1 if failures>=2 else 2)
        resources = [assets[aid] for aid in used]
        context = {'question': question, 'source_map': observed, 'answer_key': key,
                   'assets': resources, 'pages': [{'source_id': sid, 'page': page} for sid, page in sorted(pages)],
                   'sources': [sources[sid] for sid in sorted({sid for sid, _ in pages} | {question['source_id']})]}
        context['asset_candidates'] = [a for a in asset_candidates or [] if (a['source_id'],a['page']) in pages]
        if source_index is not None:
            from source_index import query_source_index
            localized = {}
            for sid in sorted({sid for sid, _ in pages}):
                source_regions = []
                if sid == question['source_id']:
                    source_regions.extend(r for values in observed.get('source_fields',{}).values() for r in values)
                    if not source_regions: source_regions.extend(regions or question['regions'])
                source_regions.extend(r for item in inventory+solution_inventory if item.get('source_id',question['source_id'])==sid for r in item.get('regions',[]))
                covered_pages = {r['page'] for r in source_regions}
                for source,page_number in sorted(pages):
                    if source == sid and page_number not in covered_pages:
                        page = next(p for p in source_index['pages'] if p['source_id']==sid and p['page']==page_number)
                        source_regions.append({'page':page_number,'bbox':[0,0,page['width'],page['height']]})
                localized[sid] = source_regions
            context['native_source'] = [query_source_index(source_index, sid,
                pages=sorted(page for source, page in pages if source == sid), regions=localized[sid], max_chars=None,layout='compact')
                for sid in sorted(localized)]
        template_question = copy.deepcopy(question)
        if regions:
            template_question['regions'] = copy.deepcopy(regions)
        if not template_question.get('options') and observed.get('option_labels'):
            template_question['options'] = [{'label':label,'blocks':[{'type':'unresolved','reason':'Observe this option in the source'}]}
                for label in observed['option_labels']]
        if key:
            template_question['answer'] = {'label':key['label'],'status':'provisional','origin':'answer-key',
                'source_ref':'.work/base/answer-key-map.json#'+question['id']}
        if 'issues' in template_question:
            template_question['issues'] = [issue for issue in template_question['issues'] if issue!='NOT_PROCESSED']
        context['response_template'] = {'run_id': candidate.get('run', {}).get('id'),
            'questions': [template_question], 'explanation_provenance': {},
            'curriculum_provenance': {question['id']:{'reason':'', 'evidence':[
                {'source_id':question['source_id'], 'page':page, 'observation':''}
                for sid,page in sorted(pages) if sid==question['source_id']]}}}
        if key and key.get('has_explanation'):
            context['response_template']['explanation_provenance'][question['id']] = {
                'origin':'solution', 'source_id':key['source_id'], 'page':key['page'],
                'pages':key.get('pages',[key['page']]), 'regions':[]}
            context['solution_regions_to_observe'] = [r for item in key.get('content_inventory',[]) for r in item.get('regions',[])]
            context['required_observations'] = ['Complete explanation_provenance regions on every solution page, including prose and all development; inventory boxes are only structure hints.']
        elif question['id'] not in (route or {}).get('pending_question_ids',[]):
            context['response_template']['explanation_provenance'][question['id']] = {'origin':'model'}
        from curriculum import catalog
        context['allowed_values'] = {'curriculum':{axis['eje']:axis['subejes'] for axis in catalog()['ejes']}, 'block_types':['text','math','image','table','unresolved'],
            'answer_status':['missing','provisional'], 'explanation_status':['missing','provisional'],
            'explanation_origins':['model','solution'],
            'math_display':[False,True], 'option_labels':observed.get('option_labels'),
            'policy':'Fill source content and observations; template values never attest fidelity. Do not resolve declined missing answers.'}
        count = len(json.dumps(context, ensure_ascii=False, separators=(',', ':')))
        index.append({'question_id': question['id'], 'source_id': question['source_id'], 'number': question['number'],
            'pages': [{'source_id': sid, 'page': page} for sid, page in sorted(pages)], 'source_context_scope': context_scope, 'asset_ids': used,
            'content_sha256': content_hash(question, candidate), 'context_sha256': hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
            'serialized_characters': count, 'complexity': complexity, 'question_limit': cap,
            'recent_rejections':failures,
            'mapping_pending': bool(observed.get('mapping_pending')),
            **({'context':context} if include_context else {})})
    batches = []
    current = []
    current_characters = 0
    def flush():
        nonlocal current, current_characters
        if not current:
            return
        page_keys = {(p['source_id'], p['page']) for item in current for p in item['pages']}
        batches.append({'id': f'batch-{len(batches)+1:02d}', 'question_ids': [item['question_id'] for item in current],
            'pages': [{'source_id': sid, 'page': page} for sid, page in sorted(page_keys)],
            'source_ids': sorted({item['source_id'] for item in current} | {sid for sid, _ in page_keys}),
            'asset_ids': sorted({aid for item in current for aid in item['asset_ids']}),
            'catalog_sha256': catalog_hash(), 'content_hashes': {item['question_id']: item['content_sha256'] for item in current},
            'context_hashes': {item['question_id']: item['context_sha256'] for item in current},
            'serialized_characters': current_characters,
            **({'contexts':[item['context'] for item in current]} if include_context else {}),
            'oversized': current_characters > max_characters})
        current = []
        current_characters = 0
    for item in index:
        effective_cap = min([item['question_limit'], *[r['question_limit'] for r in current]])
        if current and (len(current) + 1 > effective_cap or current_characters + item['serialized_characters'] > max_characters):
            flush()
        current.append(item)
        current_characters += item['serialized_characters']
        if len(current) >= item['question_limit'] or current_characters >= max_characters:
            flush()
    flush()
    return {'format': 'paessed-batch-plan', 'schema_version': '0.1.0', 'max_questions': max_questions,
        'max_characters': max_characters, 'batches': batches, 'question_index': [{k:v for k,v in item.items() if k!='context'} for item in index],
        'page_index': [{'source_id': sid, 'page': page, 'question_ids': qids} for (sid,page),qids in sorted(page_index.items())],
        'pending_mapping_question_ids': [q['question_id'] for q in index if q['mapping_pending']],
        'context_policy': 'Never truncate a question or omit its referenced pages/assets; an oversized question remains alone.',
        'token_estimate': None, 'savings': 'not_measured'}
