import base64,io,json,tempfile,unittest,zipfile,ast,copy
from pathlib import Path
from epub_audio_drama.cli import make_demo
from epub_audio_drama.core import ContractError,load,save,digest,bindings,text_check,scaffold,rendering_units,import_voices
from epub_audio_drama.epub import extract
from epub_audio_drama.kaggle import package

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.root=self.base/'demo';make_demo(self.root)
    def script(self):return load(self.root/'chapters/001/script.json')
    def lock_refs(self):
        c=load(self.root/'cast.json')
        for vid,v in c['voices'].items():
            p=self.root/v['reference_audio'];p.parent.mkdir(exist_ok=True);p.write_bytes(('fixture:'+vid).encode());v['reference_sha256']=digest(p.read_bytes());v['status']='locked'
        save(self.root/'cast.json',c)
    def test_verbatim_spans_and_render_units(self):
        script=self.script();source=(self.root/'chapters/001/source.txt').read_text();text_check(source,script)
        units=rendering_units(script,limit=40);self.assertEqual(''.join(x['text'] for x in units),source)
        self.assertTrue(all(any(ch.isalnum() for ch in x['text']) for x in units))
    def test_tampered_and_missing_text_blocked(self):
        source=(self.root/'chapters/001/source.txt').read_text();script=self.script();script['segments'][0]['text']='rewritten'
        with self.assertRaises(ContractError):text_check(source,script)
        script=self.script();script['segments'].pop()
        with self.assertRaises(ContractError):text_check(source,script)
    def test_duplicate_source_offsets_blocked(self):
        source=(self.root/'chapters/001/source.txt').read_text();script=self.script();script['segments'][1]['start']=0
        with self.assertRaises(ContractError):text_check(source,script)
    def test_unassigned_speaker_blocks(self):
        script=self.script();script['segments'][1]['speaker']=None;save(self.root/'chapters/001/script.json',script)
        with self.assertRaises(ContractError):bindings(self.root,'001',False)
    def test_missing_and_modified_reference_blocks(self):
        with self.assertRaises(ContractError):bindings(self.root,'001')
        self.lock_refs();bindings(self.root,'001');p=self.root/'voices/maya-v1.wav';p.write_bytes(b'changed')
        with self.assertRaises(ContractError):bindings(self.root,'001')
    def test_cross_person_voice_blocks(self):
        cast=load(self.root/'cast.json');cast['voices']['maya-v1']['character']='eli';save(self.root/'cast.json',cast)
        with self.assertRaises(ContractError):bindings(self.root,'001',False)
    def test_unreviewed_role_and_edited_design_block(self):
        c=load(self.root/'cast.json');c['characters']['maya']['role_reviewed']=False;save(self.root/'cast.json',c)
        with self.assertRaises(ContractError):bindings(self.root,'001',False)
        c['characters']['maya']['role_reviewed']=True;c['characters']['maya']['voice_description']='changed';save(self.root/'cast.json',c)
        with self.assertRaises(ContractError):bindings(self.root,'001',False)
    def test_reference_traversal_blocks(self):
        c=load(self.root/'cast.json');c['voices']['maya-v1']['reference_audio']='../outside.wav';save(self.root/'cast.json',c)
        with self.assertRaises(ContractError):bindings(self.root,'001',False)
    def test_quote_scaffold_does_not_guess(self):
        s=scaffold('A sign said “OPEN”. “Hello,” someone said.');self.assertEqual(sum(x['speaker'] is None for x in s['segments']),2);self.assertFalse(s['source_reviewed'])
    def test_kaggle_payload_is_scoped_and_compiles(self):
        (self.root/'private.txt').write_text('PRIVATE_SENTINEL');cast=load(self.root/'cast.json');cast['characters']['unused']={'private':'PRIVATE_SENTINEL'};save(self.root/'cast.json',cast)
        out=package(self.root,'001','example/demo-project',self.base/'payload',design_missing=True)
        code=(out/'run.py').read_text();tree=ast.parse(code);assign={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body[:4]}
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(assign['PAYLOAD']))) as z:
            self.assertFalse(any('PRIVATE_SENTINEL' in z.read(n).decode(errors='ignore') for n in z.namelist()))
            self.assertIn('project/chapters/001/source.txt',z.namelist())
            self.assertNotIn('project/private.txt',z.namelist())
        self.assertEqual(load(out/'kernel-metadata.json')['is_private'],'true');self.assertLess(len(code.encode()),1_000_000)
    def test_voice_import_preserves_other_identities(self):
        remote=self.base/'remote';make_demo(remote);cast=load(remote/'cast.json')
        for vid,v in cast['voices'].items():
            p=remote/v['reference_audio'];p.parent.mkdir(exist_ok=True);p.write_bytes(vid.encode());v['reference_sha256']=digest(p.read_bytes());v['status']='locked'
        save(remote/'cast.json',cast);local=load(self.root/'cast.json');local['characters']['later']={'name':'Later'};save(self.root/'cast.json',local)
        self.assertEqual(len(import_voices(self.root,remote)),3);self.assertIn('later',load(self.root/'cast.json')['characters']);bindings(self.root,'001')
        cast['voices']['maya-v1']['reference_sha256']='0'*64;save(remote/'cast.json',cast)
        with self.assertRaises(ContractError):import_voices(self.root,remote)
    def test_epub_spine_order_and_no_script_text(self):
        path=self.base/'original.epub'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            z.writestr('OPS/book.opf','<package><manifest><item id="b" href="b.xhtml"/><item id="a" href="a.xhtml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
            z.writestr('OPS/a.xhtml','<html><head><title>Not spoken</title></head><body><h1>One</h1><p>Hello <em>world</em>.</p><script>Not spoken</script></body></html>')
            z.writestr('OPS/b.xhtml','<html><body><p>Two.</p></body></html>')
        docs=extract(path,self.base/'book');self.assertEqual([d['spine_href'] for d in docs],['OPS/a.xhtml','OPS/b.xhtml']);self.assertEqual((self.base/'book/chapters/001/source.txt').read_text(),'One Hello world .')
    def test_epub_path_traversal_rejected(self):
        p=self.base/'bad.epub'
        with zipfile.ZipFile(p,'w') as z:z.writestr('META-INF/container.xml','<container><rootfile full-path="../bad.opf"/></container>')
        with self.assertRaises(ContractError):extract(p,self.base/'bad')

if __name__=='__main__':unittest.main()
