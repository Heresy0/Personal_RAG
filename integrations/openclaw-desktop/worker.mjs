import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {statSync,openSync,readSync,closeSync} from 'node:fs';
import {lookupThread,UUID} from './catalog.mjs';

const execute=promisify(execFile);
export const marker=id=>`[微信任务 ${id}]`;
const messageText=item=>typeof item.text==='string'?item.text:(item.content??[]).filter(x=>typeof x.text==='string').map(x=>x.text).join('\n');
const marked=(text,id)=>text===marker(id)||text.startsWith(marker(id)+'\n');
function safeEnd(text,end){
  if(end>0&&end<text.length&&/[\uD800-\uDBFF]/.test(text[end-1])&&/[\uDC00-\uDFFF]/.test(text[end]))return end-1;
  return end;
}
const clip=text=>text.slice(0,safeEnd(text,Math.min(text.length,12000)));

/** Incremental, byte-safe rollout reader. Only a correlated turn can complete a job. */
export function scan(job,maxBytes=1024*1024) {
  const size=statSync(job.rollout).size;
  if(size<job.offset)throw new Error('rollout_truncated');
  const length=Math.min(size-job.offset,maxBytes);
  if(!length)return {};
  const data=Buffer.alloc(length),fd=openSync(job.rollout,'r');
  let count;
  try{count=readSync(fd,data,0,length,job.offset);}finally{closeSync(fd);}
  const combined=Buffer.concat([Buffer.from(job.carry,'base64'),data.subarray(0,count)]);
  let start=0,found=Boolean(job.found),turn=job.turn_id,text=job.final_text,observedTurn=job.observed_turn,state=job.state,error=job.error;
  for(let end=combined.indexOf(10);end!==-1;end=combined.indexOf(10,start)) {
    const line=combined.subarray(start,end).toString('utf8');start=end+1;
    let record;try{record=JSON.parse(line);}catch{continue;}
    const event=record.payload??{};
    if(record.type==='turn_context'&&event.turn_id){observedTurn=event.turn_id;if(found&&!turn)turn=observedTurn;}
    if(record.type==='event_msg'&&event.type==='task_started'){observedTurn=event.turn_id;if(found&&!turn)turn=observedTurn;}
    const item=record.type==='response_item'?event:record.type==='event_msg'&&event.type==='item_completed'?event.item:null;
    const kind=item?String(item.type??'').toLowerCase():'';
    const role=item?.role??(kind==='usermessage'?'user':kind==='agentmessage'?'assistant':null);
    if(item&&role==='user'&&marked(messageText(item),job.id)){
      found=true;turn=event.turn_id??observedTurn??turn;state='running';error=null;
    }
    if(record.type==='event_msg'&&event.type==='user_message'&&marked(String(event.message??''),job.id)){
      found=true;turn=event.turn_id??observedTurn??turn;state='running';error=null;
    }
    if(found&&turn&&item&&role==='assistant'&&['final','final_answer'].includes(item.phase)&&
        (event.turn_id??observedTurn??turn)===turn)text=clip(messageText(item));
    if(found&&turn&&record.type==='event_msg'&&event.turn_id===turn){
      if(event.type==='task_complete'){
        text=clip(String(event.last_agent_message||text||'任务已完成，请在电脑原会话查看结果。'));
        state='completed';error=null;break;
      }
      if(['turn_aborted','task_interrupted','task_failed'].includes(event.type)){
        state='failed';error='desktop_turn_interrupted';break;
      }
    }
  }
  const carry=combined.subarray(start);
  if(carry.length>2*1024*1024)throw new Error('rollout_record_too_large');
  return {offset:job.offset+count,carry:carry.toString('base64'),found:found?1:0,turn_id:turn,observed_turn:observedTurn??null,
    final_text:text,state,error};
}

export function nativeDependencies(config,{run=execute}={}) {
  let opened=false,lastHealth=0,healthy=false;
  return {
    lookup:job=>lookupThread(config.codexHome,job.thread_id,job.workspace),
    ready:async()=>{
      if(Date.now()-lastHealth<10000)return healthy;
      lastHealth=Date.now();
      try{
        const {stdout}=await run('docker',['compose','--project-directory',config.projectRoot,'-f',config.projectRoot+'/compose.yaml','ps','--format','json','postgres'],{windowsHide:true,timeout:8000,maxBuffer:1024*1024});
        const raw=stdout.trim();let rows;try{const v=JSON.parse(raw);rows=Array.isArray(v)?v:[v];}catch{rows=raw.split('\n').filter(Boolean).map(x=>JSON.parse(x));}
        healthy=rows.some(x=>x.Service==='postgres'&&x.State==='running'&&x.Health==='healthy');
      }catch{healthy=false;}
      return healthy;
    },
    open:async job=>{
      if(opened||config.autoOpen===false)return;
      if(!UUID.test(job.thread_id))throw new Error('invalid_thread_id');
      await run('pwsh',['-NoLogo','-NoProfile','-Command',`Start-Process -FilePath 'codex://threads/${job.thread_id}'`],{windowsHide:true,timeout:15000,maxBuffer:65536});
      opened=true;
    },
    submit:async job=>{
      const body=`${marker(job.id)}\n原始接收时间：${new Date(job.received_at).toISOString()}\n\n${job.body}`;
      await run(config.codexPath,['queue','--thread',job.thread_id,'--message',body],
        {cwd:job.workspace,windowsHide:true,timeout:60000,maxBuffer:1024*1024});
      // Only enqueue. The desktop deep link owns resume; never ask another daemon to take the writer.
    },
    scan,
  };
}

export class Worker {
  constructor(queue,deps,{allow,send,now=Date.now}={}){this.queue=queue;this.deps=deps;this.allow=allow;this.send=send;this.now=now;this.busy=false;}
  async tick(){
    if(this.busy)return;
    this.busy=true;
    try{
      const job=this.queue.active();
      if(job){
        if(!this.allow(job)){this.queue.update(job.id,{state:'paused',error:'owner_or_binding_changed'});}
        else if(job.state==='pending'){
          if(await this.deps.ready()){
            const target=this.deps.lookup(job);
            await this.deps.open(job);
            const latest=this.queue.get(job.id);
            if(latest.state==='pending'&&this.allow(latest)&&this.queue.claim(job.id,target.rollout,statSync(target.rollout).size)){
              try{await this.deps.submit(job);this.queue.update(job.id,{state:'queued'});}
              catch{this.queue.update(job.id,{state:'uncertain',error:'queue_submission_uncertain'});}
            }
          }
        }else{
          const target=this.deps.lookup(job);
          if(target.rollout!==job.rollout)throw new Error('rollout_path_changed');
          // Opening a queued session does not enqueue it a second time.
          if(await this.deps.ready())await this.deps.open(job);
          this.queue.update(job.id,this.deps.scan(job));
        }
      }
      const reply=this.queue.replies(this.now());
      if(reply&&this.allow(reply)){
        const text=reply.final_text.slice(reply.reply_offset,safeEnd(reply.final_text,Math.min(reply.final_text.length,reply.reply_offset+3000)));
        if(!text){this.queue.update(reply.id,{state:'delivered'});}
        else{
          try{
            await this.send(reply,text);
            const offset=reply.reply_offset+text.length;
            this.queue.update(reply.id,{reply_offset:offset,state:offset>=reply.final_text.length?'delivered':'completed',next_delivery:0});
          }catch{this.queue.update(reply.id,{error:'reply_delivery_failed',next_delivery:this.now()+60000});}
        }
      }
    }catch(error){
      const job=this.queue.active();
      if(job)this.queue.update(job.id,{state:job.state==='pending'?'paused':'uncertain',error:String(error.message??'worker_error').slice(0,120)});
    }finally{this.busy=false;}
  }
}
