"""Single-worker QA backend: official YouTube search and authorized MP3 jobs."""
from __future__ import annotations
import asyncio, contextlib, hashlib, os, re, secrets, shutil, sqlite3, subprocess, time, uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

@dataclass
class Settings:
    root: Path = field(default_factory=lambda: Path(os.getenv("MEDIA_DATA_DIR", "./.media-data")))
    api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", ""))
    authorized_ids: frozenset[str] = field(default_factory=lambda: frozenset(filter(None, os.getenv("AUTHORIZED_VIDEO_IDS", "").split(","))))
    retention_seconds: int = 86400

class JobInput(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")

class Database:
    def __init__(self, root: Path):
        self.root = root; root.mkdir(parents=True, exist_ok=True)
        self.path = root / "jobs.sqlite3"
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, video TEXT NOT NULL,
              title TEXT NOT NULL, artist TEXT NOT NULL, license TEXT NOT NULL,
              state TEXT NOT NULL, error TEXT, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner,created);
            """)
            c.execute("UPDATE jobs SET state='failed',error='O servidor reiniciou. Tente novamente.' WHERE state IN ('downloading','converting')")
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10); c.row_factory = sqlite3.Row; return c
    def state(self, job: str, state: str, error=None):
        with self.connect() as c: c.execute("UPDATE jobs SET state=?, error=? WHERE id=?", (state,error,job))

class Limit:
    def __init__(self): self.buckets = defaultdict(deque)
    def check(self, key, count, seconds=60):
        now=time.monotonic(); q=self.buckets[key]
        while q and q[0] < now-seconds: q.popleft()
        if len(q)>=count: raise HTTPException(429,"Aguarde antes de tentar novamente.")
        q.append(now)
        if len(self.buckets)>5000:
            self.buckets=defaultdict(deque,{k:v for k,v in self.buckets.items() if v and v[-1]>now-3600})

def duration_seconds(value: str) -> int:
    m=re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",value)
    return sum(int(v or 0)*f for v,f in zip(m.groups(),(3600,60,1))) if m else 0

def convert_file(source: Path, destination: Path):
    probe=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(source)],capture_output=True,timeout=20,check=True)
    length=float(probe.stdout.strip())
    if not 0<length<=1200: raise ValueError("Unsupported duration")
    subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y","-protocol_whitelist","file,pipe","-i",str(source),"-map","0:a:0","-vn","-sn","-dn","-c:a","libmp3lame","-b:a","192k",str(destination)],capture_output=True,timeout=120,check=True)
    if not destination.is_file() or not 0<destination.stat().st_size<=40*1024*1024: raise ValueError("Invalid output")

async def youtube(settings: Settings, resource: str, params: dict):
    if not settings.api_key: raise HTTPException(503,"Configure YOUTUBE_API_KEY no servidor para ativar a busca.")
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        try: response=await client.get("https://www.googleapis.com/youtube/v3/"+resource,params={**params,"key":settings.api_key})
        except httpx.HTTPError: raise HTTPException(502,"Falha ao consultar o YouTube.") from None
    if response.status_code!=200: raise HTTPException(502,"O YouTube não aceitou a consulta. Confira a chave e a cota no servidor.")
    return response.json()

async def metadata(settings:Settings, ids:list[str]):
    data=await youtube(settings,"videos",{"part":"snippet,status,contentDetails","id":",".join(ids)})
    results=[]
    for item in data.get("items",[]):
        snippet=item["snippet"]; status=item.get("status",{}); detail=item.get("contentDetails",{})
        seconds=duration_seconds(detail.get("duration","")); video=item["id"]
        allowed=(status.get("license")=="creativeCommon" or video in settings.authorized_ids)
        allowed=allowed and status.get("privacyStatus")=="public" and 0<seconds<=1200 and snippet.get("liveBroadcastContent","none")=="none"
        results.append({"video_id":video,"title":snippet["title"],"artist":snippet.get("channelTitle",""),"duration":seconds,"license":"CC BY (declarada no YouTube)" if status.get("license")=="creativeCommon" else "Autorização cadastrada pelo operador" if video in settings.authorized_ids else "Sem autorização de download cadastrada","download_allowed":allowed})
    return results

async def search(settings:Settings, query:str):
    data=await youtube(settings,"search",{"part":"snippet","q":query,"type":"video","videoCategoryId":"10","maxResults":10})
    ids=[v["id"]["videoId"] for v in data.get("items",[]) if "videoId" in v.get("id",{})]
    return await metadata(settings,ids) if ids else []

def process_youtube(db:Database, job:dict, folder:Path):
    if shutil.disk_usage(db.root).free < 512*1024*1024: raise ValueError("Insufficient disk space")
    db.state(job["id"],"downloading")
    subprocess.run(["yt-dlp","--js-runtimes","node","--no-playlist","--no-progress","--no-warnings","--socket-timeout","15","--retries","2","--max-filesize","100M","--match-filter","duration <= 1200 & !is_live","-f","bestaudio/best","-o",str(folder/"source.%(ext)s"),"--","https://www.youtube.com/watch?v="+job["video"]],capture_output=True,timeout=240,check=True)
    candidates=[p for p in folder.glob("source.*") if p.suffix.lower() in {".webm",".m4a",".mp4",".ogg",".opus",".mp3",".wav"}]
    if len(candidates)!=1: raise ValueError("No valid source")
    db.state(job["id"],"converting"); convert_file(candidates[0],folder/"audio.mp3")
    for p in candidates: p.unlink(missing_ok=True)

def create_app(settings:Settings|None=None):
    settings=settings or Settings();db=Database(settings.root);limit=Limit()
    @asynccontextmanager
    async def lifespan(app):
        async def worker():
            last_cleanup=0.0
            while True:
                if time.monotonic()-last_cleanup>300:
                    with db.connect() as c:
                        stale=c.execute("SELECT id FROM jobs WHERE created<?",(time.time()-settings.retention_seconds,)).fetchall()
                        for j in stale: shutil.rmtree(settings.root/j["id"],ignore_errors=True)
                        c.execute("DELETE FROM jobs WHERE created<?",(time.time()-settings.retention_seconds,))
                        c.execute("DELETE FROM sessions WHERE created<?",(time.time()-7*86400,))
                    last_cleanup=time.monotonic()
                with db.connect() as c: row=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                if row is None: await asyncio.sleep(.5);continue
                job=dict(row);folder=settings.root/job["id"];folder.mkdir(exist_ok=True)
                try:
                    # Recheck authorization immediately before fetching the media.
                    videos=await app.state.metadata_provider(settings,[job["video"]])
                    if not videos or not videos[0]["download_allowed"]: raise ValueError("Authorization changed")
                    await asyncio.to_thread(app.state.processor,db,job,folder)
                    db.state(job["id"],"ready")
                except Exception:
                    shutil.rmtree(folder,ignore_errors=True)
                    db.state(job["id"],"failed","A fonte não permitiu concluir a conversão. Tente novamente mais tarde.")
        task=asyncio.create_task(worker())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
    app=FastAPI(title="Music Indie media backend",version="0.2.0",lifespan=lifespan)
    app.state.search_provider=search;app.state.metadata_provider=metadata;app.state.processor=process_youtube;app.state.db=db
    def owner(authorization:str=Header(default="")):
        token=authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}",token): raise HTTPException(401,"Conecte novamente ao backend.")
        digest=hashlib.sha256(token.encode()).hexdigest()
        with db.connect() as c: row=c.execute("SELECT created FROM sessions WHERE token_hash=?",(digest,)).fetchone()
        if not row or row["created"]<time.time()-7*86400: raise HTTPException(401,"Sessão expirada. Conecte novamente.")
        return digest
    def get_job(job_id,who):
        with db.connect() as c: row=c.execute("SELECT * FROM jobs WHERE id=? AND owner=?",(job_id,who)).fetchone()
        if not row: raise HTTPException(404,"Conversão não encontrada.")
        return dict(row)
    @app.get("/health")
    def health(): return {"status":"ok","search_configured":bool(settings.api_key)}
    @app.post("/sessions",status_code=201)
    def session(request:Request):
        limit.check("session:"+(request.client.host if request.client else "unknown"),20,3600)
        token=secrets.token_urlsafe(32)
        with db.connect() as c: c.execute("INSERT INTO sessions VALUES (?,?)",(hashlib.sha256(token.encode()).hexdigest(),time.time()))
        return {"token":token,"expires_in":7*86400}
    @app.get("/search")
    async def find(q:str,who=Depends(owner)):
        q=q.strip()
        if not 2<=len(q)<=120: raise HTTPException(422,"Busque por um nome entre 2 e 120 caracteres.")
        limit.check("search:"+who,5)
        return {"items":await app.state.search_provider(settings,q)}
    @app.post("/jobs",status_code=202)
    async def add(body:JobInput,who=Depends(owner)):
        limit.check("job:"+who,5)
        videos=await app.state.metadata_provider(settings,[body.video_id])
        if not videos: raise HTTPException(404,"Vídeo indisponível.")
        v=videos[0]
        if not v["download_allowed"]: raise HTTPException(403,"Esta gravação não tem autorização de download cadastrada ou excede os limites.")
        job=uuid.uuid4().hex
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            active=c.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND state IN ('queued','downloading','converting')",(who,)).fetchone()[0]
            total=c.execute("SELECT COUNT(*) FROM jobs WHERE owner=?",(who,)).fetchone()[0]
            global_active=c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','downloading','converting')").fetchone()[0]
            if active>=2 or total>=20 or global_active>=50: raise HTTPException(429,"Limite da fila atingido. Aguarde a conclusão ou a limpeza dos arquivos temporários.")
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,NULL,?)",(job,who,v["video_id"],v["title"],v["artist"],v["license"],"queued",time.time()))
        result=get_job(job,who);result.pop("owner");return result
    @app.get("/jobs/{job_id}")
    def status(job_id:str,who=Depends(owner)):
        row=get_job(job_id,who);row.pop("owner");return row
    @app.get("/jobs/{job_id}/audio")
    def audio(job_id:str,who=Depends(owner)):
        row=get_job(job_id,who);file=settings.root/row["id"]/"audio.mp3"
        if row["state"]!="ready" or not file.is_file(): raise HTTPException(409,"O MP3 ainda não está disponível.")
        return FileResponse(file,media_type="audio/mpeg",filename=row["id"]+".mp3",headers={"Cache-Control":"private, no-store"})
    return app
