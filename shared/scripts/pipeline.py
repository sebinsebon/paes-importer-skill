"""Shared import controls. The host agent, not this script, performs inference."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lab import ROOT, UPSTREAM, artifact_path, digest, event, inside, json_digest, now, read, write, blocks_in, question_blocks, reserve_output
from package_io import inspect_package, pack, validate
from pdf_assets import apply_crops, prepare_catalog, source_record
from curriculum import pending_curriculum, prepare_ledger, curriculum_hash
from checkpoints import recover as recover_ingest, commit as commit_ingest, json_bytes
from evidence import validate_geometry, validate_mapping



def verify_resume(run_dir):
    from checkpoints import state_lock
    with state_lock(inside(run_dir)):
        return _verify_resume(run_dir)

def _verify_resume(run_dir):
    folder = inside(run_dir)
    recover_ingest(folder)
    run = read(folder/'run.json')
    if run.get('release_sha256'):
        if digest(ROOT/'release.json') != run['release_sha256']:
            raise ValueError('Frozen laboratory release changed')
        verify_release()
    if run['config_hash'] != json_digest(run['config']):
        raise ValueError('Configuration changed since preparation')
    selection = read(folder/'selection.json')
    if run.get('selection_hash') and json_digest(selection) != run['selection_hash']:
        raise ValueError('Frozen selection changed')
    from checkpoint_export import resolve_sources
    paths = resolve_sources(folder)
    for source in read(folder/'sources.json'):
        if digest(paths[source['id']]) != source['sha256']:
            raise ValueError('Source changed since preparation')
    validate_run_contract(folder/'candidate.json')
    return {'run_dir':str(folder),'status':run['status'],'sources_unchanged':True}

def verify_release():
    path=ROOT/'release.json'
    if not path.exists():
        raise ValueError('Missing local release.json for this Skill')
    for record in read(path)['files']:
        if digest(artifact_path(ROOT,record['path'])) != record['sha256']:
            raise ValueError('Frozen laboratory file changed: '+record['path'])
    return digest(path)

def ingest(run_dir, response_path, raw_response_bytes=None, explanation_provenance=None):
    from checkpoints import state_lock
    with state_lock(inside(run_dir)):
        return _ingest(run_dir,response_path,raw_response_bytes,explanation_provenance)

def _ingest(run_dir, response_path, raw_response_bytes=None, explanation_provenance=None):
    folder=inside(run_dir)
    _verify_resume(folder)
    if (folder/'run.json').exists() and (read(folder/'run.json')['status'] != 'awaiting_ai' or (folder/'final.json').exists()):
        raise ValueError('Preserve finalized candidates; use a new run')
    response_bytes=Path(response_path).read_bytes()
    response=json.loads(response_bytes.decode('utf-8-sig'))
    original_bytes=(folder/'candidate.json').read_bytes()
    candidate=json.loads(original_bytes.decode('utf-8-sig'))
    if response.get('run_id') != candidate['run']['id']:
        raise ValueError('AI response belongs to a different run')
    questions=response.get('questions', [])
    if not isinstance(questions,list) or not questions or any(not isinstance(q,dict) or not isinstance(q.get('id'),str) for q in questions) or len({q['id'] for q in questions}) != len(questions):
        raise ValueError('AI batch must have unique questions')
    existing={q['id']:q for q in candidate['questions']}
    if any(q['id'] not in existing for q in questions):
        raise ValueError('AI question outside frozen selection')
    provenance=response.get('curriculum_provenance',{})
    if not isinstance(provenance,dict) or not set(provenance).issubset({q['id'] for q in questions}):
        raise ValueError('Curriculum provenance must refer only to batch questions')
    # Freeze operation inputs once. Proposed questions cannot alter these shared
    # manifests, and full validation below checks their global invariants first.
    catalog = read(folder/'catalog.json') if (folder/'catalog.json').exists() else None
    selection = read(folder/'selection.json') if (folder/'selection.json').exists() else None
    validation_context = {}
    asset_digests = {}
    def operation_content_hash(question, current_candidate=None, root=None):
        return content_hash(question,current_candidate,root,digest_cache=asset_digests)
    def operation_solution_hash(question, current_candidate=None, root=None):
        return solution_hash(question,current_candidate,root,digest_cache=asset_digests)
    validate(candidate,folder,validation_context=validation_context)
    if catalog is not None: validate_geometry(candidate,catalog)
    if selection is not None and candidate['schema_version']=='0.2.0': validate_mapping(candidate,selection)
    frozen_expected = {q['id']:q for q in candidate['exam']['expected_questions']}
    prior_ledger=read(folder/'curriculum-ledger.json') if (folder/'curriculum-ledger.json').exists() else {}
    ledger=copy.deepcopy(prior_ledger)
    accepted=[]; rejected=[]; unchanged=[]
    for proposed in questions:
        q=copy.deepcopy(proposed)
        try:
            if q['fidelity']['status']=='reviewed' or q['answer']['status']=='verified' or q['explanation']['status']=='verified':
                raise ValueError('Ingest provisional content; record independent reviews separately')
            if q['fidelity']['status'] not in ('pending','rejected') or q['answer']['status'] not in ('missing','provisional') or q['explanation']['status'] not in ('missing','provisional'):
                raise ValueError('Invalid provisional review status')
            prior=existing[q['id']]
            same_content=operation_content_hash(q,candidate,folder)==operation_content_hash(prior,candidate,folder)
            same_solution=operation_solution_hash(q,candidate,folder)==operation_solution_hash(prior,candidate,folder)
            if same_content:
                q['fidelity']=copy.deepcopy(prior['fidelity'])
                if same_solution:
                    q['answer']=copy.deepcopy(prior['answer'])
                    q['explanation']=copy.deepcopy(prior['explanation'])
            else:
                q['fidelity']={'status':'pending','review_ref':None}
            if not same_solution:
                q['answer']['status']='provisional' if q['answer']['label'] is not None else 'missing'
                q['explanation']['status']='provisional' if q['explanation']['blocks'] else 'missing'
            used_assets={block['asset_id'] for block in question_blocks(q) if block['type']=='image'}
            projection={**candidate, 'questions':[q],
                'exam':{**candidate['exam'],'expected_questions':[frozen_expected[q['id']]]},
                'assets':[asset for asset in candidate['assets'] if asset['id'] in used_assets], 'evidence':[]}
            validate(projection,folder,validation_context=validation_context)
            if catalog is not None: validate_geometry(projection,catalog)
            if selection is not None and candidate['schema_version'] == '0.2.0': validate_mapping(projection,selection)
            # Exact retries preserve the original rationale and create no archives.
            if q==prior and (candidate['schema_version']!='0.2.0' or ledger.get(q['id'],{}).get('curriculum_sha256')==curriculum_hash(q,operation_content_hash(q,projection,folder))):
                unchanged.append(q['id']); continue
            new_ledger=ledger
            if candidate['schema_version']=='0.2.0':
                subset={**response,'questions':[q], 'curriculum_provenance':{qid:r for qid,r in response.get('curriculum_provenance',{}).items() if qid==q['id']}}
                new_ledger={**ledger, **prepare_ledger(projection,subset,operation_content_hash,folder,ledger)}
            candidate={**candidate, 'questions':[q if old['id']==q['id'] else old for old in candidate['questions']]}
            ledger=new_ledger
            existing[q['id']]=q
            accepted.append(q['id'])
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'question_id':proposed['id'],'reason':str(exc)})
    if rejected and not accepted and not unchanged:
        error = ValueError('No questions accepted: '+ '; '.join(r['question_id']+': '+r['reason'] for r in rejected))
        error.rejected = rejected
        raise error
    result={'accepted':accepted,'rejected':rejected,'unchanged':unchanged,'questions_updated':len(accepted),'archive':None}
    if not accepted: return result
    # Recheck the complete candidate with fresh resource bytes. No per-question
    # projection or operation cache replaces cross-question/final validation.
    validate(candidate,folder)
    if catalog is not None: validate_geometry(candidate,catalog)
    if selection is not None and candidate['schema_version']=='0.2.0': validate_mapping(candidate,selection)
    if candidate['schema_version']=='0.2.0':
        accepted_response={**response,'questions':[existing[qid] for qid in accepted],
            'curriculum_provenance':{qid:value for qid,value in provenance.items() if qid in accepted}}
        ledger=prepare_ledger(candidate,accepted_response,operation_content_hash,folder,ledger)
    stamp=str(time.time_ns())
    candidate['run']['ingest_transaction'] = stamp
    archive='reports/ai/'+stamp+'.json'
    checkpoint=read(folder/'ingest-checkpoints.json') if (folder/'ingest-checkpoints.json').exists() else {}
    for qid in accepted:
        q=existing[qid]
        checkpoint[qid]={'content_sha256':operation_content_hash(q,candidate,folder),'solution_sha256':operation_solution_hash(q,candidate,folder),
                         'curriculum_sha256':ledger.get(qid,{}).get('curriculum_sha256'),'archive':archive,'status':'accepted'}
    updates={'candidate.json':json_bytes(candidate),'ingest-checkpoints.json':json_bytes(checkpoint),
             'versions/candidate-before-'+stamp+'.json':original_bytes,archive:response_bytes}
    if candidate['schema_version']=='0.2.0':updates['curriculum-ledger.json']=json_bytes(ledger)
    if raw_response_bytes is not None:
        updates['raw/'+stamp+'.json'] = raw_response_bytes
    if explanation_provenance is not None:
        provenance_path = folder/'explanation-provenance.json'
        saved = read(provenance_path) if provenance_path.exists() else {}
        for qid in accepted:
            saved[qid] = explanation_provenance.get(qid, {'origin':'none'})
        updates['explanation-provenance.json'] = json_bytes(saved)
    events=folder/'events.jsonl'
    old_events=events.read_bytes() if events.exists() else b''
    entry={'timestamp':now(),'stage':'ai_batch_ingested','kind':'measured','notes':str(len(accepted))+' questions; '+archive}
    updates['events.jsonl']=old_events+(json.dumps(entry,ensure_ascii=False)+'\n').encode('utf-8')
    commit_ingest(folder,updates,original_bytes)
    result['archive']=str(folder/archive)
    return result


def empty_question(expected):
    return {**{k: expected[k] for k in ('id', 'source_id', 'number')}, 'regions': [],
            'stem': [{'type': 'unresolved', 'reason': 'Pendiente de lectura y reconstrucción por el CLI'}],
            'options': [], 'answer': {'label': None, 'status': 'missing', 'origin': 'none', 'source_ref': None},
            'explanation': {'blocks': [], 'status': 'missing'},
            'fidelity': {'status': 'pending', 'review_ref': None}, 'curriculum': pending_curriculum(), 'issues': ['NOT_PROCESSED', 'CURRICULUM_PENDING']}


def initial_candidate(run, suite, sources):
    return {'format': 'paessed-benchmark', 'schema_version': '0.2.0', 'pipeline': run['pipeline'],
            'run': {'id': run['id'], 'cli': run['cli'], 'model': run['model'], 'created_at': now(),
                    'variant': run['variant'], 'protocol_version': run['protocol_version'], 'eligible': run['eligible'],
                    'suite_sha256': run['suite_sha256'], 'config_hash': run['config_hash'],
                    'input_mode': 'local_extraction' if run['pipeline'] == 'hybrid' else 'unavailable',
                    'all_pages_read': False},
            'exam': {'id': suite['id'], 'title': suite['title'], 'scope': suite['scope'],
                     'expected_questions': [{k: q[k] for k in ('id', 'source_id', 'number')} for q in suite['expected_questions']]},
            'sources': sources, 'questions': [empty_question(q) for q in suite['expected_questions']],
            'assets': [], 'evidence': []}


def bound_assets(blocks, candidate, root=None, *, digest_cache=None):
    ids=sorted({b['asset_id'] for b in blocks_in(blocks) if b['type']=='image'})
    if ids and candidate is None:
        raise ValueError('Hashing image content requires its candidate asset manifest')
    assets={a['id']:a for a in (candidate or {}).get('assets',[])}
    records=[]
    for aid in ids:
        record=copy.deepcopy(assets[aid])
        if root is not None:
            path = artifact_path(root,record['path'],'assets')
            cache_key = str(path)
            if digest_cache is None:
                actual = digest(path)
            else:
                if cache_key not in digest_cache: digest_cache[cache_key] = digest(path)
                actual = digest_cache[cache_key]
            if actual != record['sha256']:
                raise ValueError('Asset bytes differ from declared hash')
        records.append(record)
    return records


def content_hash(q, candidate=None, root=None, *, digest_cache=None):
    payload={k:q[k] for k in ('id','source_id','number','regions','stem','options')}
    payload['assets']=bound_assets(q['stem']+[b for o in q['options'] for b in o['blocks']],candidate,root,digest_cache=digest_cache)
    payload['source']=next((s for s in (candidate or {}).get('sources',[]) if s['id']==q['source_id']),None)
    return json_digest(payload)


def solution_hash(q, candidate=None, root=None, *, digest_cache=None):
    return json_digest({'content':content_hash(q,candidate,root,digest_cache=digest_cache),'label':q['answer']['label'],'origin':q['answer']['origin'],
                        'explanation':q['explanation']['blocks'],'assets':bound_assets(q['explanation']['blocks'],candidate,root,digest_cache=digest_cache)})


def record_review(run_dir, path):
    from checkpoints import state_lock
    with state_lock(inside(run_dir)):
        recover_ingest(inside(run_dir))
        return _record_review(inside(run_dir), path)


def _record_review(run_dir, path):
    response_bytes = Path(path).read_bytes()
    response = json.loads(response_bytes.decode('utf-8-sig'))
    original_bytes=(run_dir/'candidate.json').read_bytes()
    candidate=json.loads(original_bytes.decode('utf-8-sig'))
    by_id = {q['id']: q for q in candidate['questions']}
    kind = response['kind']
    if kind not in ('fidelity', 'answer') or response.get('independent') is not True:
        raise ValueError('Review must declare kind and independent context')
    if not all(response.get('agent', {}).get(k) for k in ('cli', 'model', 'session_id')):
        raise ValueError('Review needs CLI/model/session_id provenance')
    if (run_dir/'run.json').exists():
        run=read(run_dir/'run.json')
        if response.get('run_id')!=run['id']:
            raise ValueError('Review belongs to a different run')
        if response['agent']['session_id']==run.get('session_id'):
            raise ValueError('Review must use an independent session')
    if not response.get('checks') or len({c['question_id'] for c in response['checks']}) != len(response['checks']):
        raise ValueError('Review checks must be nonempty and unique')
    for check in response['checks']:
        q = by_id[check['question_id']]
        if check['content_sha256'] != content_hash(q,candidate,run_dir):
            raise ValueError('Review belongs to a different question version')
        if kind == 'answer' and check.get('solution_sha256') != solution_hash(q,candidate,run_dir):
            raise ValueError('Review belongs to a different answer/explanation version')
        if check['verdict'] not in ('pass', 'fail', 'abstain') or not check.get('notes') or not check.get('evidence_ids'):
            raise ValueError('Every check needs verdict, notes and localized evidence IDs')
        resource_ids = {r['id'] for r in candidate['assets'] + candidate['evidence']}
        if not set(check['evidence_ids']).issubset(resource_ids):
            raise ValueError('Review references unknown evidence')
    ref = hashlib.sha256(response_bytes).hexdigest()
    destination = inside(run_dir / 'reports/reviews' / f'{ref}.json')
    for check in response['checks']:
        q = by_id[check['question_id']]
        if kind == 'fidelity':
            q['fidelity'] = {'status': 'reviewed' if check['verdict'] == 'pass' else ('rejected' if check['verdict'] == 'fail' else 'pending'),
                             'review_ref': 'sha256:' + ref}
            if check['verdict'] != 'pass' and q['answer']['status'] == 'verified':
                q['answer']['status'] = 'provisional'
                q['explanation']['status'] = 'provisional' if q['explanation']['blocks'] else 'missing'
        elif check['verdict'] == 'pass':
            if q['fidelity']['status'] != 'reviewed' or q['answer']['label'] is None or not q['explanation']['blocks']:
                raise ValueError('Answer verification needs reviewed fidelity, a label and explanation')
            q['answer'].update(status='verified', source_ref='sha256:' + ref)
            q['explanation']['status'] = 'verified'
        else:
            q['answer']['status'] = 'provisional' if q['answer']['label'] else 'missing'
            q['explanation']['status'] = 'provisional' if q['explanation']['blocks'] else 'missing'
            q['issues'].append('ANSWER_REVIEW_' + check['verdict'].upper())
    validate(candidate, run_dir)
    version = run_dir / 'versions' / f'candidate-before-{time.time_ns()}.json'
    # Candidate replacement is the commit point. Preflight completes before
    # archival. A failed replace removes the newly created response archive.
    if (run_dir/'candidate.json').read_bytes()!=original_bytes:
        raise ValueError('Candidate changed concurrently; regenerate the review')
    staged=inside(run_dir/f'candidate-review-{time.time_ns()}.tmp')
    write(staged,candidate)
    new_archive=not destination.exists()
    events_path=run_dir/'events.jsonl'
    old_events=events_path.read_bytes() if events_path.exists() else None
    try:
        destination.parent.mkdir(parents=True,exist_ok=True)
        if new_archive:
            destination.write_bytes(response_bytes)
        elif digest(destination)!=ref:
            raise ValueError('Existing review archive differs')
        write(version,json.loads(original_bytes))
        event(run_dir, 'review_recorded', notes=f'{kind}: {ref}; independence is declared by CLI, not authenticated by script')
        os.replace(staged,run_dir/'candidate.json')
    except Exception:
        if new_archive:
            destination.unlink(missing_ok=True)
        version.unlink(missing_ok=True)
        if old_events is None:
            events_path.unlink(missing_ok=True)
        else:
            events_path.write_bytes(old_events)
        raise
    finally:
        staged.unlink(missing_ok=True)
    return {'review_ref': 'sha256:' + ref, 'questions': len(response['checks'])}


def check_review_bindings(candidate, root):
    for q in candidate['questions']:
        for kind, status, ref in [('fidelity', q['fidelity']['status'], q['fidelity']['review_ref']),
                                   ('answer', q['answer']['status'], q['answer']['source_ref'])]:
            if status not in ('reviewed', 'verified'):
                continue
            if not ref or not re.fullmatch(r'sha256:[a-f0-9]{64}', ref):
                raise ValueError(f'{q["id"]}: confirmed status needs an archived review')
            path = artifact_path(root, f'reports/reviews/{ref[7:]}.json')
            if digest(path) != ref[7:]:
                raise ValueError('Review hash mismatch')
            review = read(path)
            if (Path(root)/'run.json').exists():
                run=read(Path(root)/'run.json')
                if review.get('run_id')!=run['id'] or review.get('agent',{}).get('session_id')==run.get('session_id'):
                    raise ValueError('Review run/session provenance mismatch')
            check = next((c for c in review.get('checks', []) if c['question_id'] == q['id']), None)
            if review.get('kind') != kind or not review.get('independent') or not check or check['verdict'] != 'pass' or check['content_sha256'] != content_hash(q,candidate,root):
                raise ValueError(f'{q["id"]}: stale or failed review')
            if kind == 'answer' and check.get('solution_sha256') != solution_hash(q,candidate,root):
                raise ValueError(f'{q["id"]}: stale answer review')


def sync_assets(run_dir):
    from checkpoints import state_lock
    with state_lock(inside(run_dir)):
        recover_ingest(inside(run_dir))
        return _sync_assets(run_dir)

def _sync_assets(run_dir):
    run_dir = inside(run_dir)
    candidate = read(run_dir / 'candidate.json')
    catalog = read(run_dir / 'catalog.json')
    candidate['assets'] = catalog['assets']
    candidate['evidence'] = catalog['evidence']
    write(run_dir / 'candidate.json', candidate)
    return {'assets': len(candidate['assets']), 'evidence': len(candidate['evidence'])}


def validate_run_contract(file):
    """Freeze expected coverage and provenance outside the model-editable JSON."""
    path = Path(file)
    candidate = read(path)
    if not (path.parent / 'run.json').exists():
        if candidate['pipeline'] != 'demo':
            raise ValueError('A benchmark final must stay with its run.json/selection.json/sources.json')
        return
    run = read(path.parent / 'run.json')
    selection = read(path.parent / 'selection.json')
    expected = [{k: q[k] for k in ('id', 'source_id', 'number')} for q in selection['expected_questions']]
    if candidate['exam']['expected_questions'] != expected or candidate['exam']['scope'] != selection['scope']:
        raise ValueError('Candidate changed frozen question coverage/scope')
    if candidate['sources'] != read(path.parent / 'sources.json'):
        raise ValueError('Candidate changed frozen source provenance')
    frozen = ['id','model','cli','suite_sha256','config_hash']
    if run.get('protocol_version') == '0.3.0':
        frozen += ['variant','protocol_version','eligible']
    if candidate['pipeline'] != run['pipeline'] or any(candidate['run'].get(k) != run[k] for k in frozen):
        raise ValueError('Candidate changed frozen run identity/configuration')
