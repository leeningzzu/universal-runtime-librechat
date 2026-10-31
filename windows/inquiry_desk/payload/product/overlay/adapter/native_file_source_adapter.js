'use strict';

const crypto = require('crypto');

const MAX_SOURCE_BYTES = 64 * 1024 * 1024;
const MAX_CHAT_JSON_BYTES = 96 * 1024 * 1024;
const SUPPORTED_MEDIA = new Map([
  ['application/pdf', '.pdf'],
  ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'],
]);
const NATIVE_ORIGIN_SCHEMA = 'UR_LIBRECHAT_NATIVE_PROVIDER_SOURCE_ORIGIN_R001';

class NativeFileSourceAdapterError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'NativeFileSourceAdapterError';
    this.code = code;
  }
}

function shaText(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function shaBytes(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function header(headers, name, required = true) {
  const lower = name.toLowerCase();
  let value;
  for (const [key, raw] of Object.entries(headers || {})) {
    if (String(key).toLowerCase() === lower) {
      value = raw;
      break;
    }
  }
  if (value == null || value === '') {
    if (required) throw new NativeFileSourceAdapterError('MISSING_IDENTITY_HEADER', name);
    return null;
  }
  if (typeof value !== 'string' || /[\u0000\r\n]/.test(value)) {
    throw new NativeFileSourceAdapterError('INVALID_IDENTITY_HEADER', name);
  }
  return value;
}

function findLastUserMessage(body) {
  const messages = Array.isArray(body && body.messages) ? body.messages : [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const row = messages[i];
    if (row && row.role === 'user') return row;
  }
  throw new NativeFileSourceAdapterError('MISSING_USER_MESSAGE', 'no user message');
}

function parseDataUri(value, maxSourceBytes = MAX_SOURCE_BYTES) {
  if (typeof value !== 'string') {
    throw new NativeFileSourceAdapterError('INVALID_FILE_DATA', 'file_data must be string');
  }
  const match = /^data:([^;,]+);base64,([A-Za-z0-9+/]*={0,2})$/.exec(value);
  if (!match) {
    throw new NativeFileSourceAdapterError('INVALID_FILE_DATA', 'file_data must be canonical base64 data URI');
  }
  const mediaType = match[1];
  const encoded = match[2];
  if (!SUPPORTED_MEDIA.has(mediaType)) {
    throw new NativeFileSourceAdapterError('UNSUPPORTED_FILE_TYPE', mediaType);
  }
  const maxEncoded = Math.ceil(maxSourceBytes / 3) * 4;
  if (encoded.length > maxEncoded) {
    throw new NativeFileSourceAdapterError('SOURCE_TOO_LARGE', 'encoded source exceeds bound');
  }
  const exactBytes = Buffer.from(encoded, 'base64');
  if (!exactBytes.length || exactBytes.length > maxSourceBytes) {
    throw new NativeFileSourceAdapterError('SOURCE_TOO_LARGE', 'decoded source exceeds bound or empty');
  }
  if (exactBytes.toString('base64') !== encoded) {
    throw new NativeFileSourceAdapterError('INVALID_FILE_DATA', 'base64 is not canonical');
  }
  return {mediaType, exactBytes};
}

function safeFilename(value, mediaType) {
  if (typeof value !== 'string' || !value || value.length > 255 || /[\u0000\r\n/\\]/.test(value)) {
    throw new NativeFileSourceAdapterError('INVALID_FILENAME', 'filename must be one safe basename');
  }
  const suffix = SUPPORTED_MEDIA.get(mediaType);
  if (!suffix || !value.toLowerCase().endsWith(suffix)) {
    throw new NativeFileSourceAdapterError('FILE_MEDIA_MISMATCH', 'filename/media mismatch');
  }
  return value;
}

function structuredTurn(body, maxSourceBytes = MAX_SOURCE_BYTES) {
  const message = findLastUserMessage(body);
  if (typeof message.content === 'string') {
    return {text: message.content.trim(), file: null};
  }
  if (!Array.isArray(message.content)) {
    throw new NativeFileSourceAdapterError('INVALID_USER_CONTENT', 'user content must be text or structured array');
  }

  const texts = [];
  const files = [];
  for (const part of message.content) {
    if (!part || typeof part !== 'object') {
      throw new NativeFileSourceAdapterError('INVALID_USER_CONTENT', 'content part must be object');
    }
    if (part.type === 'text') {
      if (typeof part.text !== 'string') {
        throw new NativeFileSourceAdapterError('INVALID_USER_CONTENT', 'text part missing text');
      }
      texts.push(part.text);
      continue;
    }
    if (part.type === 'file') {
      if (!part.file || typeof part.file !== 'object') {
        throw new NativeFileSourceAdapterError('INVALID_FILE_PART', 'file object missing');
      }
      const {mediaType, exactBytes} = parseDataUri(part.file.file_data, maxSourceBytes);
      files.push({
        filename: safeFilename(part.file.filename, mediaType),
        mediaType,
        exactBytes,
        inputSha256: shaBytes(exactBytes),
      });
      continue;
    }
    throw new NativeFileSourceAdapterError('UNSUPPORTED_MEDIA_PART', String(part.type));
  }
  if (files.length > 1) {
    throw new NativeFileSourceAdapterError('MULTIPLE_SOURCE_FILES_UNSUPPORTED', 'R001 admits exactly one source file');
  }
  return {text: texts.join('').trim(), file: files[0] || null};
}

function buildOriginBinding(headers, file) {
  const userId = header(headers, 'x-librechat-user-id');
  const tenantId = header(headers, 'x-librechat-tenant-id', false);
  const conversationId = header(headers, 'x-conversation-id');
  const parentMessageId = header(headers, 'x-parent-message-id');
  const messageId = header(headers, 'x-message-id');
  return {
    schema: NATIVE_ORIGIN_SCHEMA,
    authority_class: 'NON_AUTHORITY_INGRESS_PROVENANCE',
    provider: 'librechat',
    transport: 'openai_compatible_custom_endpoint_file_data',
    authenticated_user_identity_sha256: shaText(userId),
    tenant_identity_sha256: tenantId ? shaText(tenantId) : null,
    conversation_identity_sha256: shaText(conversationId),
    parent_message_identity_sha256: shaText(parentMessageId),
    message_identity_sha256: shaText(messageId),
    filename: file.filename,
    media_type: file.mediaType,
    byte_size: file.exactBytes.length,
    exact_bytes_sha256: file.inputSha256,
    ownership_proof_class: 'LIBRECHAT_SERVER_OWNER_SCOPED_ATTACHMENT_ENCODING',
  };
}

function planTurn({headers, body, maxSourceBytes = MAX_SOURCE_BYTES}) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new NativeFileSourceAdapterError('INVALID_BODY', 'body must be object');
  }
  if (body.stream !== true) {
    throw new NativeFileSourceAdapterError('STREAM_TRUE_REQUIRED', 'stream must be true');
  }
  const turn = structuredTurn(body, maxSourceBytes);
  if (!turn.file) {
    if (!turn.text) throw new NativeFileSourceAdapterError('MISSING_LAST_USER_CONTENT', 'text-only request is empty');
    return {
      action: 'EXISTING_TEXT_ONLY_PATH',
      userText: turn.text,
      file: null,
      originBinding: null,
      formalModelTurn: true,
    };
  }

  const originBinding = buildOriginBinding(headers, turn.file);
  if (!turn.text) {
    return {
      action: 'INGEST_ONLY_SOURCE_READY',
      userText: '',
      file: turn.file,
      originBinding,
      formalModelTurn: false,
      modelProviderCall: false,
      runtimeUserEventRequired: false,
      sourceReadyProjection: 'NON_AUTHORITY_PRODUCT_STATUS',
    };
  }
  return {
    action: 'INGEST_THEN_EXISTING_SOURCE_GROUNDED_PATH',
    userText: turn.text,
    file: turn.file,
    originBinding,
    formalModelTurn: true,
    modelProviderCall: 'DEFER_TO_EXISTING_RUNTIME_FORMAL_FLOW',
    runtimeUserEventRequired: true,
  };
}

function limits() {
  return {
    maxChatJsonBytes: MAX_CHAT_JSON_BYTES,
    maxDecodedSourceBytes: MAX_SOURCE_BYTES,
  };
}

module.exports = {
  MAX_CHAT_JSON_BYTES,
  MAX_SOURCE_BYTES,
  NATIVE_ORIGIN_SCHEMA,
  NativeFileSourceAdapterError,
  buildOriginBinding,
  limits,
  parseDataUri,
  planTurn,
  structuredTurn,
};
