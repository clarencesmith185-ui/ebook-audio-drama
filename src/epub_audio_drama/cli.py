"""Explicit review, local rendering and opt-in provider commands."""
import argparse,json,sys,subprocess
from pathlib import Path
from .core import ContractError,load,save,bindings,plan_voice,digest

def make_demo(project):
    project=Path(project)
    if project.exists() and any(project.iterdir()):raise ContractError('Use an empty demo project directory')
    parts=[('narrator','Rain tapped the café window. '),('maya','“The last train leaves at nine,” '),
           ('narrator','Maya said. '),('eli','“Then we still have time,” '),('narrator','Eli replied, setting down his cup.')]
    source=''.join(t for _,t in parts);segments=[];cursor=0
    for cid,text in parts:
        segments.append({'speaker':cid,'start':cursor,'end':cursor+len(text),'text':text});cursor+=len(text)
    folder=project/'chapters/001';folder.mkdir(parents=True,exist_ok=True);(folder/'source.txt').write_text(source,encoding='utf-8')
    save(folder/'script.json',{'source_sha256':digest(source.encode()),'source_reviewed':True,'notes':['Original demo written for this repository; not taken from a book.'],'segments':segments})
    cast={'characters':{},'voices':{}}
    for cid,name,role,evidence,design in [
        ('narrator','Narrator','Reads setting and attribution tags','Narrative spans in demo','Adult neutral English narrator, warm medium-low register, clear diction, restrained delivery.'),
        ('maya','Maya','Adult traveler checking train time','Explicit dialogue tag: Maya said','Adult female English voice, medium register, clear and matter-of-fact, slightly brisk; distinct from narrator.'),
        ('eli','Eli','Adult traveler responding to Maya','Explicit dialogue tag: Eli replied','Adult male English voice, lighter medium register, calm conversational cadence; distinct from narrator.')]:
        cast['characters'][cid]={'name':name,'role':role,'evidence':[evidence],'role_reviewed':True,'voice_description':design,'default_voice':None,'aliases':[]}
    save(project/'cast.json',cast)
    for cid in cast['characters']:plan_voice(project,cid,cid+'-v1','The morning light falls across the table. There is time to think before the journey begins.')
    return project

def main():
    ap=argparse.ArgumentParser(prog='epub-drama');sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('llm-prepare');p.add_argument('project');p.add_argument('chapter');p.add_argument('--config',required=True);p.add_argument('--output')
    p=sub.add_parser('episodes',help='Split an existing speech render at sentence pauses');p.add_argument('project');p.add_argument('chapter');p.add_argument('run');p.add_argument('output');p.add_argument('--episode-minutes',type=float,required=True);p.add_argument('--mp3',action='store_true')
    p=sub.add_parser('extract');p.add_argument('epub');p.add_argument('project')
    p=sub.add_parser('demo');p.add_argument('project')
    p=sub.add_parser('validate');p.add_argument('project');p.add_argument('chapter');p.add_argument('--allow-planned',action='store_true')
    p=sub.add_parser('voice-plan');p.add_argument('project');p.add_argument('character');p.add_argument('voice');p.add_argument('--reference-text',required=True);p.add_argument('--language',default='English');p.add_argument('--revision',default='main')
    p=sub.add_parser('voice-design');p.add_argument('project');p.add_argument('voice')
    p=sub.add_parser('render');p.add_argument('project');p.add_argument('chapter');p.add_argument('--revision',default='main');p.add_argument('--backend',choices=('local','kaggle'));p.add_argument('--owner');p.add_argument('--run-dir');p.add_argument('--reference-kernel');p.add_argument('--design-missing',action='store_true')
    p=sub.add_parser('kaggle-package');p.add_argument('project');p.add_argument('chapter');p.add_argument('slug');p.add_argument('destination');p.add_argument('--reference-kernel');p.add_argument('--design-missing',action='store_true')
    p=sub.add_parser('import-voices');p.add_argument('project');p.add_argument('returned_project')
    p=sub.add_parser('mp3');p.add_argument('wav');p.add_argument('output')
    p=sub.add_parser('sound-package');p.add_argument('plan');p.add_argument('slug');p.add_argument('destination')
    p=sub.add_parser('sound-mix');p.add_argument('plan');p.add_argument('master');p.add_argument('assets');p.add_argument('output');p.add_argument('--unreviewed-draft',action='store_true');p.add_argument('--review');p.add_argument('--background-boost-db',type=float,default=0)
    p=sub.add_parser('kaggle-run');p.add_argument('project');p.add_argument('chapter');p.add_argument('--owner');p.add_argument('--run-dir');p.add_argument('--reference-kernel');p.add_argument('--design-missing',action='store_true')
    p=sub.add_parser('sound-run');p.add_argument('plan');p.add_argument('--project');p.add_argument('--owner');p.add_argument('--run-dir')
    p=sub.add_parser('kaggle-status');p.add_argument('receipt')
    p=sub.add_parser('kaggle-download');p.add_argument('receipt');p.add_argument('--destination')
    a=ap.parse_args()
    try:
        if a.command=='llm-prepare':
            from .llm import prepare
            print(prepare(a.project,a.chapter,a.config,a.output))
        elif a.command=='episodes':
            from .episodes import export
            print(export(a.project,a.chapter,a.run,a.output,a.episode_minutes,a.mp3))
        elif a.command in ('kaggle-run','sound-run'):
            from .remote import run
            if a.command=='kaggle-run':print(run('speech',a.project,a.chapter,owner=a.owner,run_dir=a.run_dir,design_missing=a.design_missing,reference_kernel=a.reference_kernel))
            else:print(run('sound',project=a.project,plan=a.plan,owner=a.owner,run_dir=a.run_dir))
        elif a.command=='kaggle-status':
            from .remote import status
            print(json.dumps(status(a.receipt),indent=2))
        elif a.command=='kaggle-download':
            from .remote import download
            print(download(a.receipt,a.destination))
        elif a.command=='sound-package':
            from .sound import package
            print(package(a.plan,a.slug,a.destination))
        elif a.command=='sound-mix':
            from .sound import mix
            print(mix(a.plan,a.master,a.assets,a.output,a.unreviewed_draft,a.review,a.background_boost_db))
        elif a.command=='extract':
            from .epub import extract
            print(json.dumps(extract(a.epub,a.project),ensure_ascii=False,indent=2))
        elif a.command=='demo':print(make_demo(a.project))
        elif a.command=='validate':
            b=bindings(a.project,a.chapter,require_audio=not a.allow_planned)
            print(json.dumps({'status':'PASS','scope':'text/identity/voice contracts only; not audible quality','planned_references_allowed':a.allow_planned,'binding_sha256':b['binding_sha256']},indent=2))
        elif a.command=='voice-plan':plan_voice(a.project,a.character,a.voice,a.reference_text,a.language,a.revision)
        elif a.command=='voice-design':
            from .tts import design_voice
            v=load(Path(a.project)/'cast.json')['voices'][a.voice]
            print(json.dumps(design_voice(a.project,v['character'],a.voice,v['reference_text'],v['language'],v['model_revision']),indent=2))
        elif a.command=='render':
            from .remote import backend,run
            if backend(a.project,a.backend)=='kaggle':
                if a.revision!='main':raise ContractError('Kaggle uses model revisions locked in cast.json; --revision is local only')
                print(run('speech',a.project,a.chapter,owner=a.owner,run_dir=a.run_dir,design_missing=a.design_missing,reference_kernel=a.reference_kernel))
            else:
                if a.owner or a.run_dir or a.reference_kernel or a.design_missing:raise ContractError('Kaggle options require --backend kaggle or configured Kaggle backend')
                from .tts import render
                print(render(a.project,a.chapter,a.revision))
        elif a.command=='kaggle-package':
            from .kaggle import package
            print(package(a.project,a.chapter,a.slug,a.destination,a.reference_kernel,a.design_missing))
        elif a.command=='import-voices':
            from .core import import_voices
            print(json.dumps(import_voices(a.project,a.returned_project)))
        elif a.command=='mp3':
            if Path(a.output).exists():raise ContractError('Output already exists; choose a new filename')
            subprocess.run(['ffmpeg','-nostdin','-i',a.wav,'-codec:a','libmp3lame','-b:a','96k',a.output],check=True)
    except (ContractError,KeyError,FileNotFoundError,json.JSONDecodeError) as e:
        ap.exit(2,f'Error: {e}\n')

if __name__=='__main__':main()
