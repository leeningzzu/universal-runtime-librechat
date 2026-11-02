const express = require('express');
const crypto = require('crypto');
const mongoose = require('mongoose');
const { isValidObjectIdString } = require('@librechat/data-schemas');
const {
  bindProjectAssistantProfile,
  fetchProjectAssistantProfileBinding,
} = require('~/server/services/ProjectAssistantProfile');
const db = require('~/models');
const { resolveRequestTenantId } = require('@librechat/api');
const configMiddleware = require('~/server/middleware/config/app');
const { buildChatOutputSource } = require('~/server/services/ProjectSource');
const {
  PROJECT_SOURCE_ACCEPT,
  MAX_NATIVE_DOCUMENT_BYTES,
  buildNativeDocumentRuntimeBundle,
  nativeDocumentFormatForFilename,
  nativeDocumentFormatsCatalog,
  nativeDocumentMediaTypeAccepted,
} = require('./nativeProjectDocumentBundle');
const {
  persistNativeProjectFile,
  deleteNativeFileOrThrow,
  readOwnedNativeFile,
  bindNativeFileToSource,
  unbindNativeFileSource,
  listOwnerNativeFiles,
  listProjectChatAttachmentCandidates,
  verifyProjectMessageFileReference,
  projectSourceRefs,
  retiredProjectSourceRefs,
} = require('~/server/services/ProjectNativeFile');
const { requireNativeFileDeleteUnreferenced } = require('~/server/services/Files/nativeDeleteReferenceGuard');
const {
  CrossStorePermanentDeleteStop,
  fetchRuntimeSourceRetirementCandidates,
  buildCrossStoreRetirementPlan,
  executeCrossStorePermanentDelete,
  digestJson,
} = require('~/server/services/Files/crossStorePermanentDelete');
const router = express.Router();
const RUNTIME_ADAPTER_BASE = String(
  process.env.UR_RUNTIME_ADAPTER_BASE || 'http://ur-runtime-adapter:9000',
).replace(/\/$/, '');
const getUserId = (req) => req.user?.id ?? req.user?._id?.toString() ?? '';

const runtimeKey = () => String(process.env.UR_SHELL_ADAPTER_KEY || '');
const sourceSupported = (filename) => nativeDocumentFormatForFilename(filename) != null;

function runtimeErrorBody(raw, fallback) {
  try {
    const body = JSON.parse(raw || '{}');
    if (body && typeof body === 'object') {
      return body;
    }
  } catch (_) {
    // Runtime returned a non-JSON body; expose only the bounded fallback below.
  }
  return { error: fallback };
}

async function runtimeProjectLibraryRemove({ projectId, sourceRefId, expectedProjectRevision, key }) {
  const response = await fetch(
    RUNTIME_ADAPTER_BASE +
      '/v1/runtime-project-library/source/' +
      encodeURIComponent(sourceRefId) +
      '/remove',
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + key,
        'X-LibreChat-Project-ID': projectId,
      },
      body: JSON.stringify({ expected_project_revision: expectedProjectRevision }),
    },
  );
  const raw = await response.text();
  return { response, raw, body: runtimeErrorBody(raw, 'Runtime Project source removal failed') };
}

async function runtimeProjectSourceRetirementCandidates({ projectId, key }) {
  const response = await fetch(
    RUNTIME_ADAPTER_BASE + '/v1/runtime-project-library/source-retirement-candidates',
    {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: 'Bearer ' + key,
        'X-LibreChat-Project-ID': projectId,
      },
    },
  );
  const raw = await response.text();
  return { response, raw, body: runtimeErrorBody(raw, 'Runtime Source retirement candidates unavailable') };
}

async function runtimeProjectSourceRetireContent({ projectId, sourceRefId, payload, key }) {
  const response = await fetch(
    RUNTIME_ADAPTER_BASE +
      '/v1/runtime-project-library/source/' + encodeURIComponent(sourceRefId) + '/retire-content',
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + key,
        'X-LibreChat-Project-ID': projectId,
      },
      body: JSON.stringify(payload),
    },
  );
  const raw = await response.text();
  return { response, raw, body: runtimeErrorBody(raw, 'Runtime Source content retirement failed') };
}

async function runtimeProjectLibraryAdoptBundle({
  projectId,
  revisionRaw,
  filename,
  bundle,
  key,
}) {
  const response = await fetch(
    RUNTIME_ADAPTER_BASE + '/v1/runtime-project-library/document-bundle',
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/zip',
        Authorization: 'Bearer ' + key,
        'X-LibreChat-Project-ID': projectId,
        'X-Runtime-Document-Filename': encodeURIComponent(filename),
        'X-Runtime-Document-Format': bundle.inputFormat,
        'X-Runtime-Document-Media-Type': bundle.mediaType,
        'X-Runtime-Document-Size': String(bundle.inputSize),
        'X-Runtime-Document-SHA256': bundle.inputSha256,
        'X-Runtime-Document-Bundle-Size': String(bundle.bundleBytes.length),
        'X-Runtime-Document-Bundle-SHA256': bundle.bundleSha256,
        'X-Project-Expected-Revision': revisionRaw,
      },
      body: bundle.bundleBytes,
    },
  );
  const raw = await response.text();
  const body = runtimeErrorBody(raw, 'Runtime Project document-bundle bridge failed');
  return { response, raw, body };
}

async function enrichRuntimeLibrary(req, body) {
  if (!body || typeof body !== 'object' || !Array.isArray(body.sources)) {
    return body;
  }
  const catalog = await listOwnerNativeFiles({ req, supportsFilename: sourceSupported });
  const sourceToFile = new Map();
  for (const file of catalog.files) {
    for (const ref of file.project_source_refs ?? []) {
      if (ref.librechat_project_id === req.params.projectId) {
        sourceToFile.set(ref.source_ref_id, file);
      }
    }
  }
  return {
    ...body,
    supported_file_extensions: nativeDocumentFormatsCatalog(),
    source_accept: PROJECT_SOURCE_ACCEPT,
    sources: body.sources.map((source) => {
      const native = sourceToFile.get(source.source_ref_id);
      return {
        ...source,
        native_file_id: native?.file_id ?? null,
        native_file_status: native?.status ?? 'LEGACY_RUNTIME_ONLY',
      };
    }),
  };
}

async function compensateRuntimeSource({ projectId, sourceRefId, projectRevision, key }) {
  if (typeof sourceRefId !== 'string' || !sourceRefId || !Number.isInteger(projectRevision)) {
    return false;
  }
  try {
    const result = await runtimeProjectLibraryRemove({
      projectId,
      sourceRefId,
      expectedProjectRevision: projectRevision,
      key,
    });
    return result.response.ok;
  } catch (_) {
    return false;
  }
}

async function adoptNativeFileIntoRuntime({ req, file, bytes, revisionRaw, provenance, preparedBundle }) {
  const { projectId } = req.params;
  const key = runtimeKey();
  if (!key) {
    return { status: 503, body: { error: 'Runtime Project Library unavailable' } };
  }
  if (
    projectSourceRefs(file.metadata).some(
      (reference) => reference.librechat_project_id === projectId,
    )
  ) {
    return {
      status: 409,
      body: { error: 'This native file is already linked to the Project' },
    };
  }
  let bundle = preparedBundle;
  if (!bundle) {
    try {
      bundle = await buildNativeDocumentRuntimeBundle({ filename: file.filename, originalBytes: bytes });
    } catch (error) {
      return {
        status: Number.isInteger(error?.status) ? error.status : 422,
        body: { error: error?.message || 'Project file extraction failed' },
      };
    }
  }
  try {
    const result = await runtimeProjectLibraryAdoptBundle({
      projectId,
      revisionRaw,
      filename: file.filename,
      bundle,
      key,
    });
    if (!result.response.ok) {
      return { status: result.response.status, body: result.body };
    }
    const sourceRefId = result.body?.saved_source_ref_id;
    const projectRevision = result.body?.project_revision;
    const runtimeProjectId = result.body?.runtime_project_id;
    if (
      typeof sourceRefId !== 'string' ||
      !sourceRefId ||
      !Number.isInteger(projectRevision) ||
      typeof runtimeProjectId !== 'string' ||
      !runtimeProjectId
    ) {
      return { status: 502, body: { error: 'Runtime Project source response is incomplete' } };
    }
    try {
      await bindNativeFileToSource({
        file,
        userId: getUserId(req),
        libreChatProjectId: projectId,
        runtimeProjectId,
        sourceRefId,
      });
    } catch (_) {
      const compensated = await compensateRuntimeSource({
        projectId,
        sourceRefId,
        projectRevision,
        key,
      });
      if (!compensated) {
        return {
          status: 500,
          body: {
            error: 'PROJECT_NATIVE_FILE_SOURCE_COMMIT_OUTCOME_UNKNOWN',
            retryAutomatically: false,
          },
        };
      }
      return {
        status: 500,
        body: { error: 'Project native File binding failed and Source was rolled back' },
      };
    }
    let presentation = {
      ...result.body,
      saved_native_file_id: file.file_id,
      native_file_provenance: provenance,
    };
    try {
      presentation = await enrichRuntimeLibrary(req, presentation);
    } catch (_) {
      // The Source and native File binding are already committed. Never undo durable state merely
      // because a non-authority presentation refresh failed; the next GET will rehydrate it.
    }
    return { status: result.response.status, body: presentation, committed: true };
  } catch (_) {
    return { status: 502, body: { error: 'Runtime Project document-bundle bridge unavailable' } };
  }
}

async function createCuratedProject(req, res) {
  const userId = getUserId(req);
  const purpose = typeof req.body?.purpose === 'string' ? req.body.purpose : 'general';
  if (!['general', 'academic-research'].includes(purpose)) {
    return res.status(400).json({ error: 'Invalid Project purpose' });
  }
  const name = typeof req.body?.name === 'string' ? req.body.name.trim() : '';
  const description = typeof req.body?.description === 'string' ? req.body.description.trim() : '';
  if (!name) {
    return res.status(400).json({ error: 'Project name is required' });
  }

  let project;
  try {
    project = await db.createChatProject(userId, {
      name,
      ...(description ? { description } : {}),
    });
    if (purpose === 'academic-research') {
      const projectId = String(project?._id || '');
      if (!isValidObjectIdString(projectId)) {
        throw new Error('Created Project identity is invalid');
      }
      await bindProjectAssistantProfile(projectId, {
        assistantProfileId: 'academic-research',
        assistantProfileRevision: 'R001',
      });
    }
    return res.status(201).json(project);
  } catch (error) {
    if (project?._id) {
      try {
        await db.deleteChatProject(userId, String(project._id));
      } catch (_) {
        // The original create/bind failure is returned below; rollback is best effort.
      }
    }
    return res.status(Number.isInteger(error?.status) ? error.status : 500).json({
      error: error?.message || 'Failed to create Project',
    });
  }
}

async function proxyRuntimeProjectInstructions(req, res, method) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const project = await db.getChatProject(getUserId(req), projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const key = String(process.env.UR_SHELL_ADAPTER_KEY || '');
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project Instructions unavailable' });
  }
  const headers = {
    Accept: 'application/json',
    Authorization: `Bearer ${key}`,
    'X-LibreChat-Project-ID': projectId,
  };
  const options = { method, headers };
  if (method === 'PUT') {
    const expectedProjectRevision = req.body?.expected_project_revision;
    const instructions = req.body?.instructions;
    if (
      !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
      (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1) ||
      typeof instructions !== 'string'
    ) {
      return res.status(400).json({ error: 'Invalid Project Instructions request' });
    }
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify({
      expected_project_revision: expectedProjectRevision,
      instructions,
    });
  }
  try {
    const response = await fetch(`${RUNTIME_ADAPTER_BASE}/v1/runtime-project-instructions`, options);
    const raw = await response.text();
    res.set('Cache-Control', 'no-store');
    res.type('application/json');
    return res.status(response.status).send(raw || '{}');
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project Instructions bridge unavailable' });
  }
}

async function proxyRuntimeProjectContextPolicy(req, res, method) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const project = await db.getChatProject(getUserId(req), projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const key = String(process.env.UR_SHELL_ADAPTER_KEY || '');
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project context policy unavailable' });
  }
  const headers = {
    Accept: 'application/json',
    Authorization: `Bearer ${key}`,
    'X-LibreChat-Project-ID': projectId,
  };
  const options = { method, headers };
  if (method === 'PUT') {
    const expectedProjectRevision = req.body?.expected_project_revision;
    const contextPolicy = req.body?.context_policy;
    if (
      !(expectedProjectRevision === null || Number.isInteger(expectedProjectRevision)) ||
      (Number.isInteger(expectedProjectRevision) && expectedProjectRevision < 1) ||
      !['PROJECT_ONLY', 'PROJECT_PLUS_GLOBAL_USER_MEMORY'].includes(contextPolicy)
    ) {
      return res.status(400).json({ error: 'Invalid Project context policy request' });
    }
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify({
      expected_project_revision: expectedProjectRevision,
      context_policy: contextPolicy,
    });
  }
  try {
    const response = await fetch(`${RUNTIME_ADAPTER_BASE}/v1/runtime-project-context-policy`, options);
    const raw = await response.text();
    res.set('Cache-Control', 'no-store');
    res.type('application/json');
    return res.status(response.status).send(raw || '{}');
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project context policy bridge unavailable' });
  }
}

async function proxyRuntimeProjectMemory(req, res, method, suffix = '') {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const project = await db.getChatProject(getUserId(req), projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const key = String(process.env.UR_SHELL_ADAPTER_KEY || '');
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project Memory unavailable' });
  }
  const headers = {
    Accept: 'application/json',
    Authorization: `Bearer ${key}`,
    'X-LibreChat-Project-ID': projectId,
  };
  const options = { method, headers };
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(req.body ?? {});
  }
  try {
    const response = await fetch(`${RUNTIME_ADAPTER_BASE}/v1/runtime-project-memory${suffix}`, options);
    const raw = await response.text();
    res.set('Cache-Control', 'no-store');
    res.type('application/json');
    return res.status(response.status).send(raw || '{}');
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project Memory bridge unavailable' });
  }
}

async function proxyRuntimeProjectLibrary(req, res) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const project = await db.getChatProject(getUserId(req), projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const key = runtimeKey();
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project Library unavailable' });
  }
  try {
    const response = await fetch(`${RUNTIME_ADAPTER_BASE}/v1/runtime-project-library`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${key}`,
        'X-LibreChat-Project-ID': projectId,
      },
    });
    const raw = await response.text();
    const body = runtimeErrorBody(raw, 'Runtime Project Library unavailable');
    res.set('Cache-Control', 'no-store');
    return res.status(response.status).json(response.ok ? await enrichRuntimeLibrary(req, body) : body);
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project Library bridge unavailable' });
  }
}
async function proxyRuntimeProjectLibraryNativeDocument(req, res) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const userId = getUserId(req);
  const project = await db.getChatProject(userId, projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }

  const filename = typeof req.query?.filename === 'string' ? req.query.filename : '';
  const format = nativeDocumentFormatForFilename(filename);
  const transportMediaType = String(req.headers['content-type'] || '')
    .split(';', 1)[0]
    .trim()
    .toLowerCase();
  const declaredMediaType = String(req.headers['x-project-file-media-type'] || '')
    .split(';', 1)[0]
    .trim()
    .toLowerCase();
  const mediaType =
    transportMediaType === 'application/octet-stream' && declaredMediaType
      ? declaredMediaType
      : transportMediaType;
  if (
    !format ||
    (transportMediaType === 'application/octet-stream' && !declaredMediaType) ||
    !nativeDocumentMediaTypeAccepted(format, mediaType)
  ) {
    return res.status(415).json({
      error: 'Unsupported Project source type',
      supported_file_extensions: nativeDocumentFormatsCatalog(),
    });
  }
  if (
    !Buffer.isBuffer(req.body) ||
    req.body.length < 1 ||
    req.body.length > MAX_NATIVE_DOCUMENT_BYTES
  ) {
    return res.status(req.body?.length > MAX_NATIVE_DOCUMENT_BYTES ? 413 : 400).json({
      error: 'Project file must be non-empty and no larger than 15 MB',
    });
  }

  const revisionRaw =
    typeof req.query?.expected_project_revision === 'string'
      ? req.query.expected_project_revision
      : '';
  if (revisionRaw && (!/^\d+$/.test(revisionRaw) || Number(revisionRaw) < 1)) {
    return res.status(400).json({ error: 'Invalid Project source revision' });
  }

  let bundle;
  try {
    bundle = await buildNativeDocumentRuntimeBundle({ filename, originalBytes: req.body });
  } catch (error) {
    return res.status(Number.isInteger(error?.status) ? error.status : 422).json({
      error: error?.message || 'Project file extraction failed',
    });
  }

  let nativeFile;
  try {
    nativeFile = await persistNativeProjectFile({
      req,
      filename,
      mediaType: format.mediaType,
      bytes: req.body,
      projectId,
    });
  } catch (error) {
    return res.status(Number.isInteger(error?.status) ? error.status : 500).json({
      error: error?.message || 'Native Project file persistence failed',
    });
  }

  const result = await adoptNativeFileIntoRuntime({
    req,
    file: nativeFile,
    bytes: req.body,
    revisionRaw,
    provenance: 'PROJECT_UPLOAD_NATIVE_AND_RUNTIME',
    preparedBundle: bundle,
  });
  if (!result.committed) {
    if (result.body?.error !== 'PROJECT_NATIVE_FILE_SOURCE_COMMIT_OUTCOME_UNKNOWN') {
      try {
        await deleteNativeFileOrThrow({ req, file: nativeFile });
      } catch (_) {
        return res.status(500).json({
          error: 'PROJECT_NATIVE_FILE_ROLLBACK_OUTCOME_UNKNOWN',
          retryAutomatically: false,
        });
      }
    }
    return res.status(result.status).json(result.body);
  }
  res.set('Cache-Control', 'no-store');
  return res.status(result.status).json(result.body);
}

async function proxyRuntimeProjectNativeFileCatalog(req, res) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  if (!(await db.getChatProject(getUserId(req), projectId))) {
    return res.status(404).json({ error: 'Project not found' });
  }
  try {
    const catalog = await listOwnerNativeFiles({ req, supportsFilename: sourceSupported });
    res.set('Cache-Control', 'no-store');
    return res.json({
      ...catalog,
      supported_file_extensions: nativeDocumentFormatsCatalog(),
      source_accept: PROJECT_SOURCE_ACCEPT,
    });
  } catch (_) {
    return res.status(500).json({ error: 'Unable to load your native files' });
  }
}

async function proxyRuntimeProjectChatFileCatalog(req, res) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  if (!(await db.getChatProject(getUserId(req), projectId))) {
    return res.status(404).json({ error: 'Project not found' });
  }
  try {
    const catalog = await listProjectChatAttachmentCandidates({
      req,
      projectId,
      supportsFilename: sourceSupported,
    });
    res.set('Cache-Control', 'no-store');
    return res.json(catalog);
  } catch (_) {
    return res.status(500).json({ error: 'Unable to load Project Chat attachments' });
  }
}

function nativeFileAdoptionRevision(req) {
  const revision = req.body?.expected_project_revision;
  if (revision == null) {
    return '';
  }
  if (!Number.isInteger(revision) || revision < 1) {
    return null;
  }
  return String(revision);
}
async function proxyRuntimeProjectLibraryFromNativeFile(req, res) {
  const { projectId, fileId } = req.params;
  if (!isValidObjectIdString(projectId) || typeof fileId !== 'string' || !fileId) {
    return res.status(404).json({ error: 'Project or file not found' });
  }
  if (!(await db.getChatProject(getUserId(req), projectId))) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const revision = nativeFileAdoptionRevision(req);
  if (revision === null) {
    return res.status(400).json({ error: 'Invalid Project source revision' });
  }
  let owned;
  try {
    owned = await readOwnedNativeFile(req, fileId);
  } catch (error) {
    return res.status(Number.isInteger(error?.status) ? error.status : 500).json({
      error: error?.message || 'Native file cannot be read',
    });
  }
  if (!sourceSupported(owned.file.filename)) {
    return res.status(415).json({ error: 'This native file type cannot become a Project source' });
  }
  const result = await adoptNativeFileIntoRuntime({
    req,
    file: owned.file,
    bytes: owned.bytes,
    revisionRaw: revision,
    provenance: 'OWNER_NATIVE_FILE_REUSE',
  });
  res.set('Cache-Control', 'no-store');
  return res.status(result.status).json(result.body);
}

async function proxyRuntimeProjectLibraryFromChatFile(req, res) {
  const { projectId, messageId, fileId } = req.params;
  const conversationId =
    typeof req.body?.conversation_id === 'string' ? req.body.conversation_id.trim() : '';
  if (
    !isValidObjectIdString(projectId) ||
    typeof messageId !== 'string' ||
    !messageId ||
    typeof fileId !== 'string' ||
    !fileId ||
    !conversationId
  ) {
    return res.status(404).json({ error: 'Project, Chat attachment or message not found' });
  }
  if (!(await db.getChatProject(getUserId(req), projectId))) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const revision = nativeFileAdoptionRevision(req);
  if (revision === null) {
    return res.status(400).json({ error: 'Invalid Project source revision' });
  }
  try {
    await verifyProjectMessageFileReference({
      userId: getUserId(req),
      projectId,
      conversationId,
      messageId,
      fileId,
    });
    const owned = await readOwnedNativeFile(req, fileId);
    if (!sourceSupported(owned.file.filename)) {
      return res.status(415).json({ error: 'This Chat attachment type cannot become a Project source' });
    }
    const result = await adoptNativeFileIntoRuntime({
      req,
      file: owned.file,
      bytes: owned.bytes,
      revisionRaw: revision,
      provenance: 'PROJECT_CHAT_ATTACHMENT_PROMOTION',
    });
    res.set('Cache-Control', 'no-store');
    return res.status(result.status).json(result.body);
  } catch (error) {
    return res.status(Number.isInteger(error?.status) ? error.status : 500).json({
      error: error?.message || 'Chat attachment cannot become a Project source',
    });
  }
}

async function proxyRuntimeProjectLibrarySaveFromMessage(req, res) {
  const { projectId, messageId } = req.params;
  if (!isValidObjectIdString(projectId) || typeof messageId !== 'string' || !messageId) {
    return res.status(404).json({ error: 'Project or message not found' });
  }
  const userId = getUserId(req);
  const project = await db.getChatProject(userId, projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const conversationId =
    typeof req.body?.conversation_id === 'string' ? req.body.conversation_id.trim() : '';
  if (!conversationId) {
    return res.status(400).json({ error: 'conversation_id is required' });
  }
  const conversation = await db.getConvo(userId, conversationId);
  const message = await db.getMessage({ user: userId, messageId });
  let source;
  try {
    source = buildChatOutputSource({
      userId,
      librechatProjectId: projectId,
      conversation,
      message,
    });
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : 409;
    return res.status(status).json({ error: error?.message || 'Message cannot be saved to Project' });
  }

  const key = String(process.env.UR_SHELL_ADAPTER_KEY || '');
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project Library unavailable' });
  }
  try {
    const response = await fetch(RUNTIME_ADAPTER_BASE + '/v1/runtime-project-library/from-message', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + key,
        'X-LibreChat-Project-ID': projectId,
      },
      body: JSON.stringify(source),
    });
    const raw = await response.text();
    res.set('Cache-Control', 'no-store');
    res.type('application/json');
    return res.status(response.status).send(raw || '{}');
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project Library bridge unavailable' });
  }
}

async function proxyRuntimeProjectSourceRetirementCandidates(req, res) {
  try {
    const projectId = req.params.projectId;
    const userId = String(getUserId(req));
    if (!isValidObjectIdString(projectId) || !userId) {
      return res.status(404).json({ code: 'PROJECT_SOURCE_RETIREMENT_PROJECT_NOT_FOUND' });
    }
    const project = await db.getChatProject(userId, projectId);
    if (!project) {
      return res.status(404).json({ code: 'PROJECT_SOURCE_RETIREMENT_PROJECT_NOT_FOUND' });
    }
    const key = runtimeKey();
    if (!key) {
      return res.status(503).json({ code: 'PROJECT_SOURCE_RETIREMENT_RUNTIME_UNAVAILABLE' });
    }
    const result = await runtimeProjectSourceRetirementCandidates({ projectId, key });
    if (!result.response.ok) {
      return res.status(result.response.status).json(result.body);
    }
    const body = result.body;
    if (
      body?.schema !== 'RUNTIME_PROJECT_SOURCE_RETIREMENT_CANDIDATES_R001' ||
      !Number.isInteger(body.project_revision) ||
      !Array.isArray(body.sources) ||
      body.candidate_count !== body.sources.length
    ) {
      return res.status(502).json({ code: 'PROJECT_SOURCE_RETIREMENT_CANDIDATES_SCHEMA_UNKNOWN' });
    }
    const catalog = await listOwnerNativeFiles({ req, supportsFilename: sourceSupported });
    const bySource = new Map();
    for (const file of catalog.files) {
      for (const ref of [...(file.project_source_refs ?? []), ...(file.retired_project_source_refs ?? [])]) {
        if (ref.librechat_project_id !== projectId) continue;
        if (bySource.has(ref.source_ref_id)) {
          return res.status(409).json({
            code: 'PROJECT_SOURCE_RETIREMENT_NATIVE_MAPPING_AMBIGUOUS',
            source_ref_id: ref.source_ref_id,
          });
        }
        bySource.set(ref.source_ref_id, file);
      }
    }
    const detachedByTuple = new Map();
    for (const source of body.sources) {
      if (
        source.active_project_binding ||
        !['DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(source.retirement_state)
      ) continue;
      const key = `${source.filename}\u0000${source.origin_input_sha256}\u0000${source.origin_input_byte_size}`;
      const rows = detachedByTuple.get(key) ?? [];
      rows.push(source.source_ref_id);
      detachedByTuple.set(key, rows);
    }
    const unclaimedNativeByTuple = new Map();
    for (const file of catalog.files) {
      if (
        file.project_source_ref_count !== 0 || file.retired_project_source_ref_count !== 0
        || typeof file.native_sha256 !== 'string' || !Number.isInteger(file.bytes)
      ) continue;
      const key = `${file.filename}\u0000${file.native_sha256}\u0000${file.bytes}`;
      const rows = unclaimedNativeByTuple.get(key) ?? [];
      rows.push(file.file_id);
      unclaimedNativeByTuple.set(key, rows);
    }
    const candidates = body.sources.map((source) => {
      const native = bySource.get(source.source_ref_id);
      const key = `${source.filename}\u0000${source.origin_input_sha256}\u0000${source.origin_input_byte_size}`;
      const legacySources = [...(detachedByTuple.get(key) ?? [])].sort();
      const legacyFiles = [...(unclaimedNativeByTuple.get(key) ?? [])].sort();
      const completedLegacy =
        source.retirement_state === 'CONTENT_RETIRED' &&
        source.completed_native_binding?.binding_class === 'EXACT_LEGACY_COHORT_SET';
      const completedSourceIds = completedLegacy
        ? [...source.completed_native_binding.source_ref_ids].sort()
        : [];
      const completedFileIds = completedLegacy
        ? [...source.completed_native_binding.native_file_ids].sort()
        : [];
      const remainingCompletedFiles = completedLegacy
        ? completedFileIds.filter((fileId) => catalog.files.some((file) => file.file_id === fileId))
        : [];
      const exactLegacyCohort =
        !native && (
          (legacySources.length > 0 && legacySources.length === legacyFiles.length) ||
          (completedLegacy && remainingCompletedFiles.length > 0)
        );
      const cohortSources = completedLegacy ? completedSourceIds : legacySources;
      const cohortFiles = completedLegacy ? remainingCompletedFiles : legacyFiles;
      const legacyCohortId = exactLegacyCohort
        ? crypto.createHash('sha256')
            .update(`${projectId}\u0000${key}\u0000${cohortFiles.join(',')}\u0000${cohortSources.join(',')}`)
            .digest('hex')
        : null;
      return {
        ...source,
        native_file_id: native?.file_id ?? null,
        native_file_status: native?.status ?? 'LEGACY_RUNTIME_ONLY',
        native_file_created_at: native?.created_at ?? null,
        native_file_modified_at: native?.modified_at ?? null,
        legacy_cohort_id: legacyCohortId,
        legacy_cohort_file_ids: legacyCohortId ? cohortFiles : [],
        legacy_cohort_source_ref_ids: legacyCohortId ? cohortSources : [],
      };
    });
    res.set('Cache-Control', 'no-store');
    return res.status(200).json({
      schema: 'LC_PROJECT_SOURCE_RETIREMENT_CANDIDATES_R001',
      authority_class: 'NON_AUTHORITY_PRESENTATION_PROJECTION',
      project_id: projectId,
      project_revision: body.project_revision,
      candidate_count: candidates.length,
      sources: candidates,
    });
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : 502;
    return res.status(status).json({
      code: error?.code || 'PROJECT_SOURCE_RETIREMENT_CANDIDATES_UNAVAILABLE',
      message: error?.message || 'Project Source retirement candidates unavailable.',
    });
  }
}

async function proxyRuntimeProjectLibraryPermanentDelete(req, res) {
  try {
    const projectId = req.params.projectId;
    const sourceRefId = req.params.sourceRefId;
    const userId = String(getUserId(req));
    const key = runtimeKey();
    const revision = Number.parseInt(String(req.body?.expected_project_revision ?? ''), 10);
    if (
      !isValidObjectIdString(projectId) || !sourceRefId || !userId || !key
      || !Number.isInteger(revision) || revision < 1
    ) {
      return res.status(400).json({ code: 'PROJECT_PERMANENT_DELETE_SCOPE_INVALID' });
    }
    const libreChatProject = await db.getChatProject(userId, projectId);
    if (!libreChatProject) {
      return res.status(404).json({ code: 'PROJECT_PERMANENT_DELETE_PROJECT_NOT_FOUND' });
    }
    if (req.body?.permanent_delete_confirmed !== true) {
      return res.status(400).json({
        code: 'PROJECT_PERMANENT_DELETE_CONFIRMATION_REQUIRED',
        message: 'One explicit permanent-delete confirmation is required.',
      });
    }
    const candidateResult = await runtimeProjectSourceRetirementCandidates({ projectId, key });
    if (!candidateResult.response.ok) {
      return res.status(candidateResult.response.status).json(candidateResult.body);
    }
    const candidateBody = candidateResult.body;
    if (
      candidateBody?.schema !== 'RUNTIME_PROJECT_SOURCE_RETIREMENT_CANDIDATES_R001'
      || !Number.isInteger(candidateBody.project_revision)
      || !Array.isArray(candidateBody.sources)
    ) {
      throw new CrossStorePermanentDeleteStop(
        'PROJECT_PERMANENT_DELETE_RUNTIME_CANDIDATES_UNKNOWN',
      );
    }
    const selectedCandidate = candidateBody.sources.find((row) => row?.source_ref_id === sourceRefId);
    if (!selectedCandidate) {
      return res.status(404).json({ code: 'PROJECT_PERMANENT_DELETE_SOURCE_NOT_FOUND' });
    }
    if (candidateBody.project_revision !== revision) {
      throw new CrossStorePermanentDeleteStop(
        'PROJECT_PERMANENT_DELETE_STALE_PROJECT_REVISION',
        'Project Sources changed. Refresh before deleting.',
      );
    }
    const alreadyDetached = ['DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(
      selectedCandidate.retirement_state,
    );
    if (Boolean(req.body?.source_already_detached) !== alreadyDetached) {
      throw new CrossStorePermanentDeleteStop(
        'PROJECT_PERMANENT_DELETE_SOURCE_STATE_CHANGED',
        'Source state changed. Refresh before deleting.',
      );
    }
    const all = await db.getFiles({ user: userId }, null, { text: 0 });
    const activeLinked = (all ?? []).filter((file) =>
      projectSourceRefs(file.metadata).some(
        (ref) => ref.librechat_project_id === projectId && ref.source_ref_id === sourceRefId,
      ),
    );
    const retiredLinked = (all ?? []).filter((file) =>
      retiredProjectSourceRefs(file.metadata).some(
        (ref) => ref.librechat_project_id === projectId && ref.source_ref_id === sourceRefId,
      ),
    );
    if (activeLinked.length > 1 || retiredLinked.length > 1 || (activeLinked.length && retiredLinked.length)) {
      throw new CrossStorePermanentDeleteStop(
        'PROJECT_PERMANENT_DELETE_NATIVE_BINDING_AMBIGUOUS',
        'More than one native File claims the selected Project Source.',
      );
    }

    // Legacy cohort: old bytes predate retiredProjectSourceRefs. The user deletes
    // the exact equal-cardinality FileID/SourceRef set in one explicit action.
    const legacyFileIds = Array.isArray(req.body?.legacy_cohort_file_ids)
      ? [...req.body.legacy_cohort_file_ids].sort()
      : [];
    const legacySourceIds = Array.isArray(req.body?.legacy_cohort_source_ref_ids)
      ? [...req.body.legacy_cohort_source_ref_ids].sort()
      : [];
    if (legacyFileIds.length || legacySourceIds.length) {
      if (
        !alreadyDetached || activeLinked.length || retiredLinked.length
        || legacyFileIds.length < 1 || legacySourceIds.length < 1
        || !legacySourceIds.includes(sourceRefId)
        || new Set(legacyFileIds).size !== legacyFileIds.length
        || new Set(legacySourceIds).size !== legacySourceIds.length
      ) {
        throw new CrossStorePermanentDeleteStop('PROJECT_PERMANENT_DELETE_LEGACY_COHORT_INVALID');
      }
      const files = await db.getFiles({ file_id: { $in: legacyFileIds } });
      if (
        files.length !== legacyFileIds.length
        || files.some((file) => String(file.user) !== userId)
      ) {
        throw new CrossStorePermanentDeleteStop('PROJECT_PERMANENT_DELETE_LEGACY_FILE_OWNER_CHANGED');
      }
      const nativeReferenceEvidence = await requireNativeFileDeleteUnreferenced({
        files, userId, models: mongoose.models, nativeDb: db,
      });
      const plan = buildCrossStoreRetirementPlan({
        files,
        projectId,
        runtimeCandidates: candidateBody,
        nativeReferenceEvidence,
      });
      if (
        plan.bindingClass !== 'EXACT_LEGACY_COHORT_SET'
        || JSON.stringify(plan.nativeFileIds) !== JSON.stringify(legacyFileIds)
        || JSON.stringify(plan.sourceRefIds) !== JSON.stringify(legacySourceIds)
      ) {
        throw new CrossStorePermanentDeleteStop('PROJECT_PERMANENT_DELETE_LEGACY_COHORT_CHANGED');
      }
      const execution = await executeCrossStorePermanentDelete({
        files,
        projectId,
        runtimeCandidates: candidateBody,
        nativeReferenceEvidence,
        userId,
        recheckNativeReferences: (rows) =>
          requireNativeFileDeleteUnreferenced({
            files: rows, userId, models: mongoose.models, nativeDb: db,
          }),
        deleteNativeFiles: async (rows) => {
          const deletedFileIds = [];
          for (const row of rows) {
            await deleteNativeFileOrThrow({ req, file: row });
            deletedFileIds.push(row.file_id);
          }
          return { deletedFileIds, failedFileIds: [] };
        },
      });
      return res.status(200).json({
        schema: 'LC_PROJECT_SOURCE_PERMANENT_DELETE_R001',
        native_file_deleted: true,
        runtime_source_retired: true,
        binding_class: execution.plan.bindingClass,
        source_ref_ids: execution.plan.sourceRefIds,
        file_ids: execution.plan.nativeFileIds,
        binding_evidence_sha256: execution.plan.bindingEvidenceSha256,
      });
    }

    // Validate actual owner-scoped original bytes before any Project detach.
    // A reused Chat File may not have nativeSha256 in legacy Mongo metadata.
    const verifiedNativeForSource = async (candidateFile) => {
      const readBack = await readOwnedNativeFile(req, candidateFile.file_id);
      const fresh = readBack.file;
      const digest = crypto.createHash('sha256').update(readBack.bytes).digest('hex');
      const storedDigest = fresh.metadata?.nativeSha256;
      if (
        fresh.file_id !== candidateFile.file_id ||
        String(fresh.user) !== userId ||
        fresh.filename !== selectedCandidate.filename ||
        digest !== selectedCandidate.origin_input_sha256 ||
        readBack.bytes.length !== selectedCandidate.origin_input_byte_size ||
        (storedDigest != null && (
          typeof storedDigest !== 'string' ||
          !/^[0-9a-f]{64}$/.test(storedDigest) ||
          storedDigest !== digest
        ))
      ) {
        throw new CrossStorePermanentDeleteStop(
          'PROJECT_PERMANENT_DELETE_NATIVE_SOURCE_SHA_UNPROVEN',
          'Native original bytes differ from the selected Project Source; nothing was deleted.',
        );
      }
      return { ...fresh, metadata: { ...fresh.metadata, nativeSha256: digest } };
    };
    let file = activeLinked[0] ?? retiredLinked[0] ?? null;
    let preflightEvidence = null;
    if (file) {
      file = await verifiedNativeForSource(file);
      const allowed = activeLinked.length
        ? projectSourceRefs(file.metadata).filter(
            (ref) => ref.librechat_project_id === projectId && ref.source_ref_id === sourceRefId,
          )
        : [];
      preflightEvidence = await requireNativeFileDeleteUnreferenced({
        files: [file],
        userId,
        models: mongoose.models,
        nativeDb: db,
        allowedProjectSourceRefsByFileId: allowed.length ? { [file.file_id]: allowed } : {},
      });
    }

    let currentRevision = revision;
    if (!alreadyDetached) {
      const removed = await runtimeProjectLibraryRemove({
        projectId,
        sourceRefId,
        expectedProjectRevision: revision,
        key,
      });
      if (!removed.response.ok) {
        return res.status(removed.response.status).json(removed.body);
      }
      // Adapter returns normalized Project Library presentation at top-level,
      // not the underlying Runtime response's nested project field.
      // Check fresh revision and exact SourceRef absence before native unbind;
      // no extra remove or delete effect is introduced.
      const removedPresentation = removed.body;
      if (
        removedPresentation?.schema !== 'UR_WEB_R004_PROJECT_LIBRARY_PRESENTATION_R001'
        || removedPresentation.initialized !== true
        || removedPresentation.authority_class !== 'NON_AUTHORITY_PRESENTATION_PROJECTION'
        || !Number.isInteger(removedPresentation.project_revision)
        || removedPresentation.project_revision <= revision
        || !Array.isArray(removedPresentation.sources)
        || !Number.isInteger(removedPresentation.source_count)
        || removedPresentation.source_count !== removedPresentation.sources.length
        || removedPresentation.sources.some((row) =>
          !row || typeof row.source_ref_id !== 'string' || row.source_ref_id === sourceRefId
        )
      ) {
        throw new CrossStorePermanentDeleteStop(
          'PROJECT_PERMANENT_DELETE_RUNTIME_DETACH_READBACK_UNKNOWN',
        );
      }
      currentRevision = removedPresentation.project_revision;
      if (file) {
        await unbindNativeFileSource({ userId, sourceRefId });
        file = await db.findFileById(file.file_id);
        if (!file || String(file.user) !== userId) {
          throw new CrossStorePermanentDeleteStop(
            'PROJECT_PERMANENT_DELETE_NATIVE_FILE_CURRENTNESS_UNKNOWN',
          );
        }
        file = await verifiedNativeForSource(file);
      }
    }

    if (alreadyDetached && activeLinked.length === 1 && file) {
      await unbindNativeFileSource({ userId, sourceRefId });
      file = await db.findFileById(file.file_id);
      if (!file || String(file.user) !== userId) {
        throw new CrossStorePermanentDeleteStop(
          'PROJECT_PERMANENT_DELETE_NATIVE_FILE_CURRENTNESS_UNKNOWN',
        );
      }
      file = await verifiedNativeForSource(file);
    }

    if (!file) {
      const retiredClaims = (all ?? []).filter((row) =>
        retiredProjectSourceRefs(row.metadata).some(
          (ref) => ref.librechat_project_id === projectId && ref.source_ref_id === sourceRefId,
        ),
      );
      if (retiredClaims.length > 0 || req.body?.runtime_source_only_confirmed !== true) {
        throw new CrossStorePermanentDeleteStop(
          'PROJECT_PERMANENT_DELETE_SOURCE_ONLY_IDENTITY_UNPROVEN',
          'Native File identity is missing or ambiguous; refresh the Project source before deleting.',
        );
      }
      const evidence = {
        schema: 'LC_RUNTIME_SOURCE_ONLY_BINDING_EVIDENCE_R001',
        project_id: projectId,
        runtime_project_id: candidateBody.project_id ?? null,
        source_ref_id: sourceRefId,
        expected_project_revision: currentRevision,
      };
      const bindingEvidenceSha256 = digestJson(evidence);
      const ownerId = crypto.createHash('sha256').update(userId).digest('hex');
      const commandId = 'runtime-source-delete-' + crypto
        .createHash('sha256')
        .update(`${ownerId}\u0000${bindingEvidenceSha256}\u0000${sourceRefId}`)
        .digest('hex')
        .slice(0, 48);
      const retired = await runtimeProjectSourceRetireContent({
        projectId,
        sourceRefId,
        key,
        payload: {
          command_id: commandId,
          expected_project_revision: currentRevision,
          owner_id: ownerId,
          external_ref_counts: {
            current_chat: 0, agents: 0, assistants: 0, shared_links: 0,
            native_other_files: 0, protected_rollbacks: 0, external_consumers: 0,
          },
          protected_asset_census_sha256: null,
          binding_class: 'EXACT_RUNTIME_SOURCE_ONLY',
          native_file_ids: [],
          source_ref_ids: [sourceRefId],
          binding_evidence_sha256: bindingEvidenceSha256,
        },
      });
      if (!retired.response.ok || retired.body?.content_retirement?.state !== 'COMPLETED') {
        return res.status(retired.response.status).json(retired.body);
      }
      return res.status(200).json({
        schema: 'LC_PROJECT_SOURCE_PERMANENT_DELETE_R001',
        native_file_deleted: false,
        runtime_source_retired: true,
        binding_class: 'EXACT_RUNTIME_SOURCE_ONLY',
        source_ref_ids: [sourceRefId],
        file_ids: [],
      });
    }

    const postDetachEvidence = await requireNativeFileDeleteUnreferenced({
      files: [file], userId, models: mongoose.models, nativeDb: db,
    });
    const runtimeCandidates = await runtimeProjectSourceRetirementCandidates({ projectId, key });
    if (!runtimeCandidates.response.ok) {
      return res.status(runtimeCandidates.response.status).json(runtimeCandidates.body);
    }
    const execution = await executeCrossStorePermanentDelete({
      files: [file],
      projectId,
      runtimeCandidates: runtimeCandidates.body,
      nativeReferenceEvidence: postDetachEvidence,
      userId,
      recheckNativeReferences: (rows) =>
        requireNativeFileDeleteUnreferenced({
          files: rows, userId, models: mongoose.models, nativeDb: db,
        }),
      deleteNativeFiles: async (rows) => {
        const deletedFileIds = [];
        for (const row of rows) {
          await deleteNativeFileOrThrow({ req, file: row });
          deletedFileIds.push(row.file_id);
        }
        return { deletedFileIds, failedFileIds: [] };
      },
    });
    return res.status(200).json({
      schema: 'LC_PROJECT_SOURCE_PERMANENT_DELETE_R001',
      native_file_deleted: true,
      runtime_source_retired: true,
      binding_class: execution.plan.bindingClass,
      source_ref_ids: execution.plan.sourceRefIds,
      file_ids: execution.plan.nativeFileIds,
      binding_evidence_sha256: execution.plan.bindingEvidenceSha256,
      preflight_reference_evidence_sha256: preflightEvidence?.referenceEvidenceSha256 ?? null,
      post_detach_reference_evidence_sha256: postDetachEvidence.referenceEvidenceSha256,
    });
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : 409;
    return res.status(status).json({
      code: error?.code || 'PROJECT_PERMANENT_DELETE_FAILED',
      message: error?.message || 'Permanent Project Source deletion failed closed.',
    });
  }
}

async function proxyRuntimeProjectLibraryRemove(req, res) {
  const { projectId, sourceRefId } = req.params;
  if (!isValidObjectIdString(projectId) || typeof sourceRefId !== 'string' || !sourceRefId) {
    return res.status(404).json({ error: 'Project or source not found' });
  }
  const userId = getUserId(req);
  const project = await db.getChatProject(userId, projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const expectedProjectRevision = req.body?.expected_project_revision;
  if (!Number.isInteger(expectedProjectRevision) || expectedProjectRevision < 1) {
    return res.status(400).json({ error: 'Invalid Project source revision' });
  }
  const key = runtimeKey();
  if (!key) {
    return res.status(503).json({ error: 'Runtime Project Library unavailable' });
  }
  try {
    const result = await runtimeProjectLibraryRemove({
      projectId,
      sourceRefId,
      expectedProjectRevision,
      key,
    });
    if (!result.response.ok) {
      return res.status(result.response.status).json(result.body);
    }
    try {
      await unbindNativeFileSource({ userId, sourceRefId });
    } catch (_) {
      return res.status(500).json({
        error: 'PROJECT_NATIVE_FILE_SOURCE_UNBIND_PENDING_REPAIR',
        retryAutomatically: false,
      });
    }
    res.set('Cache-Control', 'no-store');
    return res.status(result.response.status).json(await enrichRuntimeLibrary(req, result.body));
  } catch (_) {
    return res.status(502).json({ error: 'Runtime Project Library bridge unavailable' });
  }
}

async function proxyRuntimeProjectAssistantProfile(req, res) {
  const { projectId } = req.params;
  if (!isValidObjectIdString(projectId)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  const project = await db.getChatProject(getUserId(req), projectId);
  if (!project) {
    return res.status(404).json({ error: 'Project not found' });
  }
  try {
    const presentation = await fetchProjectAssistantProfileBinding(projectId);
    res.set('Cache-Control', 'no-store');
    return res.json({
      schema: 'UR_LIBRECHAT_PROJECT_ASSISTANT_PROFILE_PRESENTATION_R001',
      initialized: presentation.initialized,
      project_revision: presentation.projectRevision,
      binding: presentation.binding,
    });
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : 502;
    return res.status(status).json({ error: error?.message || 'Runtime Project Assistant Profile bridge unavailable' });
  }
}

// Native LibreChat owns POST '/' Project creation. Do not register a second
// Project create handler here; this router only serves Runtime-specific suffixes.
router.get('/:projectId/runtime-instructions', (req, res) =>
  proxyRuntimeProjectInstructions(req, res, 'GET'),
);
router.put('/:projectId/runtime-instructions', (req, res) =>
  proxyRuntimeProjectInstructions(req, res, 'PUT'),
);
router.get('/:projectId/runtime-context-policy', (req, res) =>
  proxyRuntimeProjectContextPolicy(req, res, 'GET'),
);
router.put('/:projectId/runtime-context-policy', (req, res) =>
  proxyRuntimeProjectContextPolicy(req, res, 'PUT'),
);
router.use('/:projectId/runtime-library', configMiddleware);
router.get('/:projectId/runtime-library', proxyRuntimeProjectLibrary);
router.get('/:projectId/runtime-library/native-files', proxyRuntimeProjectNativeFileCatalog);
router.get('/:projectId/runtime-library/chat-files', proxyRuntimeProjectChatFileCatalog);
router.post(
  '/:projectId/runtime-library/document',
  express.raw({ type: () => true, limit: '15mb' }),
  proxyRuntimeProjectLibraryNativeDocument,
);
router.post(
  '/:projectId/runtime-library/from-native-file/:fileId',
  proxyRuntimeProjectLibraryFromNativeFile,
);
router.post(
  '/:projectId/runtime-library/from-chat-file/:messageId/:fileId',
  proxyRuntimeProjectLibraryFromChatFile,
);
router.post('/:projectId/runtime-library/from-message/:messageId', proxyRuntimeProjectLibrarySaveFromMessage);
router.get(
  '/:projectId/runtime-library/source-retirement-candidates',
  proxyRuntimeProjectSourceRetirementCandidates,
);
router.post(
  '/:projectId/runtime-library/source/:sourceRefId/permanent-delete',
  proxyRuntimeProjectLibraryPermanentDelete,
);
router.post('/:projectId/runtime-library/source/:sourceRefId/remove', proxyRuntimeProjectLibraryRemove);
router.get('/:projectId/runtime-assistant-profile', proxyRuntimeProjectAssistantProfile);
router.get('/:projectId/runtime-memory', (req, res) =>
  proxyRuntimeProjectMemory(req, res, 'GET'),
);
router.post('/:projectId/runtime-memory', (req, res) =>
  proxyRuntimeProjectMemory(req, res, 'POST'),
);
router.put('/:projectId/runtime-memory/:memoryId', (req, res) =>
  proxyRuntimeProjectMemory(req, res, 'PUT', `/${encodeURIComponent(req.params.memoryId)}`),
);
router.post('/:projectId/runtime-memory/:memoryId/enabled', (req, res) =>
  proxyRuntimeProjectMemory(req, res, 'POST', `/${encodeURIComponent(req.params.memoryId)}/enabled`),
);
router.delete('/:projectId/runtime-memory/:memoryId', (req, res) =>
  proxyRuntimeProjectMemory(req, res, 'DELETE', `/${encodeURIComponent(req.params.memoryId)}`),
);

module.exports = router;
