"""Explicit, reviewable correction of physical *continuation* pages only.

Never rewrites a frozen key label, source, original page, candidate content, or
PDF. Every mutation is checkpointed using the existing crash-safe transaction.
"""
from __future__ import annotations
import copy
import time
from pathlib import Path

from checkpoints import commit, json_bytes, state_lock
from lab import artifact_path, digest, json_digest, read


def repair(folder: Path, request: dict, *, ensure_editable, frozen_route,
           validate_key, observed_inventory, validate_inventory_record):
    with state_lock(folder):
        return _repair(folder, request, ensure_editable=ensure_editable,
                       frozen_route=frozen_route, validate_key=validate_key,
                       observed_inventory=observed_inventory,
                       validate_inventory_record=validate_inventory_record)


def _repair(folder: Path, request: dict, *, ensure_editable, frozen_route,
            validate_key, observed_inventory, validate_inventory_record):
    ensure_editable(folder)
    decision = copy.deepcopy(frozen_route(folder))
    if decision.get('processing_mode') not in ('answer-key', 'mixed', 'partial-pending') or not decision.get('answer_key'):
        raise ValueError('Repair requires frozen answer-key route')
    if not isinstance(request, dict) or not isinstance(request.get('reason'),str) or len(request['reason'].strip()) < 15:
        raise ValueError('Require a substantive, source-based overall reason')
    changes = request.get('changes')
    if not isinstance(changes,list) or not changes:
        raise ValueError('Repair requires continuation entries')
    run, candidate = read(folder/'run.json'), read(folder/'candidate.json')
    catalog = read(folder/'catalog.json')
    sources = {s['id']: s for s in candidate['sources']}
    from checkpoint_export import resolve_sources
    resolve_sources(folder)
    key = copy.deepcopy(decision['answer_key'])
    entries = {entry['question_id']:entry for entry in key['entries']}
    selected = {q['id']:q for q in read(folder/'selection.json')['expected_questions']}
    provenance_file = folder/'explanation-provenance.json'
    provenance = read(provenance_file)
    page_evidence = {(e['source_id'],e['page']):e for e in catalog['evidence']}
    changed = []
    for change in changes:
        if not isinstance(change,dict) or set(change) != {'question_id','old_pages','add_pages','reason','evidence'}:
            raise ValueError('Each repair requires question_id, old_pages, add_pages, reason, evidence')
        qid = change['question_id']
        if qid not in entries or qid in changed or qid not in selected:
            raise ValueError('Unknown/duplicate solution question')
        old = entries[qid]
        source_id = old['source_id']
        source = sources.get(source_id)
        if source is None:
            raise ValueError('Answer-key entry source is not registered')
        old_pages = old.get('pages') or [old['page']]
        if change['old_pages'] != old_pages:
            raise ValueError('Stale repair: frozen pages have changed')
        added = change['add_pages']
        if (not isinstance(added,list) or not added or
            any(type(p) is not int for p in added) or len(set(added)) != len(added) or
            any(p < 1 or p > source['page_count'] or p in old_pages for p in added) or
            added != sorted(added)):
            raise ValueError('Only NEW valid source pages can be appended')
        new_pages = sorted(old_pages+added)
        if (not isinstance(change['reason'],str) or len(change['reason'].strip())<15 or
            not isinstance(change['evidence'],list) or len(change['evidence'])!=len(added)):
            raise ValueError('Require specific reason and one page-image proof per added page')
        for proof,page in zip(change['evidence'],added):
            if not isinstance(proof,dict) or set(proof) != {'source_id','page','evidence_id','sha256','observation'}:
                raise ValueError('Page proof fields are source_id/page/evidence_id/sha256/observation')
            resource = page_evidence.get((source_id,page))
            if (not resource or proof['source_id'] != source_id or proof['page'] != page or
                proof['evidence_id'] != resource['id'] or proof['sha256'] != resource['sha256'] or
                not isinstance(proof['observation'],str) or len(proof['observation'].strip()) < 12 or
                digest(artifact_path(folder,resource['path'])) != resource['sha256']):
                raise ValueError('Missing, altered or unobserved physical solution-page evidence')
        prov = provenance.get(qid)
        if (not prov or prov.get('origin') != 'solution' or prov.get('source_id') != source_id or
            prov.get('page') != old['page'] or (prov.get('pages') or [prov['page']]) != old_pages):
            raise ValueError('Explanation provenance must match the frozen key before repair')
        old['pages'] = new_pages
        # Inventory and transcribed candidate content are intentionally unchanged.
        # A subsequent inventory correction, if truly needed, is a separate repair-map.
        provenance[qid] = {**prov,'pages':new_pages}
        validate_inventory_record(observed_inventory(selected[qid],old),catalog)
        changed.append(qid)
    validate_key(key,candidate)
    decision['answer_key'] = key
    from hashlib import sha256
    run['route_hash'] = json_digest(decision)
    candidate['run']['answer_key_sha256'] = json_digest(key)
    original = (folder/'candidate.json').read_bytes()
    stamp=str(time.time_ns())
    updates={'candidate.json':json_bytes(candidate),'run.json':json_bytes(run),
             'route.json':json_bytes(decision),'answer-key-map.json':json_bytes(key),
             'explanation-provenance.json':json_bytes(provenance),
             'reports/provenance/repair-'+stamp+'.json':json_bytes({
                **request, 'protocol':'provenance-continuation-1', 'old_route_hash':read(folder/'run.json')['route_hash'],
                'new_route_hash':run['route_hash'], 'old_answer_key_sha256':read(folder/'candidate.json')['run']['answer_key_sha256'],
                'new_answer_key_sha256':candidate['run']['answer_key_sha256'],
                'source_pdf_sha256':{entries[qid]['source_id']:sources[entries[qid]['source_id']]['sha256'] for qid in changed},
                'candidate_content_unchanged':True})}
    for name in ('self-checks.json','render-reviews.json'):
        if (folder/name).exists():
            current=read(folder/name)
            updates[name]=json_bytes({qid:value for qid,value in current.items() if qid not in changed})
    for name in list(updates):
        if (folder/name).exists():
            updates['versions/provenance-'+stamp+'/'+name]=(folder/name).read_bytes()
    commit(folder,updates,original)
    return {'repaired_question_ids':changed,'old_candidate_sha256':sha256(original).hexdigest(),
            'source_pdf_sha256':{entries[qid]['source_id']:sources[entries[qid]['source_id']]['sha256'] for qid in changed},
            'content_preserved':True,
            'next':'Generate a new review and redo affected checks; no visual pass is implied'}
