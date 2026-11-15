import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from api.main import app
from factory import catalog
from chert.factory import handle_message
from chert.signatures import sign_for_test

class FactoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'FACTORY_DB': str(Path(self.tmp.name)/'catalog.db'), 'CHERT_WEBHOOK_SECRET':'test-subscription-secret', 'FACTORY_SEND_REPLIES':'0'})
        self.env.start()
        self.author = TestClient(app)
        self.reader = TestClient(app)
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def build(self, idea='Analyze my workouts'):
        r=self.author.post('/factory/build',json={'idea':idea})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()
    def test_complete_lifecycle_pins_versions_and_keeps_drafts_private(self):
        s=self.build(); sid=s['id']
        self.assertEqual(self.reader.get('/factory/library').json(),[])
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/publish',json={'version':1}).status_code,404)
        bundle=self.reader.get(f'/factory/skills/{sid}/versions/1/bundle')
        self.assertEqual(bundle.status_code,404)
        self.assertEqual(self.author.post(f'/factory/skills/{sid}/publish',json={'version':1}).status_code,200)
        self.assertEqual(len(self.reader.get('/factory/library').json()),1)
        payload={'version':1,'input':{'sessions':[{'exercise':'Squat','minutes':20,'sets':3,'reps':8,'weight_kg':40}]}}
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/run',json=payload).status_code,403)
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/install',json={'version':1}).status_code,200)
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/run',json=payload).json()['result']['volume_kg'],960)
        sug=self.reader.post(f'/factory/skills/{sid}/suggestions',json={'version':1,'text':'Explain lifting volume clearly with the units.'}).json()
        revision={'expected_version':1,'instructions':'Summarize measured workout totals and clearly explain kg units.','suggestion_id':sug['id']}
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/revisions',json=revision).status_code,404)
        self.assertEqual(self.author.post(f'/factory/skills/{sid}/revisions',json=revision).json()['version'],2)
        self.assertEqual(self.author.post(f'/factory/skills/{sid}/revisions',json=revision).status_code,409)
        self.assertEqual(self.reader.get('/factory/workspace').json()['installed'][0]['version'],1)
        self.assertEqual(self.reader.get('/factory/library').json()[0]['version'],1)
        self.assertEqual(self.author.get(f'/factory/skills/{sid}/suggestions').json()[0]['status'],'accepted')
        self.author.post(f'/factory/skills/{sid}/publish',json={'version':2})
        self.assertEqual(self.reader.get('/factory/library').json()[0]['version'],2)
        self.assertEqual(self.reader.post(f'/factory/skills/{sid}/run',json={**payload,'version':2}).status_code,403)
        data=self.reader.get(f'/factory/skills/{sid}/versions/1/bundle').content
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('SKILL.md',z.namelist())
            self.assertEqual(json.loads(z.read('manifest.json'))['version'],1)
    def test_catalog_survives_reopening_and_unknown_requests_fail(self):
        self.build()
        self.assertEqual(len(self.author.get('/factory/workspace').json()['skills']),1)
        self.assertEqual(self.author.post('/factory/build',json={'idea':'Create a time machine'}).status_code,422)
        self.assertEqual(self.author.post('/factory/build',json={'idea':'QR workout checker'}).status_code,422)
    def test_validation_and_no_sample_qr_success(self):
        s=self.build('Check if QR codes are scams')
        with patch('api.config.SANDBOX_URL',''):
            r=self.author.post(f"/factory/skills/{s['id']}/run",json={'version':1,'input':{'url':'https://example.com'}})
        self.assertEqual(r.status_code,503)
        for value in [True,-1,float('inf'), '10']:
            with self.assertRaises(HTTPException):
                catalog.workout_summary({'sessions':[{'exercise':'Squat','minutes':value}]})
        self.assertEqual(self.author.post('/factory/build',json={'idea':'workout summary'},headers={'origin':'https://untrusted.example'}).status_code,403)
    def test_retired_payment_and_operator_routes_are_absent(self):
        for route in ['/pay','/call-me','/operators/dogwood/api/me']:
            self.assertEqual(self.author.post(route,json={}).status_code,404)
        from sandbox.server import app as sandbox_app
        self.assertNotIn('/operate/stream',[r.path for r in sandbox_app.routes])
    def test_signed_chert_build_install_run_and_replay(self):
        event={'id':'event-1','type':'message.received','data':{'message':{'sender':'+15555550100','parts':[{'type':'text','value':'BUILD analyze my workouts'}]}}}
        raw=json.dumps(event).encode()
        self.assertEqual(self.author.post('/chert/webhook',content=raw).status_code,401)
        with patch.dict(os.environ,{'CHERT_WEBHOOK_SECRET':''}):
            self.assertEqual(self.author.post('/chert/webhook',content=raw).status_code,503)
        response=self.author.post('/chert/webhook',content=raw,headers={'X-Webhook-Signature':sign_for_test('test-subscription-secret',raw)})
        self.assertEqual(response.status_code,200,response.text)
        skill=response.json()['result']['skill']
        replay=self.author.post('/chert/webhook',content=raw,headers={'X-Webhook-Signature':sign_for_test('test-subscription-secret',raw)}).json()
        self.assertTrue(replay['duplicate'])
        sid=skill['id'];sender='+15555550100'
        handle_message(sender,f'PUBLISH {sid} 1')
        other='+15555550101'
        handle_message(other,f'INSTALL {sid} 1')
        result=handle_message(other,f'RUN {sid} 1 '+json.dumps({'sessions':[{'exercise':'Walk','minutes':30}]}))
        self.assertEqual(result['result']['minutes'],30)
        self.assertEqual(self.author.get('/factory/workspace').json()['skills'],[])

if __name__=='__main__':
    unittest.main()
