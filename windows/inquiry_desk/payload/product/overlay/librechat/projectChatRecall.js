const { tool } = require('@librechat/agents/langchain/tools');

const SEARCH_TOOL_NAME = 'project_chat_search';
const READ_TOOL_NAME = 'project_chat_read';
const MAX_PROJECT_CONVERSATIONS = 500;
const CONVERSATION_PAGE_SIZE = 100;
const MAX_MATCHING_MESSAGES = 500;
const MAX_SEARCH_RESULTS = 8;
const MAX_READ_MESSAGES = 20;
const MAX_MESSAGE_TEXT_CHARS = 4000;
const MAX_READ_OUTPUT_CHARS = 24 * 1024;

const searchSchema = {
  type: 'object',
  properties: {
    query: {
      type: 'string',
      description:
        'What to look for in prior chats from this same Project. Required for relevance search; optional for oldest/newest metadata selection.',
    },
    selection: {
      type: 'string',
      enum: ['relevance', 'oldest', 'newest'],
      description:
        'How to select prior Project chats. relevance searches title/message text (default); oldest/newest select by LibreChat conversation createdAt metadata without requiring a text match.',
    },
    top_k: {
      type: 'integer',
      minimum: 1,
      maximum: MAX_SEARCH_RESULTS,
      description: 'Maximum number of prior Project chats to return.',
    },
  },
};

const readSchema = {
  type: 'object',
  properties: {
    conversation_id: {
      type: 'string',
      description: 'Conversation ID returned by project_chat_search.',
    },
    message_id: {
      type: 'string',
      description:
        'Optional exact message ID returned by project_chat_search. When supplied, return that message with a bounded parent/child context window.',
    },
  },
  required: ['conversation_id'],
};

function modelMethods() {
  const { getConvosByCursor, getConvosQueried, getMessages } = require('../../../../models');
  return { getConvosByCursor, getConvosQueried, getMessages };
}

function normalizeText(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function extractQueryTerms(query) {
  const normalized = normalizeText(query);
  const terms = [];
  const seen = new Set();
  const add = (value) => {
    const term = normalizeText(value);
    if (term.length < 2 || seen.has(term)) {
      return;
    }
    seen.add(term);
    terms.push(term);
  };

  for (const value of normalized.match(/[a-z0-9][a-z0-9_.:/-]{1,}/g) ?? []) {
    add(value);
  }

  for (const value of normalized.match(/[\p{L}\p{N}]{2,}/gu) ?? []) {
    add(value);
  }

  for (const sequence of normalized.match(/\p{Script=Han}{2,}/gu) ?? []) {
    add(sequence);
    for (let index = 0; index + 1 < sequence.length && terms.length < 24; index += 1) {
      add(sequence.slice(index, index + 2));
    }
  }

  if (normalized.length >= 2) {
    add(normalized);
  }
  return terms.slice(0, 24);
}

function extractMessageText(message) {
  if (typeof message?.text === 'string' && message.text.trim()) {
    return message.text.trim();
  }
  if (typeof message?.content === 'string' && message.content.trim()) {
    return message.content.trim();
  }
  if (!Array.isArray(message?.content)) {
    return '';
  }

  const chunks = [];
  for (const part of message.content) {
    if (!part || typeof part !== 'object' || part.type !== 'text') {
      continue;
    }
    if (typeof part.text === 'string' && part.text.trim()) {
      chunks.push(part.text.trim());
      continue;
    }
    if (
      part.text &&
      typeof part.text === 'object' &&
      typeof part.text.value === 'string' &&
      part.text.value.trim()
    ) {
      chunks.push(part.text.value.trim());
      continue;
    }
    if (typeof part.content === 'string' && part.content.trim()) {
      chunks.push(part.content.trim());
    }
  }
  return chunks.join('\n').trim();
}

function scoreText(text, title, normalizedQuery, terms) {
  const normalizedText = normalizeText(text);
  const normalizedTitle = normalizeText(title);
  let score = 0;
  if (normalizedQuery && normalizedText.includes(normalizedQuery)) {
    score += 20;
  }
  if (normalizedQuery && normalizedTitle.includes(normalizedQuery)) {
    score += 16;
  }
  for (const term of terms) {
    if (normalizedText.includes(term)) {
      score += term.length >= 6 ? 4 : 2;
    }
    if (normalizedTitle.includes(term)) {
      score += term.length >= 6 ? 3 : 1;
    }
  }
  return score;
}

function boundedText(value, maxChars = MAX_MESSAGE_TEXT_CHARS) {
  const text = String(value ?? '');
  return text.length <= maxChars ? text : `${text.slice(0, maxChars)}\n...[truncated]`;
}

function messageProjection(message) {
  return {
    message_id: message.messageId,
    parent_message_id: message.parentMessageId ?? null,
    role: message.isCreatedByUser ? 'user' : 'assistant',
    text: boundedText(extractMessageText(message)),
    created_at: message.createdAt ?? null,
  };
}

async function listProjectConversations({
  userId,
  chatProjectId,
  currentConversationId,
  methods,
  sortBy = 'updatedAt',
  sortDirection = 'desc',
}) {
  const conversations = [];
  let cursor = null;
  let truncated = false;

  for (let page = 0; page < Math.ceil(MAX_PROJECT_CONVERSATIONS / CONVERSATION_PAGE_SIZE); page += 1) {
    const result = await methods.getConvosByCursor(userId, {
      cursor,
      limit: CONVERSATION_PAGE_SIZE,
      projectId: chatProjectId,
      sortBy,
      sortDirection,
    });
    const pageConversations = Array.isArray(result?.conversations) ? result.conversations : [];
    for (const conversation of pageConversations) {
      if (
        conversation?.conversationId &&
        conversation.conversationId !== currentConversationId &&
        conversation.chatProjectId === chatProjectId
      ) {
        conversations.push(conversation);
      }
      if (conversations.length >= MAX_PROJECT_CONVERSATIONS) {
        truncated = true;
        return { conversations, truncated };
      }
    }
    cursor = result?.nextCursor ?? null;
    if (!cursor) {
      return { conversations, truncated };
    }
  }

  truncated = Boolean(cursor);
  return { conversations, truncated };
}

function buildMessageSearchFilter({ userId, conversationIds, terms }) {
  const regexTerms = terms
    .filter((term) => term.length >= 2)
    .slice(0, 12)
    .map(escapeRegex);
  if (!regexTerms.length) {
    return null;
  }
  const regex = new RegExp(regexTerms.join('|'), 'i');
  return {
    user: userId,
    conversationId: { $in: conversationIds },
    $or: [{ text: regex }, { 'content.text': regex }, { 'content.text.value': regex }],
  };
}

async function projectChatSearch({
  userId,
  chatProjectId,
  currentConversationId,
  query = '',
  topK,
  selection = 'relevance',
  methods,
}) {
  const selectedMode = ['relevance', 'oldest', 'newest'].includes(selection)
    ? selection
    : 'relevance';
  const isMetadataSelection = selectedMode === 'oldest' || selectedMode === 'newest';
  const normalizedQuery = normalizeText(query);
  const terms = extractQueryTerms(query);
  if (!isMetadataSelection && (!normalizedQuery || terms.length === 0)) {
    return {
      schema: 'LC_PROJECT_CHAT_SEARCH_R001',
      chat_project_id: chatProjectId,
      query,
      candidates: [],
      error: 'QUERY_TOO_SHORT',
    };
  }

  const { conversations, truncated } = await listProjectConversations({
    userId,
    chatProjectId,
    currentConversationId,
    methods,
    sortBy: isMetadataSelection ? 'createdAt' : 'updatedAt',
    sortDirection: selectedMode === 'oldest' ? 'asc' : 'desc',
  });
  if (!conversations.length) {
    return {
      schema: 'LC_PROJECT_CHAT_SEARCH_R001',
      chat_project_id: chatProjectId,
      query,
      selection: selectedMode,
      searched_conversation_count: 0,
      truncated,
      candidates: [],
    };
  }

  if (isMetadataSelection) {
    return {
      schema: 'LC_PROJECT_CHAT_SEARCH_R001',
      chat_project_id: chatProjectId,
      query,
      selection: selectedMode,
      searched_conversation_count: conversations.length,
      candidate_limit: topK,
      truncated,
      candidates: conversations.slice(0, topK).map((conversation) => ({
        conversation_id: conversation.conversationId,
        title: conversation.title ?? '',
        created_at: conversation.createdAt ?? null,
        updated_at: conversation.updatedAt ?? null,
        relevance_score: null,
        match: null,
      })),
    };
  }

  const conversationMap = new Map(
    conversations.map((conversation) => [conversation.conversationId, conversation]),
  );
  const scores = new Map();

  const ensureScore = (conversation) => {
    let current = scores.get(conversation.conversationId);
    if (!current) {
      const titleScore = scoreText('', conversation.title ?? '', normalizedQuery, terms);
      current = {
        conversation_id: conversation.conversationId,
        title: conversation.title ?? '',
        created_at: conversation.createdAt ?? null,
        updated_at: conversation.updatedAt ?? null,
        score: titleScore,
        match: null,
      };
      scores.set(conversation.conversationId, current);
    }
    return current;
  };

  for (const conversation of conversations) {
    ensureScore(conversation);
  }

  const messageFilter = buildMessageSearchFilter({
    userId,
    conversationIds: [...conversationMap.keys()],
    terms,
  });
  const messages = messageFilter
    ? await methods.getMessages(
        messageFilter,
        'conversationId messageId parentMessageId isCreatedByUser sender text content createdAt updatedAt',
        { sort: { createdAt: -1 }, limit: MAX_MATCHING_MESSAGES },
      )
    : [];

  for (const message of messages ?? []) {
    const conversation = conversationMap.get(message.conversationId);
    if (!conversation) {
      continue;
    }
    const text = extractMessageText(message);
    if (!text) {
      continue;
    }
    const messageScore = scoreText(text, conversation.title ?? '', normalizedQuery, terms);
    if (messageScore <= 0) {
      continue;
    }
    const current = ensureScore(conversation);
    if (!current.match || messageScore > current.match.score) {
      current.match = {
        message_id: message.messageId,
        role: message.isCreatedByUser ? 'user' : 'assistant',
        excerpt: boundedText(text, 800),
        score: messageScore,
      };
    }
    current.score = Math.max(current.score, messageScore);
  }

  const candidates = [...scores.values()]
    .filter((candidate) => candidate.score > 0)
    .sort((left, right) => right.score - left.score || String(right.updated_at).localeCompare(String(left.updated_at)))
    .slice(0, topK)
    .map((candidate) => ({
      conversation_id: candidate.conversation_id,
      title: candidate.title,
      created_at: candidate.created_at,
      updated_at: candidate.updated_at,
      relevance_score: candidate.score,
      match: candidate.match
        ? {
            message_id: candidate.match.message_id,
            role: candidate.match.role,
            excerpt: candidate.match.excerpt,
          }
        : null,
    }));

  return {
    schema: 'LC_PROJECT_CHAT_SEARCH_R001',
    chat_project_id: chatProjectId,
    query,
    selection: selectedMode,
    searched_conversation_count: conversations.length,
    candidate_limit: topK,
    truncated,
    candidates,
  };
}

async function verifyProjectConversation({ userId, chatProjectId, conversationId, methods }) {
  const result = await methods.getConvosQueried(userId, [{ conversationId }], null, 2);
  const conversations = Array.isArray(result?.conversations) ? result.conversations : [];
  const conversation = conversations.find((item) => item?.conversationId === conversationId);
  if (!conversation || conversation.chatProjectId !== chatProjectId) {
    return null;
  }
  return conversation;
}

async function projectChatRead({
  userId,
  chatProjectId,
  currentConversationId,
  conversationId,
  messageId,
  methods,
}) {
  if (!conversationId || conversationId === currentConversationId) {
    return {
      schema: 'LC_PROJECT_CHAT_READ_R001',
      chat_project_id: chatProjectId,
      conversation_id: conversationId,
      messages: [],
      error: conversationId === currentConversationId ? 'CURRENT_CHAT_NOT_HISTORY' : 'INVALID_CONVERSATION_ID',
    };
  }

  const conversation = await verifyProjectConversation({
    userId,
    chatProjectId,
    conversationId,
    methods,
  });
  if (!conversation) {
    return {
      schema: 'LC_PROJECT_CHAT_READ_R001',
      chat_project_id: chatProjectId,
      conversation_id: conversationId,
      messages: [],
      error: 'PROJECT_CHAT_SCOPE_MISMATCH',
    };
  }

  const select =
    'conversationId messageId parentMessageId isCreatedByUser sender text content createdAt updatedAt error unfinished';
  let rows = [];

  if (messageId) {
    const targetRows = await methods.getMessages(
      { user: userId, conversationId, messageId },
      select,
      { sort: false, limit: 1 },
    );
    const target = targetRows?.[0];
    if (!target) {
      return {
        schema: 'LC_PROJECT_CHAT_READ_R001',
        chat_project_id: chatProjectId,
        conversation_id: conversationId,
        title: conversation.title ?? '',
        messages: [],
        error: 'MESSAGE_NOT_FOUND_IN_PROJECT_CHAT',
      };
    }

    const ancestry = [];
    let parentId = target.parentMessageId;
    for (let depth = 0; depth < 4 && typeof parentId === 'string' && parentId; depth += 1) {
      const parentRows = await methods.getMessages(
        { user: userId, conversationId, messageId: parentId },
        select,
        { sort: false, limit: 1 },
      );
      const parent = parentRows?.[0];
      if (!parent) {
        break;
      }
      ancestry.push(parent);
      parentId = parent.parentMessageId;
    }

    const children = await methods.getMessages(
      { user: userId, conversationId, parentMessageId: target.messageId },
      select,
      { sort: { createdAt: 1 }, limit: 4 },
    );
    rows = [...ancestry.reverse(), target, ...(children ?? [])];
  } else {
    rows = await methods.getMessages(
      { user: userId, conversationId },
      select,
      { sort: { createdAt: -1 }, limit: MAX_READ_MESSAGES },
    );
    rows = [...(rows ?? [])].reverse();
  }

  const unique = [];
  const seen = new Set();
  let outputChars = 0;
  let truncated = false;
  for (const row of rows) {
    if (!row?.messageId || seen.has(row.messageId)) {
      continue;
    }
    const projected = messageProjection(row);
    const cost = JSON.stringify(projected).length;
    if (outputChars + cost > MAX_READ_OUTPUT_CHARS) {
      truncated = true;
      break;
    }
    seen.add(row.messageId);
    outputChars += cost;
    unique.push(projected);
  }

  return {
    schema: 'LC_PROJECT_CHAT_READ_R001',
    chat_project_id: chatProjectId,
    conversation_id: conversationId,
    title: conversation.title ?? '',
    updated_at: conversation.updatedAt ?? null,
    anchored_message_id: messageId ?? null,
    truncated,
    messages: unique,
  };
}

function createProjectChatRecallTools({
  userId,
  chatProjectId,
  currentConversationId,
  methods = modelMethods(),
}) {
  if (
    typeof userId !== 'string' ||
    !userId ||
    typeof chatProjectId !== 'string' ||
    !chatProjectId
  ) {
    return [];
  }

  const searchTool = tool(
    async ({ query = '', selection = 'relevance', top_k = 5 }) =>
      JSON.stringify(
        await projectChatSearch({
          userId,
          chatProjectId,
          currentConversationId,
          query,
          selection,
          topK: Math.min(Math.max(Number.isInteger(top_k) ? top_k : 5, 1), MAX_SEARCH_RESULTS),
          methods,
        }),
      ),
    {
      name: SEARCH_TOOL_NAME,
      description:
        'Search prior chats from the current Project only. Default selection=relevance searches title/message content. Use selection=oldest or selection=newest for metadata-only createdAt ordering when the user asks for earliest/latest Project chats; query is optional in those modes. The Project and user scope are fixed by the server; you cannot choose another Project. Call project_chat_read on a returned conversation/message when exact historical wording or nearby context is needed.',
      schema: searchSchema,
    },
  );

  const readTool = tool(
    async ({ conversation_id, message_id }) =>
      JSON.stringify(
        await projectChatRead({
          userId,
          chatProjectId,
          currentConversationId,
          conversationId: conversation_id,
          messageId: message_id,
          methods,
        }),
      ),
    {
      name: READ_TOOL_NAME,
      description:
        'Read exact bounded messages from a prior chat in the current Project. Use a conversation_id returned by project_chat_search; do not substitute WebCodex/local-file reads for chat history. If message_id is provided, returns that exact message with a small parent/child context window. Cross-Project, other-user, hidden, and current-chat reads fail closed.',
      schema: readSchema,
    },
  );

  return [searchTool, readTool];
}

module.exports = {
  SEARCH_TOOL_NAME,
  READ_TOOL_NAME,
  createProjectChatRecallTools,
  projectChatSearch,
  projectChatRead,
  extractQueryTerms,
  extractMessageText,
};
