"""Open-license Archive.org audio provider; no API key or third-party converter."""
import asyncio, base64, json, re, subprocess
from pathlib import PurePosixPath
from urllib.parse import urlparse, quote
import httpx

class SourceError(Exception):pass

def license_name(raw):
    value=raw[0] if isinstance(raw,list) and raw else raw
    if not isinstance(value,str):return None
    u=urlparse(value)
    if u.scheme not in {'http','https'} or u.hostname not in {'creativecommons.org','www.creativecommons.org'}:return None
    if re.fullmatch(r'/licenses/by(?:-sa)?/[1-4]\.0/?',u.path):return 'Creative Commons '+u.path.strip('/').replace('licenses/','').upper()
    if re.fullmatch(r'/publicdomain/(zero|mark)/1\.0/?',u.path):return 'CC0 / domínio público declarado pela fonte'
    return None

def reference(item,name):
    return 'ia:'+base64.urlsafe_b64encode(json.dumps([item,name],ensure_ascii=False,separators=(',',':')).encode()).decode().rstrip('=')

def decode_reference(value):
    try:
        data=json.loads(base64.urlsafe_b64decode(value[3:]+'='*(-len(value[3:])%4)))
        if not isinstance(data,list) or len(data)!=2:raise ValueError()
        item,name=data
        if item in {'.','..'} or not isinstance(item,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',item):raise ValueError()
        if not isinstance(name,str) or not 1<=len(name)<=400 or name.startswith('/') or '..' in PurePosixPath(name).parts or '\\' in name:raise ValueError()
        return item,name
    except Exception:raise SourceError('Referência de áudio inválida.') from None

async def get_json(client,url,params=None):
    try:
        async with client.stream('GET',url,params=params) as response:
            if response.status_code!=200:raise SourceError('O catálogo livre não respondeu. Tente mais tarde.')
            data=bytearray()
            async for chunk in response.aiter_bytes(32768):
                data.extend(chunk)
                if len(data)>4*1024*1024:raise SourceError('Resposta do catálogo excedeu o limite.')
            return json.loads(data)
    except httpx.HTTPError:raise SourceError('Falha de conexão com o catálogo livre.') from None

def tracks_from_item(identifier,item):
    meta=item.get('metadata',{});raw=meta.get('licenseurl');label=license_name(raw)
    if not label or item.get('is_dark') or str(meta.get('access-restricted-item','')).lower()=='true':return []
    artist=meta.get('creator','Internet Archive');artist=', '.join(str(x) for x in artist) if isinstance(artist,list) else str(artist)
    result=[]
    for f in item.get('files',[]):
        name=f.get('name','')
        try:size=int(f.get('size',0))
        except (ValueError,TypeError):continue
        if not re.search(r'\.(mp3|m4a|ogg|flac|wav)$',name,re.I) or not 0<size<=100*1024*1024 or str(f.get('private','')).lower()=='true':continue
        ref=reference(identifier,name)
        if len(ref)>1003:continue
        try:decode_reference(ref)
        except SourceError:continue
        title=str(f.get('title') or name)
        result.append({'video_id':ref,'title':title,'artist':artist,'duration':0,'license':label+' · '+str(raw),'download_allowed':True,'source':'https://archive.org/details/'+identifier,'filename':name,'identifier':identifier})
    # Prefer original MP3 over other formats. Each returned result names its exact file.
    return sorted(result,key=lambda v:not v['filename'].lower().endswith('.mp3'))

async def search_archive(settings,query):
    words=re.findall(r'[^\W_]+',query,flags=re.UNICODE)[:8]
    if not words:return []
    q='('+' AND '.join('"'+w[:50]+'"' for w in words)+') AND mediatype:audio AND licenseurl:*'
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as client:
        data=await get_json(client,'https://archive.org/advancedsearch.php',{'q':q,'output':'json','rows':8,'fl[]':'identifier'})
        ids=[v['identifier'] for v in data.get('response',{}).get('docs',[]) if re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',v.get('identifier',''))]
        async def item(identifier):
            try:return tracks_from_item(identifier,await get_json(client,'https://archive.org/metadata/'+quote(identifier,safe='')))
            except SourceError:return []
        groups=await asyncio.gather(*(item(i) for i in ids))
        return [v for group in groups for v in group[:3]][:18]

async def archive_metadata(value):
    identifier,name=decode_reference(value)
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as client:
        item=await get_json(client,'https://archive.org/metadata/'+quote(identifier,safe=''))
    return [v for v in tracks_from_item(identifier,item) if v['filename']==name]

def process_archive(db,job,folder):
    identifier,name=decode_reference(job['video'])
    db.state(job['id'],'downloading')
    source=folder/('source'+PurePosixPath(name).suffix.lower())
    url='https://archive.org/download/'+quote(identifier,safe='')+'/'+quote(name,safe='/')
    with httpx.Client(timeout=httpx.Timeout(180,connect=20,read=40),follow_redirects=False) as client:
        for attempt in range(6):
            host=urlparse(url)
            if host.scheme!='https' or not(host.hostname=='archive.org' or (host.hostname or '').endswith('.archive.org')):raise SourceError('Origem de áudio não permitida.')
            with client.stream('GET',url) as response:
                if 300<=response.status_code<400:
                    from urllib.parse import urljoin
                    url=urljoin(url,response.headers.get('Location',''));continue
                if response.status_code!=200:raise SourceError('O arquivo livre não está disponível neste momento.')
                total=0
                with source.open('wb') as output:
                    for chunk in response.iter_bytes(65536):
                        total+=len(chunk)
                        if total>100*1024*1024:raise SourceError('Áudio maior que o limite de 100 MB.')
                        output.write(chunk)
                break
        else:raise SourceError('Redirecionamentos demais ao obter o áudio.')
    db.state(job['id'],'converting')
    # Import lazily to support package tests and the standalone deployment module.
    try:from .app import convert_file
    except ImportError:from app import convert_file
    convert_file(source,folder/'audio.mp3');source.unlink(missing_ok=True)
