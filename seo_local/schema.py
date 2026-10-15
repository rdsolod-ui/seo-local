"""Offline checks, not a complete JSON-LD processor or rich-result validator."""
import json
from functools import lru_cache
from pathlib import Path

VOCAB = json.loads((Path(__file__).parent / 'vocabulary/schema-30.1.json').read_text(encoding='utf-8'))
SCHEMA = {'https://schema.org', 'http://schema.org', 'https://schema.org/', 'http://schema.org/'}

@lru_cache(maxsize=4096)
def ancestors(kind):
    found, pending = set(), [kind]
    while pending:
        item = pending.pop()
        if item not in found:
            found.add(item)
            pending.extend(VOCAB['types'].get(item, []))
    return found

def validate(text):
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError('JSON-LD: лимит 2 МБ')
    issues, types, count = [], set(), 0
    def add(code, path, detail, severity='warning'):
        if len(issues) < 200:
            issues.append({'code': code, 'path': path, 'detail': detail, 'severity': severity})
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                add('duplicate_key', '$', 'Повтор ключа: ' + k)
            obj[k] = v
        return obj
    try:
        data = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Недопустимое число: ' + x)))
    except (ValueError, RecursionError) as exc:
        add('jsonld_invalid', '$', str(exc), 'error')
        return {'version': VOCAB['version'], 'nodes': 0, 'types': [], 'issues': issues, 'complete': False}
    if not isinstance(data, (dict, list)):
        add('document_shape', '$', 'Ожидается объект или массив объектов', 'error')
    complete = True
    def walk(value, path, schema=False, prefixes=None, depth=0):
        nonlocal count, complete
        if depth > 40 or count >= 3000:
            if complete:
                add('limit', path, 'Достигнут предел: 40 уровней или 3000 объектов', 'info')
            complete = False
            return
        if isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f'{path}[{i}]', schema, prefixes, depth+1)
            return
        if not isinstance(value, dict):
            return
        count += 1
        prefixes = dict(prefixes or {})
        if '@context' in value:
            contexts = value['@context'] if isinstance(value['@context'], list) else [value['@context']]
            for context in contexts:
                if isinstance(context, str) and context in SCHEMA:
                    schema = True
                elif isinstance(context, dict) and all(isinstance(v, str) and v in SCHEMA for v in context.values()):
                    for k, v in context.items():
                        if k == '@vocab': schema = True
                        else: prefixes[k] = v
                else:
                    schema = False
                    prefixes = {}
                    complete = False
                    add('context_unchecked', path+'.@context', 'Внешний/расширенный контекст не загружается. Проверка словаря этого контекста пропущена.', 'info')
        def term(raw):
            if not isinstance(raw, str): return None
            for base in SCHEMA:
                if base.endswith('/') and raw.startswith(base): return raw[len(base):]
            if ':' in raw:
                prefix, name = raw.split(':', 1)
                return name if prefix in prefixes else None
            return raw if schema else None
        raw_types = value.get('@type', [])
        raw_types = raw_types if isinstance(raw_types, list) else [raw_types]
        known = []
        for raw in raw_types:
            if not isinstance(raw, str):
                add('type_shape', path+'.@type', '@type должен быть строкой или массивом строк', 'error')
                continue
            name = term(raw)
            if name:
                types.add(name)
                if name not in VOCAB['types']: add('unknown_type', path+'.@type', f'Тип {name} не найден в Schema.org {VOCAB["version"]}')
                else: known.append(name)
        if '@id' in value and not isinstance(value['@id'], str):
            add('id_shape', path+'.@id', '@id должен быть строкой', 'error')
        if '@graph' in value and not isinstance(value['@graph'], (dict, list)):
            add('graph_shape', path+'.@graph', '@graph должен содержать объект или массив', 'error')
        for key, child in value.items():
            if key == '@context': continue
            name = term(key) if not key.startswith('@') else None
            if name:
                rule = VOCAB['properties'].get(name)
                if rule is None:
                    add('unknown_property', path+'.'+key, f'Свойство {name} не найдено в словаре; проверьте опечатку или расширение')
                elif known and rule['domain'] and not any(ancestors(k).intersection(rule['domain']) for k in known):
                    add('domain_advisory', path+'.'+key, 'Ожидаемые типы владельца: '+', '.join(rule['domain'])+'. Это рекомендация словаря, не запрет.', 'info')
                if rule and isinstance(child, dict) and '@type' in child and '@context' not in child:
                    child_types = child['@type'] if isinstance(child['@type'], list) else [child['@type']]
                    resolved = [term(t) for t in child_types]
                    if resolved and all(t in VOCAB['types'] for t in resolved) and rule['range'] and not any(ancestors(t).intersection(rule['range']) for t in resolved):
                        add('range_advisory', path+'.'+key, 'Ожидаемые типы значения: '+', '.join(rule['range'])+'. Проверьте смысл разметки.', 'info')
            walk(child, path+'.'+key, schema, prefixes, depth+1)
    walk(data, '$')
    if not types:
        complete = False
        add('no_schema_type', '$', 'Не найден проверяемый тип Schema.org. Проверьте @context и @type.', 'info')
    return {'version': VOCAB['version'], 'nodes': count, 'types': sorted(types), 'issues': issues, 'complete': complete,
            'note': 'Офлайн-проверка синтаксиса и словаря; не полная обработка JSON-LD. Schema.org не задаёт универсальных обязательных полей. Расширенные результаты не гарантируются.'}
