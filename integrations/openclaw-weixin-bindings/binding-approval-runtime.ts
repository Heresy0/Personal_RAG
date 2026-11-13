import { parsePluginBindingApprovalCustomId, resolvePluginConversationBindingApproval,
  buildPluginBindingResolvedText } from "openclaw/plugin-sdk/conversation-runtime";
import { normalizeWeixinPeer } from "./conversation-bindings.js";
import { createWeixinBindingApprovalBridge } from "./binding-approval.js";

export const weixinBindingApproval = createWeixinBindingApprovalBridge({
  parse: parsePluginBindingApprovalCustomId,
  resolve: resolvePluginConversationBindingApproval,
  format: buildPluginBindingResolvedText,
  peer: normalizeWeixinPeer,
});
