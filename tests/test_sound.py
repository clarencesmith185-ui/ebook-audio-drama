import copy,json,tempfile,unittest
from pathlib import Path
from epub_audio_drama.sound import validate,package,mix,sha
from epub_audio_drama.core import ContractError

class SoundTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
        self.plan=dict(master_sha256='placeholder',start_frame=0,end_frame=24000,assets=[dict(id='rain',prompt='Quiet rain, no voices',seconds=1,seed=1)],cues=[dict(asset='rain',kind='ambience',start=0,end=1,below_speech_db=20,evidence='PRIVATE_SOURCE_EVIDENCE')])
    def save(self):
        p=self.root/'plan.json';p.write_text(json.dumps(self.plan));return p
    def test_package_excludes_source_and_runtime_output_tree(self):
        p=package(self.save(),'example/demo-sounds',self.root/'package');s=(p/'run.py').read_text()
        self.assertNotIn('PRIVATE_SOURCE_EVIDENCE',s);self.assertNotIn('placeholder',s)
        self.assertIn('/tmp/sound-env',s);self.assertNotIn('/kaggle/working/tangoflux-env',s)
        self.assertIn('0.90',s);compile(s,'run.py','exec')
    def test_unsafe_and_duplicate_asset_ids_rejected(self):
        for name in ['../rain','a/b','']:
            p=copy.deepcopy(self.plan);p['assets'][0]['id']=name
            with self.assertRaises(ContractError):validate(p)
        self.plan['assets']*=2
        with self.assertRaises(ContractError):validate(self.plan)
    def test_unsupported_cue_rejected(self):
        self.plan['cues'][0]['evidence']=''
        with self.assertRaises(ContractError):validate(self.plan)
    def test_mix_preserves_slice_and_rejects_tampered_asset(self):
        try:
            import numpy as np,soundfile as sf,scipy
        except ImportError:self.skipTest('optional sound dependencies absent')
        import shutil
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg absent')
        master=self.root/'master.wav';pcm=(np.sin(np.arange(48000)*.05)*4000).astype('int16');sf.write(master,pcm,24000,subtype='PCM_16')
        self.plan.update(master_sha256=sha(master),start_frame=12000,end_frame=36000)
        assets=self.root/'assets';assets.mkdir();asset=assets/'rain.wav';sf.write(asset,np.sin(np.arange(44100)*.02)*.2,44100,subtype='PCM_24')
        record=dict(self.plan['assets'][0],sha256=sha(asset));(assets/'manifest.json').write_text(json.dumps([record]))
        out=mix(self.save(),master,assets,self.root/'mixed',unreviewed=True)
        self.assertTrue(np.array_equal(sf.read(out/'dry.wav',dtype='int16')[0],pcm[12000:36000]))
        self.assertEqual(json.loads((out/'manifest.json').read_text())['voice_gain_db'],0)
        record['sha256']='incorrect';(assets/'manifest.json').write_text(json.dumps([record]))
        with self.assertRaises(ContractError):mix(self.save(),master,assets,self.root/'bad',unreviewed=True)
    def test_review_required(self):
        try:import numpy,soundfile,scipy
        except ImportError:self.skipTest('optional sound dependencies absent')
        p=self.save()
        # Correct master hash still cannot bypass listening approval.
        self.plan['master_sha256']=sha(p);master=self.root/'bytes';master.write_bytes(p.read_bytes());p=self.save()
        with self.assertRaises(ContractError):mix(p,master,self.root,self.root/'out')
