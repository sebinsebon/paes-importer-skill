"""Hash-bound native PDF observations. Suggestions never certify fidelity."""
from __future__ import annotations

from pathlib import Path
import re
import ctypes
import hashlib
import pypdfium2 as pdfium
from lab import bbox, digest, inside, json_digest, read, write

INDEX_VERSION = '1.0.0'
EXTRACTOR_VERSION = 'pdfium-native-v2'


def seal_index(index):
    annotate_repetitions(index['pages'])
    index['extractor_version']=EXTRACTOR_VERSION
    index['sha256']=json_digest({k:v for k,v in index.items() if k!='sha256'})
    return index


def annotate_repetitions(pages):
    """Describe repeated source observations; never classify them as disposable."""
    grouped={}
    for page in pages:
        page['repetition_hints']=[]
        for kind,items in (('text',page.get('lines',[])),('object',page.get('objects',[]))):
            for item in items:
                normalized=[round(value/(page['width'] if i%2==0 else page['height']),3)
                            for i,value in enumerate(item['bbox'])]
                signature=(re.sub(r'\s+',' ',item['text']).strip() if kind=='text' else
                           item.get('image_sha256') or item.get('path_sha256') or item['kind'])
                key=(page['source_id'],kind,json_digest([signature,normalized]))
                grouped.setdefault(key,[]).append((page,item))
    for (_,kind,signature),items in grouped.items():
        physical_pages=sorted({page['page'] for page,_ in items})
        if len(physical_pages)<2: continue
        for page,item in items:
            rect=item['bbox']; location='top' if rect[3]<=page['height']*.15 else 'bottom' if rect[1]>=page['height']*.85 else 'interior'
            page['repetition_hints'].append({'code':'REPEATED_SOURCE_ELEMENT','status':'pending','kind':kind,
                'signature_sha256':signature,'bbox':rect,'pages':physical_pages,'location':location,
                **({'text':item['text']} if kind=='text' else {'object_id':item['id']}),
                'action':'Observe whether this is essential content, header, logo or background; repetition alone does not justify omission.'})


def _glyph_typography(textpage, position):
    raw=pdfium.raw; flags=ctypes.c_int()
    length=raw.FPDFText_GetFontInfo(textpage,position,None,0,ctypes.byref(flags))
    font=None
    if 0<length<65536:
        buffer=ctypes.create_string_buffer(length)
        raw.FPDFText_GetFontInfo(textpage,position,buffer,length,ctypes.byref(flags))
        font=buffer.value.decode('utf-8',errors='replace')
    matrix=raw.FS_MATRIX(); x=ctypes.c_double(); y=ctypes.c_double()
    result={'font_name':font,'font_size':round(raw.FPDFText_GetFontSize(textpage,position),4),
            'font_flags':flags.value,'font_weight':raw.FPDFText_GetFontWeight(textpage,position),
            'char_angle':round(raw.FPDFText_GetCharAngle(textpage,position),6)}
    if raw.FPDFText_GetMatrix(textpage,position,ctypes.byref(matrix)):
        result['text_matrix']=[round(getattr(matrix,key),6) for key in ('a','b','c','d','e','f')]
    if raw.FPDFText_GetCharOrigin(textpage,position,ctypes.byref(x),ctypes.byref(y)):
        result['origin_pdf']=[round(x.value,4),round(y.value,4)]
    return result


def valid_index(index):
    return (index.get('extractor_version')==EXTRACTOR_VERSION and
            index.get('sha256')==json_digest({k:v for k,v in index.items() if k!='sha256'}))


def _overlaps(a, b):
    return min(a[2],b[2]) > max(a[0],b[0]) and min(a[3],b[3]) > max(a[1],b[1])


def _contains(a, b, tolerance=.25):
    return a[0]-tolerance <= b[0] and a[1]-tolerance <= b[1] and a[2]+tolerance >= b[2] and a[3]+tolerance >= b[3]


def _union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]


def native_page(page, source_id, source_sha256, page_no):
    """Read each glyph once, preserving PDFium text order and visible coordinates."""
    from pdf_assets import visible_bounds
    width,height=map(float,page.get_size()); rotation=page.get_rotation()
    glyphs=[]; textpage=page.get_textpage()
    try:
        for position in range(textpage.count_chars()):
            text=textpage.get_text_range(position,1)
            rect=visible_bounds(textpage.get_charbox(position),rotation,width,height)
            if text:
                glyphs.append({'position':position,'text':text,'bbox':[round(v,3) for v in rect],
                               **_glyph_typography(textpage,position)})
    finally:
        textpage.close()
    # PDF text order supplies spaces/newlines; geometry separates independently
    # positioned runs when the producer omitted line breaks.
    lines=[]; current=[]
    def flush():
        if current:
            visible=[g for g in current if g['text'].strip()]
            if visible:
                lines.append({'text':''.join(g['text'] for g in current).strip(),
                              'bbox':_union([g['bbox'] for g in visible]),
                              'positions':[g['position'] for g in current]})
            current.clear()
    for glyph in glyphs:
        if '\n' in glyph['text'] or '\r' in glyph['text']:
            flush(); continue
        if current and glyph['text'].strip():
            prior=next((g for g in reversed(current) if g['text'].strip()),None)
            if prior and not (min(prior['bbox'][3],glyph['bbox'][3]) > max(prior['bbox'][1],glyph['bbox'][1])):
                flush()
        current.append(glyph)
    flush()
    typography_hints=[]; previous=None
    for glyph in glyphs:
        if not glyph['text'].strip() or not glyph.get('origin_pdf'): continue
        if previous and previous.get('origin_pdf') and 0<glyph['font_size']<previous['font_size']*.9:
            dx=abs(glyph['origin_pdf'][0]-previous['origin_pdf'][0]); dy=glyph['origin_pdf'][1]-previous['origin_pdf'][1]
            if dx<=previous['font_size']*2 and previous['font_size']*.1<abs(dy)<previous['font_size']*1.5:
                typography_hints.append({'code':'NATIVE_SCRIPT_POSITION_CANDIDATE','status':'pending',
                    'position':glyph['position'],'text':glyph['text'],'bbox':glyph['bbox'],
                    'script':'superscript' if dy>0 else 'subscript','reference_position':previous['position']})
        if previous is None or glyph['font_size']>=previous['font_size']*.9: previous=glyph
    objects=[]
    for obj in page.get_objects(max_depth=8):
        kind={pdfium.raw.FPDF_PAGEOBJ_IMAGE:'PdfImage',pdfium.raw.FPDF_PAGEOBJ_PATH:'PdfPath'}.get(obj.type)
        if not kind: continue
        try:
            rect=visible_bounds(obj.get_bounds(),rotation,width,height)
            bbox(rect,width,height)
        except (ValueError,RuntimeError):
            continue
        observed={'id':'obj-'+json_digest([source_sha256,page_no,kind,rect])[:20], 'kind':kind,'bbox':rect}
        if kind=='PdfImage':
            observed['image_sha256']=hashlib.sha256(obj.get_data()).hexdigest()
        else:
            segments=[]
            for i in range(pdfium.raw.FPDFPath_CountSegments(obj)):
                segment=pdfium.raw.FPDFPath_GetPathSegment(obj,i); x=ctypes.c_float(); y=ctypes.c_float()
                if pdfium.raw.FPDFPathSegment_GetPoint(segment,ctypes.byref(x),ctypes.byref(y)):
                    segments.append([pdfium.raw.FPDFPathSegment_GetType(segment),round(x.value,4),round(y.value,4),
                                     bool(pdfium.raw.FPDFPathSegment_GetClose(segment))])
            observed['path_sha256']=json_digest(segments)
        objects.append(observed)
    return {'source_id':source_id,'source_sha256':source_sha256,'page':page_no,'width':width,'height':height,
            'rotation':rotation,'glyphs':glyphs,'lines':lines,'objects':objects,'typography_hints':typography_hints}


def ensure_source_index(run_dir, catalog=None):
    """Reuse an index only after checking current PDF bytes against frozen sources."""
    root=inside(run_dir); catalog=catalog or read(root/'catalog.json')
    from checkpoint_export import resolve_sources
    paths=resolve_sources(root); sources=catalog['sources']
    for source in sources:
        if digest(Path(paths[source['id']])) != source['sha256']:
            raise ValueError('PDF bytes changed after preparation: '+source['id'])
    target=root/'native-source-index.json'
    expected={s['id']:s['sha256'] for s in sources}
    if target.exists():
        index=read(target)
        if index.get('version') == INDEX_VERSION and index.get('source_hashes') == expected and valid_index(index):
            return index
    index={'version':INDEX_VERSION,'coordinate_system':'top_left_pdf_points','source_hashes':expected,'pages':[]}
    for source in sources:
        with pdfium.PdfDocument(str(paths[source['id']])) as pdf:
            for i in range(len(pdf)):
                page=pdf[i]
                try:index['pages'].append(native_page(page,source['id'],source['sha256'],i+1))
                finally:page.close()
    seal_index(index)
    write(target,index)
    return index


def query_source_index(index, source_id, pages=None, regions=None, max_chars=16000, layout='full'):
    """Bounded text + layout; regions select intersecting glyphs, never whole lines."""
    if source_id not in index['source_hashes']: raise ValueError('Unknown indexed source')
    if layout not in ('full','compact','text'): raise ValueError('layout must be full, compact or text')
    if max_chars is not None and (type(max_chars) is not int or max_chars < 1): raise ValueError('max_chars must be positive or null')
    selected=[]; chunks=[]; remaining=max_chars; truncated=False
    for page in index['pages']:
        if page['source_id'] != source_id or (pages is not None and page['page'] not in pages): continue
        boxes=[r['bbox'] for r in regions or [] if r['page']==page['page']]
        if regions is not None and not boxes: continue
        for box in boxes: bbox(box,page['width'],page['height'])
        if not boxes:
            glyphs=page['glyphs']
        else:
            # PDFium line breaks can have zero-area boxes. Keep native whitespace
            # between selected characters so region queries do not join words or
            # paragraphs merely because those separators have no visible bounds.
            matches=[i for i,g in enumerate(page['glyphs']) if g['text'].strip() and
                     any(_overlaps(g['bbox'],box) for box in boxes)]
            selected_positions=set(matches)
            glyphs=[g for i,g in enumerate(page['glyphs']) if i in selected_positions or
                    (matches and matches[0]<i<matches[-1] and not g['text'].strip())]
        text=''.join(g['text'] for g in glyphs)
        kept=[]; used=0
        for glyph in glyphs:
            if remaining is not None and used+len(glyph['text']) > remaining: break
            kept.append(glyph); used+=len(glyph['text'])
        truncated=truncated or used < len(text)
        if remaining is not None: remaining-=used
        bounded_lines=[]
        for line in page['lines']:
            included=[g for g in kept if g['position'] in line['positions']]
            if included:
                visible=[g['bbox'] for g in included if g['text'].strip()]
                bounded_lines.append({'text':''.join(g['text'] for g in included),'bbox':_union(visible or [g['bbox'] for g in included]),
                                      'positions':[g['position'] for g in included]})
        result_page={**{k:page[k] for k in ('source_id','page','width','height','rotation')},'text':text[:used]}
        if layout!='text':
            positions={g['position'] for g in kept}
            result_page.update(lines=bounded_lines,
                typography_hints=[h for h in page.get('typography_hints',[]) if h['position'] in positions],
                repetition_hints=[h for h in page.get('repetition_hints',[]) if not boxes or any(_overlaps(h['bbox'],b) for b in boxes)],
                objects=[obj for obj in page['objects'] if not boxes or any(_overlaps(obj['bbox'],b) for b in boxes)])
            if layout=='full':
                result_page['glyphs']=kept
            else:
                styles=[]; style_ids={}; runs=[]
                for line in result_page['lines']:
                    ranges=[]
                    for position in line.pop('positions'):
                        if ranges and ranges[-1][1]==position: ranges[-1][1]=position+1
                        else: ranges.append([position,position+1])
                    line['position_ranges']=ranges
                style_keys=('font_name','font_size','font_flags','font_weight','char_angle','text_matrix')
                for glyph in kept:
                    if not glyph['text'].strip(): continue
                    style={key:glyph[key] for key in style_keys if key in glyph}; signature=json_digest(style)
                    if signature not in style_ids:
                        style_ids[signature]='style-'+str(len(styles)+1)
                        styles.append({'id':style_ids[signature],**style})
                    style_id=style_ids[signature]; position=glyph['position']
                    if runs and runs[-1]['style_id']==style_id and runs[-1]['position_range'][1]==position:
                        runs[-1]['position_range'][1]=position+1
                        runs[-1]['bbox']=_union([runs[-1]['bbox'],glyph['bbox']])
                    else:
                        runs.append({'style_id':style_id,'position_range':[position,position+1],'bbox':glyph['bbox']})
                result_page.update(styles=styles,style_runs=runs,position_range_convention='start_inclusive_end_exclusive')
        selected.append(result_page)
        chunks.append(text[:used])
    return {'source_id':source_id,'source_sha256':index['source_hashes'][source_id], 'sha256':index['source_hashes'][source_id],
            'index_sha256':index.get('sha256'),'index_version':index['version'],
            'text':'\n'.join(chunks),'pages':selected,'truncated':truncated,'max_chars':max_chars,'layout':layout}


def figure_candidates(page, assignment):
    """Build from explicitly assigned objects/labels within a question field.

    Without explicit object IDs, disconnected native objects remain separate
    candidates. This deliberately leaves figure membership for visual review.
    """
    boxes=[r['bbox'] for r in assignment.get('regions',[]) if r['page']==page['page']]
    excluded=[r['bbox'] for r in assignment.get('exclude_regions',[]) if r['page']==page['page']]
    ids=assignment.get('object_ids',[])
    objects=[o for o in page.get('objects',[]) if (not ids or o['id'] in ids) and
             any(_contains(b,o['bbox']) for b in boxes) and not any(_overlaps(o['bbox'],b) for b in excluded)]
    groups=[]
    remaining=list(objects)
    while remaining:
        group=[remaining.pop(0)]; changed=True
        while changed:
            changed=False
            for obj in list(remaining):
                # Native bounds include stroke extents. Touching/overlapping
                # paths form one candidate without an arbitrary crop margin.
                if ids or any(_contains(member['bbox'],obj['bbox']) or
                              _contains(obj['bbox'],member['bbox']) or
                              _overlaps(member['bbox'],obj['bbox']) for member in group):
                    group.append(obj); remaining.remove(obj); changed=True
        groups.append(group)
    labels=[r['bbox'] for r in assignment.get('label_regions',[]) if r['page']==page['page']]
    result=[]
    for group in groups:
        geometry=[o['bbox'] for o in group]+labels
        inferred=[]; ambiguous=[]
        # Nearby short native labels are proposed only when their nearest
        # component is unique. They remain candidates for observation.
        if not labels:
            for line in page.get('lines',[]):
                text=line['text'].strip(); label=line['bbox']; height=label[3]-label[1]
                if not text or len(text)>24 or len(text.split())>3 or height<=0: continue
                if not any(_contains(b,label) for b in boxes) or any(_overlaps(label,b) for b in excluded): continue
                distances=[]
                for component in groups:
                    bounds=_union([o['bbox'] for o in component])
                    dx=max(bounds[0]-label[2],label[0]-bounds[2],0)
                    dy=max(bounds[1]-label[3],label[1]-bounds[3],0)
                    distances.append((dx*dx+dy*dy)**.5)
                current=groups.index(group); closest=min(distances)
                if distances[current]==closest and closest <= height*2:
                    if sum(abs(d-closest)<.25 for d in distances)==1:
                        inferred.append(line); geometry.append(label)
                    else: ambiguous.append(line)
        result.append({'source_id':page['source_id'],'page':page['page'],'field':assignment.get('field'),
                       'bbox':_union(geometry),'object_ids':[o['id'] for o in group],
                       'proposed_labels':inferred,'ambiguous_labels':ambiguous,
                       'status':'pending','code':'FIGURE_MEMBERSHIP_REQUIRES_REVIEW'})
    return result


def crop_diagnostics(page, box, assignment=None):
    """Detect cut vectors and contained foreign prose, independent of glyph edges."""
    assignment=assignment or {}; result=[]
    ids=assignment.get('object_ids',[])
    for obj in page.get('objects',[]):
        if obj['kind']=='PdfPath' and _overlaps(box,obj['bbox']) and not _contains(box,obj['bbox']):
            result.append({'code':'CROP_CLIPS_VECTOR','status':'pending','object_id':obj['id'],'bbox':obj['bbox']})
        elif ids and obj['id'] in ids and not _contains(box,obj['bbox']):
            result.append({'code':'CROP_EXCLUDES_ASSIGNED_OBJECT','status':'pending','object_id':obj['id'],'bbox':obj['bbox']})
    for region in assignment.get('label_regions',[]):
        if region['page']==page['page'] and not _contains(box,region['bbox']):
            result.append({'code':'CROP_EXCLUDES_ASSIGNED_LABEL','status':'pending','bbox':region['bbox']})
    excluded=[r['bbox'] for r in assignment.get('exclude_regions',[]) if r['page']==page['page']]
    for line in page.get('lines',[]):
        if _contains(box,line['bbox']) and any(_overlaps(line['bbox'],region) for region in excluded):
            result.append({'code':'CROP_CONTAINS_FOREIGN_TEXT','status':'pending','text':line['text'],'bbox':line['bbox']})
        elif (_contains(box,line['bbox']) and not any(r['page']==page['page'] and _contains(r['bbox'],line['bbox'])
               for r in assignment.get('label_regions',[])) and
              (len(line['text'].split())>3 or re.match(r'^\s*(?:\d+[.)]|[A-E][.)])\s',line['text']))):
            result.append({'code':'CROP_CONTAINS_PROSE_CANDIDATE','status':'pending',
                           'text':line['text'],'bbox':line['bbox'],
                           'action':'Determine whether this is a figure label or duplicated stem/option prose.'})
    if not ids:
        result.append({'code':'CROP_MEMBERSHIP_UNCONFIRMED','status':'pending','bbox':box})
    return result


def mapped_crop_assignment(request, selection, native_page):
    """Associate a crop only when the frozen question/field choice is unique."""
    page=request['page']; box=request['bbox']; source=request['source_id']
    questions=[q for q in selection.get('expected_questions',[]) if q['source_id']==source and
               (q['id']==request.get('question_id') if request.get('question_id') else
                any(r['page']==page and _contains(r['bbox'],box) for r in q.get('regions',[])))]
    if len(questions)!=1: return {}
    question=questions[0]
    items=[item for item in question.get('content_inventory',[]) if item['type']=='image' and
           (not request.get('field') or item['field']==request['field']) and
           any(r['page']==page and _overlaps(r['bbox'],box) for r in item['regions'])]
    fields={item['field'] for item in items}
    if len(fields)!=1: return {}
    field=next(iter(fields)); observed=[r for item in items for r in item['regions'] if r['page']==page]
    labels=[{'page':page,'bbox':line['bbox']} for line in native_page.get('lines',[])
            if any(_contains(r['bbox'],line['bbox']) for r in observed)]
    excluded=[r for name,regions in question.get('source_fields',{}).items() if name!=field for r in regions]
    excluded += [{'page':page,'bbox':line['bbox']} for line in native_page.get('lines',[])
                 if not any(_overlaps(r['bbox'],line['bbox']) for r in observed)]
    objects=[o['id'] for o in native_page.get('objects',[]) if any(_contains(r['bbox'],o['bbox']) for r in observed)]
    return {'question_id':question['id'],'field':field,'regions':question.get('source_fields',{}).get(field,observed),
            'object_ids':objects,'label_regions':labels,'exclude_regions':excluded}
