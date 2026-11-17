#!/usr/bin/env bash
# Network-enabled executable fence test; the seed bootstrap alone has no network.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
chmod 777 "$scratch"
mkdir "$scratch/data"
chmod 777 "$scratch/data"
image='docker.io/louislam/uptime-kuma:2.5.11@sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9'
mounts=(--mount "type=bind,src=$scratch,dst=/test"
  --mount "type=bind,src=$scratch/data,dst=/source,readonly"
  --mount "type=bind,src=$repo_root/clusters/homelab/apps/uptime-kuma/reconcile.js,dst=/config/reconcile.js,readonly"
  --mount "type=bind,src=$repo_root/clusters/homelab/apps/uptime-kuma/backup.py,dst=/backup-code/backup.py,readonly")
# Unconfigured bootstrap's updater cannot contact a public service in this phase.
timeout 150 docker run --rm --network none --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  "${mounts[@]}" --entrypoint node "$image" -e \
  'require("/config/reconcile.js").bootstrap({url:"http://127.0.0.1:3001",dataDir:"/test/data"},"disposable-backup-integration-only").catch(()=>process.exitCode=1)'
cat > "$scratch/verify.js" <<'JS'
const fs=require('fs'),assert=require('assert/strict'),http=require('http'),os=require('os'),vm=require('vm'),{spawn,execFileSync}=require('child_process');
const a=require('/config/reconcile.js'),password='disposable-backup-integration-only';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(command,args,options={})=>new Promise((resolve,reject)=>{const p=spawn(command,args,{stdio:['ignore','pipe','pipe'],...options});let out='';p.stdout.on('data',x=>out+=x);p.stderr.resume();p.on('error',reject);p.on('exit',code=>code===0?resolve(out):reject(Error('child failed '+code)));});
async function stop(server){const exit=new Promise(r=>server.once('exit',r));server.kill('SIGTERM');let timer;try{await Promise.race([exit,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('stop timeout')),30000)})]);}finally{clearTimeout(timer);if(server.exitCode===null)server.kill('SIGKILL');}}
async function guardTests(){
 const flush=()=>new Promise(r=>setImmediate(r));
 for(const [value,expected] of [[false,0],[true,2],['false',2]]){
  let calls=0,tick;const exports={};
  const context={exports,require:name=>{
   if(name==='./util-server')return {setting:async()=>value,setSetting:async()=>{}};
   if(name==='axios')return {get:async()=>{calls++;return {data:{slow:'2.5.11'}}}};
   if(name==='compare-versions')return {compare:()=>false};
   if(name==='../src/util')return {log:{debug(){},info(){}}};
   if(name==='../package.json')return {version:'2.5.11'};
   throw Error('unexpected updater dependency');},process:{env:{}},setInterval:fn=>{tick=fn;return 1},clearInterval(){}};
  vm.runInNewContext(fs.readFileSync('/app/server/check-version.js','utf8'),context);
  exports.startInterval();await flush();await tick();await flush();assert.equal(calls,expected);
 }
 for(const [stored,override,expected] of [['',undefined,0],['fixture-token',undefined,1],['','override-token',1]]){
  let calls=0;const exports={},module={exports};
  const context={exports,module,require:name=>{
   if(name==='../util-server')return {setting:async()=>stored,setSetting:async()=>{},checkLogin(){},doubleCheckPassword(){}};
   if(name==='node-cloudflared-tunnel')return {CloudflaredTunnel:class{start(){calls++}stop(){}}};
   if(name==='../uptime-kuma-server')return {UptimeKumaServer:{getInstance:()=>({io:{to:()=>({emit(){}})}})}};
   if(name==='../../src/util')return {log:{info(){},error(){}}};
   throw Error('unexpected tunnel dependency');}};
  vm.runInNewContext(fs.readFileSync('/app/server/socket-handlers/cloudflared-socket-handler.js','utf8'),context);
  await module.exports.autoStart(override);assert.equal(calls,expected);
 }
 console.log('PASS: actual pinned updater/tunnel guards positive call counters and fenced zero counters; no public calls');
}
(async()=>{
 assert.equal(process.getuid(),1000);await guardTests();
 // Fixture-only settings suppress public updater/service/tunnel activity before positive startup.
 execFileSync('python3',['-c',`import sqlite3,json
c=sqlite3.connect('/test/data/kuma.db')
for k,v in {'checkUpdate':False,'nscd':False,'cloudflaredTunnelToken':''}.items():
 c.execute('delete from setting where key=?',(k,));c.execute('insert into setting(key,value,type) values(?,?,?)',(k,json.dumps(v),'general'))
c.commit();c.close()`]);
 fs.writeFileSync('/test/password',password,{mode:0o600});
 const ip=Object.values(os.networkInterfaces()).flat().find(x=>x.family==='IPv4'&&!x.internal)?.address;
 assert.ok(ip,'fixture needs enabled network');let probes=0,notifications=0,healthy=true;
 const sink=http.createServer((req,res)=>{if(req.url==='/probe'){probes++;res.statusCode=healthy?200:503}else if(req.url==='/notify'){notifications++;res.statusCode=200}else res.statusCode=200;req.resume();res.end('fixture');});
 await new Promise(r=>sink.listen(18080,'0.0.0.0',r));
 await new Promise((resolve,reject)=>http.get(`http://${ip}:18080/reachability`,r=>{r.resume();resolve()}).on('error',reject));
 await require('/app/node_modules/axios').get(`http://${ip}:18080/reachability`,{proxy:false});
 let server=spawn('node',['/app/server/server.js','--host=127.0.0.1','--port=3001','--data-dir=/test/data'],{cwd:'/app',stdio:'ignore',env:{PATH:'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',HOME:'/tmp',TMPDIR:'/tmp'}}),client;
 try{
  client=await a.connect('http://127.0.0.1:3001');await a.login(client,password);
  const n=await client.request('addNotification',{name:'Fixture webhook',type:'webhook',webhookURL:`http://${ip}:18080/notify`,webhookContentType:'json',isDefault:true,applyExisting:false},null);
  const m={key:'backup-fixture',name:'Backup fixture',ownerAppIds:['fixture'],kind:'http',enabled:true,target:{url:`http://${ip}:18080/probe`},expected:{statusCodes:[200]},intervalSeconds:60,timeoutSeconds:10,retries:1,meaning:'Disposable server health',limitations:'Integration only'};
  const created=await client.request('add',{...a.projection(m),interval:20,retryInterval:20,maxretries:0,notificationIDList:{[n.id]:true},parent:null,upsideDown:false,expiryNotification:false,conditions:[],kafkaProducerBrokers:[],kafkaProducerSaslOptions:{},rabbitmqNodes:[]});
  const detail=(await client.request('getMonitor',created.monitorID)).monitor;assert.equal(detail.interval,20);
  fs.writeFileSync('/test/catalog',JSON.stringify({monitors:[m]}));
  let firstHealthy=false;
  for(let i=0;i<60;i++){
   try{execFileSync('python3',['-c',"import sqlite3;c=sqlite3.connect('file:/source/kuma.db?mode=ro',uri=True);assert c.execute('select count(*) from heartbeat where status=1').fetchone()[0]>0;c.close()"],{stdio:'ignore'});firstHealthy=true;break}catch{await sleep(1000)}
  }
  assert.ok(firstHealthy,'positive control needs initial healthy heartbeat');healthy=false;
  for(let i=0;i<90&&!(probes>1&&notifications>0);i++)await sleep(1000);
  assert.ok(probes>1&&notifications>0,`unfenced positive control needs probes+notification; counts ${probes}/${notifications}`);
  assert.ok(fs.existsSync('/source/kuma.db-wal'));assert.throws(()=>fs.writeFileSync('/source/not-writable','x'),{code:'EROFS'});
  const output=await run('python3',['/backup-code/backup.py','snapshot','--source','/source','--destination','/test/backups','--catalog','/test/catalog']);assert.ok(JSON.parse(output).heartbeats>0);
  console.log('PASS: network-enabled unfenced native monitor+notification reach sinks; live WAL read-only snapshot');
 }finally{client?.close();await stop(server);}
 probes=0;notifications=0;
 // Environment poisoning must not reach either native subprocess in verification.
 const environment={...process.env,NODE_OPTIONS:'--require=/does-not-exist',HTTP_PROXY:'http://invalid.invalid',HTTPS_PROXY:'http://invalid.invalid',UPTIME_KUMA_PORT:'9999',UPTIME_KUMA_CLOUDFLARED_TOKEN:'hostile-token',CLOUDFLARED_TOKEN:'hostile-token'};
 const code=`import importlib.util,json
s=importlib.util.spec_from_file_location('backup','/backup-code/backup.py');b=importlib.util.module_from_spec(s);s.loader.exec_module(b)
print(json.dumps(b.verify('/test/backups','/test/restored','/test/password',observe_seconds=42)))`;
 const before=execFileSync('python3',['-c',"import hashlib,pathlib;print(hashlib.sha256(b''.join(p.read_bytes() for p in sorted(pathlib.Path('/test/backups').rglob('*')) if p.is_file())).hexdigest())"],{encoding:'utf8'});
 const output=await run('python3',['-c',code],{env:environment});assert.ok(JSON.parse(output).heartbeats>0);
 assert.equal(probes,0);assert.equal(notifications,0);
 const after=execFileSync('python3',['-c',"import hashlib,pathlib;print(hashlib.sha256(b''.join(p.read_bytes() for p in sorted(pathlib.Path('/test/backups').rglob('*')) if p.is_file())).hexdigest())"],{encoding:'utf8'});assert.equal(after,before);
 await new Promise(r=>sink.close(r));
 console.log('PASS: fenced clone zero probe/notification traffic for42s >=2x20s intervals, native login/details/history, archive unchanged, hostile env excluded');
})().catch(e=>{console.error('FAIL:',e.message);process.exitCode=1;setTimeout(()=>process.exit(1),100);});
JS
timeout 300 docker run --rm --network bridge --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  "${mounts[@]}" --entrypoint node "$image" /test/verify.js
