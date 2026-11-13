import type { ChannelPlugin } from "openclaw/plugin-sdk/channel-core";

/** Weixin direct-message IDs are opaque: preserve case and reject thread/group grammar. */
export function normalizeWeixinPeer(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const peer = value.trim().replace(/^openclaw-weixin:/i, "");
  return /^[A-Za-z0-9_-]{1,128}@im\.wechat$/.test(peer) ? peer : null;
}

function directRef(value: unknown) {
  const conversationId = normalizeWeixinPeer(value);
  return conversationId ? { conversationId } : null;
}

function samePeer(values: unknown[]) {
  const present = values.filter((value) => value !== undefined && value !== null && value !== "");
  if (!present.length) return null;
  const peers = present.map(normalizeWeixinPeer);
  return peers[0] && peers.every((peer) => peer === peers[0]) ? directRef(peers[0]) : null;
}

/** The core scopes the persistent binding tuple by channel AND accountId. */
export const weixinBindings: NonNullable<ChannelPlugin["bindings"]> = {
  compileConfiguredBinding: ({ conversationId }) => directRef(conversationId),
  matchInboundConversation: ({ compiledBinding, conversationId, parentConversationId }) => {
    if (parentConversationId || compiledBinding.parentConversationId) return null;
    return samePeer([compiledBinding.conversationId, conversationId]);
  },
  resolveCommandConversation: (ctx) => {
    if (ctx.chatType && ctx.chatType !== "direct") return null;
    if (ctx.threadId || ctx.threadParentId || !ctx.accountId?.trim()) return null;
    return samePeer([ctx.senderId, ctx.from, ctx.originatingTo, ctx.commandTo, ctx.fallbackTo]);
  },
};

export const weixinConversationBindings: NonNullable<ChannelPlugin["conversationBindings"]> = {
  supportsCurrentConversationBinding: true,
  defaultTopLevelPlacement: "current",
  resolveConversationRef: ({ accountId, conversationId, parentConversationId, threadId }) => {
    if (!accountId?.trim() || parentConversationId || threadId != null) return null;
    return directRef(conversationId);
  },
};

export const weixinBindingMessaging = {
  resolveInboundConversation: ((ctx) => {
    if (ctx.isGroup || ctx.threadId != null || ctx.threadParentId != null) return null;
    return samePeer([ctx.from, ctx.to, ctx.conversationId]);
  }) satisfies NonNullable<NonNullable<ChannelPlugin["messaging"]>["resolveInboundConversation"]>,
  resolveDeliveryTarget: ((ctx) => {
    if (ctx.parentConversationId) return null;
    const peer = normalizeWeixinPeer(ctx.conversationId);
    return peer ? { to: peer } : null;
  }) satisfies NonNullable<NonNullable<ChannelPlugin["messaging"]>["resolveDeliveryTarget"]>,
};
