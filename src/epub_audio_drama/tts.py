"""Qwen3-TTS backend. Imported only by GPU commands."""
from pathlib import Path
import gc,json,time
from .core import ContractError,load,save,digest,canonical_hash,inside,bindings,rendering_units

DESIGN_MODEL='Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign'
BASE_MODEL='Qwen/Qwen3-TTS-12Hz-1.7B-Base'

def dependencies():
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    if not torch.cuda.is_available():raise ContractError('CUDA GPU required by this renderer; CPU inference has not been validated')
    return np,sf,torch,Qwen3TTSModel

def kwargs(torch,revision):
    return dict(device_map='cuda:0',dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
                attn_implementation='sdpa',revision=revision)

def design_voice(root,cid,vid,reference_text,language,revision):
    root=Path(root);cast=load(root/'cast.json')
    if cid not in cast['characters']:raise ContractError('Add character and review role first')
    c=cast['characters'][cid]
    if not c.get('role_reviewed') or not c.get('role') or not c.get('evidence') or not c.get('voice_description'):
        raise ContractError('Role, source evidence and matching description are required')
    if vid in cast['voices']:
        planned=cast['voices'][vid]
        if planned.get('status')!='planned' or planned.get('reference_sha256'):raise ContractError('Voice already locked; never silently regenerate')
        if (planned['character'],planned['design'],planned['reference_text'],planned['language'],planned['model_revision'])!=(cid,c['voice_description'],reference_text,language,revision):raise ContractError('Planned voice contract changed')
    if not reference_text.strip():raise ContractError('Reference transcript must be nonempty')
    if not vid or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for x in vid):
        raise ContractError('Voice ID must use letters, digits, hyphens or underscores')
    target=inside(root,f'voices/{vid}.wav')
    if target.exists():raise ContractError('Reference file already exists; preserve/reconcile it before retry')
    np,sf,torch,Model=dependencies();target.parent.mkdir(parents=True,exist_ok=True)
    model=Model.from_pretrained(DESIGN_MODEL,**kwargs(torch,revision))
    seed=int(digest(vid.encode())[:8],16)%2147483647;torch.manual_seed(seed)
    waves,sr=model.generate_voice_design(text=reference_text,language=language,instruct=c['voice_description'],max_new_tokens=2048)
    audio=np.asarray(waves[0]);assert audio.size and np.isfinite(audio).all()
    sf.write(target,audio,sr)
    cast['voices'][vid]={'character':cid,'design':c['voice_description'],'reference_audio':str(target.relative_to(root)),
                         'reference_text':reference_text,'reference_sha256':digest(target.read_bytes()),'language':language,
                         'seed':seed,'design_model':DESIGN_MODEL,'model_revision':revision,'allowed_chapters':[],
                         'status':'locked','quality_status':'generated; audible transcript and voice quality not verified'}
    if not c.get('default_voice'):c['default_voice']=vid
    save(root/'cast.json',cast)
    return cast['voices'][vid]

def render(root,chapter,revision='main',max_tokens=2048):
    root=Path(root);binding=bindings(root,chapter);script=load(root/f'chapters/{chapter}/script.json')
    units=rendering_units(script)
    config={'binding':binding,'base_model':BASE_MODEL,'model_revision':revision,'max_new_tokens':max_tokens,
            'sampling_seed':'SHA256 of source, voice and segment index','gap_seconds':0.15}
    run_id=canonical_hash(config)[:16];out=root/'runs'/chapter/run_id;out.mkdir(parents=True,exist_ok=True)
    save(out/'binding.json',config)
    np,sf,torch,Model=dependencies();save(out/'environment.json',{'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(),'model_revision_requested':revision})
    model=Model.from_pretrained(BASE_MODEL,**kwargs(torch,revision))
    prompts={vid:model.create_voice_clone_prompt(ref_audio=str(inside(root,v['reference_audio'])),ref_text=v['reference_text'],x_vector_only_mode=False) for vid,v in binding['voices'].items()}
    cast=load(root/'cast.json');records=[];rate=None;started=time.time();warnings=[]
    total_chars=sum(len(s['text']) for s in units)
    for i,s in enumerate(units):
        vid=s.get('voice') or cast['characters'][s['speaker']]['default_voice'];v=binding['voices'][vid]
        signature=canonical_hash({'segment':s,'voice':v,'config':config});path=out/f'{i:05d}.wav';meta=path.with_suffix('.json')
        if path.exists() or meta.exists():
            if not path.exists() or not meta.exists() or load(meta)['signature']!=signature:raise ContractError('Incomplete or mismatched checkpoint; preserve it and select a new run/version')
            info=load(meta)
            if digest(path.read_bytes())!=info['audio_sha256']:raise ContractError('Checkpoint audio changed')
            audio,sr=sf.read(path)
        else:
            seed=int(digest((binding['source_sha256']+vid+str(i)).encode())[:8],16)%2147483647
            torch.manual_seed(seed);tick=time.time()
            waves,sr=model.generate_voice_clone(text=s['text'],language=v['language'],voice_clone_prompt=prompts[vid],max_new_tokens=max_tokens)
            audio=np.asarray(waves[0]);assert audio.size and np.isfinite(audio).all();sf.write(path,audio,sr)
            info={'signature':signature,'audio_sha256':digest(path.read_bytes()),'synthesis_seconds':time.time()-tick,
                  'source_start':s['start'],'source_end':s['end'],'character':s['speaker'],'voice':vid,'seed':seed}
            save(meta,info)
        if not audio.size or not np.isfinite(audio).all():raise ContractError('Invalid audio samples')
        if rate is None:rate=sr
        if sr!=rate:raise ContractError('Sample-rate mismatch')
        duration=len(audio)/sr
        if duration>max(15,len(s['text'])*0.65) or duration<max(0.15,len(s['text'])*0.04):warnings.append({'index':i,'issue':'duration heuristic; check omission or repetition'})
        records.append({'index':i,'file':path.name,'duration':duration,'characters':len(s['text']),'voice':vid})
        done_chars=sum(x['characters'] for x in records);elapsed=time.time()-started
        progress={'completed_segments':len(records),'total_segments':len(units),'characters_completed':done_chars,
                  'characters_total':total_chars,'audio_seconds':sum(x['duration'] for x in records),'wall_seconds_this_session':elapsed,
                  'note':'Resumed checkpoints are included in counts; do not infer throughput from this wall time after resume.'}
        save(out/'progress.json',progress)
        if (i+1)%10==0 or i+1==len(units):print('PROGRESS '+json.dumps(progress),flush=True)
    del model,prompts;gc.collect();torch.cuda.empty_cache()
    with sf.SoundFile(out/'chapter.wav','w',samplerate=rate,channels=1,subtype='PCM_16') as stream:
        for record in records:
            audio,sr=sf.read(out/record['file']);stream.write(audio);stream.write(np.zeros(int(rate*0.15)))
    report={'status':'rendered','source_reconstruction':'PASS','audible_word_accuracy':'NOT VERIFIED',
            'voice_quality':'reference reuse is not a listening-based voice-drift check','duration_flags':warnings,
            'segments':records,'audio_sha256':digest((out/'chapter.wav').read_bytes()),'config':config}
    save(out/'report.json',report)
    ledger_path=root/'ledger.json';ledger=load(ledger_path) if ledger_path.exists() else {'chapters':{}}
    ledger['chapters'][chapter]={'run':str(out.relative_to(root)),'source_sha256':binding['source_sha256'],
                                'binding_sha256':binding['binding_sha256'],'voice_references':{k:v['reference_sha256'] for k,v in binding['voices'].items()},'audible_word_accuracy':'NOT VERIFIED'}
    save(ledger_path,ledger)
    return out
