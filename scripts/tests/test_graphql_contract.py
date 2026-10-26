"""Structural validation of pinned ERP contracts; never executes financial operations."""
import datetime
import hashlib
import json
import pathlib
import re
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'contracts/graphql'


def load(name):
    return json.loads((CONTRACT / name).read_text(encoding='utf-8'))


def named(ref):
    while ref.get('ofType'):
        ref = ref['ofType']
    return ref['name']


def signature(ref):
    if ref['kind'] == 'NON_NULL':
        return signature(ref['ofType']) + '!'
    if ref['kind'] == 'LIST':
        return '[' + signature(ref['ofType']) + ']'
    return ref['name']


def schema_from_sdl(text):
    """Read the complete pinned SDL shape used here, not a general SDL parser.

    Descriptions do not affect types. This release has no unions, interfaces or
    directives; unsupported syntax fails closed rather than being guessed.
    """
    text = re.sub(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"', '', text)
    text = re.sub(r'#[^\n]*', '', text)
    if '@' in text:
        raise ValueError('Unsupported SDL directive')
    blocks = list(re.finditer(r'\b(schema|type|input|enum)\s*(\w+)?\s*\{([^{}]*)\}', text))
    types = {name: {'name': name, 'kind': 'SCALAR'}
             for name in ('String', 'Boolean', 'Int', 'Float', 'ID')}
    for name in re.findall(r'\bscalar\s+(\w+)', text):
        types[name] = {'name': name, 'kind': 'SCALAR'}
    for block in blocks:
        kind, name, _ = block.groups()
        if kind != 'schema':
            if name in types:
                raise ValueError('Duplicate SDL type')
            types[name] = {'name': name, 'kind': {'type': 'OBJECT', 'input': 'INPUT_OBJECT',
                                               'enum': 'ENUM'}[kind]}
    remainder = re.sub(r'\bscalar\s+\w+', '', text)
    remainder = re.sub(r'\b(schema|type|input|enum)\s*(\w+)?\s*\{[^{}]*\}', '', remainder)
    if remainder.strip():
        raise ValueError('Unsupported SDL definition')

    def reference(spelling):
        if spelling.endswith('!'):
            return {'kind': 'NON_NULL', 'name': None, 'ofType': reference(spelling[:-1])}
        if spelling.startswith('[') and spelling.endswith(']'):
            return {'kind': 'LIST', 'name': None, 'ofType': reference(spelling[1:-1])}
        if spelling not in types:
            raise ValueError('Unresolved SDL type: ' + spelling)
        return {'kind': types[spelling]['kind'], 'name': spelling, 'ofType': None}

    def field(line):
        match = re.fullmatch(r'(\w+)(?:\(([^()]*)\))?\s*:\s*([\w!\[\]]+)(?:\s*=\s*(.+))?', line)
        if not match:
            raise ValueError('Unsupported SDL field: ' + line)
        name, arguments, spelling, default = match.groups()
        return {'name': name, 'type': reference(spelling), 'defaultValue': default,
                'args': [field(arg.strip()) for arg in arguments.split(',')] if arguments else []}

    schema = {'types': list(types.values())}
    for block in blocks:
        kind, name, body = block.groups()
        if kind == 'schema':
            for root, target in re.findall(r'(query|mutation)\s*:\s*(\w+)', body):
                schema[root + 'Type'] = {'name': target}
        elif kind == 'enum':
            if re.sub(r'[\w\s]', '', body):
                raise ValueError('Unsupported SDL enum')
            types[name]['enumValues'] = [{'name': item} for item in body.split()]
        else:
            key = 'fields' if kind == 'type' else 'inputFields'
            types[name][key] = [field(line.strip()) for line in body.splitlines() if line.strip()]
    return schema


def validate_input(value, ref, types):
    if ref['kind'] == 'NON_NULL':
        if value is None:
            raise ValueError('Required input is null')
        return validate_input(value, ref['ofType'], types)
    if value is None:
        return
    if ref['kind'] == 'LIST':
        if not isinstance(value, list):
            raise ValueError('Example must use an explicit list')
        for item in value:
            validate_input(item, ref['ofType'], types)
        return
    name = ref['name']
    definition = types[name]
    if definition['kind'] == 'INPUT_OBJECT':
        if not isinstance(value, dict):
            raise ValueError('Expected input object')
        fields = {f['name']: f for f in definition['inputFields']}
        if set(value) - fields.keys():
            raise ValueError('Unknown input fields')
        for key, field in fields.items():
            if key not in value and field['defaultValue'] is not None:
                continue
            validate_input(value.get(key), field['type'], types)
    elif definition['kind'] == 'ENUM':
        if value not in {x['name'] for x in definition['enumValues']}:
            raise ValueError('Unknown enum value')
    elif name == 'UUID':
        uuid.UUID(value)
    elif name == 'Date':
        datetime.date.fromisoformat(value)
    elif name == 'DateTime':
        if datetime.datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('DateTime requires an offset')
    elif name in ('Int', 'BigDecimal', 'Float'):
        if type(value) not in (int, float) or (name == 'Int' and type(value) is not int):
            raise ValueError('Expected numeric scalar')
    elif name == 'Boolean':
        if type(value) is not bool:
            raise ValueError('Expected Boolean')
    elif name in ('String', 'ID'):
        if not isinstance(value, str):
            raise ValueError('Expected string')
    else:
        raise ValueError('Unsupported example scalar: ' + name)


def validate_example(example, types):
    """Validate only the deliberately restricted syntax used by examples.json.

    Not a general GraphQL parser: aliases, fragments, directives and literal
    arguments are rejected rather than silently accepted without validation.
    """
    match = re.fullmatch(
        r'(query|mutation)\s+(\w+)\s*(?:\(\$(\w+):\s*(\w+!)\))?\s*'
        r'\{\s*(\w+)\s*(?:\((\w+):\s*\$(\w+)\))?\s*(\{.*\})\s*\}',
        example['query'], re.S)
    if not match:
        raise ValueError('Unsupported example syntax')
    kind, operation, variable, vartype, fieldname, argument, used, selection = match.groups()
    if operation != example['operationName']:
        raise ValueError('operationName mismatch')
    fields = {f['name']: f for f in types[kind.title()]['fields']}
    field = fields[fieldname]
    args = {a['name']: a for a in field['args']}
    supplied = set()
    if argument:
        if used != variable or set(example['variables']) != {variable}:
            raise ValueError('Variable binding mismatch')
        arg = args[argument]
        if signature(arg['type']) != vartype:
            raise ValueError('Variable type mismatch')
        validate_input(example['variables'][variable], arg['type'], types)
        supplied.add(argument)
    elif example['variables'] or variable:
        raise ValueError('Unused variable')
    for key, arg in args.items():
        if arg['type']['kind'] == 'NON_NULL' and arg['defaultValue'] is None and key not in supplied:
            raise ValueError('Missing required argument')
    tokens = re.findall(r'[_A-Za-z][_0-9A-Za-z]*|[{}]', selection)
    if re.sub(r'[_A-Za-z][_0-9A-Za-z]*|[{}\s]', '', selection):
        raise ValueError('Unsupported selection syntax')
    cursor = 0

    def walk(type_name):
        nonlocal cursor
        if tokens[cursor] != '{':
            raise ValueError('Expected selection')
        cursor += 1
        count = 0
        fields = {f['name']: f for f in types[type_name]['fields']}
        while tokens[cursor] != '}':
            field = fields[tokens[cursor]]
            cursor += 1
            count += 1
            target = named(field['type'])
            if types[target]['kind'] == 'OBJECT':
                walk(target)
            elif tokens[cursor] == '{':
                raise ValueError('Scalar has a selection')
        cursor += 1
        if not count:
            raise ValueError('Empty selection')

    walk(named(field['type']))
    if cursor != len(tokens):
        raise ValueError('Trailing selection tokens')


class IntrospectionReferenceTest(unittest.TestCase):
    def test_full_upstream_introspection_is_pinned_not_vendored(self):
        source = load('source.json')
        self.assertNotIn('ms1-erp.introspection.json', source['artifacts'])
        reference = source['references']['introspection']
        self.assertEqual(reference['source'], 'docs/graphql/introspection.json')
        self.assertEqual(reference['sha256'],
                         'ec392a07faf6ce6ae938bd9c17a208b3ef78cd884de2376774d06f099575fd4d')
        self.assertIn('/' + source['commit'] + '/', reference['url'])
        self.assertFalse((CONTRACT / 'ms1-erp.introspection.json').exists())


class GraphQLContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = schema_from_sdl((CONTRACT / 'ms1-erp.graphql').read_text(encoding='utf-8'))
        cls.types = {t['name']: t for t in cls.schema['types']}

    def test_effective_operations_replace_old_proposal(self):
        schema = (CONTRACT / 'ms1-erp.graphql').read_text(encoding='utf-8')
        for name in ('crearOrdenCobroManual', 'configurarPlanDePagos',
                     'cobrarCuotaEnEfectivo', 'listarOrdenesCobro'):
            self.assertIn(name + '(', schema)
        self.assertNotIn('idempotencyKey', schema)
        self.assertNotIn('generarFactura', schema)

    def test_canonical_artifact_integrity(self):
        source = load('source.json')
        self.assertRegex(source['commit'], r'^[a-f0-9]{40}$')
        self.assertEqual(source['repository'], 'https://github.com/AI-Dentist/ms-erp')
        for name, artifact in source['artifacts'].items():
            self.assertEqual(hashlib.sha256((CONTRACT / name).read_bytes()).hexdigest(),
                             artifact['sha256'])

    def test_complete_sdl_type_graph_is_resolved(self):
        for kind in ('queryType', 'mutationType'):
            self.assertEqual(self.types[self.schema[kind]['name']]['kind'], 'OBJECT')
        for definition in self.types.values():
            for field in (definition.get('fields') or []) + (definition.get('inputFields') or []):
                self.assertIn(named(field['type']), self.types)
                for argument in field.get('args', []):
                    self.assertIn(named(argument['type']), self.types)

    def test_examples_match_effective_types_and_fields(self):
        examples = load('examples.json')
        self.assertEqual(len(examples), 4)
        for example in examples:
            with self.subTest(operation=example['operationName']):
                validate_example(example, self.types)

    def test_old_input_is_rejected_without_executing_a_mutation(self):
        example = load('examples.json')[1]
        example['variables']['input']['idempotencyKey'] = 'not-a-schema-field'
        with self.assertRaisesRegex(ValueError, 'Unknown input fields'):
            validate_example(example, self.types)


if __name__ == '__main__':
    unittest.main()
