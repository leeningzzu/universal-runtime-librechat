'use strict';
// R191 thin native LibreChat bridge. All tool content is read-only and
// belongs to an already authenticated, owner-validated Project context.
// No Project database, memory store, Pack engine, or alternate shell.
const { createProjectChatRecallTools } = require('./projectChatRecall');
const OWNED_TOOL_MARK = Symbol.for('aides.projectChatReadOnlyOwner');

function attachValidatedProjectChatTools({ agents, request, conversationId }) {
  const ownerId = request?.user?.id;
  const validatedProjectId = request?.chatProjectContext?.projectId;
  if (
    typeof ownerId !== 'string' || ownerId.length === 0 ||
    typeof validatedProjectId !== 'string' || validatedProjectId.length === 0
  ) {
    return { attached: 0, reason: 'NO_VALIDATED_PROJECT_CONTEXT' };
  }
  const claims = [
    request?.body?.chatProjectId,
    request?.resolvedConversation?.chatProjectId,
  ].filter((x) => x !== undefined && x !== null && x !== '');
  if (claims.some((x) => x !== validatedProjectId)) {
    const err = new Error('PROJECT_CHAT_RECALL_CONTEXT_SCOPE_MISMATCH');
    err.code = 'PROJECT_CHAT_RECALL_CONTEXT_SCOPE_MISMATCH';
    throw err;
  }
  const checked = new Set();
  let attached = 0;
  for (const agent of agents ?? []) {
    if (!agent || checked.has(agent)) continue;
    checked.add(agent);
    const tools = Array.isArray(agent.tools) ? [...agent.tools] : [];
    const byName = new Map(
      tools.filter((x) => x && typeof x.name === 'string').map((x) => [x.name, x]),
    );
    const additions = createProjectChatRecallTools({
      userId: ownerId,
      chatProjectId: validatedProjectId,
      currentConversationId: conversationId,
    });
    for (const added of additions) {
      const existing = byName.get(added.name);
      if (existing) {
        if (existing[OWNED_TOOL_MARK] === true) continue;
        const err = new Error('PROJECT_CHAT_RECALL_TOOL_NAME_COLLISION');
        err.code = 'PROJECT_CHAT_RECALL_TOOL_NAME_COLLISION';
        throw err;
      }
      Object.defineProperty(added, OWNED_TOOL_MARK, { value: true, enumerable: false });
      tools.push(added);
      byName.set(added.name, added);
      attached++;
    }
    agent.tools = tools;
  }
  return { attached, reason: 'SAME_PROJECT_READ_ONLY' };
}
module.exports = { attachValidatedProjectChatTools };
