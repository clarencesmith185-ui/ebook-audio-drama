"""Text contracts, identity registry and reproducible voice bindings (stdlib only)."""
from pathlib import Path
import hashlib,json,re

class ContractError(ValueError):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)

def canonical_hash(value):
    return digest(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())

def inside(root,relative):
    root=Path(root).resolve();p=(root/relative).resolve()
    if root not in p.parents:
        raise ContractError('Path must remain inside the project')
    return p

def scaffold(source):
    # Quotation discovery is NOT speaker recognition. Include non-dialogue quotations in review.
    pattern=r'“[^“”]*”|「[^「」]*」|"[^"\n]+"'
    segments=[];cursor=0
    for match in re.finditer(pattern,source):
        if cursor<match.start():
            segments.append({'start':cursor,'end':match.start(),'speaker':'narrator'})
        segments.append({'start':match.start(),'end':match.end(),'speaker':None,'review':'unassigned quotation; identify speech vs signage/writing'})
        cursor=match.end()
    if cursor<len(source):segments.append({'start':cursor,'end':len(source),'speaker':'narrator'})
    for segment in segments:segment['text']=source[segment['start']:segment['end']]
    return {'source_sha256':digest(source.encode()),'source_reviewed':False,'notes':[], 'segments':segments}

def text_check(source,script):
    if script.get('source_sha256')!=digest(source.encode()):raise ContractError('Source hash mismatch')
    cursor=0
    for s in script['segments']:
        start,end=s['start'],s['end']
        if not isinstance(start,int) or not isinstance(end,int) or start!=cursor or not start<end<=len(source):
            raise ContractError('Source spans must be contiguous, ordered, nonempty and in bounds')
        if s['text']!=source[start:end]:raise ContractError('Segment differs from original normalized text')
        cursor=end
    if cursor!=len(source):raise ContractError('Incomplete source coverage')
    return True

def bindings(root,chapter,require_audio=True):
    root=Path(root);source=inside(root,f'chapters/{chapter}/source.txt').read_text(encoding='utf-8')
    script=load(root/f'chapters/{chapter}/script.json');cast=load(root/'cast.json')
    text_check(source,script)
    if not source.strip():raise ContractError('Empty spine document; review/skip it explicitly, not a renderable chapter')
    if script.get('source_reviewed') is not True:raise ContractError('Complete chapter speaker/quotation review first')
    result={}
    for i,s in enumerate(script['segments']):
        cid=s.get('speaker')
        if not cid or cid not in cast['characters']:raise ContractError(f'Unassigned/unknown speaker at segment {i}')
        c=cast['characters'][cid]
        if c.get('role_reviewed') is not True or not c.get('role') or not c.get('evidence'):
            raise ContractError(f'Review role and record source evidence for {cid}')
        if not c.get('voice_description'):raise ContractError(f'Missing role-matched voice description for {cid}')
        vid=s.get('voice') or c.get('default_voice')
        if not vid or vid not in cast['voices']:raise ContractError(f'Unassigned voice for {cid}')
        v=cast['voices'][vid]
        if v['character']!=cid:raise ContractError('Voice belongs to a different person')
        if not v.get('design') or not v.get('reference_text'):raise ContractError('Missing voice design/reference transcript')
        if vid!=c.get('default_voice') and chapter not in v.get('allowed_chapters',[]):
            raise ContractError('Non-default age/voice variant needs explicit chapter scope')
        if vid==c.get('default_voice') and v['design']!=c['voice_description']:
            raise ContractError('Description changed without a new voice version')
        path=inside(root,v['reference_audio'])
        if require_audio or v.get('reference_sha256'):
            if not path.is_file() or not v.get('reference_sha256'):raise ContractError(f'Missing locked reference: {vid}')
            if digest(path.read_bytes())!=v['reference_sha256']:raise ContractError(f'Reference changed: {vid}')
        elif v.get('status')!='planned':
            raise ContractError(f'Missing reference is not explicitly planned: {vid}')
        result[vid]={'character':cid,**v}
    return {'chapter':chapter,'source_sha256':script['source_sha256'],'script_sha256':canonical_hash(script),
            'voices':result,'binding_sha256':canonical_hash(result)}

def rendering_units(script,limit=160):
    # Attach punctuation-only/whitespace spans to preceding speech; never send them to TTS alone.
    merged=[]
    for s in script['segments']:
        key=(s['speaker'],s.get('voice'))
        nonverbal=not re.search(r'\w',s['text'])
        if merged and (nonverbal or merged[-1]['key']==key):
            merged[-1]['text']+=s['text'];merged[-1]['end']=s['end']
        else:merged.append({'key':key,'speaker':s['speaker'],'voice':s.get('voice'),'start':s['start'],'end':s['end'],'text':s['text']})
    units=[]
    for s in merged:
        if not re.search(r'\w',s['text']):raise ContractError('Leading punctuation-only text needs explicit segmentation review')
        offset=0
        while offset<len(s['text']):
            end=min(offset+limit,len(s['text']))
            if end<len(s['text']):
                breaks=[m.end()+offset for m in re.finditer(r'[。！？.!?;；]\s*',s['text'][offset:end]) if m.end()>=min(40,limit)]
                if breaks:end=breaks[-1]
            chunk=s['text'][offset:end]
            if not re.search(r'\w',chunk):
                if not units:raise ContractError('Nonverbal first chunk')
                units[-1]['text']+=chunk;units[-1]['end']=s['start']+end
            else:units.append({'speaker':s['speaker'],'voice':s['voice'],'start':s['start']+offset,'end':s['start']+end,'text':chunk})
            offset=end
    if ''.join(s['text'] for s in units)!=''.join(s['text'] for s in script['segments']):raise ContractError('Rendering chunk reconstruction failed')
    return units

def plan_voice(root,cid,vid,reference_text,language='English',revision='main'):
    root=Path(root);cast=load(root/'cast.json')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',vid):raise ContractError('Invalid voice ID')
    if vid in cast['voices']:raise ContractError('Voice version already exists')
    c=cast['characters'].get(cid,{})
    if c.get('role_reviewed') is not True or not all(c.get(k) for k in ('role','evidence','voice_description')):
        raise ContractError('Review role, evidence and matching design before planning a voice')
    if not reference_text.strip():raise ContractError('Reference text must be nonempty')
    cast['voices'][vid]={'character':cid,'design':c['voice_description'],'reference_audio':f'voices/{vid}.wav',
                        'reference_text':reference_text,'reference_sha256':None,'language':language,
                        'model_revision':revision,'allowed_chapters':[],'status':'planned'}
    if not c.get('default_voice'):c['default_voice']=vid
    save(root/'cast.json',cast)

def import_voices(root,returned):
    """Merge hash-verified voice records from a downloaded project; never replace a locked voice."""
    import shutil
    root=Path(root);returned=Path(returned);local=load(root/'cast.json');remote=load(returned/'cast.json');updates=[]
    for vid,new in remote['voices'].items():
        if not new.get('reference_sha256'):continue
        old=local['voices'].get(vid)
        if not old:raise ContractError(f'Unplanned returned voice: {vid}')
        for key in ('character','design','reference_audio','reference_text','language','model_revision'):
            if old[key]!=new[key]:raise ContractError(f'Returned voice contract differs: {vid}/{key}')
        if old.get('reference_sha256') and old['reference_sha256']!=new['reference_sha256']:
            raise ContractError('Cannot replace an immutable voice')
        src=inside(returned,new['reference_audio']);data=src.read_bytes()
        if digest(data)!=new['reference_sha256']:raise ContractError('Returned reference hash mismatch')
        dest=inside(root,new['reference_audio'])
        if dest.exists() and digest(dest.read_bytes())!=new['reference_sha256']:raise ContractError('Local reference already differs')
        updates.append((vid,new,src,dest))
    # Validate the entire merge before the first mutation.
    for vid,new,src,dest in updates:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():shutil.copy2(src,dest)
        local['voices'][vid]=new
    save(root/'cast.json',local)
    return [vid for vid,_,_,_ in updates]
