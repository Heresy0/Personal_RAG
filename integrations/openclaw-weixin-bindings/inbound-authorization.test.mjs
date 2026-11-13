import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

test('plain bound-turn text uses real ingress authorization and rejects other senders',
  {skip:!process.env.OPENCLAW_TEST_WEIXIN_AUTH},async()=>{
    const {resolveWeixinInboundAuthorization}=await import(pathToFileURL(process.env.OPENCLAW_TEST_WEIXIN_AUTH).href);
    const owner='Owner@im.wechat';
    const base={accountId:'isolated-test-bot',senderId:owner,rawBody:'continue the existing conversation',
      config:{},allowFrom:[owner],commands:{shouldComputeCommandAuthorized:()=>true}};
    assert.deepEqual(await resolveWeixinInboundAuthorization(base),{senderAllowed:true,commandAuthorized:true});
    const denied=await resolveWeixinInboundAuthorization({...base,senderId:'Stranger@im.wechat'});
    assert.equal(denied.senderAllowed,false);
    assert.equal(denied.commandAuthorized,false);
    const legacy=await resolveWeixinInboundAuthorization({...base,allowFrom:[]});
    assert.equal(legacy.commandAuthorized,false);
    // The upstream optimization was the cause: ordinary text omitted authorization.
    assert.equal((await resolveWeixinInboundAuthorization({...base,commands:{shouldComputeCommandAuthorized:()=>false}})).commandAuthorized,undefined);
  });
