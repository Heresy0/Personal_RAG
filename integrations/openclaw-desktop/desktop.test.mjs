import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,appendFileSync,readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {pathToFileURL} from 'node:url';
import {Queue} from './queue.mjs';
import {Worker,scan,marker,nativeDependencies} from './worker.mjs';
import {lookupThread,plain} from './catalog.mjs';
import {authorized,registerDesktop} from './index.mjs';

const THREAD='11111111-2222-3333-4444-555555555555';
const PEER='Owner_CASE@im.wechat';
function fixture(t){
  mkdirSync('output',{recursive:true});
  const root=mkdtempSync(resolve('output/desktop-test-'));
  const file=join(root,'queue.sqlite'),rollout=join(root,'rollout.jsonl');writeFileSync(rollout,'');
  const queue=new Queue(file);t.after(()=>queue.close());
  const enqueue=(messageId='message-one',body='  原样正文\n')=>queue.enqueue({account:'test-bot',peer:PEER,messageId,body,threadId:THREAD,workspace:root}).job;
  return {root,file,rollout,queue,enqueue};
}
const event=(type,extra={})=>JSON.stringify({type:'event_msg',payload:{type,...extra}})+'\n';
function complete(job,text='任务完成'){
  return event('task_started',{turn_id:'our-turn'})+
    event('user_message',{message:marker(job.id),turn_id:'our-turn'})+
    event('task_complete',{turn_id:'our-turn',last_agent_message:text});
}
function workerFor(f,overrides={}){
  const calls={submit:0,send:[]};
  const deps={ready:async()=>true,open:async()=>{},lookup:()=>({rollout:f.rollout}),scan,
    submit:async()=>{calls.submit++;},...overrides};
  const worker=new Worker(f.queue,deps,{allow:()=>true,send:async(job,text)=>calls.send.push(text)});
  return {worker,calls};
}

test('messages are durable, body is preserved, and stable provider IDs deduplicate',t=>{
  const f=fixture(t),job=f.enqueue();
  const second=new Queue(f.file);
  try{
    assert.equal(second.get(job.id).body,'  原样正文\n');
    const again=f.enqueue();assert.equal(again.id,job.id);
    assert.throws(()=>f.enqueue('message-one','changed'),/conflict/);
    assert.notEqual(f.enqueue('message-two').id,job.id);
  }finally{second.close();}
});
test('exit-zero submission remains queued until a correlated completed turn',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f);
  await worker.tick();assert.equal(f.queue.get(job.id).state,'queued');
  await worker.tick();assert.equal(calls.submit,1);assert.deepEqual(calls.send,[]);
  appendFileSync(f.rollout,complete(job,'正确结果'));
  await worker.tick();assert.equal(f.queue.get(job.id).state,'delivered');
  assert.deepEqual(calls.send,['正确结果']);
});
test('received pending jobs survive a worker restart without changing the binding',async t=>{
  const f=fixture(t),job=f.enqueue();
  const restarted=new Queue(f.file);
  try{
    restarted.recover();assert.equal(restarted.get(job.id).thread_id,THREAD);
    assert.equal(restarted.get(job.id).state,'pending');
  }finally{restarted.close();}
});
test('a crash at the submission boundary never automatically submits twice',async t=>{
  const f=fixture(t),job=f.enqueue();
  f.queue.update(job.id,{state:'dispatching',rollout:f.rollout});f.queue.recover();
  const {worker,calls}=workerFor(f);
  await worker.tick();assert.equal(f.queue.get(job.id).state,'uncertain');assert.equal(calls.submit,0);
  appendFileSync(f.rollout,complete(job));await worker.tick();
  assert.equal(f.queue.get(job.id).state,'delivered');assert.equal(calls.submit,0);
});
test('submission failure is uncertain and is not silently retried',async t=>{
  const f=fixture(t),job=f.enqueue();let attempts=0;
  const {worker}=workerFor(f,{submit:async()=>{attempts++;throw new Error('transport lost after acceptance');}});
  await worker.tick();await worker.tick();assert.equal(attempts,1);
  assert.equal(f.queue.get(job.id).state,'uncertain');
});
test('reply failure retries only delivery, not the Codex task',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f);
  worker.send=async()=>{throw new Error('offline');};
  await worker.tick();appendFileSync(f.rollout,complete(job,'saved result'));await worker.tick();
  assert.equal(f.queue.get(job.id).state,'completed');
  worker.now=()=>Date.now()+120000;worker.send=async(_job,text)=>calls.send.push(text);
  await worker.tick();assert.equal(calls.submit,1);assert.equal(f.queue.get(job.id).state,'delivered');
});
test('an unavailable knowledge database retains messages before dispatch',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f,{ready:async()=>false});
  await worker.tick();assert.equal(f.queue.get(job.id).state,'pending');assert.equal(calls.submit,0);
});
test('changed ownership or binding pauses work without executing it',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f);worker.allow=()=>false;
  await worker.tick();assert.equal(f.queue.get(job.id).state,'paused');assert.equal(calls.submit,0);
});
test('byte-split Unicode and prior task context survive incremental polling',t=>{
  const f=fixture(t),job=f.enqueue();f.queue.update(job.id,{state:'queued',rollout:f.rollout});
  const transcript=event('task_started',{turn_id:'our-turn'})+
    JSON.stringify({type:'response_item',payload:{type:'message',role:'user',content:[{text:marker(job.id)+'\n中文'}]}})+'\n'+
    event('task_complete',{turn_id:'our-turn',last_agent_message:'中文结果'});
  appendFileSync(f.rollout,transcript);
  for(let i=0;i<Buffer.byteLength(transcript)+5;i++){
    const current=f.queue.get(job.id);if(current.state==='completed')break;
    f.queue.update(job.id,scan(current,7));
  }
  assert.equal(f.queue.get(job.id).state,'completed');assert.equal(f.queue.get(job.id).final_text,'中文结果');
});
test('another conversation turn cannot provide this task completion',t=>{
  const f=fixture(t),job=f.enqueue();f.queue.update(job.id,{state:'queued',rollout:f.rollout});
  appendFileSync(f.rollout,event('task_started',{turn_id:'other'})+event('task_complete',{turn_id:'other',last_agent_message:'wrong'}));
  f.queue.update(job.id,scan(f.queue.get(job.id)));
  assert.equal(f.queue.get(job.id).state,'queued');assert.equal(f.queue.get(job.id).final_text,'');
});

test('quoting an old task marker cannot claim an unrelated completed turn',t=>{
  const f=fixture(t),job=f.enqueue();f.queue.update(job.id,{state:'queued',rollout:f.rollout});
  appendFileSync(f.rollout,event('task_started',{turn_id:'other'})+event('user_message',{turn_id:'other',message:'请查一下 '+marker(job.id)})+event('task_complete',{turn_id:'other',last_agent_message:'unrelated'}));
  f.queue.update(job.id,scan(f.queue.get(job.id)));
  assert.equal(f.queue.get(job.id).state,'queued');assert.equal(f.queue.get(job.id).final_text,'');
});

test('reply chunks preserve surrogate pairs and do not repeat task execution',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f);
  const body='a'.repeat(2999)+'😀'+'剩余';
  f.queue.update(job.id,{state:'completed',final_text:body});
  await worker.tick();await worker.tick();assert.equal(calls.send.join(''),body);
  assert.equal(calls.send[0],'a'.repeat(2999));assert.equal(calls.submit,0);
});
test('interrupted tasks are not treated as successful or repeated',async t=>{
  const f=fixture(t),job=f.enqueue(),{worker,calls}=workerFor(f);
  await worker.tick();appendFileSync(f.rollout,event('task_started',{turn_id:'our-turn'})+event('user_message',{message:marker(job.id),turn_id:'our-turn'})+event('task_interrupted',{turn_id:'our-turn'}));
  await worker.tick();await worker.tick();assert.equal(f.queue.get(job.id).state,'failed');assert.equal(calls.submit,1);
});
test('uncertain work needs scoped acknowledgement, never cancellation of desktop execution',t=>{
  const f=fixture(t),job=f.enqueue();f.queue.update(job.id,{state:'uncertain'});
  assert.equal(f.queue.cancel(job.id,'test-bot',PEER),false);
  assert.equal(f.queue.acknowledge(job.id,'other-bot',PEER),false);
  assert.equal(f.queue.acknowledge(job.id,'test-bot',PEER),true);
  assert.equal(f.queue.get(job.id).state,'reviewed');
});
test('global dispatch authenticates the configured direct peer without relying on absent native-binding role flags',()=>{
  const config={commands:{ownerAllowFrom:['openclaw-weixin:'+PEER]}};
  const ctx={channelId:'openclaw-weixin',accountId:'bot',senderId:PEER,conversationId:PEER};
  const event={senderId:PEER,accountId:'bot',senderIsOwner:true,commandAuthorized:true,isGroup:false};
  assert.equal(authorized(config,event,ctx),true);
  assert.equal(authorized(config,{...event,senderIsOwner:undefined,commandAuthorized:undefined},ctx),true);
  for(const change of [{senderIsOwner:false},{commandAuthorized:false},{isGroup:true},{senderId:'Other@im.wechat'},{threadId:'topic'},{accountId:'../../other'}])assert.equal(authorized(config,{...event,...change},ctx),false);
  assert.equal(authorized(config,event,{...ctx,conversationId:'Other@im.wechat'}),false);
});
test('read-only catalog verifies original thread, workspace and rollout boundary',t=>{
  const f=fixture(t),home=join(f.root,'home');mkdirSync(join(home,'sessions'),{recursive:true});
  const path=join(home,'sessions','original.jsonl');writeFileSync(path,'');
  const db=new DatabaseSync(join(home,'state_5.sqlite'));
  db.exec('CREATE TABLE threads(id TEXT,cwd TEXT,rollout_path TEXT,archived INTEGER)');
  db.prepare('INSERT INTO threads VALUES(?,?,?,0)').run(THREAD,f.root,path);db.close();
  assert.equal(lookupThread(home,THREAD,f.root).rollout,path);
  assert.throws(()=>lookupThread(home,THREAD,join(f.root,'other')),/mismatch/);
  assert.equal(plain('\\\\?\\C:\\Users\\Test'),'C:\\Users\\Test');
});
test('plugin persists before acknowledgement and rejects an unauthorized inbound message',async t=>{
  const f=fixture(t),hooks={},services=[],commands=[];
  const config={commands:{ownerAllowFrom:['openclaw-weixin:'+PEER]}};
  const api={config,pluginConfig:{runtimeDir:f.root,threadId:THREAD,workspace:f.root},
    registerService:s=>services.push(s),on:(name,fn)=>hooks[name]=fn,registerCommand:c=>commands.push(c),runtime:{}};
  mkdirSync(join(f.root,'state'),{recursive:true});
  writeFileSync(join(f.root,'state/openclaw.json'),JSON.stringify({...config,plugins:{entries:{'personal-rag-desktop':{enabled:true,config:api.pluginConfig}}}}));
  mkdirSync(join(f.root,'state/openclaw-weixin/accounts'),{recursive:true});
  writeFileSync(join(f.root,'state/openclaw-weixin/accounts.json'),'["bot"]');
  writeFileSync(join(f.root,'state/openclaw-weixin/accounts/bot.json'),JSON.stringify({userId:PEER}));
  registerDesktop(api,{dependencies:()=>({ready:async()=>false})});
  await services[0].start();t.after(()=>services[0].stop());
  // This is the actual before_dispatch shape: no owner flags, account in context.
  const event={content:'  记录原文\n',messageId:'provider-id',senderId:PEER,isGroup:false};
  const ctx={channelId:'openclaw-weixin',conversationId:PEER,senderId:PEER,accountId:'bot'};
  await hooks.message_received({...event,from:PEER},ctx);
  const result=await hooks.before_dispatch(event,ctx);assert.match(result.text,/已落盘/);
  const stored=new Queue(join(f.root,'desktop-queue.sqlite'));
  try{assert.equal(stored.list('bot',PEER).length,1);assert.equal(stored.get(stored.list('bot',PEER)[0].id).body,event.content);}finally{stored.close();}
  assert.deepEqual(await hooks.before_dispatch({...event,senderId:'Other@im.wechat'},ctx),{handled:true});
  assert.match((await hooks.before_dispatch(event,ctx)).text,/不重复/);
  assert.match((await hooks.before_dispatch({...event,messageId:'missing-receipt'},ctx)).text,/未确认入队/);
  const image={...event,messageId:'image',media:[{path:'image.png'}]};
  await hooks.message_received({...image,from:PEER},ctx);
  assert.match((await hooks.before_dispatch(image,ctx)).text,/附件未入队/);
  const control={...event,messageId:'control',content:'/wxdesk'};
  await hooks.message_received({...control,from:PEER},ctx);
  assert.match((await hooks.before_dispatch(control,ctx)).text,new RegExp(THREAD));
  assert.equal(commands[0].requireAuth,true);
  // Exercise the pinned core's real global hook runner, not just our callback.
  if(process.env.OPENCLAW_TEST_HOOK_RUNNER){
    const {t:createHookRunner,u:withAdmission}=await import(pathToFileURL(process.env.OPENCLAW_TEST_HOOK_RUNNER).href);
    const registry={plugins:[{id:'personal-rag-desktop',status:'loaded'}],typedHooks:Object.entries(hooks).map(([hookName,handler])=>({pluginId:'personal-rag-desktop',hookName,handler,priority:100}))};
    const runner=createHookRunner(registry);
    const reply=await runner.runBeforeDispatch(event,withAdmission({...ctx},{prepare:async()=>{}}));
    assert.equal(reply.handled,true);assert.match(reply.text,/不重复/);
    assert.equal('reply' in reply,false);
    if(process.env.OPENCLAW_TEST_MESSAGE_MAPPERS){
      const m=await import(pathToFileURL(process.env.OPENCLAW_TEST_MESSAGE_MAPPERS).href);
      const canonical=m.n({Body:event.content,CommandBody:event.content.trim(),From:PEER,To:PEER,AccountId:'bot',
        OriginatingChannel:'openclaw-weixin',OriginatingTo:PEER,Provider:'openclaw-weixin',ChatType:'direct',MessageSidFull:'mapped-id'});
      const context=m.l(canonical);
      assert.equal(context.senderId,undefined); // Tencent does not populate SenderId.
      await runner.runMessageReceived(m.u(canonical),context);
      const projected={messageId:canonical.messageId,senderId:canonical.senderId,content:canonical.content,
        body:canonical.bodyForAgent??canonical.body,channel:canonical.channelId,isGroup:canonical.isGroup};
      const mappedReply=await runner.runBeforeDispatch(projected,withAdmission({...context},{prepare:async()=>{}}));
      assert.match(mappedReply.text,/已落盘/);
      const status=await commands[0].handler({channel:'openclaw-weixin',isAuthorizedSender:true,accountId:'bot',from:PEER,args:''});
      assert.match(status.text,new RegExp(THREAD));
    }
  }
});

test('cancellation during desktop readiness does not race into execution',async t=>{
  const f=fixture(t),job=f.enqueue();let release;
  const {worker,calls}=workerFor(f,{open:()=>new Promise(r=>release=r)});
  const running=worker.tick();await new Promise(r=>setImmediate(r));
  assert.equal(f.queue.cancel(job.id,'test-bot',PEER),true);
  release();await running;assert.equal(calls.submit,0);assert.equal(f.queue.get(job.id).state,'cancelled');
});

test('native delivery uses only the original queue and desktop deep link, without another daemon resume',async t=>{
  const f=fixture(t),job=f.enqueue(),calls=[];
  const deps=nativeDependencies({codexPath:'codex-test.exe',projectRoot:f.root},{run:async(command,args,options)=>{
    calls.push({command,args,options});return {stdout:JSON.stringify({Service:'postgres',State:'running',Health:'healthy'})};
  }});
  assert.equal(await deps.ready(),true);await deps.open(job);await deps.submit(job);
  const cli=calls.find(c=>c.command==='codex-test.exe');
  assert.deepEqual(cli.args.slice(0,4),['queue','--thread',THREAD,'--message']);
  assert.equal(cli.args.includes('--resume'),false);assert.equal(cli.args.includes('app-server'),false);
  assert.equal(cli.options.windowsHide,true);assert.equal(cli.options.cwd,f.root);
  assert.ok(cli.args[4].includes(marker(job.id)));assert.ok(cli.args[4].endsWith(job.body));
  assert.ok(calls.find(c=>c.command==='pwsh').args.at(-1).includes('codex://threads/'+THREAD));
});
