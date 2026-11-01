"""EPUB spine extraction. Preserves body wording with documented whitespace normalization."""
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
import posixpath,re
from urllib.parse import unquote,urlsplit
from .core import ContractError,digest,save,scaffold

class BodyText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.depth=0;self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='body':self.depth+=1
        if tag.lower() in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag.lower() in ('script','style'):self.skip=max(0,self.skip-1)
        if tag.lower()=='body':self.depth=max(0,self.depth-1)
    def handle_data(self,data):
        if self.depth and not self.skip:self.parts.append(data)

def safe_member(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts:raise ContractError('Unsafe EPUB member path')
    return str(p)

def extract(epub,project):
    project=Path(project)
    if project.exists() and any(project.iterdir()):raise ContractError('Use a new empty project directory')
    raw=Path(epub).read_bytes();documents=[]
    with ZipFile(epub) as z:
        if sum(x.file_size for x in z.infolist())>200_000_000:raise ContractError('EPUB exceeds 200 MB uncompressed limit')
        container=ET.fromstring(z.read('META-INF/container.xml'))
        opf=next((e.attrib['full-path'] for e in container.iter() if e.tag.endswith('rootfile')),None)
        if not opf:raise ContractError('EPUB has no OPF package')
        opf=safe_member(opf);package=ET.fromstring(z.read(opf));base=posixpath.dirname(opf)
        items={e.attrib['id']:e for e in package.iter() if e.tag.endswith('}item') or e.tag=='item'}
        refs=[e for e in package.iter() if e.tag.endswith('}itemref') or e.tag=='itemref']
        for i,ref in enumerate(refs,1):
            item=items[ref.attrib['idref']];href=urlsplit(item.attrib['href'])
            if href.scheme or href.netloc:raise ContractError('Remote EPUB spine item not supported')
            path=safe_member(posixpath.normpath(posixpath.join(base,unquote(href.path))))
            body=z.read(path)
            # EPUB content documents are XML/HTML; parser handles named HTML entities.
            declaration=re.search(br'encoding=[\'"]([^\'"]+)',body[:200],re.I)
            encoding=declaration[1].decode('ascii') if declaration else 'utf-8'
            parser=BodyText();parser.feed(body.decode(encoding));text=re.sub(r'\s+',' ',' '.join(parser.parts)).strip()
            chapter=f'{i:03d}';folder=project/'chapters'/chapter;folder.mkdir(parents=True,exist_ok=True)
            (folder/'source.txt').write_text(text,encoding='utf-8');save(folder/'script.json',scaffold(text))
            documents.append({'chapter':chapter,'spine_href':path,'linear':ref.attrib.get('linear','yes'),
                              'source_sha256':digest(text.encode()),'document_sha256':digest(body),'characters':len(text)})
    save(project/'manifest.json',{'epub_sha256':digest(raw),'normalization':'Body text-node order; join with spaces; collapse Unicode whitespace. No prose rewriting. Includes headings and notes.','documents':documents})
    save(project/'cast.json',{'characters':{'narrator':{'name':'Narrator','role':'Narration, descriptions and dialogue tags','evidence':['Narrative prose in the source text'],'role_reviewed':True,'voice_description':'','default_voice':None}},'voices':{}})
    return documents
