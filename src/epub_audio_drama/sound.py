"""Prompt-only TangoFlux packaging and non-destructive local scene mixing."""
import hashlib,json,math,re,subprocess
from pathlib import Path
from .core import ContractError

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate(plan):
    assets=plan['assets'];ids=set()
    if not assets:raise ContractError('Empty sound plan')
    for a in assets:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',a['id']) or a['id'] in ids:raise ContractError('Invalid/duplicate asset ID')
        ids.add(a['id'])
        if not a['prompt'].strip() or not 0<float(a['seconds'])<=30 or type(a['seed']) is not int:raise ContractError('Invalid prompt/duration/seed')
    for c in plan['cues']:
        if c['asset'] not in ids or not c.get('evidence') or not 0<=float(c['start'])<float(c['end']):raise ContractError('Invalid or unsupported cue')
        if c['kind'] not in ('ambience','foley') or not math.isfinite(float(c['below_speech_db'])) or c['below_speech_db']<0:raise ContractError('Invalid cue mix parameters')
    return plan

def package(plan_file,slug,destination):
    plan=validate(json.loads(Path(plan_file).read_text()))
    if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9-]+',slug):raise ContractError('Use lowercase owner/kebab-slug')
    out=Path(destination)
    if out.exists() and any(out.iterdir()):raise ContractError('Destination must be empty')
    out.mkdir(parents=True,exist_ok=True)
    # Deliberately omit evidence, source text, master paths and cue timings remotely.
    assets=[{k:a[k] for k in ('id','prompt','seconds','seed')} for a in plan['assets']]
    inner=Path(__file__).with_name('sound_renderer.txt').read_text().replace('ASSET_PAYLOAD',repr(assets))
    wrapper="""import subprocess,sys,os
from pathlib import Path
subprocess.run([sys.executable,'-m','pip','install','--quiet','uv'],check=True)
env=dict(os.environ,UV_PYTHON_INSTALL_DIR='/tmp/sound-python',UV_CACHE_DIR='/tmp/sound-uv',HF_HOME='/tmp/sound-hf',PIP_CACHE_DIR='/tmp/sound-pip')
subprocess.run([sys.executable,'-m','uv','venv','--python','3.11','/tmp/sound-env'],env=env,check=True)
py='/tmp/sound-env/bin/python'
subprocess.run([sys.executable,'-m','uv','pip','install','--python',py,'pip','numpy<2','huggingface_hub<1'],env=env,check=True)
p=Path('/tmp/sound-render.py');p.write_text(INNER)
subprocess.run([py,str(p)],env=env,check=True)
""".replace('INNER',repr(inner))
    compile(wrapper,'run.py','exec');compile(inner,'renderer','exec')
    (out/'run.py').write_text(wrapper)
    meta=dict(id=slug,title=slug.split('/')[1],code_file='run.py',language='python',kernel_type='script',is_private='true',enable_gpu='true',enable_internet='true',dataset_sources=[],competition_sources=[],kernel_sources=[],model_sources=[])
    (out/'kernel-metadata.json').write_text(json.dumps(meta,indent=2))
    (out/'payload-manifest.json').write_text(json.dumps(dict(source_sha256=sha(out/'run.py'),assets=assets,inputs=[],scope='sound prompts only; does not launch'),indent=2))
    return out

def mix(plan_file,master,assets_dir,output,unreviewed=False,review_file=None,boost_db=0):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    plan=validate(json.loads(Path(plan_file).read_text()));assets_dir=Path(assets_dir);out=Path(output)
    if sha(master)!=plan['master_sha256']:raise ContractError('Master hash mismatch')
    if not math.isfinite(boost_db):raise ContractError('Invalid boost')
    if out.exists() and any(out.iterdir()):raise ContractError('Output must be empty; preserve prior revisions')
    review=json.loads(Path(review_file).read_text()) if review_file else {}
    if not unreviewed and not review:raise ContractError('Hash-bound review required, or explicit --unreviewed-draft')
    with sf.SoundFile(master) as f:
        sr=f.samplerate;start=plan['start_frame'];end=plan['end_frame']
        if f.subtype!='PCM_16' or f.channels!=1 or not 0<=start<end<=len(f):raise ContractError('Expected mono PCM16 master and valid frame range')
        f.seek(start);pcm=f.read(end-start,dtype='int16')
    voice=pcm.astype(np.float64)/32768;bed=np.zeros_like(voice)
    rms=float(np.sqrt(np.mean(voice**2)));block=max(1,sr//10)
    env=np.array([np.sqrt(np.mean(voice[i:i+block]**2)) for i in range(0,len(voice),block)])
    duck=np.interp(np.arange(len(voice)),np.arange(len(env))*block,np.where(env>.015,.4,1))
    records={a['id']:a for a in json.loads((assets_dir/'manifest.json').read_text())};used=[]
    for c in plan['cues']:
        path=assets_dir/(c['asset']+'.wav');h=sha(path);r=records[c['asset']];spec=next(a for a in plan['assets'] if a['id']==c['asset'])
        if r['sha256']!=h or any(r[k]!=spec[k] for k in ('prompt','seconds','seed')):raise ContractError('Asset manifest mismatch')
        if not unreviewed and not (review.get(c['asset'],{}).get('approved') is True and review[c['asset']].get('sha256')==h):raise ContractError('Missing asset listening approval')
        x,xsr=sf.read(path,always_2d=True)
        if xsr!=44100 or not np.isfinite(x).all() or not 0<np.max(abs(x))<=.901 or abs(len(x)/xsr-spec['seconds'])>.15:raise ContractError('Invalid or clipped generated asset')
        x=x.mean(axis=1);g=math.gcd(xsr,sr);x=resample_poly(x,sr//g,xsr//g);x-=x.mean()
        a=round(c['start']*sr);b=round(c['end']*sr)
        if not 0<=a<b<=len(voice):raise ContractError('Cue outside selected part')
        if c['kind']=='ambience':
            fade=min(sr*2,len(x)//8);step=len(x)-fade;w=np.ones(len(x));w[:fade]=np.sin(np.linspace(0,np.pi/2,fade))**2;w[-fade:]=w[:fade][::-1]
            y=np.zeros(b-a+len(x));weights=np.zeros_like(y)
            for off in range(0,b-a,step):y[off:off+len(x)]+=x*w;weights[off:off+len(x)]+=w
            x=y[:b-a]/np.maximum(weights[:b-a],1e-9)
        else:x=x[:b-a]
        fade=min(sr,len(x)//4);x[:fade]*=np.linspace(0,1,fade);x[-fade:]*=np.linspace(1,0,fade)
        xrms=float(np.sqrt(np.mean(x*x)))
        if xrms<=1e-12:raise ContractError('Silent asset after channel conversion')
        x*=rms*10**((boost_db-c['below_speech_db'])/20)/xrms
        bed[a:a+len(x)]+=x*duck[a:a+len(x)];used.append(dict(asset=c['asset'],sha256=h))
    mixed=voice+bed
    if not np.isfinite(mixed).all() or np.max(abs(mixed))>=.97:raise ContractError('Insufficient headroom: reduce background boost; voice will not be limited')
    out.mkdir(parents=True,exist_ok=True)
    sf.write(out/'dry.wav',pcm,sr,subtype='PCM_16');assert np.array_equal(sf.read(out/'dry.wav',dtype='int16')[0],pcm)
    sf.write(out/'effects.wav',bed,sr,subtype='FLOAT');sf.write(out/'mix.wav',mixed,sr,subtype='PCM_24')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(out/'mix.wav'),'-c:a','libmp3lame','-b:a','96k',str(out/'mix.mp3')],check=True)
    decoded=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(out/'mix.mp3'),'-f','f32le','-'],capture_output=True,check=True)
    z=np.frombuffer(decoded.stdout,dtype=np.float32)
    if not len(z) or not np.isfinite(z).all() or np.max(abs(z))>=1:raise ContractError('MP3 decode/peak validation failed; do not deliver')
    manifest=dict(plan_sha256=sha(plan_file),master_sha256=sha(master),start_frame=start,end_frame=end,voice_pcm_sha256=hashlib.sha256(pcm.tobytes()).hexdigest(),voice_gain_db=0,background_boost_db=boost_db,duration=len(pcm)/sr,peak=float(np.max(abs(mixed))),decoded_peak=float(np.max(abs(z))),assets=used,asset_listening='unreviewed draft' if unreviewed else 'hash-bound approved',full_mix_listening='pending',files={p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in out.iterdir() if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));return out
