import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { createWeixinBindingApprovalBridge } from './binding-approval.ts';
import { normalizeWeixinPeer } from './conversation-bindings.ts';

const peer='Owner_ABC@im.wechat';
const token='pluginbind:example-approval:allow-once';
const denied='pluginbind:example-approval:deny';
function fixture(){
  let now=100;const calls=[];
  const bridge=createWeixinBindingApprovalBridge({
    parse:value=>{
      const match=/^pluginbind:([a-z-]+):(allow-once|allow-always|deny)$/.exec(value);
      return match?{approvalId:match[1],decision:match[2]}:null;
    },
    resolve:async params=>{calls.push(params);return {status:'approved'};},
    format:result=>result.status,
    peer:normalizeWeixinPeer,
    now:()=>now,
  });
  const payload={text:'Plugin bind approval required',interactive:{blocks:[{type:'buttons',buttons:[
    {value:token},{value:'pluginbind:example-approval:allow-always'},{value:denied},
  ]}]}};
  const ctx={channel:'openclaw-weixin',accountId:'bot-a',senderId:peer,args:token};
  return {bridge,calls,payload,ctx,advance:()=>now+=30*60_000};
}
test('binding consent gets explicit text choices, without an implicit or permanent grant',()=>{
  const f=fixture();const text=f.bridge.render(f.payload,'bot-a',peer);
  assert.match(text,/\/wxbind pluginbind:example-approval:allow-once/);
  assert.match(text,/\/wxbind pluginbind:example-approval:deny/);
  assert.doesNotMatch(text,/allow-always/);
  assert.deepEqual(f.calls,[]);
  assert.equal(f.bridge.command().requireAuth,true);
});
test('only the same sender on the same bot may resolve native consent; replay is blocked',async()=>{
  const f=fixture();f.bridge.render(f.payload,'bot-a',peer);
  const command=f.bridge.command();
  await command.handler({...f.ctx,accountId:'bot-b'});
  await command.handler({...f.ctx,senderId:'Other@im.wechat'});
  await command.handler({...f.ctx,channel:'other'});
  assert.equal(f.calls.length,0);
  assert.equal((await command.handler(f.ctx)).text,'approved');
  assert.equal(f.calls.length,1);
  await command.handler(f.ctx);assert.equal(f.calls.length,1);
});
test('expired and never-delivered approval tokens cannot be executed',async()=>{
  const f=fixture();await f.bridge.command().handler(f.ctx);assert.equal(f.calls.length,0);
  f.bridge.render(f.payload,'bot-a',peer);f.advance();
  await f.bridge.command().handler(f.ctx);assert.equal(f.calls.length,0);
});
test('deny uses the native resolver and consumes the pending request',async()=>{
  const f=fixture();f.bridge.render(f.payload,'bot-a',peer);
  await f.bridge.command().handler({...f.ctx,args:denied});
  assert.equal(f.calls[0].decision,'deny');
  await f.bridge.command().handler(f.ctx);assert.equal(f.calls.length,1);
});
test('ordinary replies and unrelated interactive controls remain unchanged',()=>{
  const f=fixture();assert.equal(f.bridge.render({text:'  original\n'},'bot-a',peer),'  original\n');
  assert.equal(f.bridge.render({text:'plain',interactive:{blocks:[{type:'buttons',buttons:[{value:'run-shell:bad'}]}]}},'bot-a',peer),'plain');
});
test('the pinned reply dispatcher preserves native consent controls for the Weixin text renderer',
  {skip:!process.env.OPENCLAW_TEST_REPLY_SDK},async()=>{
    const {createReplyDispatcher}=await import(pathToFileURL(process.env.OPENCLAW_TEST_REPLY_SDK).href);
    const f=fixture();const delivered=[];
    const dispatcher=createReplyDispatcher({deliver:async payload=>{delivered.push(f.bridge.render(payload,'bot-a',peer));}});
    try {
      dispatcher.sendFinalReply(f.payload);
      await dispatcher.waitForIdle();
      assert.equal(delivered.length,1);
      assert.ok(delivered[0].includes('/wxbind '+token));
      assert.equal((await f.bridge.command().handler(f.ctx)).text,'approved');
    } finally {dispatcher.markComplete();}
  });
test('the pinned SDK action value survives text rendering and reaches its native resolver unchanged',
  {skip:!process.env.OPENCLAW_TEST_CONVERSATION_SDK},async()=>{
    const sdk=await import(pathToFileURL(process.env.OPENCLAW_TEST_CONVERSATION_SDK).href);
    const calls=[];const value=sdk.buildPluginBindingApprovalCustomId('sdk-example','allow-once');
    const bridge=createWeixinBindingApprovalBridge({parse:sdk.parsePluginBindingApprovalCustomId,
      resolve:async p=>{calls.push(p);return {status:'approved'};},format:()=> 'native approved',peer:normalizeWeixinPeer});
    const text=bridge.render({interactive:{blocks:[{type:'buttons',buttons:[{value}]}]}},'bot-a',peer);
    assert.ok(text.includes('/wxbind '+value));
    assert.equal((await bridge.command().handler({channel:'openclaw-weixin',accountId:'bot-a',senderId:peer,args:value})).text,'native approved');
    assert.deepEqual(calls,[{approvalId:'sdk-example',decision:'allow-once',senderId:peer}]);
  });
