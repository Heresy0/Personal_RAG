import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";
type Sdk = typeof import("openclaw/plugin-sdk/conversation-runtime");
type Payload = { text?: string; interactive?: unknown };
type Pending = { account: string; peer: string; expiresAt: number };

/** Text transport for native binding consent; never creates or approves a binding implicitly. */
export function createWeixinBindingApprovalBridge(deps: {
  parse: Sdk["parsePluginBindingApprovalCustomId"];
  resolve: Sdk["resolvePluginConversationBindingApproval"];
  format: Sdk["buildPluginBindingResolvedText"];
  peer: (value: unknown) => string | null;
  now?: () => number;
}) {
  const pending = new Map<string, Pending>();
  const now = deps.now ?? Date.now;
  const account = (value: unknown) => typeof value === "string" ? value.trim().toLowerCase() : "";
  const prune = () => {
    for (const [id, entry] of pending) if (entry.expiresAt <= now()) pending.delete(id);
  };
  function render(payload: Payload, accountId: string, senderId: string) {
    const text = payload.text ?? "";
    const peer = deps.peer(senderId);
    const owner = account(accountId);
    if (!peer || !owner || !payload.interactive || typeof payload.interactive !== "object") return text;
    const blocks = (payload.interactive as { blocks?: unknown }).blocks;
    if (!Array.isArray(blocks)) return text;
    prune();
    const instructions: string[] = [];
    for (const block of blocks) {
      if (!block || block.type !== "buttons" || !Array.isArray(block.buttons)) continue;
      for (const button of block.buttons) {
        if (typeof button?.value !== "string") continue;
        const parsed = deps.parse(button.value);
        if (!parsed || !["allow-once", "deny"].includes(parsed.decision)) continue;
        const existing = pending.get(parsed.approvalId);
        if (existing && (existing.account !== owner || existing.peer !== peer)) continue;
        if (!existing && pending.size >= 512) continue;
        pending.set(parsed.approvalId, existing ?? { account: owner, peer, expiresAt: now()+30*60_000 });
        instructions.push(`${parsed.decision === "allow-once" ? "同意本次绑定" : "拒绝绑定"}：/wxbind ${button.value}`);
      }
    }
    return instructions.length ? text+'\n\n请复制发送其中一条命令（30分钟内有效）：\n'+instructions.join('\n') : text;
  }
  function command(): Parameters<OpenClawPluginApi["registerCommand"]>[0] {
    return {
      name: "wxbind",
      description: "Confirm or deny a native binding request delivered to this Weixin private chat",
      acceptsArgs: true,
      requireAuth: true,
      handler: async (ctx) => {
        const parsed = deps.parse(ctx.args?.trim() ?? "");
        prune();
        const entry = parsed ? pending.get(parsed.approvalId) : undefined;
        if (ctx.channel !== "openclaw-weixin" || !parsed || !entry ||
            !["allow-once", "deny"].includes(parsed.decision) || entry.account !== account(ctx.accountId) ||
            entry.peer !== deps.peer(ctx.senderId)) {
          return { text: "此确认命令无效、已过期或不属于当前账号和联系人。请重新发送绑定命令。" };
        }
        pending.delete(parsed.approvalId);
        const result = await deps.resolve({ approvalId: parsed.approvalId, decision: parsed.decision, senderId: ctx.senderId });
        return { text: deps.format(result) };
      },
    };
  }
  return { render, command };
}
