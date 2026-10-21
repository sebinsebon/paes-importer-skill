"""PDFium rendering and resource catalog. No question reconstruction or OCR."""
from __future__ import annotations

import re
import os
import shutil
import uuid
from pathlib import Path

import pypdfium2 as pdfium

from lab import artifact_path, bbox, digest, inside, json_digest, read, write


def render_crop(page, output, box=None, scale=1.5):
    output = inside(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = map(float, page.get_size())
    region = bbox(box if box is not None else [0, 0, width, height], width, height)
    x0, y0, x1, y1 = region
    # PDFium crop is (left,bottom,right,top) amounts, NOT a bbox.
    bitmap = page.render(scale=scale, crop=(x0, height-y1, width-x1, y0))
    try:
        bitmap.to_pil().save(output, format='PNG')
    finally:
        bitmap.close()
    return region


def visible_bounds(native, rotation, width, height):
    left, bottom, right, top = map(float, native)
    def point(x, y):
        if rotation == 90:
            return y, x
        if rotation == 180:
            return width-x, y
        if rotation == 270:
            return width-y, height-x
        return x, height-y
    corners = [point(x, y) for x in (left, right) for y in (bottom, top)]
    return [max(0., min(p[0] for p in corners)), max(0., min(p[1] for p in corners)),
            min(width, max(p[0] for p in corners)), min(height, max(p[1] for p in corners))]


def source_record(source_id, path, role='exam'):
    with pdfium.PdfDocument(str(path)) as pdf:
        return {'id': source_id, 'name': Path(path).name, 'sha256': digest(path),
                'page_count': len(pdf), 'role': role}


def crop_text_warnings(page, box):
    """Inspect actual glyph geometry, independently of the agent's inventory.

    Fully excluded nearby labels are warnings, not automatic associations.
    Complex vector figures still require source/result visual comparison.
    """
    width, height = map(float, page.get_size())
    x0, y0, x1, y1 = box
    clipped, nearby = [], []
    text = page.get_textpage()
    try:
        for index in range(text.count_chars()):
            character = text.get_text_range(index, 1)
            if not character.strip():
                continue
            rect = visible_bounds(text.get_charbox(index), page.get_rotation(), width, height)
            left, top, right, bottom = rect
            if right <= left or bottom <= top:
                continue
            intersects = min(x1, right) - max(x0, left) > .25 and min(y1, bottom) - max(y0, top) > .25
            contained = x0-.25 <= left and y0-.25 <= top and right <= x1+.25 and bottom <= y1+.25
            item = {'text': character, 'bbox': [round(v, 3) for v in rect]}
            if intersects and not contained:
                clipped.append(item)
            elif not contained and left < x1+12 and right > x0-12 and top < y1+12 and bottom > y0-12:
                nearby.append(item)
    finally:
        text.close()
    return {'clipped_text': clipped, 'nearby_text': nearby}


def resource(source, page_no, box, path, root, resource_id):
    return {'id': resource_id, 'path': Path(path).relative_to(root).as_posix(),
            'sha256': digest(path), 'mime': 'image/png', 'source_id': source,
            'page': page_no, 'bbox': [round(x, 3) for x in box]}


def prepare_catalog(sources, paths, output, scale=1.5, materialize_images=True):
    output = inside(output)
    catalog = {'coordinate_system': 'top_left_pdf_points', 'scale': scale,
               'sources': sources, 'pages': [], 'assets': [], 'asset_candidates': [], 'evidence': [], 'warnings': []}
    from source_index import native_page, INDEX_VERSION, seal_index
    native_index={'version':INDEX_VERSION,'coordinate_system':'top_left_pdf_points',
                  'source_hashes':{s['id']:s['sha256'] for s in sources},'pages':[]}
    for source in sources:
        with pdfium.PdfDocument(str(paths[source['id']])) as pdf:
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    width, height = map(float, page.get_size())
                    native = native_page(page, source['id'], source['sha256'], index+1)
                    native_index['pages'].append(native)
                    prefix = f'{source["id"]}-p{index+1:04d}'
                    full_path = output / f'evidence/pages/{prefix}.png'
                    box = render_crop(page, full_path, scale=scale)
                    catalog['evidence'].append(resource(source['id'], index+1, box, full_path, output, prefix))
                    objects = native['objects']
                    for obj in objects:
                        kind,rect=obj['kind'],obj['bbox']
                        # Keep paths as geometry; vector compositions need an explicit crop request.
                        if kind != 'PdfImage' or rect[2]-rect[0] < 4 or rect[3]-rect[1] < 4:
                            continue
                        asset_id = 'img-' + json_digest([source['sha256'], index+1, rect])[:20]
                        if any(a['id'] == asset_id for a in catalog['asset_candidates']):
                            continue
                        catalog['asset_candidates'].append({'id':asset_id,'source_id':source['id'],
                            'source_sha256':source['sha256'],'page':index+1,'bbox':rect,'object_ids':[obj['id']],
                            'status':'pending','kind':kind})
                        if not materialize_images:
                            continue
                        target = output / f'assets/{asset_id}.png'
                        render_crop(page, target, rect, scale=2)
                        catalog['assets'].append(resource(source['id'], index+1, rect, target, output, asset_id))
                    catalog['pages'].append({'source_id': source['id'], 'page': index+1,
                                             'width': width, 'height': height, 'rotation': page.get_rotation(),
                                             'evidence_id': prefix, 'objects': objects, 'lines':native['lines']})
                finally:
                    page.close()
    seal_index(native_index)
    for page,native in zip(catalog['pages'],native_index['pages']):
        page['repetition_hints']=native['repetition_hints']
        page['typography_hints']=native['typography_hints']
    write(output / 'catalog.json', catalog)
    write(output / 'native-source-index.json', native_index)
    return catalog


def materialize_assets(run_dir, ids):
    """Render only selected native image candidates; preserve frozen provenance."""
    root=inside(run_dir); catalog=read(root/'catalog.json')
    if not isinstance(ids,list) or not ids or any(not isinstance(value,str) for value in ids):
        raise ValueError('Select nonempty asset candidate IDs')
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate asset candidate ID')
    candidates={candidate['id']:candidate for candidate in catalog.get('asset_candidates',[])}
    sources={source['id']:source for source in catalog['sources']}
    requests=[]
    for candidate_id in ids:
        if candidate_id not in candidates: raise ValueError('Unknown asset candidate: '+candidate_id)
        candidate=candidates[candidate_id]; source=sources.get(candidate['source_id'])
        if not source or candidate.get('source_sha256')!=source['sha256']:
            raise ValueError('Asset candidate source hash mismatch')
        expected='img-'+json_digest([source['sha256'],candidate['page'],candidate['bbox']])[:20]
        if candidate_id!=expected: raise ValueError('Asset candidate geometry changed')
        requests.append({'id':candidate_id,'source_id':candidate['source_id'],'page':candidate['page'],
                         'bbox':candidate['bbox'],'role':'asset'})
    apply_crops(root,requests)
    current=read(root/'catalog.json')
    return [item for item in current['assets'] if item['id'] in ids]


def apply_crops(run_dir, requests):
    run_dir = inside(run_dir)
    catalog = read(run_dir / 'catalog.json')
    from checkpoint_export import resolve_sources
    paths = resolve_sources(run_dir)
    sources = {s['id']: s for s in catalog['sources']}
    ids = {r['id']: r for r in catalog['assets'] + catalog['evidence']}
    additions = []
    pending=[]
    warnings=[]
    seen=set()
    for req in requests:
        rid = req['id']
        if rid in seen:
            raise ValueError('Duplicate crop request ID')
        seen.add(rid)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid):
            raise ValueError(f'Invalid crop ID: {rid}')
        if req.get('role', 'asset') not in ('asset', 'evidence'):
            raise ValueError('Crop role must be asset or evidence')
        source_id = req['source_id']
        if source_id not in sources:
            raise ValueError('Unknown crop source')
        source_path = Path(paths[source_id])
        if digest(source_path) != sources[source_id]['sha256']:
            raise ValueError('PDF bytes changed after preparation')
        page_no = req['page']
        if isinstance(page_no, bool) or not isinstance(page_no, int) or not 1 <= page_no <= sources[source_id]['page_count']:
            raise ValueError('Invalid crop page')
        box = bbox(req['bbox'])
        if rid in ids:
            old = ids[rid]
            if old['source_id'] == source_id and old['page'] == page_no and old['bbox'] == [round(value,3) for value in box]:
                continue
            raise ValueError(f'Crop ID already used with different geometry: {rid}')
        folder = 'assets' if req.get('role', 'asset') == 'asset' else 'evidence'
        output = run_dir / f'{folder}/crops/{rid}.png'
        inside(output)
        if output.exists():
            raise ValueError('Unregistered crop output already exists; preserve it and use a new ID')
        with pdfium.PdfDocument(str(source_path)) as pdf:
            page = pdf[page_no-1]
            try:
                width,height=page.get_size()
                bbox(box,width,height)
                if folder == 'assets':
                    diagnostic = crop_text_warnings(page, box)
                    if diagnostic['clipped_text']:
                        raise ValueError(rid + ': CROP_CLIPS_TEXT ' + str(diagnostic['clipped_text'][:12]) +
                                         '; inspect the source and include complete labels using a new crop ID')
                    if diagnostic['nearby_text']:
                        warnings.append({'asset_id':rid, 'source_id':source_id, 'page':page_no,
                                         'code':'CROP_NEAR_TEXT', 'details':diagnostic['nearby_text'],
                                         'action':'Inspect source context: nearby labels may belong to the figure.'})
                    from source_index import crop_diagnostics, mapped_crop_assignment
                    native=next((p for p in catalog['pages'] if p['source_id']==source_id and p['page']==page_no),{})
                    assignment=req.get('assignment')
                    if assignment is None and (run_dir/'selection.json').exists():
                        assignment=mapped_crop_assignment(req,read(run_dir/'selection.json'),native)
                    for issue in crop_diagnostics(native,box,assignment):
                        warnings.append({'asset_id':rid,'source_id':source_id,'page':page_no,**issue})
            finally:
                page.close()
        pending.append((rid,folder,source_id,source_path,page_no,box,output))
    staging=inside(run_dir/f'.crops-{uuid.uuid4().hex}')
    staging.mkdir()
    published=[]
    try:
        for rid,folder,source_id,source_path,page_no,box,output in pending:
            temporary=staging/f'{rid}.png'
            with pdfium.PdfDocument(str(source_path)) as pdf:
                page=pdf[page_no-1]
                try:render_crop(page,temporary,box,scale=2)
                finally:page.close()
            record=resource(source_id,page_no,box,temporary,staging,rid)
            record['path']=output.relative_to(run_dir).as_posix()
            catalog[folder].append(record);additions.append(record)
        for rid,folder,source_id,source_path,page_no,box,output in pending:
            output.parent.mkdir(parents=True,exist_ok=True)
            os.replace(staging/f'{rid}.png',output);published.append(output)
        # catalog is the commit point; original request JSON lives in the run.
        catalog.setdefault('warnings', []).extend(warnings)
        write(run_dir/'crop-history'/f'{uuid.uuid4().hex}.json',{'requests':requests,'additions':additions,'warnings':warnings})
        write(run_dir / 'catalog.json', catalog)
    except Exception:
        for path in published:path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging)
    return additions
