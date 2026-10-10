"""Reuse verified single-document inputs without treating run-local IDs as content."""

import copy
import json


def content_identity(key):
    payload = key['request']
    source = json.loads(payload['messages'][1]['content'])
    did = source.get('document_id')
    if not isinstance(did, str):
        return None, None  # Batch results are stored separately for each document.
    ids = list(dict.fromkeys(p['paragraph_id'] for p in key['paragraphs']))
    mapping = {pid: f'paragraph-{i}' for i, pid in enumerate(ids)}

    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {name: ('document' if name == 'document_id' and item == did else
                           mapping.get(item, item) if name == 'paragraph_id' and isinstance(item, str)
                           else normalize(item)) for name, item in value.items()}
        return value  # Never replace IDs inside source text, quotes or prompts.

    canonical = normalize(copy.deepcopy(key))
    canonical['request']['messages'][1]['content'] = json.dumps(
        normalize(source), ensure_ascii=False, sort_keys=True)
    return {'verified_content_version': 1, 'input': canonical}, mapping


def rebind_extraction(raw, mapping):
    if not isinstance(raw, dict):
        return None
    result = copy.deepcopy(raw)
    try:
        for claim in result['extraction']['claims']:
            claim['paragraph_id'] = mapping[claim['paragraph_id']]
    except (KeyError, TypeError):
        return None
    # Validation history remains an honest record of the original inference.
    return result
