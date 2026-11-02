"""Offline CLI/contract tests: never authenticate, upload, or allocate GPUs."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from epub_audio_drama import remote
from epub_audio_drama.cli import main, make_demo
from epub_audio_drama.core import ContractError, load, save, digest


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.project = self.base/'project'; make_demo(self.project)
        self.env = patch.dict(os.environ, {'KAGGLE_API_TOKEN':'SECRET_SENTINEL','KAGGLE_USERNAME':'example'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)

    def push(self, args):
        self.assertEqual(args[:2], ['kernels','push'])
        slug = load(Path(args[3])/'kernel-metadata.json')['id']
        return f'Kernel version 1 successfully pushed. https://www.kaggle.com/code/{slug}'

    def launch(self):
        with patch.object(remote, 'cli', side_effect=self.push):
            return remote.run('speech',self.project,'001',run_dir=self.base/'run',design_missing=True)

    def test_token_only_requires_owner(self):
        del os.environ['KAGGLE_USERNAME']
        with self.assertRaisesRegex(ContractError,'--owner'): remote.run('speech',self.project,'001')
        save(self.project/'execution.json',{'backend':'kaggle','kaggle':{'owner':'example'}})
        self.launch()

    def test_credentials_preflight_and_legacy(self):
        with patch.dict(os.environ, {'HOME':str(self.base)},clear=True):
            self.assertFalse(remote.credentials_available())
            with self.assertRaisesRegex(ContractError,'KAGGLE_API_TOKEN'):remote.cli(['kernels','status','example/test'])
            folder=self.base/'.kaggle';folder.mkdir();(folder/'access_token').write_text('secret')
            self.assertTrue(remote.credentials_available())
            (folder/'access_token').unlink();(folder/'kaggle.json').write_text('{}')
            self.assertTrue(remote.credentials_available())
        with patch.dict(os.environ, {'KAGGLE_USERNAME':'example','KAGGLE_KEY':'secret'},clear=True):
            self.assertTrue(remote.credentials_available())

    def test_cli_no_secret_arguments_and_sanitized_failures(self):
        with patch.object(remote.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'ok','')) as call:
            self.assertEqual(remote.cli(['kernels','status','example/test']),'ok')
            self.assertNotIn('SECRET_SENTINEL',repr(call.call_args))
            self.assertNotIn('env',call.call_args.kwargs) # inherited environment
        with patch.object(remote.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'SECRET_SENTINEL','SECRET_SENTINEL')):
            with self.assertRaises(ContractError) as error:remote.cli(['kernels','status','example/test'])
            self.assertNotIn('SECRET_SENTINEL',str(error.exception))
        with patch.object(remote.subprocess,'run',side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ContractError,'CLI not found'):remote.cli([])
        with patch.object(remote.subprocess,'run',side_effect=subprocess.TimeoutExpired('cmd',180)):
            with self.assertRaisesRegex(ContractError,'timed out'):remote.cli([])

    def test_receipt_source_and_secret_exclusion(self):
        path=self.launch();r=load(path);code=Path(r['payload'])/'run.py'
        self.assertEqual(r['state'],'SUBMITTED');self.assertEqual(r['version'],1)
        self.assertEqual(r['source_sha256'],digest(code.read_bytes()))
        self.assertIn('/kaggle/working/remote-run.json',code.read_text())
        for p in path.parent.rglob('*'):
            if p.is_file():self.assertNotIn(b'SECRET_SENTINEL',p.read_bytes())
        with self.assertRaisesRegex(ContractError,'new and empty'):self.launch()

    def test_push_unknown_is_preserved(self):
        with patch.object(remote,'cli',side_effect=ContractError('secret')):
            with self.assertRaisesRegex(ContractError,'not confirmed'):remote.run('speech',self.project,'001',run_dir=self.base/'run',design_missing=True)
        self.assertEqual(load(self.base/'run/receipt.json')['state'],'PUSH_UNCONFIRMED')

    def test_destination_mismatch_blocks(self):
        with patch.object(remote,'cli',return_value='https://www.kaggle.com/code/example/wrong'):
            with self.assertRaisesRegex(ContractError,'different destination'):remote.run('speech',self.project,'001',run_dir=self.base/'run',design_missing=True)
        self.assertEqual(load(self.base/'run/receipt.json')['state'],'DESTINATION_MISMATCH')

    def test_status_records_latest_only_no_raw_output(self):
        p=self.launch()
        with patch.object(remote,'cli',return_value='has status "KernelWorkerStatus.COMPLETE" SECRET_SENTINEL'):
            s=remote.status(p)
        self.assertEqual(s['status'],'COMPLETE');self.assertIn('not version-specific',s['scope'])
        self.assertNotIn('SECRET_SENTINEL',p.read_text())

    def test_filtered_download_binds_marker_and_hashes(self):
        path=self.launch();r=load(path)
        def download(args):
            if args[1]=='status':return 'complete'
            self.assertEqual(args[:2],['kernels','output']);self.assertIn('--file-pattern',args)
            out=Path(args[4]);save(out/'remote-run.json',{k:r[k] for k in ('run_id','kind','slug')});(out/'chapter.wav').write_bytes(b'fixture-audio')
            return ''
        with patch.object(remote,'cli',side_effect=download):out=remote.download(path)
        self.assertEqual(load(path)['state'],'DOWNLOADED');self.assertIn('chapter.wav',load(path)['output_hashes'])
        with patch.object(remote,'cli',return_value='complete'):
            with self.assertRaisesRegex(ContractError,'new and empty'):remote.download(path)

    def test_download_missing_marker_and_running_fail(self):
        path=self.launch()
        with patch.object(remote,'cli',return_value='running'):
            with self.assertRaisesRegex(ContractError,'not COMPLETE'):remote.download(path)
        with patch.object(remote,'cli',side_effect=['complete','']):
            with self.assertRaisesRegex(ContractError,'not bound'):remote.download(path)
        self.assertEqual(load(path)['state'],'SUBMITTED')

    def test_configuration_and_render_routing(self):
        self.assertEqual(remote.backend(self.project),'local')
        save(self.project/'execution.json',{'backend':'kaggle','kaggle':{'owner':'example'}})
        self.assertEqual(remote.backend(self.project),'kaggle');self.assertEqual(remote.backend(self.project,'local'),'local')
        with patch('sys.argv',['epub-drama','render',str(self.project),'001']),patch.object(remote,'run',return_value='receipt') as run:
            main();self.assertEqual(run.call_args.args[0],'speech')
        with patch('sys.argv',['epub-drama','render',str(self.project),'001','--backend','local']),patch('epub_audio_drama.tts.render',return_value='local') as local:
            main();local.assert_called_once()
        save(self.project/'execution.json',{'kaggle':{'api_key':'secret'}})
        with self.assertRaisesRegex(ContractError,'only owner'):remote.configuration(self.project)

    def test_sound_run_prompt_only(self):
        plan=self.base/'plan.json';save(plan,{'assets':[{'id':'rain','prompt':'rain','seconds':5,'seed':1}], 'cues':[], 'master_sha256':'PRIVATE_SENTINEL'})
        with patch.object(remote,'cli',side_effect=self.push):path=remote.run('sound',plan=plan,run_dir=self.base/'sound')
        code=(path.parent/'payload/run.py').read_text();self.assertNotIn('PRIVATE_SENTINEL',code)
        self.assertEqual(load(path)['kind'],'sound')
