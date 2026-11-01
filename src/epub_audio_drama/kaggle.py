"""Create a self-contained private notebook payload. Never uploads or launches anything."""
from pathlib import Path
import base64,io,zipfile,json,re
from .core import bindings,load,digest,save,ContractError

def package(root,chapter,slug,destination,reference_kernel=None,design_missing=False):
    root=Path(root);destination=Path(destination)
    if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9-]+',slug):raise ContractError('Use owner/lowercase-hyphenated-slug')
    if reference_kernel and not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9-]+',reference_kernel):raise ContractError('Invalid reference kernel slug')
    if destination.exists() and any(destination.iterdir()):raise ContractError('Use a new empty payload/version directory')
    binding=bindings(root,chapter,require_audio=not design_missing);cast=load(root/'cast.json');used={v['character'] for v in binding['voices'].values()}
    scoped={'characters':{k:v for k,v in cast['characters'].items() if k in used},'voices':binding['voices']}
    # Selected chapter + selected voices only; never recursively copy a private project.
    files={f'project/chapters/{chapter}/{name}':(root/f'chapters/{chapter}/{name}').read_bytes() for name in ('source.txt','script.json')}
    files['project/cast.json']=json.dumps(scoped,ensure_ascii=False,indent=2).encode()
    for p in Path(__file__).parent.glob('*.py'):files[f'code/epub_audio_drama/{p.name}']=p.read_bytes()
    files['code/LICENSE']=Path(__file__).with_name('LICENSE.txt').read_bytes()
    if not reference_kernel:
        for v in binding['voices'].values():
            if v.get('reference_sha256'):files['project/'+v['reference_audio']]=(root/v['reference_audio']).read_bytes()
            elif not design_missing or v.get('status')!='planned':raise ContractError('Missing voice must be explicitly planned')
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in files.items():z.writestr(name,data)
    code='PAYLOAD='+repr(base64.b64encode(buf.getvalue()).decode())+'\nHASHES='+repr({k:digest(v) for k,v in files.items()})+'\nCHAPTER='+repr(chapter)+'\nDESIGN_MISSING='+repr(design_missing)+'\n'
    code+='''import base64,io,zipfile,sys,subprocess,hashlib,json,shutil
from pathlib import Path
subprocess.check_call([sys.executable,'-m','pip','install','qwen-tts','soundfile','numpy'])
work=Path('/kaggle/working/epub-drama');work.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))) as z:z.extractall(work)
for name,expected in HASHES.items():assert hashlib.sha256((work/name).read_bytes()).hexdigest()==expected,name
root=work/'project'
cast=json.loads((root/'cast.json').read_text())
for v in cast['voices'].values():
 if not v.get('reference_sha256'):
  assert DESIGN_MISSING and v.get('status')=='planned','Missing unplanned reference'
  continue
 destination=root/v['reference_audio']
 if destination.exists():continue
 candidates=[p for p in Path('/kaggle/input').rglob('*') if p.is_file() and p.suffix.lower() in ('.wav','.flac') and hashlib.sha256(p.read_bytes()).hexdigest()==v['reference_sha256']]
 assert candidates,'Exact reference not found in attached input'
 destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(candidates[0],destination)
sys.path.insert(0,str(work/'code'))
from epub_audio_drama.tts import render,design_voice
if DESIGN_MISSING:
 for vid,v in cast['voices'].items():
  if not v.get('reference_sha256'):
   design_voice(root,v['character'],vid,v['reference_text'],v['language'],v['model_revision'])
   print('VOICE_LOCKED',vid,flush=True)
print(render(root,CHAPTER),flush=True)
'''
    if len(code.encode())>=1_000_000:raise ContractError('Kaggle source exceeds 1 MB; use --reference-kernel for existing hash-verified reference audio')
    compile(code,'run.py','exec');destination.mkdir(parents=True,exist_ok=True)
    (destination/'run.py').write_text(code,encoding='utf-8')
    meta={'id':slug,'title':slug.split('/')[1],'code_file':'run.py','language':'python','kernel_type':'script',
          'is_private':'true','enable_gpu':'true','enable_internet':'true','dataset_sources':[],
          'competition_sources':[],'kernel_sources':[reference_kernel] if reference_kernel else [],'model_sources':[]}
    save(destination/'kernel-metadata.json',meta)
    save(destination/'payload-manifest.json',{'payload_sha256':digest(code.encode()),'metadata_sha256':digest((destination/'kernel-metadata.json').read_bytes()),'chapter':chapter,'binding':binding,'embedded_files':list(files),'status':'PREPARED_NOT_UPLOADED'})
    return destination
