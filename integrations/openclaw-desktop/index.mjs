import {join} from 'node:path';
import {Queue} from './queue.mjs';
import {Worker,nativeDependencies} from './worker.mjs';
import {UUID} from './catalog.mjs';
import {readFileSync} from 'node:fs';

const peerPattern=/^[A-Za-z0-9_-]{1,128}@im\.wechat$/;
const accountPattern=/^[A-Za-z0-9_-]{1,128}$/;
export function authorized(config,event,ctx){
  const sender=event.senderId??ctx.senderId??ctx.conversationId,account=event.accountId??ctx.accountId;
  // before_dispatch does not expose senderIsOwner/commandAuthorized. Identity is
  // checked against the live owner ACL AND the logged-in Weixin account below.
  return ctx.channelId==='openclaw-weixin'&&event.senderIsOwner!==false&&event.commandAuthorized!==false&&
    event.isGroup===false&&!event.parentConversationId&&event.threadId==null&&
    typeof account==='string'&&accountPattern.test(account)&&typeof sender==='string'&&peerPattern.test(sender)&&
    (!ctx.conversationId||ctx.conversationId===sender)&&
    (config.commands?.ownerAllowFrom??[]).includes('openclaw-weixin:'+sender);
}

export function registerDesktop(api,{QueueClass=Queue,dependencies=nativeDependencies}={}){
  const options=api.pluginConfig;
  if(!options||!UUID.test(options.threadId??''))throw new Error('desktop_thread_not_configured');
  let queue,worker,timer,inFlight;
  const receipts=new Map();
  const receiptKey=(account,peer,id)=>JSON.stringify([account,peer,id]);
  const owner=peer=>{
    try{
      const current=JSON.parse(readFileSync(join(options.runtimeDir,'state/openclaw.json'),'utf8'));
      const entry=current.plugins?.entries?.['personal-rag-desktop'];
      return entry?.enabled===true&&entry.config?.threadId===options.threadId&&entry.config?.workspace===options.workspace&&
        (current.commands?.ownerAllowFrom??[]).includes('openclaw-weixin:'+peer);
    }catch{return false;}
  };
  const identity=(account,peer)=>{
    if(typeof account!=='string'||!accountPattern.test(account)||!owner(peer))return false;
    try{
      const directory=join(options.runtimeDir,'state/openclaw-weixin');
      if(!JSON.parse(readFileSync(join(directory,'accounts.json'),'utf8')).includes(account))return false;
      return JSON.parse(readFileSync(join(directory,'accounts',account+'.json'),'utf8')).userId===peer;
    }catch{return false;}
  };
  const allow=job=>identity(job.account,job.peer)&&job.thread_id===options.threadId&&job.workspace===options.workspace;
  // Shared by the global pre-dispatch entry and the native command entry.
  // Both callers authenticate the transport identity before reaching this function.
  const control=(args,account,peer)=>{
    if(!queue)return '桌面队列尚未启动。';
    const [action='status',id,confirmation]=(args??'').trim().split(/\s+/).filter(Boolean);
    if(action==='status')return `桌面原会话：${options.threadId}\n目录：${options.workspace}\n`+
      queue.list(account,peer).map(j=>`${j.id} ${j.state}${j.error?' ('+j.error+')':''}`).join('\n');
    const job=UUID.test(id??'')?queue.get(id):null;
    if(!job||job.peer!==peer||job.account!==account)return '找不到当前账号与联系人的任务。';
    if(action==='result')return `${job.id} ${job.state}\n${job.final_text||'尚无已完成结果。'}`;
    if(action==='cancel')return queue.cancel(id,account,peer)?'已取消尚未投递的任务。':'只能取消 pending；不会中断桌面任务。';
    if(action==='acknowledge'&&confirmation==='confirm')return queue.acknowledge(id,account,peer)?
      '已解除此任务的队列等待；没有撤回或重发桌面任务。':'只能确认 uncertain 或 failed 任务。';
    return '用法：/wxdesk status | result <任务ID> | cancel <任务ID> | acknowledge <任务ID> confirm。确认前请在桌面核对原任务是否已执行。';
  };
  api.registerService({id:'personal-rag-desktop-queue',
    start:async()=>{
      queue=new QueueClass(join(options.runtimeDir,'desktop-queue.sqlite'));
      queue.recover();
      worker=new Worker(queue,dependencies(options),{allow,send:async(job,text)=>{
        const adapter=await api.runtime.channel.outbound.loadAdapter('openclaw-weixin');
        if(!adapter?.sendText)throw new Error('weixin_outbound_unavailable');
        const result=await adapter.sendText({cfg:api.config,to:job.peer,accountId:job.account,text});
        if(!result?.messageId)throw new Error('weixin_delivery_not_confirmed');
      }});
      const tick=()=>{if(!worker.busy)inFlight=worker.tick();};
      timer=setInterval(tick,3000);timer.unref();tick();
    },
    stop:async()=>{clearInterval(timer);await inFlight;queue?.close();queue=undefined;}
  });
  // This observer supplies raw text/media facts missing from before_dispatch.
  api.on('message_received',(event,ctx)=>{
    if(ctx.channelId!=='openclaw-weixin')return;
    const peer=event.senderId??ctx.senderId??event.from,id=event.messageId??ctx.messageId;
    if(!id||!identity(ctx.accountId,peer))return;
    for(const [key,value] of receipts)if(value.expires<Date.now())receipts.delete(key);
    if(receipts.size>=256)return;
    receipts.set(receiptKey(ctx.accountId,peer,id),{content:event.content,timestamp:event.timestamp,
      media:Boolean(event.media?.length||event.originalMedia?.length||event.mediaPaths?.length||event.mediaPath||event.mediaUrl||event.mediaUrls?.length||event.mediaStagingPending||event.metadata?.mediaStagingPending||event.metadata?.originalMediaPath||event.metadata?.originalMediaPaths?.length),expires:Date.now()+300000});
  });
  api.on('before_dispatch',async(event,ctx)=>{
    if(ctx.channelId!=='openclaw-weixin')return;
    const peer=event.senderId??ctx.senderId??ctx.conversationId,account=ctx.accountId;
    if(!authorized(api.config,event,ctx)||!identity(account,peer))return {handled:true};
    if(!queue)return {handled:true,text:'桌面队列尚未就绪，未确认收到；请稍后重试。'};
    const messageId=event.messageId??ctx.messageId;
    const receipt=receipts.get(receiptKey(account,peer,messageId));
    if(!receipt||receipt.expires<Date.now())return {handled:true,text:'接收元数据尚未就绪，未确认入队；请稍后重试。'};
    if(receipt.media)return {handled:true,text:'桌面投递暂只支持文字，本条附件未入队。'};
    const body=receipt.content;
    if(typeof body!=='string'||!body.trim()||body.length>12000||typeof messageId!=='string'||!messageId||messageId.length>512)return {handled:true,text:'文字为空、超过12000字符或消息ID无效，本条未入队。'};
    if(/^\/wxdesk(?:\s|$)/.test(body.trim()))return {handled:true,text:control(body.trim().slice('/wxdesk'.length).trim(),account,peer)};
    if(body.trimStart().startsWith('/'))return {handled:true,text:'当前为桌面原会话模式。查看状态请发送 /wxdesk；会话绑定在本机配置中设置。'};
    try{
      const {job,duplicate}=queue.enqueue({account,peer,
        messageId,body,threadId:options.threadId,workspace:options.workspace,
        receivedAt:Number.isFinite(receipt.timestamp)?receipt.timestamp:Date.now()});
      return {handled:true,text:`${duplicate?'此消息已收到，不重复入队':'已落盘，等待桌面原会话处理'}。任务 ${job.id}，状态 ${job.state}。`};
    }catch{return {handled:true,text:'队列写入失败，未确认收到本条消息；请查看本机状态后重试。'};}
  },{priority:100});
  api.registerCommand({name:'wxdesk',description:'Desktop queue status and saved results',acceptsArgs:true,requireAuth:true,
    handler:async ctx=>{
      const peer=ctx.senderId??ctx.from??ctx.to;
      if(ctx.channel!=='openclaw-weixin'||!ctx.isAuthorizedSender||!identity(ctx.accountId,peer))return {text:'无权访问桌面队列。'};
      return {text:control(ctx.args,ctx.accountId,peer)};
    }
  });
}

export default {id:'personal-rag-desktop',name:'Personal RAG desktop queue',register:registerDesktop};
