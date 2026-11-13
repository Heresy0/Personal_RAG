import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { normalizeWeixinPeer, weixinBindings as bindings,
  weixinConversationBindings as support, weixinBindingMessaging as messaging } from './conversation-bindings.ts';

const peer='Owner_ABC-12@im.wechat';
const other='Other_ABC-12@im.wechat';
const accountId='example-im-bot';

test('command, ordinary message and delivery use the same opaque direct peer',()=>{
  const expected={conversationId:peer};
  assert.deepEqual(bindings.resolveCommandConversation({accountId,senderId:peer,from:peer,originatingTo:peer,commandTo:peer}),expected);
  assert.deepEqual(messaging.resolveInboundConversation({from:peer,to:peer,conversationId:peer,isGroup:false}),expected);
  assert.deepEqual(messaging.resolveDeliveryTarget(expected),{to:peer});
  assert.deepEqual(support.resolveConversationRef({accountId,...expected}),expected);
});
test('normalization accepts the channel prefix, preserves peer case and rejects foreign grammar',()=>{
  assert.equal(normalizeWeixinPeer(` openclaw-weixin:${peer} `),peer);
  for (const bad of ['',null,{},'telegram:'+peer,'group:room','../'+peer,peer+':topic:1',peer+'\nBAD','@im.wechat']) assert.equal(normalizeWeixinPeer(bad),null);
  assert.notEqual(normalizeWeixinPeer(peer),normalizeWeixinPeer(peer.toLowerCase()));
});
test('inconsistent sender/target cannot silently bind a different peer',()=>{
  assert.equal(bindings.resolveCommandConversation({accountId,senderId:peer,originatingTo:other}),null);
  assert.equal(messaging.resolveInboundConversation({from:peer,to:other,isGroup:false}),null);
  assert.equal(bindings.resolveCommandConversation({accountId,senderId:peer,from:'bad'}),null);
});
test('group and thread contexts are excluded',()=>{
  assert.equal(bindings.resolveCommandConversation({accountId,senderId:peer,chatType:'group'}),null);
  assert.equal(bindings.resolveCommandConversation({accountId,senderId:peer,threadId:'1'}),null);
  assert.equal(messaging.resolveInboundConversation({from:peer,isGroup:true}),null);
  assert.equal(messaging.resolveInboundConversation({from:peer,isGroup:false,threadParentId:'1'}),null);
  assert.equal(messaging.resolveDeliveryTarget({conversationId:peer,parentConversationId:other}),null);
  assert.equal(support.resolveConversationRef({accountId,conversationId:peer,threadId:1}),null);
});
test('configured bindings only match the exact direct peer',()=>{
  const compiledBinding=bindings.compileConfiguredBinding({conversationId:peer,binding:{}});
  assert.deepEqual(bindings.matchInboundConversation({compiledBinding,conversationId:peer,binding:{}}),{conversationId:peer});
  assert.equal(bindings.matchInboundConversation({compiledBinding,conversationId:other,binding:{}}),null);
  assert.equal(bindings.matchInboundConversation({compiledBinding,conversationId:peer,parentConversationId:other,binding:{}}),null);
});
test('binding support uses the native current-conversation store, not an adapter-owned shadow store',()=>{
  assert.equal(support.supportsCurrentConversationBinding,true);
  assert.equal(support.defaultTopLevelPlacement,'current');
  assert.equal(support.bindingStore,undefined);
  assert.equal(bindings.resolveCommandConversation({accountId:'',senderId:peer}),null);
  assert.equal(support.resolveConversationRef({conversationId:peer}),null);
});

test('pinned OpenClaw core keeps account and peer in the canonical binding tuple',
  {skip:!process.env.OPENCLAW_TEST_BINDING_CORE},async()=>{
    const {A:resolve}=await import(pathToFileURL(process.env.OPENCLAW_TEST_BINDING_CORE).href);
    const plugin={id:'openclaw-weixin',bindings,config:{defaultAccountId:()=>accountId}};
    const resolveFor=(account,person)=>resolve({cfg:{},plugin,channel:'openclaw-weixin',accountId:account,
      senderId:person,from:person,originatingTo:person,commandTo:person});
    assert.deepEqual(resolveFor(accountId,peer),{channel:'openclaw-weixin',accountId,conversationId:peer});
    assert.notDeepEqual(resolveFor('another-im-bot',peer),resolveFor(accountId,peer));
    assert.notDeepEqual(resolveFor(accountId,other),resolveFor(accountId,peer));
  });
