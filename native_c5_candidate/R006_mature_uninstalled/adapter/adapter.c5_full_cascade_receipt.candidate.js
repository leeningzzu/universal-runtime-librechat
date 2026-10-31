'use strict';

const http = require('http');
const crypto = require('crypto');
const nativeFileSource = require('./native_file_source_adapter');
const { captureCurrentProjectRuntimeReferences } =
  require('./c5CurrentRuntimeSourceRefOwner.candidate.js');

const PORT = Number(process.env.PORT || '9000');
const KEY = String(process.env.UR_SHELL_ADAPTER_KEY || '');
const RUNTIME_PROXY_KEY = String(process.env.UR_RUNTIME_PROXY_KEY || '');
const RUNTIME = String(process.env.UR_RUNTIME_BASE || '').replace(/\/$/, '');
const MODEL = 'runtime-daily-chat-r001';

if (!KEY || !RUNTIME_PROXY_KEY || !RUNTIME) {
  console.error(JSON.stringify({event:'startup_error', code:'MISSING_REQUIRED_ENV'}));
  process.exit(20);
}

const CANDIDATE_HOST_RUNTIME_PORTS = new Set(['19093', '19100', '19103', '19115']);
function isAllowedRuntimeUrl(runtimeUrl) {
  return (
    runtimeUrl.protocol === 'http:' &&
    (
      (runtimeUrl.hostname === 'host.docker.internal' &&
        CANDIDATE_HOST_RUNTIME_PORTS.has(runtimeUrl.port)) ||
      runtimeUrl.hostname === '127.0.0.1'
    ) &&
    !runtimeUrl.username &&
    !runtimeUrl.password &&
    !runtimeUrl.hash
  );
}
const runtimeUrl = new URL(RUNTIME);
const allowedRuntime = isAllowedRuntimeUrl(runtimeUrl);

if (!allowedRuntime) {
  console.error(JSON.stringify({event:'startup_error', code:'RUNTIME_BASE_NOT_FIXED_ALLOWED', runtime:RUNTIME}));
  process.exit(21);
}

const shells = new Map();
const creationLocks = new Map();

const MEMORY_INSTRUCTIONS =
  'The system automatically stores important user information and can update or delete memories based on user requests, enabling dynamic memory management.';
const MEMORY_MARKER = '# Existing memory about the user:';
const MEMORY_PREFIX = `${MEMORY_INSTRUCTIONS}\n\n${MEMORY_MARKER}\n`;
const PERSONAL_CONTEXT_SCHEMA = 'RUNTIME_NON_AUTHORITY_USER_PERSONAL_CONTEXT_V1';
const PERSONAL_CONTEXT_AUTHORITY_CLASS = 'NON_AUTHORITY_USER_PERSONAL_CONTEXT';
const PERSONAL_CONTEXT_SOURCE_CLASS = 'PRODUCT_SHELL_SAVED_MEMORY';
const PERSONAL_CONTEXT_CURRENTNESS_CLASS = 'REQUEST_SNAPSHOT_ONLY';
const PERSONAL_CONTEXT_PERSISTENCE_CLASS = 'JOB_BOUND_WORKING_INPUT';
const PERSONAL_CONTEXT_MAX_BYTES = 64 * 1024;
const PROJECT_CONTEXT_POLICY_PROJECT_ONLY = 'PROJECT_ONLY';
const PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY = 'PROJECT_PLUS_GLOBAL_USER_MEMORY';
const PROJECT_CONTEXT_POLICY_DEFAULT = PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY;
const PROJECT_CONTEXT_POLICIES = new Set([
  PROJECT_CONTEXT_POLICY_PROJECT_ONLY,
  PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY,
]);

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
function canonicalSha256(value) {
  return crypto.createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');
}
function personalContextFail(code, status=400) {
  const error = new Error(code); error.status = status; throw error;
}
function validateWithoutKeysMemoryText(text) {
  if (typeof text !== 'string' || !text.trim()) personalContextFail('PERSONAL_CONTEXT_MEMORY_TEXT_EMPTY');
  if (Buffer.byteLength(text, 'utf8') > PERSONAL_CONTEXT_MAX_BYTES) personalContextFail('PERSONAL_CONTEXT_MEMORY_TEXT_TOO_LARGE', 413);
  if (text !== text.trim()) personalContextFail('PERSONAL_CONTEXT_MEMORY_TEXT_NOT_CANONICAL');
  const blocks = text.split('\n\n');
  blocks.forEach((block, index) => {
    if (block.includes('\r') || block.includes('\n')) personalContextFail('PERSONAL_CONTEXT_MEMORY_BLOCK_MULTILINE');
    const match = /^(\d+)\. \[([^\]\r\n]+)\]\. (.+)$/.exec(block);
    if (!match || Number(match[1]) !== index + 1 || !match[2].trim() || !match[3].trim()) personalContextFail('PERSONAL_CONTEXT_MEMORY_FORMAT_MISMATCH');
  });
  return text;
}
function extractPersonalContext(body) {
  const messages = Array.isArray(body && body.messages) ? body.messages : [];
  const matches = [];
  for (const message of messages) {
    if (!message || message.role !== 'system' || typeof message.content !== 'string') continue;
    let from = 0;
    while (true) {
      const at = message.content.indexOf(MEMORY_PREFIX, from);
      if (at < 0) break;
      matches.push({text:message.content, at});
      from = at + MEMORY_PREFIX.length;
    }
  }
  if (matches.length === 0) return null;
  if (matches.length !== 1) personalContextFail('PERSONAL_CONTEXT_MARKER_AMBIGUOUS');
  const {text, at} = matches[0];
  const memoryText = validateWithoutKeysMemoryText(text.slice(at + MEMORY_PREFIX.length));
  return {
    schema:PERSONAL_CONTEXT_SCHEMA,
    authority_class:PERSONAL_CONTEXT_AUTHORITY_CLASS,
    source_class:PERSONAL_CONTEXT_SOURCE_CLASS,
    currentness_class:PERSONAL_CONTEXT_CURRENTNESS_CLASS,
    persistence_class:PERSONAL_CONTEXT_PERSISTENCE_CLASS,
    text:memoryText,
    text_sha256:crypto.createHash('sha256').update(memoryText, 'utf8').digest('hex'),
  };
}

function normalizeOptionalProjectId(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (!/^[a-f0-9]{24}$/i.test(raw)) {
    const e = new Error('INVALID_LIBRECHAT_PROJECT_ID'); e.status = 400; throw e;
  }
  return raw;
}
function buildBindingDescriptor(shellId, projectId='') {
  const normalizedProjectId = normalizeOptionalProjectId(projectId);
  if (!normalizedProjectId) {
    return {
      project_scoped:false,
      cache_key:shellId,
      lock_key:stableId('legacy-shell-create-lock', shellId),
      project_command_id:stableId('final-shell-project', shellId),
      project_display_name:'LibreChat Daily Chat',
      project_instructions:'Runtime-managed final-shell Daily Chat first slice.',
      chat_command_id:stableId('final-shell-chat', shellId),
      chat_title:'Daily Chat',
      librechat_project_id:'',
    };
  }
  return {
    project_scoped:true,
    cache_key:stableId('librechat-project-chat-cache', normalizedProjectId, shellId),
    lock_key:stableId('librechat-project-create-lock', normalizedProjectId),
    project_command_id:stableId('final-shell-project-by-librechat-project', normalizedProjectId),
    project_display_name:'LibreChat Project Context',
    project_instructions:'',
    chat_command_id:stableId('final-shell-chat-by-librechat-project', normalizedProjectId, shellId),
    chat_title:'LibreChat Chat ' + hash(shellId).slice(0, 20),
    librechat_project_id:normalizedProjectId,
  };
}
async function withCreationLock(lockKey, fn) {
  const previous = creationLocks.get(lockKey) || Promise.resolve();
  let releaseCurrent;
  const current = new Promise((resolve) => { releaseCurrent = resolve; });
  const tail = previous.catch(() => {}).then(() => current);
  creationLocks.set(lockKey, tail);
  await previous.catch(() => {});
  try {
    return await fn();
  } finally {
    releaseCurrent();
    if (creationLocks.get(lockKey) === tail) creationLocks.delete(lockKey);
  }
}

function log(obj) {
  process.stdout.write(JSON.stringify({ts:new Date().toISOString(), ...obj}) + '\n');
}
function hash(text) {
  return crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');
}
function stableId(prefix, ...parts) {
  return prefix + '-' + hash(parts.join('\x1f')).slice(0, 28);
}
function lastUserContent(body) {
  const messages = Array.isArray(body && body.messages) ? body.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] || {};
    if (m.role !== 'user') continue;
    if (typeof m.content === 'string' && m.content.trim()) return m.content.trim();
    if (Array.isArray(m.content)) {
      const text = m.content
        .map(x => x && x.type === 'text' ? String(x.text || '') : '')
        .join('')
        .trim();
      if (text) return text;
    }
  }
  return '';
}
function authOk(req) {
  return String(req.headers.authorization || '') === 'Bearer ' + KEY;
}
async function readJsonBody(req, max=1024*1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > max) throw new Error('REQUEST_BODY_TOO_LARGE');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

async function readRawBody(req, max=64*1024*1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > max) { const e = new Error('REQUEST_BODY_TOO_LARGE'); e.status = 413; throw e; }
    chunks.push(chunk);
  }
  const body = Buffer.concat(chunks);
  if (!body.length) { const e = new Error('RUNTIME_DOCUMENT_BODY_EMPTY'); e.status = 400; throw e; }
  return body;
}
async function runtimeRaw(method, path, body, contentType='application/octet-stream') {
  const response = await fetch(RUNTIME + path, {
    method,
    headers: {
      'Accept': 'application/json',
      'Content-Type': contentType,
      'X-UR-Runtime-Proxy': RUNTIME_PROXY_KEY,
    },
    body,
  });
  const raw = await response.text();
  let parsed = {};
  try { parsed = raw ? JSON.parse(raw) : {}; } catch (_) { parsed = {raw}; }
  if (!response.ok) {
    const e = new Error('RUNTIME_HTTP_' + response.status + ':' + JSON.stringify(parsed));
    e.status = response.status;
    e.runtimeBody = parsed;
    throw e;
  }
  return parsed;
}
function header(req, name) {
  return String(req.headers[name.toLowerCase()] || '');
}
function decodeDocumentFilename(req) {
  let filename = '';
  try { filename = decodeURIComponent(header(req, 'x-runtime-document-filename')); } catch (_) {}
  if (!filename || filename.length > 255 || /[\r\n\0]/.test(filename) || filename.includes('/') || filename.includes('\\')) {
    const e = new Error('RUNTIME_DOCUMENT_FILENAME_INVALID'); e.status = 400; throw e;
  }
  const lower = filename.toLowerCase();
  if (!lower.endsWith('.pdf') && !lower.endsWith('.docx')) {
    const e = new Error('RUNTIME_DOCUMENT_TYPE_UNSUPPORTED'); e.status = 415; throw e;
  }
  return filename;
}

const NATIVE_DOCUMENT_MAX_BYTES = 15 * 1024 * 1024;

function parseProjectNativeDocumentBundleMetadata(req, body) {
  const filename = decodeDocumentFilename(req);
  const lower = filename.toLowerCase();
  const inputFormat = lower.endsWith('.pdf') ? 'pdf' : 'docx';
  const expectedMediaType =
    inputFormat === 'pdf'
      ? 'application/pdf'
      : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const declaredFormat = header(req, 'x-runtime-document-format');
  const declaredMediaType = header(req, 'x-runtime-document-media-type');
  const contentType = header(req, 'content-type').split(';', 1)[0].trim();
  if (
    contentType !== 'application/zip' ||
    declaredFormat !== inputFormat ||
    declaredMediaType !== expectedMediaType
  ) {
    const e = new Error('RUNTIME_NATIVE_DOCUMENT_BUNDLE_FORMAT_MISMATCH'); e.status = 415; throw e;
  }

  const originalSize = Number(header(req, 'x-runtime-document-size'));
  const originalSha = header(req, 'x-runtime-document-sha256').toLowerCase();
  const bundleSize = Number(header(req, 'x-runtime-document-bundle-size'));
  const bundleSha = header(req, 'x-runtime-document-bundle-sha256').toLowerCase();
  const actualBundleSha = crypto.createHash('sha256').update(body).digest('hex');
  if (
    !Number.isSafeInteger(originalSize) || originalSize < 1 ||
    originalSize > NATIVE_DOCUMENT_MAX_BYTES ||
    !/^[0-9a-f]{64}$/.test(originalSha) ||
    !Number.isSafeInteger(bundleSize) || bundleSize !== body.length ||
    !/^[0-9a-f]{64}$/.test(bundleSha) ||
    bundleSha !== actualBundleSha
  ) {
    const e = new Error(
      originalSize > NATIVE_DOCUMENT_MAX_BYTES
        ? 'RUNTIME_NATIVE_DOCUMENT_ORIGINAL_TOO_LARGE'
        : 'RUNTIME_NATIVE_DOCUMENT_BUNDLE_IDENTITY_MISMATCH'
    );
    e.status = originalSize > NATIVE_DOCUMENT_MAX_BYTES ? 413 : 409;
    throw e;
  }

  const revisionRaw = header(req, 'x-project-expected-revision');
  let expectedProjectRevision = null;
  if (revisionRaw) {
    if (!/^\d+$/.test(revisionRaw)) {
      const e = new Error('RUNTIME_PROJECT_DOCUMENT_REVISION_INVALID'); e.status = 400; throw e;
    }
    expectedProjectRevision = Number(revisionRaw);
    if (!Number.isSafeInteger(expectedProjectRevision) || expectedProjectRevision < 1) {
      const e = new Error('RUNTIME_PROJECT_DOCUMENT_REVISION_INVALID'); e.status = 400; throw e;
    }
  }
  return {
    bundleSha,
    expectedProjectRevision,
    filename,
    inputFormat,
    originalSha,
    originalSize,
  };
}

function projectSourceRows(body) {
  return Array.isArray(body && body.sources)
    ? body.sources.filter(x => x && x.source_ref && typeof x.source_ref.source_ref_id === 'string')
    : [];
}
function projectionFromSourceRow(row) {
  const sourceRef = row && row.source_ref;
  const binding = sourceRef && sourceRef.source_artifact_binding;
  if (!sourceRef || !binding) throw new Error('RUNTIME_SOURCE_PROJECTION_INVALID');

  let mediaType = String(binding.media_type || '');
  let byteSize = Number(binding.byte_size || 0);
  let inputSha256 = String(binding.input_sha256 || '');

  if (sourceRef.origin_class === 'PROJECT_DOCUMENT_BUNDLE') {
    const receipt = row && row.ingest_receipt;
    const originSha256 = String(sourceRef.origin_input_sha256 || '');
    const originMediaType = String(sourceRef.origin_media_type || '');
    const originalByteSize = receipt && receipt.document_original_byte_size;
    if (
      !/^[0-9a-f]{64}$/.test(originSha256) ||
      !originMediaType ||
      !Number.isInteger(originalByteSize) ||
      originalByteSize < 1
    ) {
      throw new Error('RUNTIME_DOCUMENT_SOURCE_PROJECTION_INVALID');
    }
    mediaType = originMediaType;
    byteSize = originalByteSize;
    inputSha256 = originSha256;
  }

  return {
    status: 'ready',
    filename: String(sourceRef.filename || ''),
    media_type: mediaType,
    byte_size: byteSize,
    input_sha256: inputSha256,
    source_ref_id: sourceRef.source_ref_id,
    source_artifact_sha256: String(binding.sha256 || ''),
  };
}
function projectLibraryProjection(current) {
  const project = current && current.project;
  const rawRows = current && current.sources;
  const rows = projectSourceRows(current);
  if (
    !project ||
    typeof project.project_id !== 'string' || !project.project_id ||
    !Number.isInteger(project.project_revision) || project.project_revision < 1 ||
    !Array.isArray(rawRows) ||
    rows.length !== rawRows.length
  ) {
    throw new Error('RUNTIME_PROJECT_LIBRARY_PROJECTION_INVALID');
  }
  const sources = rows.map((row) => {
    const sourceRef = row.source_ref;
    const binding = sourceRef.source_artifact_binding;
    if (
      sourceRef.project_id !== project.project_id ||
      typeof sourceRef.source_ref_id !== 'string' || !sourceRef.source_ref_id ||
      typeof sourceRef.filename !== 'string' || !sourceRef.filename ||
      !binding ||
      typeof binding.artifact_identity_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(binding.artifact_identity_sha256) ||
      !Number.isInteger(binding.revision) || binding.revision < 1 ||
      typeof binding.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(binding.sha256)
    ) {
      throw new Error('RUNTIME_PROJECT_LIBRARY_SOURCE_INVALID');
    }
    const byteSize = binding.byte_size;
    const originClass = String(sourceRef.origin_class || 'RUNTIME_SOURCE');
    let provenance = null;
    if (originClass === 'CHAT_OUTPUT') {
      const raw = sourceRef.provenance;
      if (
        !raw || typeof raw !== 'object' ||
        typeof raw.owner_user_id !== 'string' || !raw.owner_user_id ||
        typeof raw.conversation_id !== 'string' || !raw.conversation_id ||
        typeof raw.message_id !== 'string' || !raw.message_id ||
        typeof raw.parent_message_id !== 'string' || !raw.parent_message_id ||
        typeof raw.content_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(raw.content_sha256)
      ) {
        throw new Error('RUNTIME_PROJECT_LIBRARY_CHAT_OUTPUT_PROVENANCE_INVALID');
      }
      provenance = {
        kind:'CHAT_OUTPUT',
        conversation_id:raw.conversation_id,
        message_id:raw.message_id,
        parent_message_id:raw.parent_message_id,
        message_created_at:typeof raw.message_created_at === 'string' ? raw.message_created_at : null,
        message_updated_at:typeof raw.message_updated_at === 'string' ? raw.message_updated_at : null,
        response_endpoint:typeof raw.response_endpoint === 'string' && raw.response_endpoint ? raw.response_endpoint : null,
        response_model:typeof raw.response_model === 'string' && raw.response_model ? raw.response_model : null,
        response_agent_id:typeof raw.response_agent_id === 'string' && raw.response_agent_id ? raw.response_agent_id : null,
      };
    }
    return {
      source_ref_id: sourceRef.source_ref_id,
      filename: sourceRef.filename,
      origin_class: originClass,
      role: String(sourceRef.role || 'PROJECT_SOURCE'),
      media_type: typeof binding.media_type === 'string' && binding.media_type ? binding.media_type : null,
      byte_size: Number.isInteger(byteSize) && byteSize >= 0 ? byteSize : null,
      source_artifact_revision: binding.revision,
      source_artifact_sha256: binding.sha256,
      provenance,
      can_remove:true,
    };
  });
  return {
    schema:'UR_WEB_R004_PROJECT_LIBRARY_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    project_revision:project.project_revision,
    source_count:sources.length,
    sources,
  };
}
function projectSourceRegistryContextSha(current) {
  const projection = projectLibraryProjection(current);
  const bindingRows = projection.sources.map((item) => [
    item.source_ref_id,
    item.source_artifact_sha256,
  ]);
  return hash(JSON.stringify(bindingRows));
}

const PROJECT_SOURCE_SEARCH_MAX_RESULTS = 3;
const PROJECT_SOURCE_SEARCH_MAX_RESULT_CHARS = 16000;

function projectSourceSearchPresentation(current, semanticResult) {
  const project = current && current.project;
  const rows = projectSourceRows(current);
  const chunkMode = semanticResult && semanticResult.result === 'PASS';
  if (
    !project ||
    typeof project.project_id !== 'string' || !project.project_id ||
    !Number.isInteger(project.project_revision) || project.project_revision < 1 ||
    !semanticResult || typeof semanticResult !== 'object' ||
    semanticResult.schema !== 'UR_WEB_R004_P2C_PROJECT_SEMANTIC_SEARCH_RESPONSE_R001' ||
    semanticResult.authority_class !== 'NON_AUTHORITY_RETRIEVAL_PROPOSAL' ||
    !['PASS', 'PASS_EMPTY_PROJECT'].includes(semanticResult.result) ||
    (chunkMode && semanticResult.retrieval_mode !== 'SOURCE_CHUNK_DENSE_R001') ||
    (chunkMode && semanticResult.chunk_size_chars !== 1500) ||
    (chunkMode && semanticResult.chunk_overlap_chars !== 100) ||
    (chunkMode && (!Number.isInteger(semanticResult.chunk_count_total) || semanticResult.chunk_count_total < 0)) ||
    (semanticResult.result === 'PASS_EMPTY_PROJECT' && semanticResult.source_count !== 0) ||
    semanticResult.project_id !== project.project_id ||
    !Array.isArray(semanticResult.results) ||
    !Number.isInteger(semanticResult.source_count) || semanticResult.source_count < 0 ||
    semanticResult.source_count !== rows.length
  ) {
    throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_SHAPE_INVALID');
  }

  const byId = new Map(rows.map((row) => [row.source_ref.source_ref_id, row]));
  const selectedHits = semanticResult.results.slice(0, PROJECT_SOURCE_SEARCH_MAX_RESULTS);
  let remainingChars = PROJECT_SOURCE_SEARCH_MAX_RESULT_CHARS;
  const results = [];

  for (let hitIndex = 0; hitIndex < selectedHits.length; hitIndex += 1) {
    const hit = selectedHits[hitIndex];
    if (
      !hit || typeof hit !== 'object' ||
      typeof hit.source_ref_id !== 'string' || !hit.source_ref_id ||
      typeof hit.source_artifact_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(hit.source_artifact_sha256) ||
      typeof hit.source_text_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(hit.source_text_sha256) ||
      typeof hit.filename !== 'string' || !hit.filename ||
      !Number.isFinite(hit.score) ||
      hit.source_text_truncated_for_embedding !== false ||
      hit.full_source_chunk_coverage !== true ||
      !Array.isArray(hit.chunks) || hit.chunks.length < 1 || hit.chunks.length > 5
    ) {
      throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_HIT_INVALID');
    }

    const row = byId.get(hit.source_ref_id);
    const ref = row && row.source_ref;
    const binding = ref && ref.source_artifact_binding;
    const derivation = row && row.text_derivation;
    if (
      !ref || !binding || !derivation ||
      ref.project_id !== project.project_id ||
      binding.sha256 !== hit.source_artifact_sha256 ||
      derivation.source_sha256 !== binding.sha256 ||
      typeof derivation.derivation_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(derivation.derivation_sha256) ||
      hit.source_text_sha256 !== derivation.derivation_sha256 ||
      typeof derivation.decoded_text !== 'string' ||
      hash(derivation.decoded_text) !== derivation.derivation_sha256
    ) {
      throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_CURRENTNESS_INVALID');
    }

    if (remainingChars <= 0) break;
    const sourcesLeft = selectedHits.length - hitIndex;
    let sourceBudget = Math.floor(remainingChars / Math.max(1, sourcesLeft));
    let content = '';
    const chunkHits = [];

    for (const chunk of hit.chunks) {
      if (
        !chunk || typeof chunk !== 'object' ||
        !Number.isInteger(chunk.rank) || chunk.rank < 1 ||
        !Number.isFinite(chunk.score) ||
        !Number.isInteger(chunk.chunk_index) || chunk.chunk_index < 0 ||
        !Number.isInteger(chunk.start_char) || chunk.start_char < 0 ||
        !Number.isInteger(chunk.end_char) || chunk.end_char <= chunk.start_char ||
        chunk.end_char > derivation.decoded_text.length ||
        chunk.end_char - chunk.start_char > 1500 ||
        typeof chunk.chunk_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(chunk.chunk_sha256)
      ) {
        throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_CHUNK_INVALID');
      }
      const exact = derivation.decoded_text.slice(chunk.start_char, chunk.end_char);
      if (hash(exact) !== chunk.chunk_sha256) {
        throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_CHUNK_CURRENTNESS_INVALID');
      }
      const header = '[Project Source chunk rank ' + chunk.rank + '; chars ' +
        chunk.start_char + '-' + chunk.end_char + ']';
      const block = (content ? '\n\n' : '') + header + '\n' + exact;
      if (block.length > sourceBudget || block.length > remainingChars) break;
      content += block;
      sourceBudget -= block.length;
      remainingChars -= block.length;
      chunkHits.push({
        rank:chunk.rank,
        score:chunk.score,
        chunk_index:chunk.chunk_index,
        start_char:chunk.start_char,
        end_char:chunk.end_char,
        chunk_sha256:chunk.chunk_sha256,
      });
    }

    if (!content || chunkHits.length < 1) {
      throw new Error('RUNTIME_PROJECT_SOURCE_SEARCH_CHUNK_BUDGET_EMPTY');
    }
    results.push({
      rank:hit.rank,
      score:hit.score,
      source_ref_id:ref.source_ref_id,
      filename:ref.filename,
      origin_class:String(ref.origin_class || 'RUNTIME_SOURCE'),
      media_type:typeof binding.media_type === 'string' && binding.media_type ? binding.media_type : null,
      content,
      content_selection_mode:'QUERY_RELEVANT_CHUNKS',
      chunk_hits:chunkHits,
      full_source_chunk_coverage:true,
      content_truncated_for_tool:content.length < derivation.decoded_text.length,
      source_text_truncated_for_embedding:false,
    });
  }

  return {
    schema:'UR_WEB_R004_PROJECT_SOURCE_SEARCH_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_RETRIEVAL_PROJECTION',
    project_revision:project.project_revision,
    source_count:rows.length,
    result_count:results.length,
    max_result_chars:PROJECT_SOURCE_SEARCH_MAX_RESULT_CHARS,
    retrieval_mode:semanticResult.result === 'PASS_EMPTY_PROJECT' ? 'EMPTY_PROJECT' : semanticResult.retrieval_mode,
    chunk_size_chars:chunkMode ? semanticResult.chunk_size_chars : null,
    chunk_overlap_chars:chunkMode ? semanticResult.chunk_overlap_chars : null,
    chunk_count_total:chunkMode ? semanticResult.chunk_count_total : 0,
    project_sources_context_sha256:projectSourceRegistryContextSha(current),
    network_calls:semanticResult.network_calls,
    external_model_provider_calls:semanticResult.external_model_provider_calls,
    results,
  };
}

function hydrateActiveSource(entry, body) {
  const rows = projectSourceRows(body);
  if (rows.length > 1) throw new Error('RUNTIME_SOURCE_CARDINALITY_AMBIGUOUS_FIRST_SLICE');
  entry.active_source = rows.length === 1 ? projectionFromSourceRow(rows[0]) : null;
}

async function runtimeJson(method, path, payload) {
  const opts = {
    method,
    headers: {
      'Accept': 'application/json',
      'X-UR-Runtime-Proxy': RUNTIME_PROXY_KEY,
    },
  };
  if (payload !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(payload);
  }
  const response = await fetch(RUNTIME + path, opts);
  const raw = await response.text();
  let body = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = {raw}; }
  if (!response.ok) {
    const e = new Error('RUNTIME_HTTP_' + response.status + ':' + JSON.stringify(body));
    e.status = response.status;
    e.runtimeBody = body;
    throw e;
  }
  return body;
}
function openAIChunk(content, finishReason=null) {
  return {
    id: 'chatcmpl-ur-daily-r001',
    object: 'chat.completion.chunk',
    created: Math.floor(Date.now()/1000),
    model: MODEL,
    choices: [{
      index: 0,
      delta: content === null ? {} : {content},
      finish_reason: finishReason,
    }],
  };
}
function sendSse(res, obj) {
  if (res.writableEnded || res.destroyed) return false;
  res.write('data: ' + JSON.stringify(obj) + '\n\n');
  return true;
}
function finishSse(res) {
  if (!res.writableEnded && !res.destroyed) {
    sendSse(res, openAIChunk(null, 'stop'));
    res.write('data: [DONE]\n\n');
    res.end();
  }
}
function terminateSseFailure(res, code) {
  if (!res.writableEnded && !res.destroyed) {
    // SSE comments are non-content. Never append Adapter-authored Assistant bytes.
    res.write(': runtime-stop ' + String(code || 'ADAPTER_FAILURE').replace(/[\r\n]/g, ' ') + '\n\n');
    res.end();
  }
}
async function resume(entry) {
  const body = await runtimeJson('GET', `/api/web/projects/${encodeURIComponent(entry.project.project_id)}`);
  const project = body && body.project;
  const rows = Array.isArray(body && body.chats)
    ? body.chats.filter(x => x && x.chat && x.chat.chat_id === entry.chat.chat_id)
    : [];
  if (!project || rows.length !== 1) throw new Error('RUNTIME_RESUME_SCOPE_MISMATCH');
  entry.project = project;
  entry.chat = rows[0].chat;
  hydrateActiveSource(entry, body);
  return rows[0];
}
async function getOrCreateLegacyShell(shellId) {
  let entry = shells.get(shellId);
  if (entry) { await resume(entry); return entry; }
  const binding = buildBindingDescriptor(shellId, '');
  const projectCreated = await runtimeJson('POST', '/api/web/projects', {
    command_id: binding.project_command_id,
    display_name: binding.project_display_name,
    instructions: binding.project_instructions,
  });
  const project = projectCreated && projectCreated.project;
  if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  const chatCreated = await runtimeJson('POST', `/api/web/projects/${encodeURIComponent(project.project_id)}/chats`, {
    command_id:binding.chat_command_id,
    expected_project_revision:project.project_revision,
    title:binding.chat_title,
  });
  if (!chatCreated || !chatCreated.chat || !chatCreated.chat.chat_id) throw new Error('RUNTIME_CHAT_CREATE_SHAPE');
  entry = {
    shell_id:shellId,
    librechat_project_id:'',
    project:chatCreated.project,
    chat:chatCreated.chat,
    active_message_id:null,
    document_admission_in_flight:false,
    active_source:null,
    completed_message_ids:new Set(),
    failed_message_ids:new Set(),
    user_turns:new Map(),
  };
  shells.set(shellId, entry);
  await resume(entry);
  log({event:'runtime_shell_created',shell_id:shellId,project_id:entry.project.project_id,runtime_chat_id:entry.chat.chat_id});
  return entry;
}

async function lookupProjectContainerForInstructions(projectId) {
  const binding = buildBindingDescriptor('project-instructions-read', projectId);
  const params = new URLSearchParams({
    command_id:binding.project_command_id,
    display_name:binding.project_display_name,
  });
  const resolved = await runtimeJson('GET', `/api/web/project-instructions/resolve?${params.toString()}`);
  if (!resolved || resolved.found === false) return {binding,current:null};
  if (
    resolved.found !== true ||
    typeof resolved.project_id !== 'string' || !resolved.project_id ||
    !Number.isInteger(resolved.project_revision) ||
    !resolved.project_instruction_binding ||
    typeof resolved.project_instructions !== 'string'
  ) {
    throw new Error('RUNTIME_PROJECT_INSTRUCTIONS_LOOKUP_INVALID');
  }
  return {
    binding,
    current:{
      project:{
        project_id:resolved.project_id,
        project_revision:resolved.project_revision,
        project_instruction_binding:resolved.project_instruction_binding,
      },
      project_instructions:resolved.project_instructions,
    },
  };
}

async function ensureRuntimeProjectForLibreChatProject(projectId) {
  const lookup = await lookupProjectContainerForInstructions(projectId);
  let project = lookup.current && lookup.current.project;
  if (!project) {
    const created = await runtimeJson('POST', '/api/web/projects', {
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions:lookup.binding.project_instructions,
    });
    project = created && created.project;
  }
  if (!project || typeof project.project_id !== 'string' || !project.project_id) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  const current = await runtimeJson(
    'GET',
    '/api/web/projects/' + encodeURIComponent(project.project_id),
  );
  if (
    !current ||
    !current.project ||
    current.project.project_id !== project.project_id ||
    !Number.isInteger(current.project.project_revision)
  ) {
    throw new Error('RUNTIME_PROJECT_RESUME_SHAPE');
  }
  return current;
}

async function getOrCreateProjectShell(shellId, projectId) {
  const binding = buildBindingDescriptor(shellId, projectId);
  let entry = shells.get(binding.cache_key);
  if (entry) { await resume(entry); return entry; }
  return withCreationLock(binding.lock_key, async () => {
    entry = shells.get(binding.cache_key);
    if (entry) { await resume(entry); return entry; }
    const lookup = await lookupProjectContainerForInstructions(binding.librechat_project_id);
    let project;
    if (lookup.current) {
      project = lookup.current.project;
    } else {
      const projectCreated = await runtimeJson('POST','/api/web/projects',{
        command_id:binding.project_command_id,
        display_name:binding.project_display_name,
        instructions:binding.project_instructions,
      });
      project = projectCreated && projectCreated.project;
    }
    if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
      throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
    }
    const current = await runtimeJson('GET',`/api/web/projects/${encodeURIComponent(project.project_id)}`);
    project = current && current.project;
    if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
      throw new Error('RUNTIME_PROJECT_RESUME_SHAPE');
    }
    const chats = Array.isArray(current && current.chats)
      ? current.chats.map(x => x && x.chat).filter(Boolean)
      : [];
    const exactChats = chats.filter(x => x && x.title === binding.chat_title);
    if (exactChats.length > 1) throw new Error('RUNTIME_DERIVED_CHAT_AMBIGUOUS');
    let chat = exactChats.length === 1 ? exactChats[0] : null;
    if (!chat) {
      const chatCreated = await runtimeJson('POST',`/api/web/projects/${encodeURIComponent(project.project_id)}/chats`,{
        command_id:binding.chat_command_id,
        expected_project_revision:project.project_revision,
        title:binding.chat_title,
      });
      if (!chatCreated || !chatCreated.chat || !chatCreated.chat.chat_id) throw new Error('RUNTIME_CHAT_CREATE_SHAPE');
      project = chatCreated.project;
      chat = chatCreated.chat;
    }
    entry = {
      shell_id:shellId,
      librechat_project_id:binding.librechat_project_id,
      project,
      chat,
      active_message_id:null,
      document_admission_in_flight:false,
      active_source:null,
      completed_message_ids:new Set(),
      failed_message_ids:new Set(),
      user_turns:new Map(),
    };
    shells.set(binding.cache_key, entry);
    await resume(entry);
    log({event:'runtime_project_shell_created',shell_id:shellId,librechat_project_id_sha256:hash(binding.librechat_project_id),project_id:entry.project.project_id,runtime_chat_id:entry.chat.chat_id});
    return entry;
  });
}

async function getOrCreateShell(shellId, projectId='') {
  const normalizedProjectId = normalizeOptionalProjectId(projectId);
  if (!normalizedProjectId) return getOrCreateLegacyShell(shellId);
  return getOrCreateProjectShell(shellId, normalizedProjectId);
}

function projectInstructionsProjection(current) {
  const project = current && current.project;
  const instructions = current && current.project_instructions;
  const binding = project && project.project_instruction_binding;
  if (
    !project ||
    !Number.isInteger(project.project_revision) ||
    typeof instructions !== 'string' ||
    !binding ||
    typeof binding.artifact_id !== 'string' || !binding.artifact_id ||
    !Number.isInteger(binding.revision) || binding.revision < 1 ||
    typeof binding.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(binding.sha256) ||
    hash(instructions) !== binding.sha256
  ) {
    throw new Error('RUNTIME_PROJECT_INSTRUCTIONS_PROJECTION_INVALID');
  }
  return {
    project_revision:project.project_revision,
    instructions,
    instruction_revision:binding.revision,
    instruction_sha256:binding.sha256,
  };
}

function effectivePersonalContextForPolicy(contextPolicy, requestedPersonalContext) {
  if (!PROJECT_CONTEXT_POLICIES.has(contextPolicy)) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_INVALID'); e.status = 409; throw e;
  }
  return contextPolicy === PROJECT_CONTEXT_POLICY_PROJECT_ONLY
    ? null
    : requestedPersonalContext;
}

function projectContextPolicyPresentation(body) {
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_PROJECT_CONTEXT_POLICY_R001' ||
    body.authority_class !== 'RUNTIME_PROJECT_AUTHORITY_PROJECTION' ||
    typeof body.project_id !== 'string' || !body.project_id ||
    !Number.isInteger(body.project_revision) || body.project_revision < 1 ||
    !PROJECT_CONTEXT_POLICIES.has(body.context_policy) ||
    typeof body.explicit !== 'boolean'
  ) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_SHAPE_INVALID'); e.status = 502; throw e;
  }
  return {
    schema:'UR_WEB_R004_PROJECT_CONTEXT_POLICY_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:true,
    project_revision:body.project_revision,
    context_policy:body.context_policy,
    explicit:body.explicit,
  };
}

function emptyProjectContextPolicyPresentation() {
  return {
    schema:'UR_WEB_R004_PROJECT_CONTEXT_POLICY_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:false,
    project_revision:null,
    context_policy:PROJECT_CONTEXT_POLICY_DEFAULT,
    explicit:false,
  };
}

async function handleProjectContextPolicyGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(emptyProjectContextPolicyPresentation()));
  }
  const runtimeProjectId = lookup.current.project.project_id;
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(runtimeProjectId)}/context-policy`,
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const projection = projectContextPolicyPresentation(result.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

function projectContextPolicyMutationCommand(projectId, expectedProjectRevision, contextPolicy) {
  return {
    command_id:stableId(
      'librechat-project-context-policy',
      projectId,
      String(expectedProjectRevision),
      contextPolicy,
    ),
    expected_project_revision:expectedProjectRevision,
    context_policy:contextPolicy,
  };
}

async function applyProjectContextPolicyMutation({
  projectId,
  runtimeProjectId,
  expectedProjectRevision,
  contextPolicy,
  mutate = runtimeJsonResult,
  readCurrent = runtimeJsonResult,
}) {
  const runtimePath = `/api/web/projects/${encodeURIComponent(runtimeProjectId)}/context-policy`;
  const result = await mutate(
    'PUT',
    runtimePath,
    projectContextPolicyMutationCommand(
      projectId,
      expectedProjectRevision,
      contextPolicy,
    ),
  );
  if (!result.ok) {
    return {ok:false, result};
  }
  const after = await readCurrent('GET', runtimePath);
  if (!after.ok) {
    return {ok:false, result:after};
  }
  return {
    ok:true,
    projection:projectContextPolicyPresentation(after.body),
  };
}

async function handleProjectContextPolicyPut(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  const contextPolicy = body && body.context_policy;
  if (
    !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
    (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1) ||
    !PROJECT_CONTEXT_POLICIES.has(contextPolicy)
  ) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_REQUEST_INVALID'); e.status = 400; throw e;
  }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  let project = lookup.current && lookup.current.project;
  if (!project) {
    if (expectedProjectRevision !== null) {
      const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_SCOPE_MISSING'); e.status = 409; throw e;
    }
    const created = await runtimeJson('POST','/api/web/projects',{
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions:lookup.binding.project_instructions,
    });
    project = created && created.project;
  } else if (expectedProjectRevision === null) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  const effectiveExpectedRevision = expectedProjectRevision === null
    ? project.project_revision
    : expectedProjectRevision;
  const mutation = await applyProjectContextPolicyMutation({
    projectId,
    runtimeProjectId:project.project_id,
    expectedProjectRevision:effectiveExpectedRevision,
    contextPolicy,
  });
  if (!mutation.ok) return sendRuntimeJsonResult(res, mutation.result);
  const projection = mutation.projection;
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

function projectMemoryContextPresentation(body, runtimeProjectId, projectRevision) {
  const context = body && body.project_memory_context;
  const contextSha = body && body.project_memory_context_sha256;
  const guard = body && body.project_memory_state_guard;
  const guardSha = body && body.project_memory_state_guard_sha256;
  const validContext =
    (context === null && contextSha === null) ||
    (
      context &&
      typeof context === 'object' &&
      context.schema === 'UR_WEB_PROJECT_MEMORY_CONTEXT_R001' &&
      context.project_id === runtimeProjectId &&
      Array.isArray(context.items) &&
      typeof contextSha === 'string' && /^[0-9a-f]{64}$/.test(contextSha)
    );
  if (
    !body ||
    body.schema !== 'UR_WEB_PROJECT_MEMORY_CONTEXT_PROJECTION_R002' ||
    body.project_id !== runtimeProjectId ||
    !Number.isInteger(body.active_memory_count) || body.active_memory_count < 0 ||
    !validContext ||
    !guard || typeof guard !== 'object' || guard.project_id !== runtimeProjectId ||
    typeof guardSha !== 'string' || !/^[0-9a-f]{64}$/.test(guardSha) ||
    !body.state_binding || typeof body.state_binding !== 'object'
  ) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_CONTEXT_SHAPE_INVALID'); e.status = 502; throw e;
  }
  if (context !== null && context.items.length !== body.active_memory_count) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_CONTEXT_COUNT_MISMATCH'); e.status = 502; throw e;
  }
  return {
    schema:'UR_WEB_R004_PROJECT_MEMORY_CONTEXT_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:true,
    project_revision:projectRevision,
    active_memory_count:body.active_memory_count,
    project_memory_context:context,
    project_memory_context_sha256:contextSha,
    project_memory_state_guard:guard,
    project_memory_state_guard_sha256:guardSha,
    state_binding:body.state_binding,
  };
}

function emptyProjectMemoryContextPresentation() {
  return {
    schema:'UR_WEB_R004_PROJECT_MEMORY_CONTEXT_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:false,
    project_revision:null,
    active_memory_count:0,
    project_memory_context:null,
    project_memory_context_sha256:null,
    project_memory_state_guard:null,
    project_memory_state_guard_sha256:null,
    state_binding:null,
  };
}

async function handleProjectMemoryContextGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(emptyProjectMemoryContextPresentation()));
  }
  const project = lookup.current.project;
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(project.project_id)}/memory/context`,
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const projection = projectMemoryContextPresentation(
    result.body,
    project.project_id,
    project.project_revision,
  );
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function getEntryProjectContextPolicy(entry) {
  await resume(entry);
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(entry.project.project_id)}/context-policy`,
  );
  if (!result.ok) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_UNAVAILABLE'); e.status = result.status; throw e;
  }
  const projection = projectContextPolicyPresentation(result.body);
  if (projection.project_revision !== entry.project.project_revision) {
    const e = new Error('RUNTIME_PROJECT_CONTEXT_POLICY_REVISION_MISMATCH'); e.status = 409; throw e;
  }
  return projection;
}

async function handleProjectInstructionsGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  const projection = lookup.current
    ? {initialized:true,...projectInstructionsProjection(lookup.current)}
    : {initialized:false,project_revision:null,instructions:'',instruction_revision:null,instruction_sha256:hash('')};
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  res.end(JSON.stringify(projection));
}

async function handleProjectLibraryGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify({
      schema:'UR_WEB_R004_PROJECT_LIBRARY_PRESENTATION_R001',
      authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
      initialized:false,
      project_revision:null,
      source_count:0,
      sources:[],
    }));
  }
  const runtimeProjectId = lookup.current.project.project_id;
  const current = await runtimeJson('GET', `/api/web/projects/${encodeURIComponent(runtimeProjectId)}`);
  if (!current || !current.project || current.project.project_id !== runtimeProjectId) {
    throw new Error('RUNTIME_PROJECT_LIBRARY_SCOPE_MISMATCH');
  }
  const projection = projectLibraryProjection(current);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify({initialized:true,...projection}));
}

function validateChatOutputSaveBody(projectId, body) {
  const content = body && body.content;
  const filename = body && body.filename;
  const provenance = body && body.provenance;
  if (
    typeof content !== 'string' || !content ||
    typeof filename !== 'string' || !filename ||
    !provenance || typeof provenance !== 'object' ||
    typeof provenance.owner_user_id !== 'string' || !provenance.owner_user_id ||
    provenance.librechat_project_id !== projectId ||
    typeof provenance.conversation_id !== 'string' || !provenance.conversation_id ||
    typeof provenance.message_id !== 'string' || !provenance.message_id ||
    typeof provenance.parent_message_id !== 'string' || !provenance.parent_message_id ||
    typeof provenance.content_sha256 !== 'string' ||
    provenance.content_sha256 !== hash(content)
  ) {
    const e = new Error('RUNTIME_PROJECT_LIBRARY_CHAT_OUTPUT_REQUEST_INVALID'); e.status = 400; throw e;
  }
  return {content, filename, provenance};
}


async function handleProjectLibraryDocumentBundle(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readRawBody(req);
  const upload = parseProjectNativeDocumentBundleMetadata(req, body);

  const beforeLookup = await lookupProjectContainerForInstructions(projectId);
  if (!beforeLookup.current && upload.expectedProjectRevision !== null) {
    const e = new Error('RUNTIME_PROJECT_DOCUMENT_SCOPE_MISSING'); e.status = 409; throw e;
  }
  if (beforeLookup.current && upload.expectedProjectRevision === null) {
    const e = new Error('RUNTIME_PROJECT_DOCUMENT_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  const current = await ensureRuntimeProjectForLibreChatProject(projectId);
  const project = current.project;
  const effectiveExpectedRevision =
    upload.expectedProjectRevision === null ? project.project_revision : upload.expectedProjectRevision;
  if (project.project_revision !== effectiveExpectedRevision) {
    const e = new Error('RUNTIME_PROJECT_DOCUMENT_REVISION_STALE'); e.status = 409; throw e;
  }

  const query = new URLSearchParams({
    command_id: stableId(
      'librechat-project-native-document-bundle-add',
      projectId,
      String(effectiveExpectedRevision),
      upload.filename,
      upload.inputFormat,
      upload.originalSha,
      upload.bundleSha,
    ),
    filename: upload.filename,
    expected_project_revision: String(effectiveExpectedRevision),
  });
  const adopted = await runtimeRaw(
    'POST',
    '/api/web/projects/' + encodeURIComponent(project.project_id) + '/sources/document-bundle?' + query.toString(),
    body,
    'application/zip',
  );
  const sourceRef = adopted && adopted.source_ref;
  const documentArtifact = adopted && adopted.document_bundle_artifact;
  if (
    !sourceRef ||
    typeof sourceRef.source_ref_id !== 'string' || !sourceRef.source_ref_id ||
    sourceRef.project_id !== project.project_id ||
    !documentArtifact ||
    documentArtifact.input_format !== upload.inputFormat ||
    documentArtifact.input_sha256 !== upload.originalSha ||
    documentArtifact.sha256 !== upload.bundleSha
  ) {
    throw new Error('RUNTIME_PROJECT_NATIVE_DOCUMENT_ADOPTION_SHAPE_INVALID');
  }

  const after = await runtimeJson(
    'GET',
    '/api/web/projects/' + encodeURIComponent(project.project_id),
  );
  const projection = projectLibraryProjection(after);
  if (!projection.sources.some((item) => item.source_ref_id === sourceRef.source_ref_id)) {
    throw new Error('RUNTIME_PROJECT_NATIVE_DOCUMENT_REHYDRATE_MISMATCH');
  }
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify({
    initialized:true,
    ...projection,
    saved_source_ref_id:sourceRef.source_ref_id,
  }));
}


async function handleProjectSourceSearch(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const query = body && body.query;
  const limit = body && body.limit !== undefined ? body.limit : 3;
  const expectedSourceContextSha256 = body && body.expected_source_context_sha256;
  const expectedProjectRevision = body && body.expected_project_revision;
  if (
    typeof query !== 'string' || !query.trim() || query.length > 1200 ||
    !Number.isInteger(limit) || limit < 1 || limit > PROJECT_SOURCE_SEARCH_MAX_RESULTS ||
    typeof expectedSourceContextSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(expectedSourceContextSha256) ||
    !Number.isInteger(expectedProjectRevision) || expectedProjectRevision < 1
  ) {
    const e = new Error('RUNTIME_PROJECT_SOURCE_SEARCH_REQUEST_INVALID'); e.status = 400; throw e;
  }
  const current = await ensureRuntimeProjectForLibreChatProject(projectId);
  if (current.project.project_revision !== expectedProjectRevision) {
    const e = new Error('RUNTIME_PROJECT_SOURCE_SEARCH_PROJECT_REVISION_STALE'); e.status = 409; throw e;
  }
  if (projectSourceRegistryContextSha(current) !== expectedSourceContextSha256) {
    const e = new Error('RUNTIME_PROJECT_SOURCE_SEARCH_STALE_SINCE_CONTEXT'); e.status = 409; throw e;
  }
  const runtimeProjectId = current.project.project_id;
  const semantic = await runtimeJsonResult(
    'POST',
    '/api/web/projects/' + encodeURIComponent(runtimeProjectId) + '/semantic-search',
    {query:query.trim(), top_k:limit},
  );
  if (!semantic.ok) return sendRuntimeJsonResult(res, semantic);
  const after = await runtimeJson('GET', '/api/web/projects/' + encodeURIComponent(runtimeProjectId));
  if (!after || !after.project || after.project.project_revision !== expectedProjectRevision) {
    const e = new Error('RUNTIME_PROJECT_SOURCE_SEARCH_PROJECT_CHANGED_DURING_RETRIEVAL'); e.status = 409; throw e;
  }
  if (projectSourceRegistryContextSha(after) !== expectedSourceContextSha256) {
    const e = new Error('RUNTIME_PROJECT_SOURCE_SEARCH_CHANGED_DURING_RETRIEVAL'); e.status = 409; throw e;
  }
  const projection = projectSourceSearchPresentation(after, semantic.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function handleProjectLibrarySaveFromMessage(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = validateChatOutputSaveBody(projectId, await readJsonBody(req));
  const current = await ensureRuntimeProjectForLibreChatProject(projectId);
  const project = current.project;
  const commandId = stableId(
    'librechat-project-source-save',
    projectId,
    body.provenance.conversation_id,
    body.provenance.message_id,
    body.provenance.content_sha256,
  );
  const result = await runtimeJsonResult(
    'POST',
    '/api/web/projects/' + encodeURIComponent(project.project_id) + '/sources/chat-output',
    {
      command_id:commandId,
      expected_project_revision:project.project_revision,
      filename:body.filename,
      content:body.content,
      provenance:body.provenance,
    },
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const after = await runtimeJson(
    'GET',
    '/api/web/projects/' + encodeURIComponent(project.project_id),
  );
  const projection = projectLibraryProjection(after);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify({
    initialized:true,
    ...projection,
    saved_source_ref_id:result.body && result.body.source_ref && result.body.source_ref.source_ref_id,
  }));
}

async function handleProjectLibraryRemove(req, res, sourceRefId) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  if (!Number.isInteger(expectedProjectRevision) || expectedProjectRevision < 1) {
    const e = new Error('RUNTIME_PROJECT_LIBRARY_REVISION_INVALID'); e.status = 400; throw e;
  }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  const project = lookup.current && lookup.current.project;
  if (!project) {
    const e = new Error('RUNTIME_PROJECT_LIBRARY_SCOPE_MISSING'); e.status = 409; throw e;
  }
  const commandId = stableId(
    'librechat-project-source-remove',
    projectId,
    sourceRefId,
  );
  const result = await runtimeJsonResult(
    'POST',
    '/api/web/projects/' + encodeURIComponent(project.project_id) +
      '/sources/' + encodeURIComponent(sourceRefId) + '/remove',
    {
      command_id:commandId,
      expected_project_revision:expectedProjectRevision,
    },
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const after = await runtimeJson(
    'GET',
    '/api/web/projects/' + encodeURIComponent(project.project_id),
  );
  const projection = projectLibraryProjection(after);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify({
    initialized:true,
    ...projection,
    lifecycle:result.body && result.body.lifecycle,
  }));
}

async function handlePromotedPackCatalogGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const result = await runtimeJsonResult('GET', '/api/web/packs/promoted');
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const body = result.body;
  const validPacks =
    body &&
    Array.isArray(body.packs) &&
    body.packs.every(
      (pack) =>
        pack &&
        typeof pack.pack_id === 'string' && pack.pack_id.length > 0 &&
        typeof pack.version === 'string' && pack.version.length > 0 &&
        pack.promotion_status === 'PROMOTED' &&
        typeof pack.purpose === 'string' &&
        Array.isArray(pack.capabilities) &&
        pack.capabilities.every((item) => typeof item === 'string' && item.length > 0) &&
        typeof pack.manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.manifest_sha256) &&
        typeof pack.content_manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.content_manifest_sha256) &&
        typeof pack.promotion_receipt_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.promotion_receipt_sha256),
    );
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_PROMOTED_PACK_CATALOG_R001' ||
    body.authority_class !== 'NON_AUTHORITY_PRESENTATION_PROJECTION' ||
    !Number.isInteger(body.pack_count) ||
    body.pack_count < 0 ||
    !validPacks ||
    body.pack_count !== body.packs.length
  ) {
    throw new Error('RUNTIME_PROMOTED_PACK_CATALOG_SHAPE_INVALID');
  }
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(body));
}

function isValidUserInstallablePackItem(pack) {
  return (
    pack &&
    typeof pack === 'object' &&
    pack.schema_revision === 'RUNTIME_USER_INSTALLABLE_PACK_POLICY_R001' &&
    typeof pack.pack_id === 'string' && pack.pack_id.length > 0 &&
    typeof pack.pack_version === 'string' && pack.pack_version.length > 0 &&
    typeof pack.pack_manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.pack_manifest_sha256) &&
    typeof pack.pack_content_manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.pack_content_manifest_sha256) &&
    typeof pack.pack_promotion_receipt_sha256 === 'string' && /^[0-9a-f]{64}$/.test(pack.pack_promotion_receipt_sha256) &&
    (pack.visibility === null || typeof pack.visibility === 'string') &&
    typeof pack.eligibility === 'string' && pack.eligibility.length > 0 &&
    typeof pack.installed === 'boolean'
  );
}

async function handleUserInstallablePackCatalogGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const result = await runtimeJsonResult('GET', '/api/web/packs/user-installable');
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const body = result.body;
  const validPacks =
    body &&
    Array.isArray(body.packs) &&
    body.packs.every(isValidUserInstallablePackItem);
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_USER_INSTALLABLE_PACK_CATALOG_R001' ||
    body.authority_class !== 'NON_AUTHORITY_PRESENTATION_PROJECTION' ||
    !Number.isInteger(body.pack_count) ||
    body.pack_count < 0 ||
    !validPacks ||
    body.pack_count !== body.packs.length
  ) {
    const e = new Error('RUNTIME_USER_INSTALLABLE_PACK_CATALOG_SHAPE_INVALID'); e.status = 502; throw e;
  }
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(body));
}

async function handleUserPackInstallMutation(req, res, action) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const packId = body && body.pack_id;
  const packVersion = body && body.pack_version;
  if (
    typeof packId !== 'string' || !packId ||
    typeof packVersion !== 'string' || !packVersion
  ) {
    const e = new Error('RUNTIME_USER_PACK_TARGET_INVALID'); e.status = 400; throw e;
  }
  let payload;
  if (action === 'uninstall') {
    const commandId = body && body.command_id;
    if (typeof commandId !== 'string' || !commandId) {
      const e = new Error('RUNTIME_USER_PACK_UNINSTALL_COMMAND_ID_REQUIRED'); e.status = 400; throw e;
    }
    payload = { command_id: commandId };
  }
  const path =
    `/api/web/packs/${encodeURIComponent(packId)}/${encodeURIComponent(packVersion)}/install`;
  const result = await runtimeJsonResult(
    action === 'install' ? 'POST' : 'DELETE',
    path,
    payload,
  );
  return sendRuntimeJsonResult(res, result);
}


function isValidProjectPackBinding(binding) {
  return (
    binding === null ||
    (
      binding &&
      typeof binding === 'object' &&
      typeof binding.pack_id === 'string' && binding.pack_id.length > 0 &&
      typeof binding.pack_version === 'string' && binding.pack_version.length > 0 &&
      typeof binding.pack_manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(binding.pack_manifest_sha256) &&
      typeof binding.pack_content_manifest_sha256 === 'string' && /^[0-9a-f]{64}$/.test(binding.pack_content_manifest_sha256) &&
      typeof binding.pack_promotion_receipt_sha256 === 'string' && /^[0-9a-f]{64}$/.test(binding.pack_promotion_receipt_sha256)
    )
  );
}

function projectPackBindingPresentation(body) {
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_PROJECT_PACK_BINDING_R001' ||
    body.authority_class !== 'RUNTIME_PROJECT_AUTHORITY_PROJECTION' ||
    typeof body.project_id !== 'string' || body.project_id.length === 0 ||
    !Number.isInteger(body.project_revision) || body.project_revision < 1 ||
    !isValidProjectPackBinding(body.binding)
  ) {
    const e = new Error('RUNTIME_PROJECT_PACK_BINDING_SHAPE_INVALID'); e.status = 502; throw e;
  }
  return {
    schema: 'UR_WEB_R004_PROJECT_PACK_BINDING_PRESENTATION_R001',
    authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized: true,
    project_revision: body.project_revision,
    binding: body.binding,
  };
}

function emptyProjectPackBindingPresentation() {
  return {
    schema: 'UR_WEB_R004_PROJECT_PACK_BINDING_PRESENTATION_R001',
    authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized: false,
    project_revision: null,
    binding: null,
  };
}


function isValidProjectLocalWorkBinding(binding) {
  return (
    binding === null ||
    (
      binding &&
      typeof binding === 'object' &&
      binding.executor === 'webcodex-local' &&
      binding.binding_class === 'MACHINE_LOCAL_PROJECT_ROOT' &&
      typeof binding.local_project_root === 'string' &&
      binding.local_project_root.length > 0
    )
  );
}

function projectLocalWorkBindingPresentation(body) {
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_PROJECT_LOCAL_WORK_BINDING_R001' ||
    body.authority_class !== 'RUNTIME_PROJECT_AUTHORITY_PROJECTION' ||
    typeof body.project_id !== 'string' || body.project_id.length === 0 ||
    !Number.isInteger(body.project_revision) || body.project_revision < 1 ||
    !isValidProjectLocalWorkBinding(body.binding)
  ) {
    const e = new Error('RUNTIME_PROJECT_LOCAL_WORK_BINDING_SHAPE_INVALID'); e.status = 502; throw e;
  }
  return {
    schema:'UR_WEB_R004_PROJECT_LOCAL_WORK_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:true,
    project_revision:body.project_revision,
    binding:body.binding,
  };
}

function emptyProjectLocalWorkBindingPresentation() {
  return {
    schema:'UR_WEB_R004_PROJECT_LOCAL_WORK_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:false,
    project_revision:null,
    binding:null,
  };
}

async function handleProjectLocalWorkBindingGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(emptyProjectLocalWorkBindingPresentation()));
  }
  const project = lookup.current.project;
  const result = await runtimeJsonResult(
    'GET',
    '/api/web/projects/' + encodeURIComponent(project.project_id) + '/local-work-binding',
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const projection = projectLocalWorkBindingPresentation(result.body);
  if (projection.project_revision !== project.project_revision) {
    const e = new Error('RUNTIME_PROJECT_LOCAL_WORK_BINDING_REVISION_MISMATCH'); e.status = 409; throw e;
  }
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

function isValidAssistantProfileBinding(binding) {
  return (
    binding === null ||
    (
      binding &&
      typeof binding === 'object' &&
      typeof binding.assistant_profile_id === 'string' && binding.assistant_profile_id.length > 0 &&
      typeof binding.assistant_profile_revision === 'string' && binding.assistant_profile_revision.length > 0
    )
  );
}

function projectAssistantProfilePresentation(body) {
  if (
    !body ||
    body.schema !== 'UR_RUNTIME_PROJECT_ASSISTANT_PROFILE_BINDING_R001' ||
    body.authority_class !== 'RUNTIME_PROJECT_AUTHORITY_PROJECTION' ||
    typeof body.project_id !== 'string' || body.project_id.length === 0 ||
    !Number.isInteger(body.project_revision) || body.project_revision < 1 ||
    !isValidAssistantProfileBinding(body.binding)
  ) {
    const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_BINDING_SHAPE_INVALID'); e.status = 502; throw e;
  }
  return {
    schema:'UR_WEB_R004_PROJECT_ASSISTANT_PROFILE_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:true,
    project_revision:body.project_revision,
    binding:body.binding,
  };
}

function emptyProjectAssistantProfilePresentation() {
  return {
    schema:'UR_WEB_R004_PROJECT_ASSISTANT_PROFILE_PRESENTATION_R001',
    authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
    initialized:false,
    project_revision:null,
    binding:null,
  };
}

async function handleProjectAssistantProfileGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(emptyProjectAssistantProfilePresentation()));
  }
  const project = lookup.current.project;
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(project.project_id)}/assistant-profile-binding`,
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const projection = projectAssistantProfilePresentation(result.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function handleProjectAssistantProfileMutation(req, res, action) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  if (
    !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
    (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1)
  ) {
    const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_REVISION_INVALID'); e.status = 400; throw e;
  }
  const assistantProfileId = body && body.assistant_profile_id;
  const assistantProfileRevision = body && body.assistant_profile_revision;
  if (
    action === 'bind' &&
    (
      typeof assistantProfileId !== 'string' || assistantProfileId.length === 0 ||
      typeof assistantProfileRevision !== 'string' || assistantProfileRevision.length === 0
    )
  ) {
    const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_TARGET_INVALID'); e.status = 400; throw e;
  }

  const lookup = await lookupProjectContainerForInstructions(projectId);
  let project = lookup.current && lookup.current.project;
  if (!project) {
    if (expectedProjectRevision !== null || action !== 'bind') {
      const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_SCOPE_MISSING'); e.status = 409; throw e;
    }
    const created = await runtimeJson('POST','/api/web/projects',{
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions:lookup.binding.project_instructions,
    });
    project = created && created.project;
  } else if (expectedProjectRevision === null) {
    const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  if (
    expectedProjectRevision !== null &&
    project.project_revision !== expectedProjectRevision
  ) {
    const e = new Error('RUNTIME_PROJECT_ASSISTANT_PROFILE_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  const effectiveExpectedRevision = expectedProjectRevision === null
    ? project.project_revision
    : expectedProjectRevision;
  const runtimePath = `/api/web/projects/${encodeURIComponent(project.project_id)}/assistant-profile-binding`;
  const payload = action === 'bind'
    ? {
        command_id:stableId(
          'librechat-project-assistant-profile-bind',
          projectId,
          String(effectiveExpectedRevision),
          assistantProfileId,
          assistantProfileRevision,
        ),
        expected_project_revision:effectiveExpectedRevision,
        assistant_profile_id:assistantProfileId,
        assistant_profile_revision:assistantProfileRevision,
      }
    : {
        command_id:stableId(
          'librechat-project-assistant-profile-unbind',
          projectId,
          String(effectiveExpectedRevision),
        ),
        expected_project_revision:effectiveExpectedRevision,
      };
  const result = await runtimeJsonResult(action === 'bind' ? 'PUT' : 'DELETE', runtimePath, payload);
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const after = await runtimeJsonResult('GET', runtimePath);
  if (!after.ok) return sendRuntimeJsonResult(res, after);
  const projection = projectAssistantProfilePresentation(after.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function handleProjectPackBindingGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(emptyProjectPackBindingPresentation()));
  }
  const project = lookup.current.project;
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(project.project_id)}/pack-binding`,
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const projection = projectPackBindingPresentation(result.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function handleProjectPackBindingMutation(req, res, action) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  if (
    !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
    (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1)
  ) {
    const e = new Error('RUNTIME_PROJECT_PACK_BINDING_REVISION_INVALID'); e.status = 400; throw e;
  }
  const packId = body && body.pack_id;
  const packVersion = body && body.pack_version;
  if (
    action === 'bind' &&
    (
      typeof packId !== 'string' || packId.length === 0 ||
      typeof packVersion !== 'string' || packVersion.length === 0
    )
  ) {
    const e = new Error('RUNTIME_PROJECT_PACK_BINDING_TARGET_INVALID'); e.status = 400; throw e;
  }

  const lookup = await lookupProjectContainerForInstructions(projectId);
  let project = lookup.current && lookup.current.project;
  if (!project) {
    if (expectedProjectRevision !== null || action !== 'bind') {
      const e = new Error('RUNTIME_PROJECT_PACK_BINDING_SCOPE_MISSING'); e.status = 409; throw e;
    }
    const created = await runtimeJson('POST','/api/web/projects',{
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions:lookup.binding.project_instructions,
    });
    project = created && created.project;
  } else if (expectedProjectRevision === null) {
    const e = new Error('RUNTIME_PROJECT_PACK_BINDING_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  if (
    expectedProjectRevision !== null &&
    project.project_revision !== expectedProjectRevision
  ) {
    const e = new Error('RUNTIME_PROJECT_PACK_BINDING_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  const effectiveExpectedRevision = expectedProjectRevision === null
    ? project.project_revision
    : expectedProjectRevision;
  const runtimePath = `/api/web/projects/${encodeURIComponent(project.project_id)}/pack-binding`;
  const payload = action === 'bind'
    ? {
        command_id:stableId(
          'librechat-project-pack-bind',
          projectId,
          String(effectiveExpectedRevision),
          packId,
          packVersion,
        ),
        expected_project_revision:effectiveExpectedRevision,
        pack_id:packId,
        pack_version:packVersion,
      }
    : {
        command_id:stableId(
          'librechat-project-pack-unbind',
          projectId,
          String(effectiveExpectedRevision),
        ),
        expected_project_revision:effectiveExpectedRevision,
      };
  const result = await runtimeJsonResult(action === 'bind' ? 'PUT' : 'DELETE', runtimePath, payload);
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const after = await runtimeJsonResult('GET', runtimePath);
  if (!after.ok) return sendRuntimeJsonResult(res, after);
  const projection = projectPackBindingPresentation(after.body);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(projection));
}

async function handleProjectInstructionsPut(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  const instructions = body && body.instructions;
  if (
    !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
    (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1) ||
    typeof instructions !== 'string'
  ) {
    const e = new Error('RUNTIME_PROJECT_INSTRUCTIONS_REQUEST_INVALID'); e.status = 400; throw e;
  }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  let current = lookup.current;
  if (expectedProjectRevision === null && !current) {
    const created = await runtimeJson('POST','/api/web/projects',{
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions,
    });
    const project = created && created.project;
    if (!project || !project.project_id) throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
    const afterCreate = await runtimeJson('GET', `/api/web/projects/${encodeURIComponent(project.project_id)}`);
    const projection = {initialized:true,...projectInstructionsProjection(afterCreate)};
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify(projection));
  }
  if (!current) { const e = new Error('RUNTIME_PROJECT_INSTRUCTIONS_SCOPE_MISSING'); e.status = 409; throw e; }
  const preflight = projectInstructionsProjection(current);
  if (expectedProjectRevision === null) {
    if (preflight.instruction_sha256 === hash(instructions)) {
      res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
      return res.end(JSON.stringify({initialized:true,...preflight}));
    }
    if (preflight.instruction_sha256 !== hash('')) {
      const e = new Error('RUNTIME_PROJECT_INSTRUCTIONS_STALE_SINCE_LOAD'); e.status = 409; throw e;
    }
  }
  const effectiveExpectedRevision = expectedProjectRevision === null
    ? preflight.project_revision
    : expectedProjectRevision;
  await runtimeJson('PUT',`/api/web/projects/${encodeURIComponent(current.project.project_id)}/instructions`,{
    command_id:stableId('librechat-project-instructions',projectId,String(effectiveExpectedRevision),hash(instructions)),
    expected_project_revision:effectiveExpectedRevision,
    instructions,
  });
  const after = await runtimeJson('GET', `/api/web/projects/${encodeURIComponent(current.project.project_id)}`);
  const projection = {initialized:true,...projectInstructionsProjection(after)};
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  res.end(JSON.stringify(projection));
}

function validateMemoryId(value) {
  const memoryId = String(value || '');
  if (!memoryId.startsWith('MEM_') || memoryId.length > 256 || /[\\/\u0000-\u001F\u007F]/.test(memoryId)) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_ID_INVALID'); e.status = 400; throw e;
  }
  return memoryId;
}

async function runtimeJsonResult(method, path, payload, extraHeaders = {}) {
  const options = {
    method,
    headers: {
      'Accept': 'application/json',
      'X-UR-Runtime-Proxy': RUNTIME_PROXY_KEY,
      ...extraHeaders,
    },
  };
  if (payload !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(RUNTIME + path, options);
  const raw = await response.text();
  let body = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = {raw}; }
  return {ok:response.ok,status:response.status,raw,body};
}

function sendRuntimeJsonResult(res, result) {
  res.writeHead(result.status, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(result.raw || JSON.stringify(result.body || {}));
}

async function handleProjectMemoryGet(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify({initialized:false,project_revision:null,state_binding:null,state_revision:0,memories:[]}));
  }
  const project = lookup.current.project;
  const result = await runtimeJsonResult(
    'GET',
    `/api/web/projects/${encodeURIComponent(project.project_id)}/memory`,
  );
  if (!result.ok) return sendRuntimeJsonResult(res, result);
  const body = result.body;
  if (
    !body ||
    body.schema !== 'UR_WEB_PROJECT_MEMORY_LIST_R001' ||
    body.project_id !== project.project_id ||
    !Number.isInteger(body.state_revision) || body.state_revision < 0 ||
    !Array.isArray(body.memories)
  ) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_LIST_SHAPE_INVALID'); e.status = 502; throw e;
  }
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify({...body,initialized:true,project_revision:project.project_revision}));
}

async function handleProjectMemoryCreate(req, res) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  const body = await readJsonBody(req);
  const expectedProjectRevision = body && body.expected_project_revision;
  const content = body && body.content;
  if (
    !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
    (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1) ||
    typeof content !== 'string'
  ) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_CREATE_REQUEST_INVALID'); e.status = 400; throw e;
  }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  let project = lookup.current && lookup.current.project;
  if (!project) {
    if (expectedProjectRevision !== null) {
      const e = new Error('RUNTIME_PROJECT_MEMORY_SCOPE_MISSING'); e.status = 409; throw e;
    }
    const created = await runtimeJson('POST','/api/web/projects',{
      command_id:lookup.binding.project_command_id,
      display_name:lookup.binding.project_display_name,
      instructions:lookup.binding.project_instructions,
    });
    project = created && created.project;
  } else if (expectedProjectRevision === null) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_STALE_SINCE_LOAD'); e.status = 409; throw e;
  }
  if (!project || !project.project_id || !Number.isInteger(project.project_revision)) {
    throw new Error('RUNTIME_PROJECT_CREATE_SHAPE');
  }
  const effectiveExpectedRevision = expectedProjectRevision === null
    ? project.project_revision
    : expectedProjectRevision;
  const result = await runtimeJsonResult(
    'POST',
    `/api/web/projects/${encodeURIComponent(project.project_id)}/memory`,
    {
      command_id:stableId('librechat-project-memory-create',projectId,String(effectiveExpectedRevision),hash(content)),
      expected_project_revision:effectiveExpectedRevision,
      content,
    },
  );
  return sendRuntimeJsonResult(res, result);
}

async function handleProjectMemoryItemMutation(req, res, memoryId, action) {
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!projectId) { const e = new Error('RUNTIME_PROJECT_IDENTITY_REQUIRED'); e.status = 400; throw e; }
  memoryId = validateMemoryId(memoryId);
  const body = await readJsonBody(req);
  const expectedMemoryRevision = body && body.expected_memory_revision;
  if (!Number.isInteger(expectedMemoryRevision) || expectedMemoryRevision < 1) {
    const e = new Error('RUNTIME_PROJECT_MEMORY_REVISION_REQUIRED'); e.status = 400; throw e;
  }
  const lookup = await lookupProjectContainerForInstructions(projectId);
  if (!lookup.current) { const e = new Error('RUNTIME_PROJECT_MEMORY_SCOPE_MISSING'); e.status = 409; throw e; }
  const project = lookup.current.project;
  let method;
  let path;
  let payload;
  if (action === 'revise') {
    if (typeof body.content !== 'string') { const e = new Error('RUNTIME_PROJECT_MEMORY_CONTENT_REQUIRED'); e.status = 400; throw e; }
    method = 'PUT';
    path = `/api/web/projects/${encodeURIComponent(project.project_id)}/memory/${encodeURIComponent(memoryId)}`;
    payload = {
      command_id:stableId('librechat-project-memory-revise',projectId,memoryId,String(expectedMemoryRevision),hash(body.content)),
      expected_memory_revision:expectedMemoryRevision,
      content:body.content,
    };
  } else if (action === 'enabled') {
    if (typeof body.enabled !== 'boolean') { const e = new Error('RUNTIME_PROJECT_MEMORY_ENABLED_REQUIRED'); e.status = 400; throw e; }
    method = 'POST';
    path = `/api/web/projects/${encodeURIComponent(project.project_id)}/memory/${encodeURIComponent(memoryId)}/enabled`;
    payload = {
      command_id:stableId('librechat-project-memory-enabled',projectId,memoryId,String(expectedMemoryRevision),String(body.enabled)),
      expected_memory_revision:expectedMemoryRevision,
      enabled:body.enabled,
    };
  } else if (action === 'delete') {
    method = 'DELETE';
    path = `/api/web/projects/${encodeURIComponent(project.project_id)}/memory/${encodeURIComponent(memoryId)}`;
    payload = {
      command_id:stableId('librechat-project-memory-delete',projectId,memoryId,String(expectedMemoryRevision)),
      expected_memory_revision:expectedMemoryRevision,
    };
  } else {
    const e = new Error('RUNTIME_PROJECT_MEMORY_ACTION_INVALID'); e.status = 400; throw e;
  }
  const result = await runtimeJsonResult(method, path, payload);
  return sendRuntimeJsonResult(res, result);
}
function parseRuntimeSse(onEvent) {
  let buffer = '';
  let eventName = 'message';
  let dataLines = [];
  async function dispatch() {
    if (!dataLines.length) {
      eventName = 'message';
      return;
    }
    const raw = dataLines.join('\n');
    dataLines = [];
    const data = JSON.parse(raw);
    await onEvent(eventName, data);
    eventName = 'message';
  }
  return {
    async push(text) {
      buffer += text;
      while (buffer.includes('\n')) {
        const idx = buffer.indexOf('\n');
        const line = buffer.slice(0, idx).replace(/\r$/, '');
        buffer = buffer.slice(idx + 1);
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
        else if (line === '') await dispatch();
      }
    },
    async end(text='') {
      buffer += text;
      if (buffer.trim()) {
        for (const line of buffer.split(/\r?\n/)) {
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
          else if (line === '') await dispatch();
        }
      }
      await dispatch();
    },
  };
}
async function canonicalVerify(entry, final) {
  if (
    !final ||
    typeof final.assistant_event_id !== 'string' ||
    !final.assistant_event_id ||
    typeof final.head_event_id !== 'string' ||
    !final.head_event_id ||
    final.assistant_event_id !== final.head_event_id
  ) {
    throw new Error('RUNTIME_FINAL_ASSISTANT_HEAD_ID_MISMATCH');
  }

  const row = await resume(entry);
  if (
    !row.chat ||
    row.chat.head_event_id !== final.head_event_id ||
    row.chat.chat_revision !== final.chat_revision
  ) {
    throw new Error('RUNTIME_CANONICAL_COMMITTED_HEAD_MISMATCH');
  }
  const events = Array.isArray(row.events) ? row.events : [];
  const exact = events
    .map(x => x && x.event)
    .filter(x => x && x.event_id === final.assistant_event_id);
  if (exact.length !== 1) throw new Error('RUNTIME_CANONICAL_ASSISTANT_EVENT_MISSING');
  const event = exact[0];
  if (
    event.event_id !== final.assistant_event_id ||
    event.event_id !== final.head_event_id ||
    event.event_type !== 'ASSISTANT_MESSAGE' ||
    event.actor_class !== 'ASSISTANT' ||
    event.content !== final.assistant_text
  ) {
    throw new Error('RUNTIME_CANONICAL_ASSISTANT_MISMATCH');
  }
  return event;
}
function ensureUserTurnMap(entry) {
  if (!(entry.user_turns instanceof Map)) entry.user_turns = new Map();
  return entry.user_turns;
}

async function restartSafeReplayGuard(
  entry,
  shellId,
  messageId,
  parentMessageId,
  query,
  personalContextSha256,
  projectContextPolicy,
) {
  const row = await resume(entry);
  if (!row.chat || row.chat.chat_id !== entry.chat.chat_id) {
    throw new Error('RUNTIME_REPLAY_SCOPE_MISMATCH');
  }
  const userTurnIdentity = stableId('librechat-user-turn-identity', shellId, parentMessageId);
  const assistantAttemptIdentity = stableId('librechat-assistant-attempt-identity', shellId, messageId);
  const sendCommandId = stableId('final-shell-send', userTurnIdentity);
  const querySha256 = hash(query);
  const sourceRefId = entry.active_source ? entry.active_source.source_ref_id : null;
  const turns = ensureUserTurnMap(entry);
  let turnState = turns.get(userTurnIdentity);

  if (turnState) {
    if (
      turnState.query_sha256 !== querySha256 ||
      turnState.source_ref_id !== sourceRefId ||
      turnState.personal_context_sha256 !== personalContextSha256 ||
      turnState.project_context_policy !== projectContextPolicy
    ) {
      const e = new Error('FAILED_RETRY_USER_TURN_CONTEXT_MISMATCH');
      e.status = 409;
      throw e;
    }
    if (turnState.completed === true) {
      if (sourceRefId) {
        const e = new Error('SOURCE_GROUNDED_REGENERATE_REQUIRES_SEPARATE_CONFIRMATION');
        e.status = 409;
        throw e;
      }
      if (personalContextSha256) {
        const e = new Error('PERSONAL_CONTEXT_REGENERATE_REQUIRES_SEPARATE_CONFIRMATION');
        e.status = 409;
        throw e;
      }
      if (!turnState.assistant_event_id || !turnState.job_id) {
        const e = new Error('PLAIN_REGENERATE_PREDECESSOR_BINDING_MISSING');
        e.status = 409;
        throw e;
      }
      return {
        sendCommandId,
        userTurnIdentity,
        assistantAttemptIdentity,
        expectedChatRevision: row.chat.chat_revision,
        failedRetry: false,
        regeneratePlain: true,
        regenerateCommandId: stableId(
          'final-shell-plain-regenerate',
          shellId,
          messageId,
          turnState.assistant_event_id,
        ),
        targetAssistantEventId: turnState.assistant_event_id,
        predecessorJobId: turnState.job_id,
        turnState,
      };
    }
    return {
      sendCommandId,
      userTurnIdentity,
      assistantAttemptIdentity,
      expectedChatRevision: turnState.expected_chat_revision,
      failedRetry: true,
      regeneratePlain: false,
      turnState,
    };
  }

  turnState = {
    user_turn_identity: userTurnIdentity,
    first_assistant_attempt_identity: assistantAttemptIdentity,
    first_message_id: messageId,
    parent_message_id: parentMessageId,
    expected_chat_revision: entry.chat.chat_revision,
    query_sha256: querySha256,
    source_ref_id: sourceRefId,
    personal_context_sha256: personalContextSha256,
    project_context_policy: projectContextPolicy,
    runtime_user_event_id: null,
    completed: false,
    assistant_event_id: null,
    cancelled_retry_lineage: null,
  };
  turns.set(userTurnIdentity, turnState);
  return {
    sendCommandId,
    userTurnIdentity,
    assistantAttemptIdentity,
    expectedChatRevision: turnState.expected_chat_revision,
    failedRetry: false,
    turnState,
  };
}


async function admitNativeProviderSource(entry, shellId, messageId, plan) {
  const file = plan && plan.file;
  if (!file || !Buffer.isBuffer(file.exactBytes) || !file.exactBytes.length) {
    throw new Error('NATIVE_FILE_PLAN_MISSING_EXACT_BYTES');
  }
  const bodySha = file.inputSha256;
  if (!/^[0-9a-f]{64}$/.test(bodySha) || crypto.createHash('sha256').update(file.exactBytes).digest('hex') !== bodySha) {
    throw new Error('NATIVE_FILE_PLAN_SHA_MISMATCH');
  }
  if (entry.active_message_id || entry.document_admission_in_flight) {
    const e = new Error('RUNTIME_SHELL_BUSY'); e.status = 409; throw e;
  }
  entry.document_admission_in_flight = true;
  try {
    await resume(entry);
    if (entry.active_source) {
      if (entry.active_source.input_sha256 === bodySha) return entry.active_source;
      const e = new Error('ONE_RUNTIME_DOCUMENT_PER_SHELL_FIRST_SLICE'); e.status = 409; throw e;
    }
    const query = new URLSearchParams({
      command_id: stableId('native-provider-document-intake', shellId, messageId, file.filename, bodySha),
      filename: file.filename,
      expected_project_revision: String(entry.project.project_revision),
      chat_id: entry.chat.chat_id,
    });
    const adopted = await runtimeRaw(
      'POST',
      `/api/web/projects/${encodeURIComponent(entry.project.project_id)}/sources/document?${query.toString()}`,
      file.exactBytes,
      file.mediaType,
    );
    const sourceRef = adopted && adopted.source_ref;
    const documentArtifact = adopted && adopted.document_bundle_artifact;
    if (
      !sourceRef || typeof sourceRef.source_ref_id !== 'string' || !sourceRef.source_ref_id ||
      sourceRef.project_id !== entry.project.project_id ||
      !documentArtifact || documentArtifact.input_sha256 !== bodySha
    ) {
      throw new Error('RUNTIME_NATIVE_DOCUMENT_ADMISSION_SHAPE_MISMATCH');
    }
    await resume(entry);
    if (!entry.active_source || entry.active_source.source_ref_id !== sourceRef.source_ref_id) {
      throw new Error('RUNTIME_NATIVE_DOCUMENT_SOURCE_REHYDRATE_MISMATCH');
    }
    entry.active_source = {
      ...entry.active_source,
      filename:file.filename,
      media_type:file.mediaType,
      byte_size:file.exactBytes.length,
      input_sha256:bodySha,
      source_ref_id:sourceRef.source_ref_id,
      source_artifact_sha256:documentArtifact.sha256,
      source_origin_binding:plan.originBinding,
    };
    log({
      event:'runtime_native_source_ready',
      shell_id:shellId,
      message_id:messageId,
      source_ref_id:sourceRef.source_ref_id,
      input_sha256:bodySha,
      origin_binding_sha256:hash(JSON.stringify(plan.originBinding)),
    });
    return entry.active_source;
  } finally {
    entry.document_admission_in_flight = false;
  }
}

function finishSourceOnlySse(res, sourceRefId) {
  res.writeHead(200, {
    'Content-Type':'text/event-stream',
    'Cache-Control':'no-cache',
    'Connection':'keep-alive',
    'X-Accel-Buffering':'no',
    'X-UR-Source-Ready':'true',
    'X-UR-Source-Ref':String(sourceRefId || ''),
  });
  sendSse(res, {
    id:'chatcmpl-ur-source-ready-r001',
    object:'chat.completion.chunk',
    created:Math.floor(Date.now()/1000),
    model:MODEL,
    choices:[{index:0,delta:{role:'assistant'},finish_reason:null}],
  });
  finishSse(res);
}

async function handleRuntimeDocument(req, res) {
  const shellId = header(req, 'x-conversation-id');
  if (!shellId) { const e = new Error('MISSING_LIBRECHAT_CONVERSATION_ID'); e.status = 400; throw e; }
  const filename = decodeDocumentFilename(req);
  const mediaType = header(req, 'x-runtime-document-media-type') || 'application/octet-stream';
  const declaredSize = Number(header(req, 'x-runtime-document-size'));
  const declaredSha = header(req, 'x-runtime-document-sha256').toLowerCase();
  const body = await readRawBody(req);
  const bodySha = crypto.createHash('sha256').update(body).digest('hex');
  if (!Number.isSafeInteger(declaredSize) || declaredSize !== body.length || !/^[0-9a-f]{64}$/.test(declaredSha) || declaredSha !== bodySha) {
    const e = new Error('RUNTIME_DOCUMENT_BYTE_IDENTITY_MISMATCH'); e.status = 409; throw e;
  }
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  const entry = await getOrCreateShell(shellId, projectId);
  if (entry.active_message_id || entry.document_admission_in_flight) {
    const e = new Error('RUNTIME_SHELL_BUSY'); e.status = 409; throw e;
  }
  entry.document_admission_in_flight = true;
  try {
    await resume(entry);
    if (entry.active_source) {
      if (entry.active_source.input_sha256 && entry.active_source.input_sha256 === bodySha) {
        res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
        return res.end(JSON.stringify(entry.active_source));
      }
      const e = new Error('ONE_RUNTIME_DOCUMENT_PER_SHELL_FIRST_SLICE'); e.status = 409; throw e;
    }
    const query = new URLSearchParams({
      command_id: stableId('h2a-document-intake', shellId, filename, bodySha),
      filename,
      expected_project_revision: String(entry.project.project_revision),
      chat_id: entry.chat.chat_id,
    });
    const adopted = await runtimeRaw(
      'POST',
      `/api/web/projects/${encodeURIComponent(entry.project.project_id)}/sources/document?${query.toString()}`,
      body,
      mediaType,
    );
    const sourceRef = adopted && adopted.source_ref;
    const documentArtifact = adopted && adopted.document_bundle_artifact;
    if (
      !sourceRef || typeof sourceRef.source_ref_id !== 'string' || !sourceRef.source_ref_id ||
      sourceRef.project_id !== entry.project.project_id ||
      !documentArtifact || documentArtifact.input_sha256 !== bodySha
    ) {
      throw new Error('RUNTIME_DOCUMENT_ADMISSION_SHAPE_MISMATCH');
    }
    await resume(entry);
    if (!entry.active_source || entry.active_source.source_ref_id !== sourceRef.source_ref_id) {
      throw new Error('RUNTIME_DOCUMENT_SOURCE_REHYDRATE_MISMATCH');
    }
    entry.active_source = {
      ...entry.active_source,
      filename,
      media_type: mediaType,
      byte_size: body.length,
      input_sha256: bodySha,
      source_ref_id: sourceRef.source_ref_id,
      source_artifact_sha256: documentArtifact.sha256,
    };
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    res.end(JSON.stringify(entry.active_source));
    log({event:'runtime_document_ready', shell_id:shellId, source_ref_id:sourceRef.source_ref_id, input_sha256:bodySha});
  } finally {
    entry.document_admission_in_flight = false;
  }
}

async function handleRuntimeDocumentStatus(req, res) {
  const shellId = header(req, 'x-conversation-id');
  if (!shellId) { const e = new Error('MISSING_LIBRECHAT_CONVERSATION_ID'); e.status = 400; throw e; }
  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  const entry = await getOrCreateShell(shellId, projectId);
  if (entry.document_admission_in_flight) {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify({status:'uploading'}));
  }
  await resume(entry);
  res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
  return res.end(JSON.stringify(entry.active_source || {status:'idle'}));
}

async function handleCompletion(req, res, body) {
  if (body.stream !== true) throw new Error('STREAM_TRUE_REQUIRED');
  const shellId = String(req.headers['x-conversation-id'] || '');
  const messageId = String(req.headers['x-message-id'] || '');
  const parentMessageId = String(req.headers['x-parent-message-id'] || '');
  if (!shellId || !messageId || !parentMessageId) throw new Error('MISSING_LIBRECHAT_IDENTITY_HEADERS');
  const turnPlan = nativeFileSource.planTurn({headers:req.headers, body});
  const query = turnPlan.userText;
  const requestedPersonalContext = extractPersonalContext(body);

  const projectId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  const entry = await getOrCreateShell(shellId, projectId);
  if (turnPlan.file) {
    const source = await admitNativeProviderSource(entry, shellId, messageId, turnPlan);
    if (turnPlan.action === 'INGEST_ONLY_SOURCE_READY') {
      entry.completed_message_ids.add(messageId);
      log({event:'runtime_native_source_only_turn_complete', shell_id:shellId, message_id:messageId, source_ref_id:source.source_ref_id, model_called:false});
      return finishSourceOnlySse(res, source.source_ref_id);
    }
  }
  const contextPolicyProjection = await getEntryProjectContextPolicy(entry);
  const projectContextPolicy = contextPolicyProjection.context_policy;
  const personalContext = effectivePersonalContextForPolicy(
    projectContextPolicy,
    requestedPersonalContext,
  );
  const personalContextSha256 = personalContext ? canonicalSha256(personalContext) : null;
  if (entry.document_admission_in_flight) { const e=new Error('RUNTIME_DOCUMENT_NOT_READY'); e.status=409; throw e; }
  if (entry.active_message_id) { const e=new Error('ONE_ACTIVE_RUNTIME_REQUEST_PER_SHELL'); e.status=409; throw e; }
  if (entry.completed_message_ids.has(messageId) || entry.failed_message_ids.has(messageId)) {
    const e=new Error('MESSAGE_ID_REPLAY_FORBIDDEN'); e.status=409; throw e;
  }

  entry.active_message_id = messageId;
  let responseStarted = false;
  let visible = '';
  let downstreamClosed = false;
  let runtimeTerminalSeen = false;
  let runtimeExecutionInstanceId = null;
  let runtimeStopIssued = false;
  let runtimeStopResult = null;
  let approved = null;
  let cancelled = null;

  const stopAcceptedStatuses = new Set([
    'STOP_REQUEST_ACCEPTED_PRECLAIM',
    'STOP_REQUEST_ACCEPTED_PENDING_CONFIRMATION',
  ]);
  const requestRuntimeStopForDownstreamClose = async () => {
    if (
      !downstreamClosed ||
      runtimeTerminalSeen ||
      runtimeStopIssued ||
      !runtimeExecutionInstanceId
    ) return runtimeStopResult;
    runtimeStopIssued = true;
    const stopPath =
      '/api/web/projects/' + encodeURIComponent(entry.project.project_id) +
      '/chats/' + encodeURIComponent(entry.chat.chat_id) +
      '/formal-model/stop';
    const body = await runtimeJson('POST', stopPath, {
      job_id: approved.job_id,
      decision_request_event_id: approved.decision_request_event_id,
      execution_instance_id: runtimeExecutionInstanceId,
    });
    runtimeStopResult = body;
    if (!body || !stopAcceptedStatuses.has(body.status) || body.stop_requested !== true) {
      throw new Error('RUNTIME_STOP_NOT_ACCEPTED:' + JSON.stringify(body));
    }
    log({
      event:'runtime_stop_requested_from_downstream_close',
      shell_id:shellId,
      message_id:messageId,
      project_id:entry.project.project_id,
      runtime_chat_id:entry.chat.chat_id,
      job_id:approved.job_id,
      execution_instance_id:runtimeExecutionInstanceId,
      stop_status:body.status,
    });
    return body;
  };
  const onDownstreamClose = () => {
    if (runtimeTerminalSeen || res.writableEnded) return;
    downstreamClosed = true;
    void requestRuntimeStopForDownstreamClose().catch((error) => {
      log({
        event:'runtime_stop_bridge_failed',
        shell_id:shellId,
        message_id:messageId,
        error:String(error && error.stack || error),
      });
    });
  };
  res.once('close', onDownstreamClose);
  try {
    const replay = await restartSafeReplayGuard(
      entry,
      shellId,
      messageId,
      parentMessageId,
      query,
      personalContextSha256,
      projectContextPolicy,
    );
    const activeSource = entry.active_source;
    approved = null;
    let expectedStatus;
    let expectedTrigger;
    if (replay.regeneratePlain === true) {
      const regeneratePath =
        '/api/web/projects/' + encodeURIComponent(entry.project.project_id) +
        '/chats/' + encodeURIComponent(entry.chat.chat_id) +
        '/messages/' + encodeURIComponent(replay.targetAssistantEventId) +
        '/regenerate-plain/send-and-approve';
      const regenerated = await runtimeJson('POST', regeneratePath, {
        command_id: replay.regenerateCommandId,
        expected_chat_revision: replay.expectedChatRevision,
      });
      const formal = regenerated && regenerated.formal;
      const branch = regenerated && regenerated.branch;
      const event = regenerated && regenerated.event;
      const predecessorAssistant = branch && branch.predecessor_assistant_event;
      if (
        !regenerated ||
        regenerated.result !== 'PASS_PLAIN_REGENERATE_PREPARE_R001' ||
        !formal ||
        formal.status !== 'APPROVED_PLAIN_INITIAL_JOB' ||
        formal.human_action_trigger !== 'EXPLICIT_PLAIN_REGENERATE_AND_APPROVE_ONE_GENERATION_CONFIRM' ||
        formal.provider_called !== false ||
        formal.network_called !== false ||
        formal.model_called !== false ||
        formal.secret_read !== false ||
        formal.grant_created !== false ||
        formal.attempt_claim_created !== false ||
        regenerated.predecessor_job_id !== replay.predecessorJobId ||
        regenerated.fresh_job_id !== formal.job_id ||
        regenerated.fresh_job_id === replay.predecessorJobId ||
        !predecessorAssistant ||
        predecessorAssistant.event_id !== replay.targetAssistantEventId ||
        !event ||
        event.event_type !== 'USER_MESSAGE' ||
        event.actor_class !== 'USER' ||
        event.content !== query ||
        !Array.isArray(event.related_source_ref_ids) ||
        event.related_source_ref_ids.length !== 0 ||
        !regenerated.chat ||
        regenerated.chat.head_event_id !== event.event_id ||
        !Number.isInteger(regenerated.chat.chat_revision) ||
        regenerated.chat.chat_revision <= replay.expectedChatRevision ||
        !Number.isInteger(formal.project_memory_active_count) ||
        formal.project_memory_active_count < 0 ||
        !Array.isArray(formal.project_memory_ids) ||
        formal.project_memory_ids.length !== formal.project_memory_active_count ||
        (formal.project_memory_active_count === 0 && formal.project_memory_context_sha256 !== null) ||
        (formal.project_memory_active_count > 0 &&
          !/^[0-9a-f]{64}$/.test(String(formal.project_memory_context_sha256 || '')))
      ) {
        throw new Error('RUNTIME_PLAIN_REGENERATE_APPROVAL_CEILING_MISMATCH');
      }
      approved = {
        ...formal,
        event,
        chat: regenerated.chat,
        project_context_policy: projectContextPolicy,
      };
      expectedStatus = 'APPROVED_PLAIN_INITIAL_JOB';
      expectedTrigger = 'EXPLICIT_PLAIN_REGENERATE_AND_APPROVE_ONE_GENERATION_CONFIRM';
      log({
        event:'plain_regenerate_branch_prepared',
        shell_id:shellId,
        message_id:messageId,
        predecessor_assistant_event_id:replay.targetAssistantEventId,
        new_user_event_id:event.event_id,
        predecessor_job_id:replay.predecessorJobId,
        fresh_job_id:formal.job_id,
        project_memory_active_count:formal.project_memory_active_count,
      });
    } else if (replay.failedRetry === true) {
      if (activeSource) {
        const e = new Error('SOURCE_GROUNDED_RETRY_REQUIRES_SEPARATE_CONFIRMATION'); e.status = 409; throw e;
      }
      if (personalContextSha256) {
        const e = new Error('PERSONAL_CONTEXT_RETRY_REQUIRES_SEPARATE_CONFIRMATION'); e.status = 409; throw e;
      }
      const lineage = replay.turnState.cancelled_retry_lineage;
      if (
        !lineage ||
        lineage.predecessor_job_id !== replay.turnState.cancelled_retry_lineage.predecessor_job_id ||
        !lineage.predecessor_job_bundle_binding ||
        !lineage.predecessor_web_formal_job_intake_binding ||
        !lineage.predecessor_cancellation_outcome_binding ||
        lineage.initiating_user_event_id !== replay.turnState.runtime_user_event_id
      ) {
        const e = new Error('CONFIRMED_CANCEL_RETRY_LINEAGE_MISSING'); e.status = 409; throw e;
      }
      const retryPath =
        '/api/web/projects/' + encodeURIComponent(entry.project.project_id) +
        '/chats/' + encodeURIComponent(entry.chat.chat_id) +
        '/formal-model/retry-after-confirmed-cancel';
      const retryApproved = await runtimeJson('POST', retryPath, {
        predecessor_job_id: lineage.predecessor_job_id,
        predecessor_job_bundle_binding: lineage.predecessor_job_bundle_binding,
        predecessor_web_formal_job_intake_binding: lineage.predecessor_web_formal_job_intake_binding,
        predecessor_cancellation_outcome_binding: lineage.predecessor_cancellation_outcome_binding,
        source_context: null,
        source_context_sha256: null,
        initiating_user_event_id: lineage.initiating_user_event_id,
      });
      if (
        !retryApproved ||
        retryApproved.status !== 'APPROVED_FRESH_RETRY_JOB' ||
        retryApproved.retry_context_mode !== 'PLAIN' ||
        retryApproved.predecessor_job_id !== lineage.predecessor_job_id ||
        retryApproved.job_id === lineage.predecessor_job_id ||
        retryApproved.predecessor_claim_replayed !== false ||
        retryApproved.predecessor_claim_refunded !== false ||
        !retryApproved.job_bundle_binding ||
        !retryApproved.web_formal_job_intake_binding ||
        !retryApproved.initiating_user_event ||
        retryApproved.initiating_user_event.event_id !== lineage.initiating_user_event_id
      ) {
        throw new Error('RUNTIME_CONFIRMED_CANCEL_RETRY_APPROVAL_MISMATCH');
      }
      approved = {
        ...retryApproved,
        project_context_policy: projectContextPolicy,
        event: retryApproved.initiating_user_event,
      };
      expectedStatus = 'APPROVED_FRESH_RETRY_JOB';
      expectedTrigger = 'EXPLICIT_RETRY_AND_APPROVE_ONE_GENERATION_CLICK';
      log({
        event:'confirmed_cancel_retry_prepared',
        shell_id:shellId,
        message_id:messageId,
        predecessor_job_id:lineage.predecessor_job_id,
        fresh_job_id:approved.job_id,
        initiating_user_event_id:lineage.initiating_user_event_id,
        project_memory_active_count:approved.project_memory_active_count,
      });
    } else {
      const approvalPath = activeSource
        ? '/api/web/projects/' + encodeURIComponent(entry.project.project_id) + '/chats/' + encodeURIComponent(entry.chat.chat_id) + '/formal-model/source/send-and-approve'
        : '/api/web/projects/' + encodeURIComponent(entry.project.project_id) + '/chats/' + encodeURIComponent(entry.chat.chat_id) + '/formal-model/plain/send-and-approve';
      const approvalPayload = {
        command_id: replay.sendCommandId,
        expected_chat_revision: replay.expectedChatRevision,
        content: query,
        ...(personalContext ? {personal_context: personalContext} : {}),
        ...(activeSource ? {source_ref_id: activeSource.source_ref_id} : {}),
      };
      approved = await runtimeJson('POST', approvalPath, approvalPayload);
      expectedStatus = activeSource ? 'APPROVED_SOURCE_INITIAL_JOB' : 'APPROVED_PLAIN_INITIAL_JOB';
      expectedTrigger = activeSource
        ? 'EXPLICIT_SOURCE_SEND_AND_APPROVE_ONE_GENERATION_CLICK'
        : 'EXPLICIT_SEND_AND_APPROVE_ONE_GENERATION_CLICK';
    }

    if (
      approved.status !== expectedStatus ||
      approved.project_context_policy !== projectContextPolicy ||
      approved.human_action_trigger !== expectedTrigger ||
      approved.provider_called !== false ||
      approved.network_called !== false ||
      approved.model_called !== false ||
      approved.secret_read !== false ||
      approved.grant_created !== false ||
      approved.attempt_claim_created !== false
    ) {
      throw new Error('RUNTIME_PREEXECUTION_APPROVAL_CEILING_MISMATCH');
    }
    const expectedSourceRefs = activeSource ? [activeSource.source_ref_id] : [];
    if (
      !approved.event ||
      approved.event.event_type !== 'USER_MESSAGE' ||
      approved.event.actor_class !== 'USER' ||
      approved.event.content !== query ||
      !Array.isArray(approved.event.related_source_ref_ids) ||
      JSON.stringify(approved.event.related_source_ref_ids) !== JSON.stringify(expectedSourceRefs) ||
      (activeSource && approved.source_ref_id !== activeSource.source_ref_id)
    ) {
      throw new Error('RUNTIME_APPROVED_USER_EVENT_MISMATCH');
    }
    if (replay.regeneratePlain === true) {
      if (
        !replay.turnState.runtime_user_event_id ||
        replay.turnState.runtime_user_event_id === approved.event.event_id
      ) {
        throw new Error('PLAIN_REGENERATE_RUNTIME_USER_EVENT_NOT_FRESH');
      }
    } else if (
      replay.turnState.runtime_user_event_id &&
      replay.turnState.runtime_user_event_id !== approved.event.event_id
    ) {
      throw new Error('FAILED_RETRY_RUNTIME_USER_EVENT_MISMATCH');
    }
    replay.turnState.runtime_user_event_id = approved.event.event_id;
    if (personalContext) {
      const binding = approved.personal_context_binding;
      if (
        approved.personal_context_sha256 !== personalContextSha256 ||
        !binding ||
        binding.artifact_sha256 !== personalContextSha256 ||
        !/^[0-9a-f]{64}$/.test(String(binding.artifact_identity_sha256 || '')) ||
        !Number.isInteger(binding.artifact_revision) || binding.artifact_revision < 1
      ) {
        throw new Error('RUNTIME_PERSONAL_CONTEXT_BINDING_MISMATCH');
      }
    } else if (approved.personal_context_sha256 != null || approved.personal_context_binding != null) {
      throw new Error('RUNTIME_PERSONAL_CONTEXT_UNEXPECTED');
    }

    entry.chat = approved.chat;

    const streamResponse = await fetch(
      RUNTIME +
        `/api/web/projects/${encodeURIComponent(entry.project.project_id)}` +
        `/chats/${encodeURIComponent(entry.chat.chat_id)}/formal-model/stream`,
      {
        method:'POST',
        headers:{
          'Content-Type':'application/json',
          'Accept':'text/event-stream',
          'X-UR-Runtime-Proxy':RUNTIME_PROXY_KEY,
        },
        body:JSON.stringify({
          command_id:stableId('final-shell-stream', shellId, messageId),
          job_id:approved.job_id,
          decision_request_event_id:approved.decision_request_event_id,
          project_context_policy:projectContextPolicy,
        }),
      },
    );
    if (!streamResponse.ok || !streamResponse.body) {
      throw new Error('RUNTIME_STREAM_HTTP_' + streamResponse.status);
    }

    res.writeHead(200, {
      'Content-Type':'text/event-stream',
      'Cache-Control':'no-cache',
      'Connection':'keep-alive',
      'X-Accel-Buffering':'no',
    });
    responseStarted = true;
    sendSse(res, {
      id:'chatcmpl-ur-daily-r001',
      object:'chat.completion.chunk',
      created:Math.floor(Date.now()/1000),
      model:MODEL,
      choices:[{index:0,delta:{role:'assistant'},finish_reason:null}],
    });

    let final = null;
    cancelled = null;
    let runtimeError = null;
    const decoder = new TextDecoder('utf-8');
    const parser = parseRuntimeSse(async (eventName, data) => {
      if (eventName === 'open') {
        if (
          data.project_id !== entry.project.project_id ||
          data.chat_id !== entry.chat.chat_id ||
          data.job_id !== approved.job_id ||
          data.decision_request_event_id !== approved.decision_request_event_id ||
          typeof data.execution_instance_id !== 'string' ||
          !data.execution_instance_id
        ) {
          throw new Error('RUNTIME_STREAM_OPEN_IDENTITY_MISMATCH');
        }
        runtimeExecutionInstanceId = data.execution_instance_id;
        await requestRuntimeStopForDownstreamClose();
      } else if (eventName === 'delta') {
        const text = String(data.text || '');
        if (!text) throw new Error('RUNTIME_DELTA_EMPTY');
        visible += text;
        if (!downstreamClosed) sendSse(res, openAIChunk(text, null));
      } else if (eventName === 'final') {
        runtimeTerminalSeen = true;
        final = data;
      } else if (eventName === 'cancelled') {
        runtimeTerminalSeen = true;
        cancelled = data;
        if (
          !approved ||
          !approved.job_bundle_binding ||
          !approved.web_formal_job_intake_binding ||
          !replay.turnState.runtime_user_event_id ||
          !data ||
          !data.cancellation_receipt_binding
        ) {
          throw new Error('RUNTIME_CANCEL_RETRY_LINEAGE_SHAPE_MISMATCH');
        }
        replay.turnState.cancelled_retry_lineage = {
          predecessor_job_id: approved.job_id,
          predecessor_job_bundle_binding: approved.job_bundle_binding,
          predecessor_web_formal_job_intake_binding: approved.web_formal_job_intake_binding,
          predecessor_cancellation_outcome_binding: data.cancellation_receipt_binding,
          initiating_user_event_id: replay.turnState.runtime_user_event_id,
        };
        log({
          event:'runtime_stop_cancelled_terminal',
          shell_id:shellId,
          message_id:messageId,
          job_id:data && data.job_id,
          execution_instance_id:runtimeExecutionInstanceId,
          cancellation:data,
        });
      } else if (eventName === 'error') {
        runtimeTerminalSeen = true;
        runtimeError = data;
      }
    });

    for await (const chunk of streamResponse.body) {
      await parser.push(decoder.decode(chunk, {stream:true}));
    }
    await parser.end(decoder.decode());

    if (runtimeError) throw new Error('RUNTIME_STREAM_ERROR:' + JSON.stringify(runtimeError));
    if (cancelled) throw new Error('RUNTIME_STREAM_CANCELLED:' + JSON.stringify(cancelled));
    if (!final || typeof final.assistant_text !== 'string' || !final.assistant_text) {
      throw new Error('RUNTIME_STREAM_FINAL_MISSING');
    }
    if (visible !== final.assistant_text) throw new Error('RUNTIME_VISIBLE_FINAL_MISMATCH');

    const canonical = await canonicalVerify(entry, final);
    entry.chat.chat_revision = final.chat_revision;
    entry.chat.head_event_id = final.head_event_id;
    entry.completed_message_ids.add(messageId);
    replay.turnState.completed = true;
    replay.turnState.assistant_event_id = canonical.event_id;
    replay.turnState.job_id = final.job_id;
    replay.turnState.expected_chat_revision = final.chat_revision;
    replay.turnState.cancelled_retry_lineage = null;

    finishSse(res);
    log({
      event:'daily_chat_completed',
      shell_id:shellId,
      message_id:messageId,
      project_id:entry.project.project_id,
      project_context_policy:projectContextPolicy,
      runtime_chat_id:entry.chat.chat_id,
      job_id:final.job_id,
      assistant_event_id:canonical.event_id,
      assistant_sha256:hash(final.assistant_text),
    });
  } catch (e) {
    const userCancelled = Boolean(cancelled && downstreamClosed && runtimeStopIssued);
    if (!userCancelled) entry.failed_message_ids.add(messageId);
    log({
      event:userCancelled ? 'daily_chat_cancelled' : 'daily_chat_stop',
      shell_id:shellId,
      message_id:messageId,
      runtime_stop_issued:runtimeStopIssued,
      error:String(e && e.stack || e),
    });
    if (!responseStarted) {
      res.writeHead(409, {'Content-Type':'application/json','Cache-Control':'no-store'});
      res.end(JSON.stringify({error:{message:String(e && e.message || e), retry_allowed:false}}));
    } else if (!res.writableEnded && !res.destroyed) {
      terminateSseFailure(res, e && e.message ? e.message : 'RUNTIME_OR_CANONICAL_FAILURE');
    }
  } finally {
    res.removeListener('close', onDownstreamClose);
    entry.active_message_id = null;
  }
}

async function handleProjectRetirement(req, res, action) {
  const nativeId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  if (!nativeId) { const e = new Error('RUNTIME_PROJECT_ID_REQUIRED'); e.status = 400; throw e; }
  const binding = buildBindingDescriptor('c5-native-project-retirement', nativeId);
  const query = new URLSearchParams({
    command_id: binding.project_command_id,
    display_name: binding.project_display_name,
  });
  const resolved = await runtimeJsonResult(
    'GET', '/api/web/project-retirement/resolve?' + query.toString()
  );
  if (!resolved.ok) return sendRuntimeJsonResult(res, resolved);
  if (action === 'get' &&
      resolved.body?.found === false &&
      resolved.body?.native_only_verified === true &&
      typeof resolved.body?.project_id === 'string') {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify({found:false,native_only_verified:true}));
  }
  if (resolved.body?.found !== true || typeof resolved.body?.project_id !== 'string') {
    const e = new Error('RUNTIME_PROJECT_SCOPE_NOT_RESOLVED'); e.status = 409; throw e;
  }
  if (action === 'get') {
    res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
    return res.end(JSON.stringify({
      found:true,
      status:resolved.body.status,
      project_revision:resolved.body.project_revision,
      retirement:resolved.body.retirement || null,
    }));
  }
  const body = await readJsonBody(req,4096);
  if (!body || typeof body.retirement_id !== 'string' || !body.retirement_id) {
    const e = new Error('RETIREMENT_ID_REQUIRED'); e.status = 400; throw e;
  }
  if (action === 'prepare' &&
      (!Number.isInteger(body.expected_project_revision) ||
       body.expected_project_revision < 1)) {
    const e = new Error('EXPECTED_PROJECT_REVISION_REQUIRED'); e.status = 400; throw e;
  }
  const result = await runtimeJsonResult(
    'POST', '/api/web/projects/' +
      encodeURIComponent(resolved.body.project_id) +
      '/retirement/' + action, body
  );
  return sendRuntimeJsonResult(res,result);
}



async function handleC5RuntimeCanonicalProjectReferences(req,res) {
  const nativeId=normalizeOptionalProjectId(header(req,'x-librechat-project-id'));
  const actor=header(req,'x-librechat-authenticated-user-id');
  if (!nativeId || !/^[a-f0-9]{24}$/i.test(actor)) {
    const e=new Error('C5_NATIVE_PROJECT_ACTOR_REQUIRED');e.status=400;throw e;
  }
  const binding=buildBindingDescriptor('c5-native-project-retirement',nativeId);
  const params=new URLSearchParams({
    command_id:binding.project_command_id,
    display_name:binding.project_display_name,
  });
  const resolvePath='/api/web/project-retirement/resolve?'+params.toString();
  const first=await runtimeJsonResult('GET',resolvePath);
  if(!first.ok) return sendRuntimeJsonResult(res,first);
  const resolved=first.body;
  if(resolved?.found!==true || typeof resolved.project_id!=='string') {
    const e=new Error('C5_RUNTIME_PROJECT_NOT_CANONICAL');e.status=409;throw e;
  }
  const canonicalPath='/api/web/projects/'+encodeURIComponent(resolved.project_id);
  // Normal Runtime resume and memory routes deliberately refuse RETIRED
  // Projects; use the exact existing-owner C5 read-only retired inventory.
  // No new Runtime project creation, cross-project FileID guess, or mutation.
  const runtime=await runtimeJsonResult('GET',
    canonicalPath+'/c5-reference-inventory');
  if(!runtime.ok) return sendRuntimeJsonResult(res,runtime);
  const second=await runtimeJsonResult('GET',resolvePath);
  if(!second.ok) return sendRuntimeJsonResult(res,second);
  if(second.body?.found!==true ||
    second.body.project_id!==resolved.project_id ||
    second.body.project_revision!==resolved.project_revision ||
    second.body.status!==resolved.status) {
    const e=new Error('C5_RUNTIME_PROJECT_CHANGED_DURING_REFERENCE_READ');
    e.status=409;throw e;
  }
  const snapshot=captureCurrentProjectRuntimeReferences({
    nativeProjectId:nativeId,actorId:actor,resolved,
    resumed:runtime.body,memory:runtime.body?.memory,
  });
  res.writeHead(200,{
    'Content-Type':'application/json','Cache-Control':'no-store',
  });
  return res.end(JSON.stringify(snapshot));
}
// C5 whole Project cascade receipt: use the existing one Adapter -> Runtime
// authenticated internal channel. No second DB, executor, worker or proxy.
// The originating LibreChat Project owner must be verified in the server route;
// Adapter then binds the same project and actor to the Runtime receipt owner.
async function handleC5CascadeReceipt(req, res) {
  const nativeId = normalizeOptionalProjectId(header(req, 'x-librechat-project-id'));
  const actor = header(req, 'x-librechat-authenticated-user-id');
  if (!nativeId || !/^[a-f0-9]{24}$/i.test(actor)) {
    const e = new Error('C5_NATIVE_PROJECT_AND_ACTOR_REQUIRED');
    e.status = 400; throw e;
  }
  const binding = buildBindingDescriptor('c5-native-project-retirement', nativeId);
  const params = new URLSearchParams({
    command_id: binding.project_command_id,
    display_name: binding.project_display_name,
  });
  const status = await runtimeJsonResult(
    'GET', '/api/web/project-retirement/resolve?' + params.toString()
  );
  if (!status.ok) return sendRuntimeJsonResult(res, status);
  if (status.body?.found !== true ||
      typeof status.body?.project_id !== 'string') {
    const e = new Error('C5_CANONICAL_RUNTIME_PROJECT_NOT_VERIFIED');
    e.status = 409; throw e;
  }
  let payload;
  if (req.method === 'POST') {
    payload = await readJsonBody(req, 256 * 1024);
    if (payload?.projectId !== nativeId || payload?.ownerId !== actor) {
      const e = new Error('C5_RECEIPT_OWNER_AND_PROJECT_SCOPE_INVALID');
      e.status = 409; throw e;
    }
  }
  const result = await runtimeJsonResult(
    req.method,
    '/api/web/projects/' + encodeURIComponent(nativeId) + '/cascade-receipt',
    payload,
    {'X-LibreChat-Authenticated-User-ID': actor}
  );
  return sendRuntimeJsonResult(res, result);
}
const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/v1/models') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      const health = await runtimeJson('GET','/api/health');
      res.writeHead(200, {'Content-Type':'application/json','Cache-Control':'no-store'});
      return res.end(JSON.stringify({
        object:'list',
        data:[{id:MODEL,object:'model',owned_by:'universal-runtime'}],
        runtime_health:health,
      }));
    }




    if (req.url === '/v1/runtime-project-c5-source-ref-inventory') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method !== 'GET') {
        res.writeHead(405, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'method not allowed'}}));
      }
      return await handleC5RuntimeCanonicalProjectReferences(req,res);
    }
    if (req.url === '/v1/runtime-project-cascade-receipt') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method !== 'GET' && req.method !== 'POST') {
        res.writeHead(405, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'method not allowed'}}));
      }
      return await handleC5CascadeReceipt(req,res);
    }

    if (req.url === '/v1/runtime-project-retirement' ||
        /^\/v1\/runtime-project-retirement\/(prepare|confirm|abort|commit)$/.test(req.url)) {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      const action = req.url === '/v1/runtime-project-retirement'
        ? 'get' : req.url.split('/').pop();
      if ((action === 'get' && req.method !== 'GET') ||
          (action !== 'get' && req.method !== 'POST')) {
        res.writeHead(405, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'method not allowed'}}));
      }
      return await handleProjectRetirement(req,res,action);
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-project-instructions') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectInstructionsGet(req, res);
    }
    if (req.method === 'PUT' && req.url === '/v1/runtime-project-instructions') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectInstructionsPut(req, res);
    }

    if (req.url === '/v1/runtime-project-context-policy') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method === 'GET') {
        return await handleProjectContextPolicyGet(req, res);
      }
      if (req.method === 'PUT') {
        return await handleProjectContextPolicyPut(req, res);
      }
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-project-memory/context') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectMemoryContextGet(req, res);
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-project-library') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectLibraryGet(req, res);
    }

    if (req.method === 'POST' && req.url === '/v1/runtime-project-library/document-bundle') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectLibraryDocumentBundle(req, res);
    }

    if (req.method === 'POST' && req.url === '/v1/runtime-project-source-search') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectSourceSearch(req, res);
    }

    if (req.method === 'POST' && req.url === '/v1/runtime-project-library/from-message') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectLibrarySaveFromMessage(req, res);
    }
    const runtimeProjectLibraryRemoveMatch =
      /^\/v1\/runtime-project-library\/source\/([^/?]+)\/remove$/.exec(req.url);
    if (req.method === 'POST' && runtimeProjectLibraryRemoveMatch) {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      let sourceRefId;
      try { sourceRefId = decodeURIComponent(runtimeProjectLibraryRemoveMatch[1]); }
      catch (_) { const e = new Error('RUNTIME_SOURCE_REF_ID_INVALID'); e.status = 400; throw e; }
      return await handleProjectLibraryRemove(req, res, sourceRefId);
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-promoted-packs') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handlePromotedPackCatalogGet(req, res);
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-user-installable-packs') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleUserInstallablePackCatalogGet(req, res);
    }

    if (req.url === '/v1/runtime-user-pack-install') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method === 'POST') {
        return await handleUserPackInstallMutation(req, res, 'install');
      }
      if (req.method === 'DELETE') {
        return await handleUserPackInstallMutation(req, res, 'uninstall');
      }
    }

    if (req.url === '/v1/runtime-project-pack-binding') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method === 'GET') {
        return await handleProjectPackBindingGet(req, res);
      }
      if (req.method === 'PUT') {
        return await handleProjectPackBindingMutation(req, res, 'bind');
      }
      if (req.method === 'DELETE') {
        return await handleProjectPackBindingMutation(req, res, 'unbind');
      }
    }


    if (req.method === 'GET' && req.url === '/v1/runtime-project-local-work-binding') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectLocalWorkBindingGet(req, res);
    }

    if (req.url === '/v1/runtime-project-assistant-profile') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      if (req.method === 'GET') {
        return await handleProjectAssistantProfileGet(req, res);
      }
      if (req.method === 'PUT') {
        return await handleProjectAssistantProfileMutation(req, res, 'bind');
      }
      if (req.method === 'DELETE') {
        return await handleProjectAssistantProfileMutation(req, res, 'unbind');
      }
    }

    if (req.method === 'GET' && req.url === '/v1/runtime-project-memory') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectMemoryGet(req, res);
    }
    if (req.method === 'POST' && req.url === '/v1/runtime-project-memory') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleProjectMemoryCreate(req, res);
    }
    const runtimeProjectMemoryMatch = /^\/v1\/runtime-project-memory\/([^/?]+?)(\/enabled)?$/.exec(req.url);
    if (runtimeProjectMemoryMatch) {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      let memoryId;
      try { memoryId = decodeURIComponent(runtimeProjectMemoryMatch[1]); }
      catch (_) { const e = new Error('RUNTIME_PROJECT_MEMORY_ID_INVALID'); e.status = 400; throw e; }
      if (req.method === 'PUT' && !runtimeProjectMemoryMatch[2]) {
        return await handleProjectMemoryItemMutation(req, res, memoryId, 'revise');
      }
      if (req.method === 'POST' && runtimeProjectMemoryMatch[2] === '/enabled') {
        return await handleProjectMemoryItemMutation(req, res, memoryId, 'enabled');
      }
      if (req.method === 'DELETE' && !runtimeProjectMemoryMatch[2]) {
        return await handleProjectMemoryItemMutation(req, res, memoryId, 'delete');
      }
    }

    if (req.method === 'POST' && req.url === '/v1/runtime-document') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleRuntimeDocument(req, res);
    }
    if (req.method === 'GET' && req.url === '/v1/runtime-document/status') {
      if (!authOk(req)) {
        res.writeHead(401, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({error:{message:'unauthorized'}}));
      }
      return await handleRuntimeDocumentStatus(req, res);
    }

    if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
      res.writeHead(404, {'Content-Type':'application/json'});
      return res.end(JSON.stringify({error:{message:'not found'}}));
    }
    if (!authOk(req)) {
      res.writeHead(401, {'Content-Type':'application/json'});
      return res.end(JSON.stringify({error:{message:'unauthorized'}}));
    }
    const body = await readJsonBody(req, nativeFileSource.MAX_CHAT_JSON_BYTES);
    await handleCompletion(req, res, body);
  } catch (e) {
    log({event:'adapter_request_error', error:String(e && e.stack || e)});
    if (!res.headersSent) {
      const status = Number(e && e.status) || 500;
      res.writeHead(status, {'Content-Type':'application/json','Cache-Control':'no-store'});
      res.end(JSON.stringify({error:{message:String(e && e.message || e), retry_allowed:false}}));
    } else if (!res.writableEnded && !res.destroyed) {
      terminateSseFailure(res, e && e.message ? e.message : 'RUNTIME_OR_CANONICAL_FAILURE');
    }
  }
});

if (require.main === module) {
  server.listen(PORT, '0.0.0.0', async () => {
    try {
      const health = await runtimeJson('GET','/api/health');
      log({event:'ready', port:PORT, runtime_base:RUNTIME, runtime_health:health});
    } catch (e) {
      log({event:'runtime_health_failed', error:String(e && e.stack || e)});
      process.exit(22);
    }
  });
}

module.exports = {
  MEMORY_INSTRUCTIONS,
  MEMORY_MARKER,
  MEMORY_PREFIX,
  PERSONAL_CONTEXT_SCHEMA,
  PERSONAL_CONTEXT_AUTHORITY_CLASS,
  PERSONAL_CONTEXT_SOURCE_CLASS,
  PERSONAL_CONTEXT_CURRENTNESS_CLASS,
  PERSONAL_CONTEXT_PERSISTENCE_CLASS,
  PERSONAL_CONTEXT_MAX_BYTES,
  PROJECT_CONTEXT_POLICY_PROJECT_ONLY,
  PROJECT_CONTEXT_POLICY_PLUS_GLOBAL_USER_MEMORY,
  PROJECT_CONTEXT_POLICY_DEFAULT,
  isAllowedRuntimeUrl,
  projectContextPolicyMutationCommand,
  applyProjectContextPolicyMutation,
  effectivePersonalContextForPolicy,
  projectContextPolicyPresentation,
  emptyProjectContextPolicyPresentation,
  projectMemoryContextPresentation,
  emptyProjectMemoryContextPresentation,
  isValidAssistantProfileBinding,
  projectAssistantProfilePresentation,
  emptyProjectAssistantProfilePresentation,
  projectLibraryProjection,
  projectSourceSearchPresentation,
  projectSourceRegistryContextSha,
  PROJECT_SOURCE_SEARCH_MAX_RESULTS,
  PROJECT_SOURCE_SEARCH_MAX_RESULT_CHARS,
  validateChatOutputSaveBody,
  ensureRuntimeProjectForLibreChatProject,
  canonicalJson,
  canonicalSha256,
  validateWithoutKeysMemoryText,
  extractPersonalContext,
};
