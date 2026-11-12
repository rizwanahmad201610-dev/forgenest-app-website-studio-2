"""ForgeNest: a local Windows GUI website for creating installers and static websites.
No web framework required. Python 3.9+; Windows required only for EXE builds.
"""
import base64
import datetime as dt
import html
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'site'
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
DB = DATA / 'projects.sqlite'
HOST = '127.0.0.1'
PORT = int(os.environ.get('FORGENEST_PORT', '8765'))
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='builder')
MAX_UPLOAD = 300 * 1024 * 1024
DBLOCK = threading.RLock()


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            status TEXT NOT NULL, created TEXT NOT NULL, detail TEXT DEFAULT '',
            icon TEXT DEFAULT '', artifact TEXT DEFAULT '', archive TEXT DEFAULT '',
            log TEXT DEFAULT '' )''')


def db_one(pid):
    with DBLOCK, sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        row = c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        return dict(row) if row else None


def db_all():
    with DBLOCK, sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute('SELECT * FROM projects ORDER BY created DESC')]


def db_create(pid, name, kind, status, detail=''):
    with DBLOCK, sqlite3.connect(DB) as c:
        c.execute('INSERT INTO projects (id,name,kind,status,created,detail) VALUES (?,?,?,?,?,?)',
                  (pid,name,kind,status,dt.datetime.now().astimezone().isoformat(timespec='seconds'),detail))


def db_update(pid, **fields):
    fields = {k:v for k,v in fields.items() if k in {'name','status','detail','icon','artifact','archive','log'}}
    if fields:
        with DBLOCK, sqlite3.connect(DB) as c:
            c.execute('UPDATE projects SET ' + ', '.join(k+'=?' for k in fields) + ' WHERE id=?', (*fields.values(), pid))


def slug(s, maxlen=55):
    text = re.sub(r'[^A-Za-z0-9_-]+', '-', s.strip()).strip('-_')[:maxlen]
    return text or 'MyApp'


def valid_name(s):
    if not s or len(s)>64 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]*', s):
        raise ValueError('Use a name with letters, numbers, spaces, hyphens or underscores (up to 64 characters).')
    if s.endswith('.') or s.endswith(' '):
        raise ValueError('Name cannot end with a dot or space.')
    return s


def clean_rel(name):
    name = name.replace('\\','/').strip('/')
    p = Path(name)
    if not name or name.startswith('.') or any(part in ('.','..','') for part in p.parts) or ':' in name:
        raise ValueError('Invalid resource path: ' + name[:100])
    if len(name)>200: raise ValueError('Resource path too long.')
    return name


def parse_form(headers, raw):
    content_type = headers.get('Content-Type', '')
    if 'multipart/form-data' not in content_type:
        raise ValueError('Expected a file-upload form.')
    payload = b'MIME-Version: 1.0\r\nContent-Type: ' + content_type.encode('latin-1') + b'\r\n\r\n' + raw
    msg = BytesParser(policy=default).parsebytes(payload)
    fields, files = {}, {}
    for part in msg.iter_parts():
        disposition = part.get('Content-Disposition', '')
        if not disposition.startswith('form-data'): continue
        field = part.get_param('name', header='content-disposition')
        filename = part.get_filename()
        content = part.get_payload(decode=True) or b''
        if filename is None:
            fields[field] = content.decode('utf-8',errors='replace')
        else:
            files.setdefault(field,[]).append((Path(filename).name,content))
    return fields, files


def _command_exists(cmd):
    return bool(shutil.which(cmd))


def interpreters():
    found = {}
    def add(path):
        try:
            real = str(Path(path).resolve())
            if not Path(real).is_file() or real in found: return
            p = subprocess.run([real,'-c','import sys;print("%d.%d.%d"%sys.version_info[:3])'],
                               text=True, capture_output=True, timeout=4, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if p.returncode==0 and re.fullmatch(r'\d+\.\d+\.\d+',p.stdout.strip()): found[real]=p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired): pass
    add(sys.executable)
    if os.name=='nt':
        try:
            p=subprocess.run(['py','-0p'],text=True,capture_output=True,timeout=7,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for line in (p.stdout+p.stderr).splitlines():
                m=re.search(r'([A-Za-z]:\\[^\r\n]*?python(?:w)?\.exe)\s*$',line,re.I)
                if m: add(m.group(1))
        except (OSError,subprocess.TimeoutExpired): pass
    for name in ('python','python3'):
        path=shutil.which(name)
        if path: add(path)
    return [{'path':path,'version':ver} for path,ver in sorted(found.items(),key=lambda v:v[1],reverse=True)]


def jdks():
    found={}
    paths=[]
    for env in ('JAVA_HOME','JDK_HOME'):
        if os.environ.get(env): paths.append(Path(os.environ[env])/'bin'/'jpackage.exe')
    if shutil.which('jpackage'):paths.append(Path(shutil.which('jpackage')))
    if os.name=='nt':
        for base in (Path('C:/Program Files/Java'), Path('C:/Program Files/Eclipse Adoptium'), Path('C:/Program Files/Microsoft'), Path('C:/Program Files/Amazon Corretto')):
            if base.exists(): paths.extend(base.glob('*/bin/jpackage.exe'))
    for path in paths:
        try:
            path=path.resolve()
            if path.exists() and str(path) not in found:
                java=path.with_name('java.exe' if os.name=='nt' else 'java')
                p=subprocess.run([str(java),'-version'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                ver=re.search(r'"([^"]+)"',p.stderr+p.stdout)
                found[str(path)]=ver.group(1) if ver else 'Installed JDK'
        except (OSError,subprocess.TimeoutExpired):pass
    return [{'path':k,'version':v} for k,v in found.items()]


def find_inno():
    candidates=[]
    x=shutil.which('ISCC.exe') or shutil.which('iscc')
    if x:candidates.append(Path(x))
    if os.name=='nt':
        for env in ('ProgramFiles','ProgramFiles(x86)'):
            p=Path(os.environ.get(env,'C:/Program Files'))
            for v in ('Inno Setup 7','Inno Setup 6'):
                candidates.append(p/v/'ISCC.exe')
    return next((str(p) for p in candidates if p.is_file()),None)


def png_to_ico(data):
    # Prefer multi-size icons via Pillow, but do not require it for already-good PNGs.
    try:
        from PIL import Image
        im=Image.open(io.BytesIO(data)).convert('RGBA')
        if max(im.size)>2000: im.thumbnail((2000,2000))
        out=io.BytesIO()
        im.save(out,format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
        return out.getvalue()
    except ImportError:
        if data[:8]!=b'\x89PNG\r\n\x1a\n':
            raise ValueError('Upload a PNG or ICO image. JPG conversion needs Pillow installed.')
        w,h=struct.unpack('>II',data[16:24])
        if w>256 or h>256: raise ValueError('For PNG without Pillow, use an image no larger than 256x256.')
        directory=struct.pack('<HHH',0,1,1)
        entry=struct.pack('<BBBBHHII',0 if w==256 else w,0 if h==256 else h,0,0,1,32,len(data),22)
        return directory+entry+data


def write_icon(source, dest):
    if not source: return ''
    name,data=source
    suffix=Path(name).suffix.lower()
    if suffix=='.ico':
        if len(data)<22 or data[:4]!=b'\x00\x00\x01\x00':raise ValueError('This .ico file is not a valid Windows icon.')
        dest.write_bytes(data)
    elif suffix in {'.png','.jpg','.jpeg','.webp','.bmp'}:
        dest.write_bytes(png_to_ico(data))
    else: raise ValueError('Use a PNG, JPG, WEBP or ICO logo image.')
    return str(dest)


def logline(pid, s):
    with DBLOCK:
        d=DATA/pid
        with (d/'build.log').open('a',encoding='utf8',errors='replace') as f:f.write(s.rstrip()+'\n')


def runstep(pid, cmd, cwd=None, timeout=1800):
    logline(pid,'> '+ ' '.join('"'+x+'"' if ' ' in x else x for x in map(str,cmd)))
    startup=getattr(subprocess,'CREATE_NO_WINDOW',0)
    with subprocess.Popen(list(map(str,cmd)),cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,errors='replace',creationflags=startup) as p:
        start=time.monotonic()
        for line in p.stdout:
            logline(pid,line.rstrip())
            if time.monotonic()-start>timeout:
                p.kill();raise RuntimeError('Build took too long and was stopped.')
        result=p.wait()
    if result:raise RuntimeError('Build step failed. Open Build Log in Projects for details.')


def quote_iss(s):
    return s.replace('"','""').replace('\r',' ').replace('\n',' ')


def make_installer(pid, name, app_image_dir, app_exe, icon_path):
    iscc=find_inno()
    if not iscc: raise RuntimeError('Inno Setup is missing. Install Inno Setup from jrsoftware.org/isdl.php and try Build again.')
    d=DATA/pid
    out=d/'output';out.mkdir(exist_ok=True)
    filename=slug(name)+'_Setup'
    script=d/'installer.iss'
    lines=['[Setup]', 'AppId={{'+str(uuid.uuid5(uuid.NAMESPACE_URL,'forgenest:'+pid))+'}',
           'AppName='+name,'AppVersion=1.0', 'DefaultDirName={autopf}\\'+slug(name),
           'DefaultGroupName='+name, 'OutputDir='+str(out),'OutputBaseFilename='+filename,
           'Compression=lzma2','SolidCompression=yes','WizardStyle=modern','PrivilegesRequired=lowest']
    if icon_path: lines.append('SetupIconFile='+str(icon_path))
    lines.extend(['UninstallDisplayIcon={app}\\'+app_exe, '[Files]'])
    if app_image_dir:
        lines.append('Source: "'+quote_iss(str(app_image_dir/'*'))+'"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs')
    else:
        lines.append('Source: "'+quote_iss(str(d/'build'/'dist'/app_exe))+'"; DestDir: "{app}"; Flags: ignoreversion')
    lines.extend(['[Tasks]','Name: desktopicon; Description: "Create desktop shortcut"; Flags: unchecked',
                  '[Icons]','Name: "{autoprograms}\\'+name+'"; Filename: "{app}\\'+app_exe+'"',
                  'Name: "{autodesktop}\\'+name+'"; Filename: "{app}\\'+app_exe+'"; Tasks: desktopicon',
                  '[Run]','Filename: "{app}\\'+app_exe+'"; Description: "Launch '+name+'"; Flags: nowait postinstall skipifsilent'])
    script.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    runstep(pid,[iscc,str(script)])
    product=out/(filename+'.exe')
    if not product.is_file():
        matches=list(out.glob('*.exe'))
        if not matches: raise RuntimeError('The installer compiler finished but no EXE was found.')
        product=matches[0]
    return product


def make_archive(pid):
    d=DATA/pid
    archive=d/'project_export.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for item in d.rglob('*'):
            if not item.is_file() or item==archive: continue
            if any(p in {'build','work'} for p in item.relative_to(d).parts):continue
            # The project's original files, site files, installer and build log are exportable.
            z.write(item,item.relative_to(d))
    db_update(pid,archive=str(archive))


def execute_build(pid, setting):
    d=DATA/pid; files=d/'source'; build=d/'build'; build.mkdir(exist_ok=True)
    name=setting['name'];kind=setting['kind'];runtime=setting['runtime']
    icon=str(d/'logo.ico') if (d/'logo.ico').is_file() else None
    try:
        if os.name!='nt':raise RuntimeError('Windows .exe installers must be built on Windows. Run this website on a Windows PC.')
        if not find_inno():raise RuntimeError('Inno Setup is not installed. Install it once from https://jrsoftware.org/isdl.php (ask a parent for help).')
        db_update(pid,status='building',detail='Compiling '+kind.title()+' app…')
        if kind=='python':
            pythons={x['path'] for x in interpreters()}
            if runtime not in pythons:raise RuntimeError('Selected Python version is not installed on this computer.')
            try:
                p=subprocess.run([runtime,'-m','PyInstaller','--version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                installed=p.returncode==0
            except Exception:installed=False
            if not installed:
                if not setting.get('install_build_tools'):raise RuntimeError('PyInstaller is missing for this Python version. Tick "Install missing build tool automatically" and build again.')
                logline(pid,'Installing PyInstaller for selected Python version…')
                runstep(pid,[runtime,'-m','pip','install','pyinstaller'])
            entry=files/clean_rel(setting['entry'])
            if not entry.is_file() or entry.suffix.lower() not in {'.py','.pyw'}:raise RuntimeError('Select a valid .py or .pyw file.')
            req=files/'requirements.txt'
            if req.exists() and setting.get('install_requirements'):
                runstep(pid,[runtime,'-m','pip','install','-r',str(req)])
            dist=build/'dist';dist.mkdir(exist_ok=True)
            cmd=[runtime,'-m','PyInstaller','--noconfirm','--clean','--onefile','--name',slug(name),
                 '--distpath',str(dist),'--workpath',str(build/'cache'),'--specpath',str(build)]
            if setting.get('gui',True):cmd.append('--windowed')
            if icon:cmd+=['--icon',icon]
            for src in files.rglob('*'):
                if not src.is_file() or src==entry:continue
                rel=src.relative_to(files)
                cmd+=['--add-data',str(src)+os.pathsep+str(rel.parent)]
            # Basic convenience for apps opening images by filename; all files are bundled.
            cmd.append(str(entry))
            runstep(pid,cmd,cwd=files)
            executable=slug(name)+'.exe'
            if not (dist/executable).is_file():raise RuntimeError('PyInstaller did not produce the expected Windows executable.')
            db_update(pid,detail='Creating the one-file installer…')
            installer=make_installer(pid,name,None,executable,icon)
        else:
            found={x['path'] for x in jdks()}
            if runtime not in found:raise RuntimeError('Selected Java JDK is not available. Install a JDK with jpackage.')
            entry=files/clean_rel(setting['entry'])
            if not entry.is_file() or entry.suffix.lower()!='.jar':raise RuntimeError('Select a .jar file.')
            root=build/'java_image'
            cmd=[runtime,'--type','app-image','--input',str(files),'--main-jar',str(entry.relative_to(files)),
                 '--name',slug(name),'--dest',str(root)]
            if icon:cmd+=['--icon',icon]
            if setting.get('main_class'):cmd+=['--main-class',setting['main_class']]
            runstep(pid,cmd,cwd=files)
            image_dir=root/slug(name)
            if not image_dir.is_dir():raise RuntimeError('jpackage did not produce an application image.')
            db_update(pid,detail='Creating the one-file installer…')
            installer=make_installer(pid,name,image_dir,slug(name)+'.exe',icon)
        db_update(pid,status='ready',artifact=str(installer),detail='Your single .exe installer is ready to download.')
        logline(pid,'SUCCESS: '+str(installer))
    except Exception as e:
        db_update(pid,status='error',detail=str(e))
        logline(pid,'ERROR: '+str(e))
        logline(pid,traceback.format_exc())
    finally:
        try:make_archive(pid)
        except Exception as e:logline(pid,'Archive warning: '+str(e))


def safe_html_page(title, content, accent='#8a6bff'):
    title=html.escape(title)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
    :root{{--accent:{accent}}}*{{box-sizing:border-box}}body{{margin:0;background:#0c1220;color:#eff5ff;font-family:system-ui,-apple-system,Segoe UI,sans-serif}}header{{padding:24px 8%;background:#131d34}}h1{{font-size:clamp(32px,6vw,60px)}}main{{max-width:980px;margin:auto;padding:70px 25px}}p{{line-height:1.7;color:#c2d0e4}}.btn{{display:inline-block;color:white;background:var(--accent);padding:14px 22px;border-radius:12px;text-decoration:none}}footer{{padding:26px 8%;color:#74849a}}
    </style></head><body><header><strong>✦ {title}</strong></header><main>{content}</main><footer>Built with ForgeNest</footer></body></html>'''


def build_site_template(name, prompt):
    name=html.escape(name)
    description=html.escape(prompt[:1000])
    content=f'<p style="color:#b8aaff;text-transform:uppercase;letter-spacing:.2em">Welcome</p><h1>{name}</h1><p>{description or "A new website created with ForgeNest."}</p><a class="btn" href="mailto:hello@example.com">Get in touch</a>'
    return safe_html_page(name,content)


def extract_ai_html(output):
    if '```html' in output:output=output.split('```html',1)[1].split('```',1)[0]
    elif output.lstrip().startswith('```'):output=output.split('```',1)[1].split('```',1)[0]
    if '<html' not in output.lower() and '<!doctype html' not in output.lower():raise RuntimeError('AI returned no valid HTML page.')
    return output.strip()


def ai_site(name,prompt,key,existing=''):
    query=f'''Create a complete beautiful responsive SINGLE-FILE static HTML website (inline CSS and JavaScript) titled {name}. User request: {prompt[:5000]}. Existing index.html to redesign if provided: {existing[:12000]}. Return only the full HTML code, no explanations, no markdown fences. Never include tracking, remote scripts or secrets. Use accessible semantic HTML.'''
    body=json.dumps({'model':'gpt-4.1-mini','input':query,'max_output_tokens':5500}).encode('utf8')
    req=urlrequest.Request('https://api.openai.com/v1/responses',body,{'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
    try:
        with urlrequest.urlopen(req,timeout=75) as resp: obj=json.load(resp)
    except HTTPError as e:
        msg=e.read(1024).decode('utf8','replace')
        raise RuntimeError('AI API error: '+msg[:220])
    texts=[c.get('text','') for item in obj.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text']
    return extract_ai_html('\n'.join(texts))


def make_site(pid,setting,uploads):
    d=DATA/pid;source=d/'site_source';source.mkdir(exist_ok=True)
    name=setting['name']
    try:
        mode=setting.get('mode','template')
        db_update(pid,status='building',detail='Creating website…')
        if uploads:
            sitefiles=[]
            for path,data in uploads:
                if path.lower().endswith('.zip'):
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        if len(archive.infolist())>500:raise ValueError('Uploaded website ZIP has too many files.')
                        if sum(o.file_size for o in archive.infolist())>MAX_UPLOAD:raise ValueError('Website ZIP is too large.')
                        entries=[o for o in archive.infolist() if not o.is_dir()]
                        paths=[o.filename.replace('\\','/') for o in entries]
                        # Keep the directory contents if the ZIP contains one common root folder.
                        first={p.split('/')[0] for p in paths if '/' in p}
                        topstrip=next(iter(first))+'/' if len(first)==1 and all(p.startswith(next(iter(first))+'/') for p in paths) else ''
                        for obj in entries:
                            rel=obj.filename.replace('\\','/')
                            if topstrip:rel=rel[len(topstrip):]
                            if rel:sitefiles.append((rel,archive.read(obj)))
                else:sitefiles.append((path,data))
            for path,data in sitefiles:
                rel=clean_rel(path)
                if rel.lower().endswith(('.exe','.py','.jar','.bat','.cmd','.ps1')):raise ValueError('Website uploads must be HTML, CSS, JavaScript or assets, not executables.')
                dest=source/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            # Pick first HTML file as entry for uploads without index.html.
            if not (source/'index.html').exists():
                pages=list(source.rglob('*.html'))
                if pages:(source/'index.html').write_bytes(pages[0].read_bytes())
            if not (source/'index.html').exists():raise ValueError('Uploaded website needs an index.html page.')
        if mode=='ai':
            if not setting.get('api_key'):raise ValueError('AI mode requires an OpenAI API key, provided only for this request.')
            existing=(source/'index.html').read_text(encoding='utf8',errors='replace') if (source/'index.html').exists() else ''
            (source/'index.html').write_text(ai_site(name,setting.get('prompt',''),setting['api_key'],existing),encoding='utf8')
        elif not uploads:

            (source/'index.html').write_text(build_site_template(name,setting.get('prompt','')),encoding='utf8')
        zipped=d/(slug(name)+'_Website.zip')
        with zipfile.ZipFile(zipped,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for f in source.rglob('*'):
                if f.is_file():z.write(f,f.relative_to(source))
        db_update(pid,status='ready',artifact=str(zipped),detail='Website ZIP is ready. Upload it to a static host to go public.')
    except Exception as e:
        db_update(pid,status='error',detail=str(e))
        logline(pid,'ERROR: '+str(e))
    finally:
        try:make_archive(pid)
        except Exception:pass


def check_origin(handler):
    origin=handler.headers.get('Origin','')
    return not origin or origin in {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}


class Handler(BaseHTTPRequestHandler):
    server_version='ForgeNest/1.0'
    def log_message(self,format,*args):
        try:
            with (DATA/'server.log').open('a',encoding='utf8') as f:f.write('%s %s\n'%(self.log_date_time_string(),format%args))
        except Exception:pass

    def respond(self,code,data):
        b=json.dumps(data,ensure_ascii=False).encode('utf8')
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b)

    def file_response(self,path,ctype,filename=None,inline=False,preview=False):
        path=Path(path)
        if not path.is_file():return self.respond(404,{'error':'File not found.'})
        self.send_response(200);self.send_header('Content-Type',ctype)
        if preview:self.send_header('Content-Security-Policy','sandbox allow-scripts')
        if filename:self.send_header('Content-Disposition',('inline' if inline else 'attachment')+'; filename="'+slug(filename,100)+'"')
        self.send_header('Content-Length',str(path.stat().st_size));self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)

    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        if path=='/api/status':
            return self.respond(200,{'windows':os.name=='nt','python':interpreters(),'java':jdks(),'inno':bool(find_inno()),'ai_available':True})
        if path=='/api/projects':return self.respond(200,{'projects':db_all()})
        match=re.fullmatch(r'/api/projects/([a-f0-9]{32})/(download|archive|log|preview)',path)
        if match:
            pid,action=match.groups();proj=db_one(pid)
            if not proj:return self.respond(404,{'error':'Project not found.'})
            if action=='log':
                log=(DATA/pid/'build.log')
                if not log.exists():return self.respond(200,{'log':'No log yet.'})
                return self.respond(200,{'log':log.read_text(encoding='utf8',errors='replace')[-40000:]})
            if action=='download':
                f=proj.get('artifact')
                return self.file_response(f,'application/octet-stream',Path(f).name if f else None) if f else self.respond(404,{'error':'Not ready.'})
            if action=='archive':
                f=proj.get('archive')
                return self.file_response(f,'application/zip',slug(proj['name'])+'_Project.zip') if f else self.respond(404,{'error':'Not ready.'})
            if action=='preview' and proj['kind']=='website':
                f=DATA/pid/'site_source'/'index.html'
                return self.file_response(f,'text/html; charset=utf-8',preview=True)
        if path in ('/','/index.html'):return self.file_response(STATIC/'index.html','text/html; charset=utf-8')
        if path.startswith('/static/'):
            relative=path[len('/static/'):]
            if '..' in Path(relative).parts:return self.respond(403,{'error':'Forbidden'})
            suffix=Path(relative).suffix.lower()
            types={'.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'}
            return self.file_response(STATIC/relative,types.get(suffix,'application/octet-stream'))
        return self.respond(404,{'error':'Not found.'})

    def do_POST(self):
        if not check_origin(self):return self.respond(403,{'error':'Invalid request origin.'})
        if int(self.headers.get('Content-Length','0'))>MAX_UPLOAD:return self.respond(413,{'error':'Upload exceeds 300 MB limit.'})
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
        path=urlsplit(self.path).path
        try:
            fields,files=parse_form(self.headers,raw)
            if path=='/api/build':
                kind=fields.get('kind','')
                if kind not in ('python','java'):raise ValueError('Choose Python or Java.')
                name=valid_name(fields.get('name','').strip())
                entry=clean_rel(fields.get('entry',''))
                runtimes={r['path'] for r in (interpreters() if kind=='python' else jdks())}
                runtime=fields.get('runtime','')
                if runtime not in runtimes:raise ValueError('Choose an installed '+kind.title()+' version.')
                # Files and their relative paths must match exactly.
                paths=json.loads(fields.get('paths','[]'))
                source=files.get('resources',[])
                if not source: raise ValueError('Upload your program files.')
                if len(paths)!=len(source): raise ValueError('Resource names were not received correctly.')
                if len(paths)>500:raise ValueError('Maximum 500 files per project.')
                if entry not in paths:raise ValueError('Choose an entry file among the uploaded files.')
                if kind=='java' and not entry.lower().endswith('.jar'):raise ValueError('Java entry must be a .jar file.')
                if kind=='python' and not entry.lower().endswith(('.py','.pyw')):raise ValueError('Python entry must be a .py or .pyw file.')
                pid=uuid.uuid4().hex;d=DATA/pid;source_dir=d/'source';source_dir.mkdir(parents=True)
                for p,(_,b) in zip(paths,source):
                    rel=clean_rel(p);dest=source_dir/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                    if dest.exists():raise ValueError('Two uploaded files share the same path.')
                    dest.write_bytes(b)
                icon=write_icon(files.get('icon',[None])[0],d/'logo.ico') if files.get('icon') else ''
                setting={'kind':kind,'name':name,'entry':entry,'runtime':runtime,'gui':fields.get('gui','yes')=='yes',
                         'main_class':fields.get('main_class','').strip(),
                         'install_requirements':fields.get('install_requirements','no')=='yes',
                         'install_build_tools':fields.get('install_build_tools','no')=='yes'}
                (d/'settings.json').write_text(json.dumps(setting,indent=2),encoding='utf8')
                db_create(pid,name,kind,'queued','Waiting to begin build…')
                if icon:db_update(pid,icon=icon)
                EXECUTOR.submit(execute_build,pid,setting)
                return self.respond(201,{'id':pid,'message':'Build queued.'})
            elif path=='/api/site':
                name=valid_name(fields.get('name','').strip())
                paths=json.loads(fields.get('paths','[]'))
                uploaded=files.get('resources',[])
                if len(paths)!=len(uploaded):raise ValueError('Website resource names did not match uploads.')
                pid=uuid.uuid4().hex;(DATA/pid).mkdir()
                uploads=[(p,b) for p,(_,b) in zip(paths,uploaded)]
                setting={'name':name,'prompt':fields.get('prompt',''), 'mode':fields.get('mode','template'),
                         'api_key':fields.get('api_key','').strip()}
                db_create(pid,name,'website','queued','Generating website…')
                EXECUTOR.submit(make_site,pid,setting,uploads)
                return self.respond(201,{'id':pid})
            elif path=='/api/import':
                item=files.get('archive',[None])[0]
                if not item:raise ValueError('Choose a project ZIP from ForgeNest.')
                filename,b=item
                with zipfile.ZipFile(io.BytesIO(b)) as z:
                    total=0
                    # Only imports data, no execution; builds must be requested again.
                    names=z.namelist()
                    if len(names)>1200:raise ValueError('ZIP has too many files.')
                    if 'settings.json' not in names and 'site_source/index.html' not in names:
                        raise ValueError('Not a ForgeNest project export.')
                    pid=uuid.uuid4().hex;d=DATA/pid;d.mkdir()
                    for obj in z.infolist():
                        if obj.is_dir():continue
                        rel=clean_rel(obj.filename)
                        total+=obj.file_size
                        if total>MAX_UPLOAD:raise ValueError('Extracted files exceed limit.')
                        dest=d/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                        dest.write_bytes(z.read(obj))
                kind='website' if (d/'site_source'/'index.html').exists() else json.loads((d/'settings.json').read_text())['kind']
                original_name=(json.loads((d/'settings.json').read_text()).get('name','Imported App') if (d/'settings.json').exists() else 'Imported Website')
                name=valid_name(original_name)
                artifacts=list(d.glob('output/*.exe')) + list(d.glob('*_Website.zip'))
                status='ready' if artifacts else 'imported'
                db_create(pid,name,kind,status,'Imported project. Files available for download.' if artifacts else 'Imported source. Build again on this computer to make an EXE.')
                if artifacts:db_update(pid,artifact=str(artifacts[0]))
                make_archive(pid)
                return self.respond(201,{'id':pid})
        except (ValueError,json.JSONDecodeError,zipfile.BadZipFile) as e:
            return self.respond(400,{'error':str(e)})
        except Exception as e:
            self.log_message('POST error %s',traceback.format_exc())
            return self.respond(500,{'error':str(e)})
        return self.respond(404,{'error':'Unknown endpoint.'})


def main(open_browser=True):
    init_db()
    httpd=ThreadingHTTPServer((HOST,PORT),Handler)
    url=f'http://{HOST}:{PORT}/'
    print('ForgeNest running at '+url)
    if open_browser:
        threading.Timer(0.8,lambda:webbrowser.open(url)).start()
    httpd.serve_forever()

if __name__=='__main__':main()
