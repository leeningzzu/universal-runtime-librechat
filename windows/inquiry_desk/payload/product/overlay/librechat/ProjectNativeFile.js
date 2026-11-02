'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { v4 } = require('uuid');
const { FileContext, FileSources } = require('librechat-data-provider');
const { sanitizeFilename, getStorageMetadata } = require('@librechat/api');
const { getStrategyFunctions } = require('~/server/services/Files/strategies');
const { processDeleteRequest } = require('~/server/services/Files/process');
const { getFileStrategy } = require('~/server/utils/getFileStrategy');
const db = require('~/models');

const PROJECT_FILE_METADATA_SCHEMA = 'LC_PROJECT_NATIVE_FILE_METADATA_R001';
const PROJECT_FILE_CATALOG_SCHEMA = 'LC_PROJECT_NATIVE_FILE_CATALOG_R001';
const MAX_PROJECT_NATIVE_FILES = 2000;
const MAX_PROJECT_CHAT_ATTACHMENT_MESSAGES = 5000;

function ownerId(req) {
  return String(req?.user?.id ?? req?.user?._id ?? '');
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function boundedMetadata(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function projectSourceRefs(metadata) {
  const rows = boundedMetadata(metadata).projectSourceRefs;
  if (!Array.isArray(rows)) {
    return [];
  }
  const seen = new Set();
  return rows.filter((row) => {
    if (
      !row ||
      typeof row !== 'object' ||
      typeof row.librechat_project_id !== 'string' ||
      typeof row.runtime_project_id !== 'string' ||
      typeof row.source_ref_id !== 'string'
    ) {
      return false;
    }
    const key = `${row.librechat_project_id}\u0000${row.runtime_project_id}\u0000${row.source_ref_id}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function retiredProjectSourceRefs(metadata) {
  const rows = boundedMetadata(metadata).retiredProjectSourceRefs;
  if (!Array.isArray(rows)) {
    return [];
  }
  const seen = new Set();
  return rows.filter((row) => {
    if (
      !row ||
      typeof row !== 'object' ||
      typeof row.librechat_project_id !== 'string' ||
      typeof row.runtime_project_id !== 'string' ||
      typeof row.source_ref_id !== 'string' ||
      typeof row.detached_at_utc !== 'string' ||
      row.binding_class !== 'EXACT_NATIVE_FILE_SOURCE_REF'
    ) {
      return false;
    }
    const key = `${row.librechat_project_id}\u0000${row.runtime_project_id}\u0000${row.source_ref_id}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function mergeRetiredProjectSourceRefs(metadata, additions) {
  const existing = retiredProjectSourceRefs(metadata);
  return retiredProjectSourceRefs({ retiredProjectSourceRefs: [...existing, ...additions] });
}

function projectFileMetadata(metadata, patch = {}) {
  return {
    ...boundedMetadata(metadata),
    schema: PROJECT_FILE_METADATA_SCHEMA,
    projectLibraryFile: true,
    ...patch,
  };
}

function localPathForFile(req, file) {
  const userId = ownerId(req);
  if (!userId || file?.source !== FileSources.local || typeof file?.filepath !== 'string') {
    return null;
  }
  const prefix = `/uploads/${userId}/`;
  if (!file.filepath.startsWith(prefix)) {
    return null;
  }
  const relative = file.filepath.slice(prefix.length);
  if (!relative || relative.includes('\0')) {
    return null;
  }
  const root = path.resolve(req.config.paths.uploads, userId);
  const candidate = path.resolve(root, relative);
  const rel = path.relative(root, candidate);
  if (rel.startsWith('..') || path.isAbsolute(rel) || rel.includes(`..${path.sep}`)) {
    return null;
  }
  return candidate;
}

async function readOwnedNativeFile(req, fileId) {
  const userId = ownerId(req);
  if (!userId || typeof fileId !== 'string' || !fileId) {
    const error = new Error('PROJECT_NATIVE_FILE_ID_INVALID');
    error.status = 400;
    throw error;
  }
  const file = await db.findFileById(fileId);
  if (!file || String(file.user) !== userId) {
    const error = new Error('PROJECT_NATIVE_FILE_NOT_FOUND');
    error.status = 404;
    throw error;
  }
  const physicalPath = localPathForFile(req, file);
  if (!physicalPath) {
    const error = new Error('PROJECT_NATIVE_FILE_LOCAL_BYTES_UNAVAILABLE');
    error.status = 409;
    throw error;
  }
  let bytes;
  try {
    bytes = await fs.promises.readFile(physicalPath);
  } catch (cause) {
    const error = new Error(cause?.code === 'ENOENT' ? 'PROJECT_NATIVE_FILE_BYTES_MISSING' : 'PROJECT_NATIVE_FILE_READ_FAILED');
    error.status = cause?.code === 'ENOENT' ? 409 : 500;
    throw error;
  }
  if (Number.isInteger(file.bytes) && file.bytes >= 0 && bytes.length !== file.bytes) {
    const error = new Error('PROJECT_NATIVE_FILE_SIZE_MISMATCH');
    error.status = 409;
    throw error;
  }
  return { file, bytes, physicalPath };
}

function isMissingLocalStorageError(error) {
  return error?.code === 'ENOENT' || /not found|does not exist|no such file/i.test(String(error?.message ?? ''));
}

async function compensateNativeProjectFilePersistence({
  req,
  fileId,
  filepath,
  filename,
  storageMetadata,
  deleteFile,
}) {
  let databaseCleared = false;
  let storageCleared = false;
  try {
    const existing = await db.findFileById(fileId);
    if (existing) {
      await db.deleteFiles([fileId]);
    }
    databaseCleared = (await db.findFileById(fileId)) == null;
  } catch (_) {
    databaseCleared = false;
  }

  try {
    if (typeof deleteFile !== 'function') {
      throw new Error('PROJECT_NATIVE_FILE_STORAGE_DELETE_UNAVAILABLE');
    }
    await deleteFile(req, {
      file_id: fileId,
      filepath,
      ...storageMetadata,
      filename,
      source: FileSources.local,
    });
    storageCleared = true;
  } catch (error) {
    storageCleared = isMissingLocalStorageError(error);
  }

  const physicalPath = localPathForFile(req, { source: FileSources.local, filepath });
  if (physicalPath) {
    try {
      await fs.promises.access(physicalPath);
      storageCleared = false;
    } catch (error) {
      storageCleared = error?.code === 'ENOENT' && storageCleared;
    }
  }
  return databaseCleared && storageCleared;
}

async function persistNativeProjectFile({ req, filename, mediaType, bytes, projectId }) {
  const userId = ownerId(req);
  if (!userId || !Buffer.isBuffer(bytes) || bytes.length < 1) {
    const error = new Error('PROJECT_NATIVE_FILE_INPUT_INVALID');
    error.status = 400;
    throw error;
  }
  const nativeStrategy = getFileStrategy(req.config, { isImage: false });
  if (nativeStrategy !== FileSources.local) {
    const error = new Error('PROJECT_NATIVE_FILE_REQUIRES_LOCAL_NATIVE_STORAGE');
    error.status = 503;
    throw error;
  }
  const safeName = sanitizeFilename(filename);
  if (!safeName || safeName.length > 255) {
    const error = new Error('PROJECT_NATIVE_FILE_NAME_INVALID');
    error.status = 400;
    throw error;
  }
  const fileId = v4();
  const storageName = `${fileId}__${safeName}`;
  const { saveBuffer, deleteFile } = getStrategyFunctions(FileSources.local);
  if (typeof saveBuffer !== 'function') {
    const error = new Error('PROJECT_NATIVE_FILE_STORAGE_WRITE_UNAVAILABLE');
    error.status = 503;
    throw error;
  }

  let filepath = null;
  let storageMetadata = {};
  let storageCommitted = false;
  try {
    filepath = await saveBuffer({
      userId,
      buffer: bytes,
      fileName: storageName,
      basePath: 'uploads',
      tenantId: req.user?.tenantId,
    });
    storageCommitted = true;
    if (typeof filepath !== 'string' || !filepath.startsWith(`/uploads/${userId}/`)) {
      const error = new Error('PROJECT_NATIVE_FILE_STORAGE_RESULT_INVALID');
      error.status = 500;
      throw error;
    }
    storageMetadata = getStorageMetadata({ filepath, source: FileSources.local });
    const record = await db.createFile(
      {
        user: userId,
        file_id: fileId,
        bytes: bytes.length,
        filepath,
        ...storageMetadata,
        filename: safeName,
        context: FileContext.unknown,
        type: mediaType,
        embedded: false,
        source: FileSources.local,
        tenantId: req.user?.tenantId,
        metadata: projectFileMetadata({}, {
          nativeSha256: sha256(bytes),
          origin: 'PROJECT_UPLOAD',
          pendingLibreChatProjectId: projectId,
          projectSourceRefs: [],
        }),
      },
      true,
    );
    if (!record || record.file_id !== fileId || String(record.user) !== userId) {
      const error = new Error('PROJECT_NATIVE_FILE_DATABASE_COMMIT_INVALID');
      error.status = 500;
      throw error;
    }
    return record;
  } catch (cause) {
    if (storageCommitted) {
      const rolledBack =
        typeof filepath === 'string' &&
        (await compensateNativeProjectFilePersistence({
          req,
          fileId,
          filepath,
          filename: safeName,
          storageMetadata,
          deleteFile,
        }));
      if (!rolledBack) {
        const error = new Error('PROJECT_NATIVE_FILE_PERSISTENCE_OUTCOME_UNKNOWN');
        error.status = 500;
        error.retryAutomatically = false;
        throw error;
      }
    }
    throw cause;
  }
}
async function deleteNativeFileOrThrow({ req, file }) {
  if (
    !req || !file || typeof file.file_id !== 'string' || !file.file_id
    || typeof file.filepath !== 'string' || !file.filepath
  ) {
    const error = new Error('PROJECT_NATIVE_FILE_DELETE_SCOPE_INVALID');
    error.status = 400;
    throw error;
  }
  const result = await processDeleteRequest({ req: { ...req, body: {} }, files: [file] });
  if (
    !result ||
    !Array.isArray(result.deletedFileIds) ||
    !result.deletedFileIds.includes(file.file_id) ||
    (Array.isArray(result.failedFileIds) && result.failedFileIds.length > 0)
  ) {
    const error = new Error('PROJECT_NATIVE_FILE_ROLLBACK_UNVERIFIED');
    error.status = 500;
    throw error;
  }
}

async function bindNativeFileToSource({ file, userId, libreChatProjectId, runtimeProjectId, sourceRefId }) {
  if (!file || String(file.user) !== userId) {
    throw new Error('PROJECT_NATIVE_FILE_OWNER_CHANGED');
  }
  const exactReference = {
    librechat_project_id: libreChatProjectId,
    runtime_project_id: runtimeProjectId,
    source_ref_id: sourceRefId,
  };
  const existing = projectSourceRefs(file.metadata);
  const next = projectSourceRefs({ projectSourceRefs: [...existing, exactReference] });
  const retired = retiredProjectSourceRefs(file.metadata).filter(
    (row) =>
      row.librechat_project_id !== exactReference.librechat_project_id ||
      row.runtime_project_id !== exactReference.runtime_project_id ||
      row.source_ref_id !== exactReference.source_ref_id,
  );
  const updated = await db.updateFile(
    {
      file_id: file.file_id,
      metadata: projectFileMetadata(file.metadata, {
        pendingLibreChatProjectId: null,
        projectSourceRefs: next,
        retiredProjectSourceRefs: retired,
      }),
    },
    { user: userId },
  );
  if (!updated) {
    throw new Error('PROJECT_NATIVE_FILE_SOURCE_BINDING_FAILED');
  }
  const readBack = await db.findFileById(file.file_id);
  const exactPersisted = projectSourceRefs(readBack?.metadata).some(
    (reference) =>
      reference.librechat_project_id === exactReference.librechat_project_id &&
      reference.runtime_project_id === exactReference.runtime_project_id &&
      reference.source_ref_id === exactReference.source_ref_id,
  );
  if (
    !readBack ||
    String(readBack.user) !== userId ||
    !exactPersisted ||
    readBack.metadata?.pendingLibreChatProjectId != null
  ) {
    throw new Error('PROJECT_NATIVE_FILE_SOURCE_BINDING_READBACK_FAILED');
  }
  return readBack;
}
async function unbindNativeFileSource({ userId, sourceRefId }) {
  const files = await db.getFiles({ user: userId }, null, { text: 0 });
  for (const file of files ?? []) {
    const refs = projectSourceRefs(file.metadata);
    if (!refs.some((row) => row.source_ref_id === sourceRefId)) {
      continue;
    }
    const detachedAt = new Date().toISOString();
    const removed = refs
      .filter((row) => row.source_ref_id === sourceRefId)
      .map((row) => ({ ...row, binding_class: 'EXACT_NATIVE_FILE_SOURCE_REF', detached_at_utc: detachedAt }));
    const updated = await db.updateFile(
      {
        file_id: file.file_id,
        metadata: projectFileMetadata(file.metadata, {
          projectSourceRefs: refs.filter((row) => row.source_ref_id !== sourceRefId),
          retiredProjectSourceRefs: mergeRetiredProjectSourceRefs(file.metadata, removed),
        }),
      },
      { user: userId },
    );
    if (!updated) {
      throw new Error('PROJECT_NATIVE_FILE_SOURCE_UNBINDING_FAILED');
    }
    const readBack = await db.findFileById(file.file_id);
    if (
      !readBack ||
      String(readBack.user) !== userId ||
      projectSourceRefs(readBack.metadata).some((row) => row.source_ref_id === sourceRefId) ||
      !retiredProjectSourceRefs(readBack.metadata).some((row) => row.source_ref_id === sourceRefId)
    ) {
      throw new Error('PROJECT_NATIVE_FILE_SOURCE_UNBINDING_READBACK_FAILED');
    }
    return readBack;
  }
  return null;
}
async function unbindAllNativeFileSourcesForProject({ userId, libreChatProjectId }) {
  const files = await db.getFiles({ user: userId }, null, { text: 0 });
  let changed = 0;
  for (const file of files ?? []) {
    const refs = projectSourceRefs(file.metadata);
    const next = refs.filter(
      (reference) => reference.librechat_project_id !== libreChatProjectId,
    );
    if (next.length === refs.length) {
      continue;
    }
    const detachedAt = new Date().toISOString();
    const removed = refs
      .filter((row) => row.librechat_project_id === libreChatProjectId)
      .map((row) => ({ ...row, binding_class: 'EXACT_NATIVE_FILE_SOURCE_REF', detached_at_utc: detachedAt }));
    const updated = await db.updateFile(
      {
        file_id: file.file_id,
        metadata: projectFileMetadata(file.metadata, {
          projectSourceRefs: next,
          retiredProjectSourceRefs: mergeRetiredProjectSourceRefs(file.metadata, removed),
        }),
      },
      { user: userId },
    );
    if (!updated) {
      throw new Error('PROJECT_NATIVE_FILE_PROJECT_UNBINDING_FAILED');
    }
    changed += 1;
  }
  const after = await db.getFiles({ user: userId }, null, { text: 0 });
  const remaining = (after ?? []).filter((file) =>
    projectSourceRefs(file.metadata).some(
      (reference) => reference.librechat_project_id === libreChatProjectId,
    ),
  );
  if (remaining.length) {
    throw new Error('PROJECT_NATIVE_FILE_PROJECT_UNBINDING_UNVERIFIED');
  }
  return {
    schema: 'LC_PROJECT_NATIVE_FILE_PROJECT_UNBIND_R001',
    project_id: libreChatProjectId,
    updated_file_count: changed,
    remaining_reference_count: 0,
    verified: true,
  };
}

function filePresentation(req, file, supportsFilename) {
  const physicalPath = localPathForFile(req, file);
  let physicalStatus = 'UNSUPPORTED_STORAGE';
  if (physicalPath) {
    physicalStatus = fs.existsSync(physicalPath) ? 'AVAILABLE' : 'MISSING_BYTES';
  }
  const supported = supportsFilename(file.filename) === true;
  const refs = projectSourceRefs(file.metadata);
  return {
    file_id: file.file_id,
    filename: file.filename,
    bytes: Number.isInteger(file.bytes) ? file.bytes : null,
    native_sha256:
      typeof file.metadata?.nativeSha256 === 'string' && /^[0-9a-f]{64}$/.test(file.metadata.nativeSha256)
        ? file.metadata.nativeSha256
        : null,
    media_type: typeof file.type === 'string' ? file.type : null,
    source: file.source ?? FileSources.local,
    status: !supported ? 'UNSUPPORTED_TYPE' : physicalStatus,
    supported,
    project_source_ref_count: refs.length,
    project_source_refs: refs,
    retired_project_source_ref_count: retiredProjectSourceRefs(file.metadata).length,
    retired_project_source_refs: retiredProjectSourceRefs(file.metadata),
    created_at: file.createdAt ?? null,
    modified_at: file.updatedAt ?? null,
  };
}

async function listOwnerNativeFiles({ req, supportsFilename }) {
  const userId = ownerId(req);
  const files = await db.getFiles({ user: userId }, null, { text: 0 });
  const eligible = (files ?? [])
    .filter((file) => ![FileContext.agents, FileContext.assistants, FileContext.skill_file].includes(file.context))
    .slice(0, MAX_PROJECT_NATIVE_FILES)
    .map((file) => filePresentation(req, file, supportsFilename))
    .sort((left, right) => String(right.created_at ?? '').localeCompare(String(left.created_at ?? '')));
  return {
    schema: PROJECT_FILE_CATALOG_SCHEMA,
    authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION',
    file_count: eligible.length,
    files: eligible,
  };
}

function collectFileIds(value, output, depth = 0) {
  if (depth > 8 || value == null) {
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectFileIds(item, output, depth + 1);
    return;
  }
  if (typeof value !== 'object') {
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    if ((key === 'file_id' || key === 'fileId') && typeof item === 'string' && item) {
      output.add(item);
    } else if (typeof item === 'object' && item != null) {
      collectFileIds(item, output, depth + 1);
    }
  }
}

async function verifyProjectMessageFileReference({ userId, projectId, conversationId, messageId, fileId }) {
  const conversation = await db.getConvo(userId, conversationId);
  if (!conversation || conversation.chatProjectId !== projectId) {
    const error = new Error('PROJECT_CHAT_ATTACHMENT_SCOPE_MISMATCH');
    error.status = 409;
    throw error;
  }
  const message = await db.getMessage({ user: userId, messageId });
  if (!message || message.conversationId !== conversationId) {
    const error = new Error('PROJECT_CHAT_ATTACHMENT_MESSAGE_NOT_FOUND');
    error.status = 404;
    throw error;
  }
  const ids = new Set();
  collectFileIds(message.files, ids);
  if (!ids.has(fileId)) {
    const error = new Error('PROJECT_CHAT_ATTACHMENT_FILE_NOT_REFERENCED');
    error.status = 409;
    throw error;
  }
  return { conversation, message };
}

async function listProjectChatAttachmentCandidates({ req, projectId, supportsFilename }) {
  const userId = ownerId(req);
  const conversations = [];
  let cursor = null;
  for (let page = 0; page < 20; page += 1) {
    const result = await db.getConvosByCursor(userId, {
      cursor,
      limit: 100,
      isArchived: false,
      projectId,
      sortBy: 'updatedAt',
      sortDirection: 'desc',
    });
    conversations.push(...(result?.conversations ?? []));
    cursor = result?.nextCursor ?? null;
    if (!cursor) break;
  }
  const conversationIds = conversations.map((row) => row.conversationId).filter(Boolean);
  if (!conversationIds.length) {
    return { schema: 'LC_PROJECT_CHAT_FILE_CATALOG_R001', authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION', file_count: 0, files: [] };
  }
  const messages = await db.getMessages(
    {
      user: userId,
      conversationId: { $in: conversationIds },
      files: { $exists: true, $ne: [] },
    },
    'conversationId messageId files createdAt',
    { sort: { createdAt: -1 }, limit: MAX_PROJECT_CHAT_ATTACHMENT_MESSAGES },
  );
  const references = new Map();
  for (const message of messages ?? []) {
    const ids = new Set();
    collectFileIds(message.files, ids);
    for (const fileId of ids) {
      if (!references.has(fileId)) {
        references.set(fileId, {
          conversation_id: message.conversationId,
          message_id: message.messageId,
          message_created_at: message.createdAt ?? null,
        });
      }
    }
  }
  const ownerFiles = await db.getFiles({ user: userId }, null, { text: 0 });
  const byId = new Map((ownerFiles ?? []).map((file) => [file.file_id, file]));
  const rows = [];
  for (const [fileId, reference] of references.entries()) {
    const file = byId.get(fileId);
    if (!file) continue;
    rows.push({ ...filePresentation(req, file, supportsFilename), ...reference });
  }
  return {
    schema: 'LC_PROJECT_CHAT_FILE_CATALOG_R001',
    authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION',
    file_count: rows.length,
    files: rows,
  };
}

module.exports = {
  PROJECT_FILE_CATALOG_SCHEMA,
  ownerId,
  persistNativeProjectFile,
  deleteNativeFileOrThrow,
  readOwnedNativeFile,
  bindNativeFileToSource,
  unbindNativeFileSource,
  unbindAllNativeFileSourcesForProject,
  listOwnerNativeFiles,
  listProjectChatAttachmentCandidates,
  verifyProjectMessageFileReference,
  projectSourceRefs,
  retiredProjectSourceRefs,
};
