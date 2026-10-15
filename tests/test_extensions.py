import json
import socket
import tempfile
import unittest
from unittest.mock import patch
from seo_local.schema import validate
from seo_local.lighthouse import Lighthouse, summarize
from seo_local.safe_proxy import ProxyHandler

class Extensions(unittest.TestCase):
    def test_graph_inheritance_and_multiple_types(self):
        result=validate(json.dumps({'@context':'https://schema.org','@graph':[{'@type':['LocalBusiness','Organization'],'name':'A','address':{'@type':'PostalAddress','streetAddress':'Road'}}]}))
        self.assertEqual(result['issues'], [])
        self.assertIn('PostalAddress',result['types'])

    def test_unknown_terms_and_domain(self):
        r=validate('{"@context":"https://schema.org","@type":"Organization","nmae":"X","cookingMethod":"Bake"}')
        self.assertEqual({i['code'] for i in r['issues']},{'unknown_property','domain_advisory'})
        self.assertEqual(r['issues'][0]['path'],'$.nmae')

    def test_syntax_duplicates_nonfinite(self):
        self.assertEqual(validate('{')['issues'][0]['code'],'jsonld_invalid')
        self.assertEqual(validate('{"n":NaN}')['issues'][0]['code'],'jsonld_invalid')
        self.assertIn('duplicate_key',[i['code'] for i in validate('{"a":1,"a":2}')['issues']])

    def test_custom_context_is_not_falsely_validated(self):
        r=validate('{"@context":"https://example.org/context","@type":"Something","custom":1}')
        self.assertFalse(r['complete'])
        self.assertNotIn('unknown_type',[i['code'] for i in r['issues']])

    def test_prefix_full_iri_and_shape(self):
        self.assertIn('Organization',validate('{"@context":{"s":"https://schema.org/"},"@type":"s:Organization","s:name":"A"}')['types'])
        self.assertIn('Organization',validate('{"@type":"https://schema.org/Organization"}')['types'])
        r=validate('{"@context":"https://schema.org","@type":42,"@id":{},"@graph":5}')
        self.assertTrue({'type_shape','id_shape','graph_shape'} <= {i['code'] for i in r['issues']})

    def test_range_advisory(self):
        r=validate('{"@context":"https://schema.org","@type":"Organization","address":{"@type":"Product","name":"X"}}')
        self.assertIn('range_advisory',[i['code'] for i in r['issues']])

    def test_lighthouse_import_and_paths(self):
        fixture={'finalUrl':'https://example.org/','lighthouseVersion':'13.5.0','categories':{'seo':{'score':.98}},'audits':{},'configSettings':{'formFactor':'mobile'}}
        with tempfile.TemporaryDirectory() as directory:
            lh=Lighthouse(directory)
            identifier=lh.import_report(fixture)
            self.assertEqual(lh.read(identifier)['summary']['scores']['seo'],98)
            with self.assertRaises(ValueError): lh.read('../../file')
            with self.assertRaises(ValueError): summarize({})
            fixture['categories']['seo']['score']=2
            with self.assertRaises(ValueError): summarize(fixture)

    def test_proxy_resolves_then_pins_public_ip(self):
        handler=object.__new__(ProxyHandler)
        with patch('seo_local.safe_proxy.Network.addresses',return_value=['93.184.216.34']),patch('socket.create_connection') as connect:
            handler.connect_public('example.org',443)
            connect.assert_called_once_with(('93.184.216.34',443),timeout=15)
        with self.assertRaises(ValueError): handler.connect_public('127.0.0.1',80)
        with self.assertRaises(ValueError): handler.connect_public('example.org',22)

if __name__=='__main__': unittest.main()
