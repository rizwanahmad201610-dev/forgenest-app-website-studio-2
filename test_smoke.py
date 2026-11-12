import io,json,threading,time,urllib.request,zipfile
from http.server import ThreadingHTTPServer
import server

def mp(fields, files=[]):
 boundary='TestMultipart42'; body=io.BytesIO()
 for k,v in fields.items():
  body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
 for key,name,data in files:
  body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode());body.write(data);body.write(b'\r\n')
 body.write(f'--{boundary}--\r\n'.encode());return body.getvalue(),f'multipart/form-data; boundary={boundary}'
server.init_db();print('init',flush=True)
httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=httpd.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{httpd.server_port}'
def get(s):return urllib.request.urlopen(base+s,timeout=15).read()
def post(s,fields,files=[]):
 data,ct=mp(fields,files);return json.load(urllib.request.urlopen(urllib.request.Request(base+s,data,{'Content-Type':ct}),timeout=15))
assert b'ForgeNest' in get('/');print('GET home pass',flush=True)
assert 'python' in json.loads(get('/api/status'));print('GET status pass',flush=True)
p=post('/api/site',{'name':'Example Site','prompt':'maths game','mode':'template','paths':'[]'});print('POST site',p,flush=True)
for _ in range(100):
 row=server.db_one(p['id'])
 if row['status'] not in ('queued','building'):break
 time.sleep(.05)
assert row['status']=='ready',row
with zipfile.ZipFile(io.BytesIO(get('/api/projects/'+p['id']+'/download'))) as z:assert b'maths game' in z.read('index.html')
print('download site pass',flush=True)
archive=get('/api/projects/'+p['id']+'/archive');assert zipfile.is_zipfile(io.BytesIO(archive));print('export pass',flush=True)
i=post('/api/import',{},[('archive','save.zip',archive)]);assert server.db_one(i['id'])['status']=='ready';print('import pass',flush=True)
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as z:z.writestr('site/index.html','<html><body>Existing</body></html>')
p2=post('/api/site',{'name':'My Website','mode':'upload','paths':'["my.zip"]'},[('resources','my.zip',out.getvalue())])
for _ in range(100):
 row=server.db_one(p2['id'])
 if row['status'] not in ('queued','building'):break
 time.sleep(.05)
assert row['status']=='ready',row
with zipfile.ZipFile(io.BytesIO(get('/api/projects/'+p2['id']+'/download'))) as z:assert b'Existing' in z.read('index.html')
print('ZIP import in site builder pass',flush=True)
httpd.shutdown();print('ALL SMOKE TESTS PASSED',flush=True)
