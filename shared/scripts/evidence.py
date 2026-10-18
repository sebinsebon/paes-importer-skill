"""Localized evidence coverage checks. Coverage is not proof of comprehension."""
import re
from lab import artifact_path, bbox, digest

TOLERANCE = .01  # PDF points, never a percentage of observed content.


def field_paths(question):
    from package_io import located_blocks
    return {'stem': ['stem'], 'options': ['options/' + o['label'] for o in question['options']] or ['options'],
            'assets_math': [p for p, b in located_blocks(question) if b['type'] in ('math', 'table', 'image') and not p.startswith('explanation.')] or ['stem'],
            'answer': ['answer'], 'explanation': ['explanation'], 'consistency': ['stem', 'options', 'answer', 'explanation']}


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def contains(outer, inner, tolerance=TOLERANCE):
    return all(outer[i] <= inner[i] + tolerance for i in (0, 1)) and all(outer[i] >= inner[i] - tolerance for i in (2, 3))


def rectangle_covered(target, boxes, tolerance=TOLERANCE):
    """Cover using a rectangle UNION, preserving holes and disjoint slices."""
    left, top, right, bottom = target
    boxes = [box for box in boxes if overlaps(target, box)]
    if not boxes:
        return False
    boundaries = sorted({left, right, *[max(left, min(right, box[i])) for box in boxes for i in (0, 2)]})
    for x0, x1 in zip(boundaries, boundaries[1:]):
        if x1 - x0 <= tolerance:
            continue
        intervals = sorted((max(top, box[1]), min(bottom, box[3])) for box in boxes
                           if box[0] <= x0 + tolerance and box[2] >= x1 - tolerance)
        reached = top
        for y0, y1 in intervals:
            if y0 > reached + tolerance:
                return False
            reached = max(reached, y1)
        if reached < bottom - tolerance:
            return False
    return True


def cover_regions(required, available, tolerance=TOLERANCE):
    for region in required:
        matches = [r for r in available if r['page'] == region['page']]
        if not matches:
            return False
        if region.get('bbox') is not None and not rectangle_covered(region['bbox'],
                [r['bbox'] for r in matches if r.get('bbox') is not None], tolerance):
            return False
    return True


def validate_source_fields(record, catalog):
    expected = {'stem', *['options/' + label for label in record.get('option_labels', [])]}
    fields = record.get('source_fields')
    if not isinstance(fields, dict) or set(fields) != expected:
        raise ValueError('source_fields must contain stem and every observed options/LABEL')
    pages = {(p['source_id'], p['page']): p for p in catalog['pages']}
    mapped = record.get('regions', [])
    if not mapped:
        raise ValueError('source_fields require frozen question regions')
    for field, regions in fields.items():
        if not isinstance(regions, list) or not regions:
            raise ValueError('source_fields need nonempty essential regions: ' + field)
        for region in regions:
            if not isinstance(region, dict) or type(region.get('page')) is not int:
                raise ValueError('Invalid source_fields physical page')
            page = pages.get((record['source_id'], region['page']))
            if page is None:
                raise ValueError('source_fields page absent from source catalog')
            bbox(region.get('bbox'), page['width'], page['height'])
        if not cover_regions(regions, mapped):
            raise ValueError('source_fields outside frozen question regions: ' + field)
    if {r['page'] for r in mapped} != {r['page'] for regions in fields.values() for r in regions}:
        raise ValueError('source_fields must observe every frozen question page')
    return True


def validate_geometry(candidate, catalog):
    pages = {(p['source_id'], p['page']): p for p in catalog['pages']}
    for q in candidate['questions']:
        for r in q['regions']:
            page = pages.get((q['source_id'], r['page']))
            if not page:
                raise ValueError(q['id'] + ': unknown catalog page')
            bbox(r['bbox'], page['width'], page['height'])
    for resource in candidate['assets'] + candidate['evidence']:
        page = pages.get((resource['source_id'], resource['page']))
        if not page:
            raise ValueError('Resource page absent from catalog')
        bbox(resource['bbox'], page['width'], page['height'])


def containing_field(path, question):
    if path.startswith('stem'):
        return 'stem'
    if path.startswith('explanation'):
        return 'explanation'
    match = re.match(r'options\[(\d+)\]', path)
    if match:
        index = int(match.group(1))
        if index >= len(question['options']):
            raise ValueError('Evidence references unknown option block')
        return 'options/' + question['options'][index]['label']
    return path


def citation_requirements(question, dimension, field, selection=None, key=None, provenance=None):
    """Return (source_id, regions) for one cited path, including nested blocks."""
    field = containing_field(field, question)
    fields = selection.get('source_fields', {}) if selection else {}
    source = question['source_id']
    if field == 'options' and fields:
        return source, [r for name, regions in fields.items() if name.startswith('options/') for r in regions]
    if field in fields:
        return source, fields[field]
    entry = key if field == 'answer' else provenance if field == 'explanation' else None
    if entry and entry.get('source_id'):
        pages = entry.get('pages') or ([entry['page']] if entry.get('page') else [])
        return entry['source_id'], [{'page': page, 'bbox': None} for page in pages]
    regions = (selection.get('field_regions', {}).get(dimension) if selection else None) or question['regions']
    return source, regions


def validate_citations(question, dimension, check, candidate, root, selection=None, key=None, provenance=None):
    resources = {r['id']: r for r in candidate['assets'] + candidate['evidence']}
    expected = set(field_paths(question)[dimension])
    if set(check.get('field_paths', [])) != expected:
        raise ValueError(question['id'] + ': evidence field coverage mismatch for ' + dimension)
    refs = check.get('evidence', [])
    if not refs:
        raise ValueError('Localized evidence required')
    requirements = {field: citation_requirements(question, dimension, field, selection, key, provenance) for field in expected}
    supplied = {field: [] for field in expected}
    for citation in refs:
        resource = resources.get(citation.get('id'))
        if (not resource or resource['sha256'] != citation.get('sha256') or
                not isinstance(citation.get('observation'), str) or not citation['observation'].strip() or
                digest(artifact_path(root, resource['path'])) != citation['sha256']):
            raise ValueError('Unknown, altered or unjustified source evidence')
        fields = citation.get('fields', [])
        if not isinstance(fields, list) or not fields or not set(fields).issubset(expected):
            raise ValueError('Evidence citation must name covered field paths')
        for field in fields:
            source, regions = requirements[field]
            if resource['source_id'] != source or not any(resource['page'] == r['page'] and
                    (r.get('bbox') is None or overlaps(resource['bbox'], r['bbox'])) for r in regions):
                raise ValueError(question['id'] + ': evidence does not cover the question field/source region')
            supplied[field].append(resource)
    # Unresolved/fail checks may cite only available evidence, without claiming pass.
    if check.get('status', 'pass') == 'pass':
        for field in expected:
            if not supplied[field]:
                raise ValueError(question['id'] + ': fields without source evidence')
            if not cover_regions(requirements[field][1], supplied[field]):
                raise ValueError(question['id'] + ': evidence does not cover every essential field region/page: ' + field)
    return True


def validate_mapping(candidate, selection):
    mapped = {q['id']: q for q in selection['expected_questions']}
    for q in candidate['questions']:
        record = mapped[q['id']]
        if record.get('mapping_pending'):
            continue
        if not q['regions']:
            from lab import blocks_in
            source_blocks = list(blocks_in(q['stem'])) + [block for option in q['options']
                            for block in blocks_in(option['blocks'])]
            if any(block['type'] == 'unresolved' for block in source_blocks):
                continue  # Explicit source placeholders remain representable.
            raise ValueError(q['id'] + ': resolved question omits frozen source regions')
        labels = record.get('option_labels')
        if labels is not None and [o['label'] for o in q['options']] != labels:
            raise ValueError(q['id'] + ': options differ from frozen observed labels')
        observed = record.get('regions') or [{'page': record['page'], 'bbox': None}]
        for region in q['regions']:
            if not any(region['page'] == old['page'] and (old.get('bbox') is None or
                       contains(old['bbox'], region['bbox'])) for old in observed):
                raise ValueError(q['id'] + ': question region outside frozen source map')
        if {r['page'] for r in observed} - {r['page'] for r in q['regions']}:
            raise ValueError(q['id'] + ': question omits frozen source page')
        essential = [r for regions in record.get('source_fields', {}).values() for r in regions]
        if essential and not cover_regions(essential, q['regions']):
            raise ValueError(q['id'] + ': question omits essential source field region')
