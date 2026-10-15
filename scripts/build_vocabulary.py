"""Build the offline vocabulary from the pinned official Schema.org release."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = root / 'artifacts/schema-source.jsonld'
def refs(value):
    return [x['@id'].removeprefix('schema:') for x in (value if isinstance(value, list) else [value]) if isinstance(x, dict) and x.get('@id', '').startswith('schema:')]
result = {'version': '30.1', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'types': {}, 'properties': {}}
for node in json.loads(source.read_text(encoding='utf-8'))['@graph']:
    if not node['@id'].startswith('schema:'):
        continue
    name = node['@id'][7:]
    kinds = node.get('@type', [])
    if 'rdfs:Class' in kinds:
        result['types'][name] = refs(node.get('rdfs:subClassOf', []))
    if 'rdf:Property' in kinds:
        result['properties'][name] = {'domain': refs(node.get('schema:domainIncludes', [])), 'range': refs(node.get('schema:rangeIncludes', []))}
(root / 'seo_local/vocabulary/schema-30.1.json').write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding='utf-8')
print(len(result['types']), 'types;', len(result['properties']), 'properties')
