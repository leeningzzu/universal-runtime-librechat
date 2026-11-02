const crypto = require('crypto');
const { parseTextParts } = require('librechat-data-provider');

function sourceError(message, status = 400) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function asIso(value) {
  if (value == null) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date.toISOString();
}

function extractAssistantSourceText(message) {
  if (!message || typeof message !== 'object') {
    throw sourceError('Assistant message not found', 404);
  }
  if (message.isCreatedByUser !== false) {
    throw sourceError('Only assistant messages can be saved to Project sources', 409);
  }
  if (message.error || message.unfinished === true) {
    throw sourceError('Only completed assistant messages can be saved to Project sources', 409);
  }
  const content = Array.isArray(message.content) ? message.content : [];
  if (content.some((part) => part && part.groupId != null)) {
    throw sourceError('Parallel/Compare responses must be saved one lane at a time', 409);
  }

  const persistedText = typeof message.text === 'string' ? message.text : '';
  if (persistedText.trim()) {
    return persistedText;
  }

  const text = parseTextParts(content, true);
  if (typeof text !== 'string' || !text.trim()) {
    throw sourceError('Assistant message has no visible text to save', 409);
  }
  return text;
}

function sanitizeFilenameSegment(value) {
  const normalized = String(value || '')
    .replace(/[\u0000-\u001f<>:"/\\|?*]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return normalized.slice(0, 96) || 'Chat response';
}

function buildChatOutputSource({
  userId,
  librechatProjectId,
  conversation,
  message,
}) {
  if (typeof userId !== 'string' || !userId) {
    throw sourceError('Authenticated user scope is required', 401);
  }
  if (
    !conversation ||
    typeof conversation.conversationId !== 'string' ||
    !conversation.conversationId ||
    String(conversation.chatProjectId || '') !== librechatProjectId
  ) {
    throw sourceError('Conversation does not belong to this Project', 409);
  }
  if (
    !message ||
    message.conversationId !== conversation.conversationId ||
    typeof message.messageId !== 'string' ||
    !message.messageId ||
    typeof message.parentMessageId !== 'string' ||
    !message.parentMessageId
  ) {
    throw sourceError('Message does not belong to this Project conversation', 409);
  }

  const content = extractAssistantSourceText(message);
  const contentSha256 = crypto.createHash('sha256').update(content, 'utf8').digest('hex');
  const filename = sanitizeFilenameSegment(conversation.title) + ' - saved response.md';

  return {
    content,
    filename,
    provenance: {
      schema: 'UR_LIBRECHAT_CHAT_OUTPUT_PROVENANCE_R001',
      owner_user_id: userId,
      librechat_project_id: librechatProjectId,
      conversation_id: conversation.conversationId,
      message_id: message.messageId,
      parent_message_id: message.parentMessageId,
      message_created_at: asIso(message.createdAt),
      message_updated_at: asIso(message.updatedAt),
      response_endpoint: typeof message.endpoint === 'string' && message.endpoint ? message.endpoint : null,
      response_model: typeof message.model === 'string' && message.model ? message.model : null,
      response_agent_id: typeof message.agent_id === 'string' && message.agent_id ? message.agent_id : null,
      response_spec: typeof message.spec === 'string' && message.spec ? message.spec : null,
      content_sha256: contentSha256,
    },
  };
}

module.exports = {
  buildChatOutputSource,
  extractAssistantSourceText,
  sanitizeFilenameSegment,
};
