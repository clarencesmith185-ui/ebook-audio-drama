"""Offline provider and review-boundary tests; no paid requests or login."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from epub_audio_drama import llm
from epub_audio_drama.cli import make_demo, main
from epub_audio_drama.core import ContractError, load, save
from epub_audio_drama.kaggle import package


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.project = self.base/'project'; make_demo(self.project)
        self.source = (self.project/'chapters/001/source.txt').read_text()
        self.config = self.base/'llm.local.json'
        save(self.config, {'backend':'api','model':'test-model','api_key_env':'TEST_LLM_KEY'})
        self.data = {'characters':[{'id':'narrator','name':'Narrator','role':'Narration',
                    'voice_description':'Clear adult voice','evidence_start':0,'evidence_end':4}],
                    'segments':[{'start':0,'end':len(self.source),'speaker':'narrator'}],
                    'sound_cues':[{'start':0,'end':4,'prompt':'Quiet rain'}]}

    def test_api_request_credentials_and_review_only(self):
        before = {p: p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        response = MagicMock(); response.__enter__.return_value.read.return_value = json.dumps(
            {'choices':[{'message':{'content':json.dumps(self.data)}}]}).encode()
        opener = MagicMock(); opener.open.return_value = response
        with patch.dict(os.environ, {'TEST_LLM_KEY':'SECRET_SENTINEL'}), patch.object(llm,'build_opener',return_value=opener):
            output = llm.prepare(self.project,'001',self.config)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.headers['Authorization'],'Bearer SECRET_SENTINEL')
        self.assertEqual(request.full_url,'https://api.openai.com/v1/chat/completions')
        self.assertIn(self.source, json.loads(request.data)['messages'][1]['content'])
        artifact = load(output)
        self.assertFalse(artifact['source_reviewed']); self.assertEqual(artifact['status'],'UNREVIEWED_SUGGESTIONS')
        self.assertNotIn('SECRET_SENTINEL',output.read_text())
        for p, original in before.items(): self.assertEqual(p.read_bytes(), original)
        # Explicit payload allowlist must exclude local config/review material and credentials.
        save(self.project/'llm.local.json', {'api_key':'PRIVATE_CONFIG_SENTINEL'})
        payload = package(self.project,'001','owner/test-run',self.base/'payload',design_missing=True)
        manifest = load(payload/'payload-manifest.json')
        self.assertFalse(any('llm-review' in p or 'llm.local' in p for p in manifest['embedded_files']))
        self.assertNotIn('PRIVATE_CONFIG_SENTINEL',(payload/'run.py').read_text())

    def test_missing_key_and_sanitized_failure(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ContractError,'not set'):
            llm.prepare(self.project,'001',self.config)
        with patch.dict(os.environ, {'TEST_LLM_KEY':'SECRET'}), patch.object(llm,'build_opener',side_effect=RuntimeError('SECRET private text')):
            with self.assertRaises(ContractError) as caught: llm.prepare(self.project,'001',self.config)
        self.assertNotIn('SECRET',str(caught.exception)); self.assertFalse((self.project/'llm-review').exists())

    def test_codex_saved_login_and_stdin(self):
        save(self.config, {'backend':'codex','model':'test-codex'})
        def run(command, **kwargs):
            self.assertEqual(command[:2],['codex','exec'])
            self.assertIn('--ignore-user-config', command); self.assertIn('--ephemeral', command)
            self.assertIn('read-only', command); self.assertIn('forced_login_method="chatgpt"', command)
            self.assertEqual(command[-1],'-'); self.assertNotIn(self.source, ' '.join(command))
            self.assertIn(self.source,kwargs['input']); self.assertEqual(kwargs['timeout'],180)
            self.assertNotIn('OPENAI_API_KEY',kwargs['env']); self.assertNotIn('KAGGLE_API_TOKEN',kwargs['env'])
            self.assertEqual(kwargs['env']['CODEX_HOME'],'/saved/login')
            Path(command[command.index('--output-last-message')+1]).write_text(json.dumps(self.data))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'SECRET','KAGGLE_API_TOKEN':'SECRET','CODEX_HOME':'/saved/login'}), patch.object(llm.subprocess,'run',side_effect=run):
            output = llm.prepare(self.project,'001',self.config)
        self.assertEqual(load(output)['backend'],'codex')

    def test_codex_failures_are_sanitized(self):
        save(self.config, {'backend':'codex','model':'test-codex'})
        for error in [FileNotFoundError('SECRET'), subprocess.TimeoutExpired('SECRET',1), subprocess.CalledProcessError(1,'SECRET')]:
            with self.subTest(error=type(error).__name__), patch.object(llm.subprocess,'run',side_effect=error):
                with self.assertRaises(ContractError) as caught: llm.prepare(self.project,'001',self.config)
                self.assertNotIn('SECRET',str(caught.exception))

    def test_reject_malformed_or_unsafe_suggestions(self):
        invalid = ['not json', '```json\n{}\n```', '{}']
        for change in [lambda d: d['segments'][0].update(start=1),
                       lambda d: d['segments'][0].update(end=len(self.source)+1),
                       lambda d: d['segments'][0].update(speaker='unknown'),
                       lambda d: d['segments'][0].update(start=True),
                       lambda d: d['characters'].append(copy.deepcopy(d['characters'][0])),
                       lambda d: d['characters'][0].update(evidence_end=len(self.source)+1),
                       lambda d: d['sound_cues'][0].update(end=0),
                       lambda d: d.update(source_reviewed=True)]:
            data=copy.deepcopy(self.data); change(data); invalid.append(json.dumps(data))
        for raw in invalid:
            with self.subTest(raw=raw[:80]), self.assertRaises(ContractError): llm.validate_suggestions(raw,self.source)

    def test_source_bounds_and_existing_output_block_calls(self):
        with patch.object(llm,'_api') as api:
            with self.assertRaises(ContractError): llm.prepare(self.project,'../001',self.config)
            with self.assertRaises(ContractError): llm.prepare(self.project,'001',self.config,self.project/'cast.json')
            (self.project/'chapters/001/source.txt').write_text('x'*(llm.MAX_SOURCE+1))
            with self.assertRaises(ContractError): llm.prepare(self.project,'001',self.config)
            api.assert_not_called()

    def test_changed_source_not_saved(self):
        def call(*args):
            (self.project/'chapters/001/source.txt').write_text('changed')
            return json.dumps(self.data)
        with patch.object(llm,'_api',side_effect=call), self.assertRaisesRegex(ContractError,'changed'):
            llm.prepare(self.project,'001',self.config)
        self.assertFalse((self.project/'llm-review').exists())

    def test_bad_config_and_redirect(self):
        for config in [{'backend':'api','model':'m','api_key':'SECRET'},
                       {'backend':'api','model':'m','timeout_seconds':0},
                       {'backend':'api','model':'m','base_url':'http://example.com/v1'},
                       {'backend':'api','model':'m','base_url':'https://SECRET@example.com/v1'},
                       {'backend':'codex','model':'m','api_key_env':'KEY'}]:
            save(self.config,config)
            with self.assertRaises(ContractError): llm.prepare(self.project,'001',self.config)
        self.assertIsNone(llm._NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere'))

    def test_cli_dispatch(self):
        with patch('sys.argv',['epub-drama','llm-prepare',str(self.project),'001','--config',str(self.config)]), patch.object(llm,'prepare',return_value='review.json') as prepare:
            main()
        prepare.assert_called_once_with(str(self.project),'001',str(self.config),None)
