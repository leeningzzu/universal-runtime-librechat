'use strict';
/**
 * C5 whole-Project effect owners for the current LibreChat process.
 *
 * Thin composition only: native Mongo models own Project/Chat/File references;
 * the existing Adapter/Runtime owns target-Project Job, writer and protected
 * recovery admission. No second DB, file store, scheduler or delete engine.
 * Unsupported or ambiguous physical owners fail closed before mutation.
 */
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const NATIVE_ID = /^[a-f0-9]{24}$/i;
const FILE_ID = /^[A-Za-z0-9_-]{1,256}$/;
const MAX_FILES = 2000;
const RUNTIME_ADAPTER_BASE = String(
  process.env.UR_RUNTIME_ADAPTER_BASE || 'http://ur-runtime-adapter:9000',
).replace(/\/$/, '');
const LOCAL_ROOTS = ['/app/uploads/', '/app/client/public/images/'];
const LOGICAL_LOCAL_ROOTS = Object.freeze([
  { logical: '/uploads/', physical: '/app/uploads/' },
  { logical: '/images/', physical: '/app/client/public/images/' },
]);

class C5OwnerStop extends Error {
  constructor(code) {
    super(code);
    this.name = 'C5OwnerStop';
    this.code = code;
  }
}
const need = (condition, code) => {
  if (!condition) throw new C5OwnerStop(code);
};
const id = (value) => String(value ?? '');
const isPlain = (value) => value && typeof value === 'object' && !Array.isArray(value);

function safeLocalPath(value, expectedOwnerId = '') {
  if (typeof value !== 'string' || !path.posix.isAbsolute(value) || value.includes('\0')) return null;
  if (!NATIVE_ID.test(expectedOwnerId)) return null;
  const normalized = path.posix.normalize(value);
  for (const { logical, physical } of LOGICAL_LOCAL_ROOTS) {
    const physicalOwnerRoot = physical + expectedOwnerId + '/';
    if (normalized.startsWith(physicalOwnerRoot)) return normalized;
    const logicalOwnerRoot = logical + expectedOwnerId + '/';
    if (!normalized.startsWith(logicalOwnerRoot)) continue;
    const relative = normalized.slice(logicalOwnerRoot.length);
    if (!relative) return null;
    const resolved = path.posix.normalize(physicalOwnerRoot + relative);
    return resolved.startsWith(physicalOwnerRoot) ? resolved : null;
  }
  return null;
}
function logicalLocalPath(value, expectedOwnerId) {
  const physical = safeLocalPath(value, expectedOwnerId);
  if (!physical || !NATIVE_ID.test(expectedOwnerId)) return null;
  for (const { logical, physical: physicalRoot } of LOGICAL_LOCAL_ROOTS) {
    const ownerRoot = physicalRoot + expectedOwnerId + '/';
    if (!physical.startsWith(ownerRoot)) continue;
    const relative = physical.slice(ownerRoot.length);
    return relative ? logical + expectedOwnerId + '/' + relative : null;
  }
  return null;
}
function configuredStorageOwnerUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return false;
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol) &&
      !parsed.username && !parsed.password && parsed.pathname === '/';
  } catch {
    return false;
  }
}

function createC5WholeProjectDeleteOwners({ request, models, nativeDb, fetchImpl = globalThis.fetch }) {
  const projectId = id(request?.params?.projectId);
  const ownerId = id(request?.user?.id ?? request?.user?._id);
  need(NATIVE_ID.test(projectId) && NATIVE_ID.test(ownerId), 'C5_NATIVE_OWNER_SCOPE_REQUIRED');
  need(models && nativeDb && typeof nativeDb.getSharedResourceFileIds === 'function',
    'C5_CURRENT_NATIVE_MODELS_REQUIRED');
  for (const name of ['ChatProject', 'Conversation', 'File', 'Message', 'Assistant']) {
    need(models[name] && typeof models[name].find === 'function' &&
      typeof models[name].countDocuments === 'function', 'C5_NATIVE_MODEL_MISSING_' + name);
  }
  need(typeof fetchImpl === 'function', 'C5_CURRENT_ADAPTER_FETCH_REQUIRED');
  const writeFence = request?.app?.locals?.aidesC5WriteFence;
  need(writeFence && ['acquire', 'acquirePrepare', 'assertHeld', 'release'].every((name) =>
    typeof writeFence[name] === 'function'), 'C5_LIBRECHAT_WRITE_FENCE_REQUIRED');
  const key = String(process.env.UR_SHELL_ADAPTER_KEY || '');
  need(key.length >= 12, 'C5_EXISTING_ADAPTER_AUTH_KEY_REQUIRED');
  const base = new URL(RUNTIME_ADAPTER_BASE);
  need(base.protocol === 'http:' && base.pathname === '/' && !base.username && !base.password &&
    ['ur-runtime-adapter', 'ur-web-r004-daily-adapter-r005', '127.0.0.1'].includes(base.hostname),
  'C5_CURRENT_ADAPTER_ORIGIN_INVALID');

  const sealed = new Map();
  let currentRevision = null;
  let currentLeaseId = null;
  let currentMembershipSha256 = null;
  let knownMissing = new Set();
  let prepareFenceHeld = false;
  let directForwardGuardPrepared = false;

  async function adapterJson(method, endpoint, payload, {
    allowAccepted = false, nativeOwnerVerified = false,
  } = {}) {
    let response;
    try {
      response = await fetchImpl(base.origin + endpoint, {
        method,
        headers: {
          Accept: 'application/json',
          Authorization: 'Bearer ' + key,
          'Content-Type': 'application/json',
          'X-LibreChat-Project-ID': projectId,
          'X-LibreChat-Authenticated-User-ID': ownerId,
          ...(nativeOwnerVerified === true ? {
            'X-C5-Native-Owner-Verified': 'C5_CURRENT_LIBRECHAT_NATIVE_OWNER_VERIFIED_R001',
          } : {}),
        },
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
        redirect: 'error',
        cache: 'no-store',
      });
    } catch {
      throw new C5OwnerStop('C5_ADAPTER_EFFECT_OWNER_OUTCOME_UNKNOWN');
    }
    let result;
    try { result = await response.json(); }
    catch { throw new C5OwnerStop('C5_ADAPTER_EFFECT_OWNER_RESULT_UNREADABLE'); }
    need(isPlain(result), 'C5_ADAPTER_EFFECT_OWNER_RESULT_INVALID');
    if (response?.status !== 200 &&
        !(allowAccepted === true && response?.status === 202)) {
      // Preserve only a bounded first-party C5 control code. Never surface raw
      // paths, backup contents, stack traces, provider text or arbitrary errors.
      const candidate = String(
        result?.detail?.code || result?.code || result?.error?.code || '',
      );
      if (/^C5_[A-Z0-9_]{1,120}$/.test(candidate)) {
        throw new C5OwnerStop(candidate);
      }
      throw new C5OwnerStop('C5_ADAPTER_EFFECT_OWNER_REJECTED');
    }
    return result;
  }

  const C5_PREPARE_OPERATION_RE = /^C5PREP_[0-9A-F]{64}$/;

  function assertAsyncPrepareResponse(result, expectedOperation = null) {
    need(result?.schema === 'AIDES_C5_PROTECTED_BACKUP_PREPARE_OPERATION_R001' &&
      C5_PREPARE_OPERATION_RE.test(String(result.operationId || '')) &&
      (expectedOperation == null || result.operationId === expectedOperation) &&
      ['PREPARING','BACKUP_VERIFIED','FAILED_PRE_EFFECT',
       'INTERRUPTED_OR_UNKNOWN'].includes(result.phase) &&
      typeof result.backupVerified === 'boolean' &&
      result.backupVerified === (result.phase === 'BACKUP_VERIFIED') &&
      result.retryAutomatically === false &&
      Number.isInteger(result.recordRevision) && result.recordRevision >= 1 &&
      (result.lastFailureCode == null ||
        /^C5_[A-Z0-9_]{1,120}$/.test(result.lastFailureCode)),
    'C5_PREPARE_PERSISTED_OPERATION_INVALID');
    return result;
  }

  async function nativeMembership(chatIds, { postEffect = false } = {}) {
    need(Array.isArray(chatIds) && chatIds.length <= 2000 &&
      chatIds.every((value) => typeof value === 'string' && value.length > 0) &&
      new Set(chatIds).size === chatIds.length && typeof postEffect === 'boolean',
    'C5_NATIVE_MEMBERSHIP_INPUT_INVALID');
    const expected = [...chatIds].sort();
    if (!postEffect) {
      const [project, rows] = await Promise.all([
        models.ChatProject.findOne({ _id: projectId, user: ownerId })
          .select('_id user').lean(),
        models.Conversation.find({ user: ownerId, chatProjectId: projectId })
          .limit(2001).select('conversationId user chatProjectId').lean(),
      ]);
      need(project && id(project._id) === projectId && id(project.user) === ownerId &&
        Array.isArray(rows) && rows.length <= 2000,
      'C5_NATIVE_PROJECT_OWNER_OR_MEMBERSHIP_UNAVAILABLE');
      const actual = rows.map((row) => {
        need(id(row.user) === ownerId && row.chatProjectId === projectId &&
          typeof row.conversationId === 'string' && row.conversationId.length > 0,
        'C5_NATIVE_PROJECT_CHAT_MEMBERSHIP_INVALID');
        return row.conversationId;
      }).sort();
      need(new Set(actual).size === actual.length && actual.length === expected.length &&
        actual.every((value, index) => value === expected[index]),
      'C5_NATIVE_PROJECT_MEMBERSHIP_CHANGED');
    } else {
      // The first-party Project delete legitimately removes the Project row and
      // unassigns its Chats before C5 deletes those Chats. Preserve the sealed
      // original membership digest while proving that no member was moved,
      // re-owned, or newly assigned during the effect.
      const [project, rows, assigned] = await Promise.all([
        models.ChatProject.findOne({ _id: projectId }).select('_id user').lean(),
        models.Conversation.find({ conversationId: { $in: expected } })
          .limit(2001).select('conversationId user chatProjectId').lean(),
        models.Conversation.countDocuments({ chatProjectId: projectId }),
      ]);
      need(project == null && Array.isArray(rows) && rows.length <= expected.length &&
        Number.isSafeInteger(assigned) && assigned === 0,
      'C5_NATIVE_POST_EFFECT_PROJECT_OR_ASSIGNMENT_REMAINS');
      const seen = new Set();
      for (const row of rows) {
        need(typeof row.conversationId === 'string' && expected.includes(row.conversationId) &&
          !seen.has(row.conversationId) && id(row.user) === ownerId &&
          (row.chatProjectId == null || row.chatProjectId === ''),
        'C5_NATIVE_POST_EFFECT_CHAT_MOVED_OR_REOWNED');
        seen.add(row.conversationId);
      }
    }
    return crypto.createHash('sha256').update(JSON.stringify(expected)).digest('hex');
  }

  async function mongoWriteCounters() {
    const admin = models.File?.db?.db?.admin?.();
    need(admin && typeof admin.serverStatus === 'function',
      'C5_NATIVE_MONGO_WRITE_COUNTER_OWNER_UNAVAILABLE');
    const status = await admin.serverStatus();
    const counters = status?.opcounters;
    need(counters && ['insert', 'update', 'delete'].every((key) =>
      Number.isSafeInteger(counters[key]) && counters[key] >= 0),
    'C5_NATIVE_MONGO_WRITE_COUNTERS_INVALID');
    return {
      insert: counters.insert,
      update: counters.update,
      delete: counters.delete,
    };
  }

  const sameCounters = (left, right) => ['insert','update','delete'].every((key) =>
    Number.isSafeInteger(left?.[key]) && left[key] >= 0 && left[key] === right?.[key]);

  function isConfirmedPrepareRequest() {
    const fullPath = request?.originalUrl?.split('?')[0] || request?.path || '';
    return request?.method === 'POST' &&
      fullPath === `/api/projects/${projectId}/c5-whole-delete/prepare` &&
      request?.body?.confirmedIrreversibleProjectDelete === true &&
      request?.body?.deleteProtectionPolicy === 'FORWARD_ONLY_DURABLE_RECEIPT_R001' &&
      request?.headers?.['x-c5-delete-protection-policy'] ===
        'FORWARD_ONLY_DURABLE_RECEIPT_R001';
  }

  async function admission(phase, payload) {
    const result = await adapterJson('POST', '/v1/runtime-project-c5-admission', {
      phase,
      projectId,
      ownerId,
      ...(currentLeaseId ? { leaseId: currentLeaseId } : {}),
      ...payload,
    });
    need(result.schema === 'AIDES_C5_TARGET_PROJECT_ADMISSION_R001' &&
      result.projectId === projectId && result.ownerId === ownerId &&
      result.jobScope === 'TARGET_PROJECT_CURRENT_EFFECTS' &&
      typeof result.permitted === 'boolean' &&
      typeof result.exclusiveWriter === 'boolean' &&
      typeof result.forwardRecoveryReady === 'boolean' &&
      result.protectedBackupReady === false && result.backupCreated === false &&
      result.protectionMode === 'FORWARD_ONLY_DURABLE_RECEIPT_R001' &&
      Number.isInteger(result.activePinnedJobs) && result.activePinnedJobs >= 0 &&
      Number.isInteger(result.projectRevision) && result.projectRevision > 0 &&
      typeof result.projectMembershipSealed === 'boolean' &&
      typeof result.mongoWriteCountersMatchBackup === 'boolean' &&
      result.mongoWriteCountersAdmitted === true &&
      Number.isInteger(result.runtimeCurrentRevision) &&
      result.runtimeCurrentRevision >= result.projectRevision &&
      typeof result.projectMembershipSha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(result.projectMembershipSha256) &&
      typeof result.leaseId === 'string' && /^[A-Za-z0-9_-]{16,128}$/.test(result.leaseId) &&
      Array.isArray(result.knownMissingOriginalFileIds) &&
      result.knownMissingOriginalFileIds.length <= MAX_FILES &&
      result.knownMissingOriginalFileIds.every((value) => FILE_ID.test(value)),
    'C5_ADAPTER_TARGET_PROJECT_ADMISSION_INVALID');
    if (currentLeaseId !== null) {
      need(result.leaseId === currentLeaseId, 'C5_ADMISSION_LEASE_CHANGED');
    }
    currentLeaseId = result.leaseId;
    currentMembershipSha256 = result.projectMembershipSha256;
    knownMissing = new Set(result.knownMissingOriginalFileIds);
    currentRevision = result.projectRevision;
    return result;
  }

  async function fileState(fileId, targetChats) {
    need(FILE_ID.test(fileId), 'C5_NATIVE_FILE_ID_INVALID');
    const [rows, messages, assistants, runRows, codeRows, dynamicRows, agentHeld] = await Promise.all([
      models.File.find({ file_id: fileId })
        .limit(2001).select('file_id user conversationId filepath source bytes embedded metadata').lean(),
      models.Message.find({ 'files.file_id': fileId })
        .limit(2001).select('user conversationId files').lean(),
      models.Assistant.find({ file_ids: fileId })
        .limit(2001).select('_id user file_ids').lean(),
      models.File.find({ $or: [
        { 'metadata.runFile.sourceFileId': fileId },
        { 'metadata.runFile.inputFileIds': fileId },
      ] }).limit(2001).select('file_id user metadata.runFile').lean(),
      models.File.find({ 'metadata.codeEnvRef.file_id': fileId })
        .limit(2001).select('file_id user metadata.codeEnvRef').lean(),
      models.File.find({ 'metadata.codeEnvRefs': { $exists: true } })
        .limit(2001).select('file_id user metadata.codeEnvRefs').lean(),
      nativeDb.getSharedResourceFileIds({ file_ids: [fileId] }),
    ]);
    need([rows, messages, assistants, runRows, codeRows, dynamicRows].every(Array.isArray) &&
      [rows, messages, assistants, runRows, codeRows, dynamicRows].every((x) => x.length <= 2000) &&
      Array.isArray(agentHeld) && agentHeld.every((x) => FILE_ID.test(x)),
    'C5_NATIVE_FILE_REFERENCE_READ_INCOMPLETE');

    let dynamicCodeStorageRef = false;
    let dynamicCodeDependentRef = false;
    for (const row of dynamicRows) {
      const refs = row?.metadata?.codeEnvRefs;
      need(isPlain(refs), 'C5_NATIVE_CODE_ENV_REFERENCE_MAP_INVALID');
      for (const ref of Object.values(refs)) {
        if (ref == null) continue;
        need(isPlain(ref) && FILE_ID.test(ref.file_id), 'C5_NATIVE_CODE_ENV_REFERENCE_INVALID');
        if (ref.file_id === fileId) {
          if (row.file_id === fileId) dynamicCodeStorageRef = true;
          else dynamicCodeDependentRef = true;
        }
      }
    }
    const legacyCodeStorageRef = codeRows.some((row) => row.file_id === fileId);
    const legacyCodeDependentRef = codeRows.some((row) => row.file_id !== fileId);
    const vectorOwnerAvailable = configuredStorageOwnerUrl(process.env.RAG_API_URL);
    const codeEnvOwnerAvailable = configuredStorageOwnerUrl(process.env.LIBRECHAT_CODE_BASEURL);

    const refs = [];
    const localPaths = new Set();
    const storageSources = new Set();
    let ownedTargetRow = false;
    let unboundOwnedRows = 0;
    let bytes = 0;
    let embedded = false;
    let vectorDeleteRequired = false;
    let codeEnvDeleteRequired = legacyCodeStorageRef || dynamicCodeStorageRef;
    let unsupportedStorage = false;
    for (const row of rows) {
      const rowOwner = id(row.user);
      const chat = id(row.conversationId);
      if (rowOwner === ownerId && targetChats.has(chat)) {
        refs.push({ kind: 'chat', id: chat });
        ownedTargetRow = true;
      } else if (rowOwner === ownerId && !chat) {
        unboundOwnedRows += 1;
      } else {
        refs.push({ kind: 'native-file-row', id: id(row._id ?? row.file_id) || 'unknown' });
      }
      if (Number.isSafeInteger(row.bytes) && row.bytes >= 0) bytes = Math.max(bytes, row.bytes);
      if (typeof row.source === 'string' && row.source) storageSources.add(row.source);
      embedded = embedded || row.embedded === true;
      vectorDeleteRequired = vectorDeleteRequired || row.embedded === true || row.source === 'vectordb';
      codeEnvDeleteRequired = codeEnvDeleteRequired || row.source === 'execute_code';
      const local = safeLocalPath(row.filepath, rowOwner);
      if (local) localPaths.add(local);
      else if (row.source === 'text') { /* metadata-only native text */ }
      else if (row.source === 'vectordb' && vectorOwnerAvailable) { /* RAG owner */ }
      else if (row.source === 'execute_code' && codeEnvOwnerAvailable && codeEnvDeleteRequired) {
        /* Code API storage owner */
      } else unsupportedStorage = true;
    }

    let targetMessageCount = 0;
    for (const row of messages) {
      const chat = id(row.conversationId);
      const targetMessage = targetChats.has(chat) && id(row.user) === ownerId;
      const links = Array.isArray(row.files) ? row.files.filter((x) => x?.file_id === fileId) : [];
      need(links.length > 0, 'C5_NATIVE_MESSAGE_FILE_REFERENCE_MALFORMED');
      if (targetMessage) targetMessageCount += 1;
      refs.push(targetMessage ? { kind: 'chat', id: chat } : { kind: 'native-message', id: chat || 'unknown' });
      for (const link of links) {
        if (!targetMessage) continue;
        const local = safeLocalPath(link.filepath, ownerId);
        if (local) localPaths.add(local);
        if (typeof link.source === 'string' && link.source) storageSources.add(link.source);
        if (Number.isSafeInteger(link.bytes) && link.bytes >= 0) bytes = Math.max(bytes, link.bytes);
      }
    }
    const allMessagesTarget = messages.length > 0 && targetMessageCount === messages.length;
    if (unboundOwnedRows > 0) {
      if (allMessagesTarget) ownedTargetRow = true;
      else refs.push({ kind: 'native-file-row', id: fileId });
    }
    const messageOnlyTargetOwned = rows.length === 0 && allMessagesTarget;
    const ownedTargetStorage = ownedTargetRow || messageOnlyTargetOwned;

    if (assistants.length > 0) refs.push({ kind: 'assistant', id: 'shared' });
    if (agentHeld.includes(fileId)) refs.push({ kind: 'agent', id: 'shared' });
    if (runRows.length > 0) refs.push({ kind: 'run-file', id: 'shared' });
    if (legacyCodeDependentRef || dynamicCodeDependentRef) refs.push({ kind: 'code-env', id: 'shared' });

    const knownMissingOriginal = knownMissing.has(fileId);
    if (knownMissingOriginal) {
      need(rows.length === 0 && localPaths.size === 0, 'C5_KNOWN_MISSING_NATIVE_BYTES_REAPPEARED');
    }
    for (const value of localPaths) {
      try {
        const stat = await fs.lstat(value);
        if (!stat.isFile()) unsupportedStorage = true;
        else if (Number.isSafeInteger(stat.size) && stat.size >= 0) bytes = Math.max(bytes, stat.size);
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error;
        if (!knownMissingOriginal) unsupportedStorage = true;
      }
    }
    if (messageOnlyTargetOwned && localPaths.size === 0 && !knownMissingOriginal) unsupportedStorage = true;
    if (storageSources.size > 1) unsupportedStorage = true;

    const uniqueRefs = [...new Map(refs.map((ref) => [ref.kind + ':' + ref.id, ref])).values()];
    return {
      fileId,
      refs: uniqueRefs,
      rows,
      paths: [...localPaths],
      bytes: knownMissingOriginal ? 0 : bytes,
      source: storageSources.size === 1 ? [...storageSources][0] : null,
      embedded,
      vectorDeleteRequired,
      vectorOwnerAvailable,
      codeEnvDeleteRequired,
      codeEnvOwnerAvailable,
      ownedTargetRow,
      ownedTargetStorage,
      messageOnlyTargetOwned,
      unsupportedStorage,
      knownMissingOriginal,
    };
  }
  async function readCompleteProjectFileGraph({
    projectId: p, ownerId: u, chatIds, expectedProjectRevision,
  }) {
    need(p === projectId && u === ownerId && Array.isArray(chatIds) &&
      chatIds.length <= 2000 && chatIds.every((x) => typeof x === 'string' && x.length > 0) &&
      new Set(chatIds).size === chatIds.length && expectedProjectRevision === currentRevision,
    'C5_FILE_GRAPH_SCOPE_OR_REVISION_CHANGED');
    const targetChats = new Set(chatIds);
    const [fileRows, messageRows, runtime] = await Promise.all([
      models.File.find({ user: ownerId, conversationId: { $in: chatIds } })
        .limit(2001).select('file_id').lean(),
      models.Message.find({ user: ownerId, conversationId: { $in: chatIds } })
        .limit(2001).select('files').lean(),
      adapterJson('GET', '/v1/runtime-project-c5-source-ref-inventory'),
    ]);
    need(fileRows.length <= 2000 && messageRows.length <= 2000 &&
      runtime.schema === 'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001' &&
      runtime.nativeProjectId === projectId && runtime.actorId === ownerId &&
      runtime.sourceRefsProvenComplete === true &&
      runtime.runtimeProjectRevision === expectedProjectRevision &&
      Array.isArray(runtime.sources) && runtime.sources.length === runtime.sourceRefCount &&
      runtime.sources.every((row) => row && typeof row.source_ref_id === 'string' &&
        /^SRC_[A-Z0-9]{8,64}$/.test(row.source_ref_id) &&
        typeof row.source_sha256 === 'string' && /^[0-9a-f]{64}$/.test(row.source_sha256)) &&
      Array.isArray(runtime.retirementSources) &&
      runtime.retirementSources.length === runtime.retirementSourceCount &&
      typeof runtime.protectedAssetCensusSha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(runtime.protectedAssetCensusSha256) &&
      runtime.retirementSources.length <= 2000 &&
      runtime.retirementSources.every((row) => row &&
        typeof row.source_ref_id === 'string' &&
        /^SRC_[A-Z0-9]{8,64}$/.test(row.source_ref_id) &&
        typeof row.origin_input_sha256 === 'string' &&
        /^[0-9a-f]{64}$/.test(row.origin_input_sha256) &&
        Number.isInteger(row.origin_input_byte_size) &&
        row.origin_input_byte_size > 0 &&
        typeof row.active_project_binding === 'boolean' &&
        ['ACTIVE','DETACHED_RETAINED','CONTENT_RETIRED'].includes(row.retirement_state)),
    'C5_RUNTIME_OR_NATIVE_FILE_GRAPH_NOT_CURRENT');
    const ids = new Set();
    for (const row of fileRows) need(FILE_ID.test(row.file_id) && (ids.add(row.file_id), true),
      'C5_NATIVE_PROJECT_FILE_ID_INVALID');
    for (const row of messageRows) {
      need(row.files === undefined || Array.isArray(row.files), 'C5_NATIVE_MESSAGE_FILES_INVALID');
      for (const file of row.files || []) {
        need(FILE_ID.test(file?.file_id), 'C5_NATIVE_MESSAGE_FILE_ID_INVALID');
        ids.add(file.file_id);
      }
    }
    need(ids.size <= MAX_FILES, 'C5_NATIVE_PROJECT_FILE_GRAPH_UNBOUNDED');
    const files = [];
    sealed.clear();
    for (const fileId of ids) {
      const state = await fileState(fileId, targetChats);
      sealed.set(fileId, state);
      const onlyTargetRefs = state.refs.length > 0 && state.refs.every((ref) =>
        ref.kind === 'chat' && targetChats.has(ref.id));
      const independentLibrary = !state.ownedTargetStorage && !state.knownMissingOriginal;
      const retentionReason = state.unsupportedStorage
        ? 'UNSUPPORTED_STORAGE_OWNER'
        : independentLibrary
          ? 'INDEPENDENT_LIBRARY_OR_UNBOUND_FILE'
          : !onlyTargetRefs
            ? 'SHARED_OR_EXTERNAL_REFERENCE'
            : 'PROTECTED_OR_UNVERIFIED';
      const logicalPaths = state.paths.map((value) => logicalLocalPath(value, ownerId));
      need(logicalPaths.every(Boolean) && new Set(logicalPaths).size === logicalPaths.length,
        'C5_DURABLE_LOGICAL_FILE_PATH_UNAVAILABLE');
      files.push({
        id: fileId,
        ownerId,
        refs: state.refs,
        refsComplete: true,
        bytes: state.bytes,
        protected: state.unsupportedStorage,
        backupProtected: false,
        independentLibrary,
        vectorRefsProven: !state.vectorDeleteRequired || state.vectorOwnerAvailable,
        agentRefsProven: true,
        runtimeSourceRefsProven: !state.codeEnvDeleteRequired || state.codeEnvOwnerAvailable,
        nativeChatAnchor: state.ownedTargetStorage && onlyTargetRefs,
        retentionReason,
        seal: {
          schema: 'C5_NATIVE_FILE_SEAL_R001',
          rowPresent: state.rows.length > 0,
          ownedTargetStorage: state.ownedTargetStorage,
          messageOnlyTargetOwned: state.messageOnlyTargetOwned,
          knownMissingOriginal: state.knownMissingOriginal,
          bytes: state.bytes,
          logicalPaths,
          source: state.source,
          vectorDeleteRequired: state.vectorDeleteRequired,
          vectorOwnerAvailable: state.vectorOwnerAvailable,
          codeEnvDeleteRequired: state.codeEnvDeleteRequired,
          codeEnvOwnerAvailable: state.codeEnvOwnerAvailable,
          unsupportedStorage: state.unsupportedStorage,
          refs: state.refs,
        },
        ...(state.knownMissingOriginal ? {
          knownMissingOriginal: true,
          originalRecoveryState: 'KNOWN_MISSING_NOT_RESTORED',
        } : {}),
      });
    }
    return {
      authoritative: true,
      complete: true,
      projectId,
      ownerId,
      projectRevision: expectedProjectRevision,
      // Reuse the exact Runtime Project/Source/Memory projection already read
      // for this file graph. Cold Prepare must not issue two additional serial
      // Adapter/Runtime reads for the same revision.
      runtimeCurrentReferences: runtime,
      runtimeSources: runtime.retirementSources
        .filter((row) => row.active_project_binding === true)
        .map((row) => ({
          source_ref_id: row.source_ref_id,
          source_sha256: row.origin_input_sha256,
        })),
      protectedAssetCensusSha256: runtime.protectedAssetCensusSha256,
      files,
    };
  }
  async function recheckExclusiveFile({ projectId: p, ownerId: u, fileId, plan }) {
    need(p === projectId && u === ownerId && plan?.projectId === p,
      'C5_RECHECK_FILE_SCOPE_CHANGED');
    const chats = new Set(plan.chats);
    const prior = sealed.get(fileId);
    need(prior, 'C5_DURABLE_FILE_SEAL_NOT_RESTORED');
    const state = await fileState(fileId, chats);
    const priorOnlyTarget = prior.refs.length > 0 && prior.refs.every((ref) =>
      ref.kind === 'chat' && chats.has(ref.id));
    const currentOtherConsumer = state.refs.some((ref) =>
      ref.kind !== 'native-file-row' && !(ref.kind === 'chat' && chats.has(ref.id)));
    const noOther = priorOnlyTarget && !currentOtherConsumer;
    return {
      authoritative: true,
      refsComplete: true,
      noOtherConsumers: noOther && !prior.unsupportedStorage &&
        (!prior.vectorDeleteRequired || prior.vectorOwnerAvailable) &&
        (!prior.codeEnvDeleteRequired || prior.codeEnvOwnerAvailable),
      ownerAuthorized: prior.ownedTargetStorage || prior.knownMissingOriginal,
    };
  }
  async function restoreDurableFileSeals({ projectId: p, ownerId: u, plan, snapshot }) {
    need(p === projectId && u === ownerId && plan?.projectId === p &&
      snapshot?.projectId === p && snapshot?.ownerId === u &&
      snapshot?.planSha256 === plan.planSha256 && Array.isArray(snapshot.files),
    'C5_DURABLE_FILE_SEAL_RESTORE_SCOPE_INVALID');
    const expected = new Set([
      ...plan.exclusive.map((file) => file.id),
      ...plan.retained.map((file) => file.id),
    ]);
    need(snapshot.files.length === expected.size,
      'C5_DURABLE_FILE_SEAL_RESTORE_CARDINALITY_CHANGED');
    sealed.clear();
    for (const file of snapshot.files) {
      need(expected.has(file.id) && file.seal?.schema === 'C5_NATIVE_FILE_SEAL_R001',
        'C5_DURABLE_FILE_SEAL_RESTORE_ROW_INVALID');
      const paths = file.seal.logicalPaths.map((value) => safeLocalPath(value, ownerId));
      need(paths.every(Boolean) && paths.length === file.seal.logicalPaths.length,
        'C5_DURABLE_FILE_SEAL_PATH_RESTORE_FAILED');
      sealed.set(file.id, {
        fileId: file.id,
        refs: file.seal.refs.map((ref) => ({ kind: ref.kind, id: ref.id })),
        rows: file.seal.rowPresent ? [{ file_id: file.id, user: ownerId }] : [],
        paths,
        bytes: file.seal.bytes,
        source: file.seal.source,
        vectorDeleteRequired: file.seal.vectorDeleteRequired,
        vectorOwnerAvailable: file.seal.vectorOwnerAvailable,
        codeEnvDeleteRequired: file.seal.codeEnvDeleteRequired,
        codeEnvOwnerAvailable: file.seal.codeEnvOwnerAvailable,
        ownedTargetRow: file.seal.rowPresent && file.seal.ownedTargetStorage,
        ownedTargetStorage: file.seal.ownedTargetStorage,
        messageOnlyTargetOwned: file.seal.messageOnlyTargetOwned,
        unsupportedStorage: file.seal.unsupportedStorage,
        knownMissingOriginal: file.seal.knownMissingOriginal,
      });
    }
    return true;
  }

  async function readSealedNativeFileDeleteDescriptor({ projectId: p, ownerId: u, fileId }) {
    need(p === projectId && u === ownerId && FILE_ID.test(fileId),
      'C5_SEALED_FILE_DESCRIPTOR_SCOPE_INVALID');
    const prior = sealed.get(fileId);
    need(prior, 'C5_SEALED_FILE_DESCRIPTOR_MISSING');
    if (prior.knownMissingOriginal || prior.paths.length === 0) return null;
    need(prior.paths.length === 1 && prior.ownedTargetStorage === true &&
      prior.unsupportedStorage === false,
    'C5_SEALED_FILE_DESCRIPTOR_AMBIGUOUS');
    const filepath = logicalLocalPath(prior.paths[0], ownerId);
    need(filepath, 'C5_SEALED_FILE_LOGICAL_PATH_UNAVAILABLE');
    return {
      file_id: fileId,
      user: ownerId,
      filepath,
      source: prior.source || 'local',
      c5SealedStorageOnly: true,
    };
  }

  async function verifyFileBytesAndDerivativesAbsent({ projectId: p, ownerId: u, fileId }) {
    need(p === projectId && u === ownerId, 'C5_VERIFY_FILE_OWNER_SCOPE_CHANGED');
    const prior = sealed.get(fileId);
    if (!prior) {
      // Never treat missing original metadata as proof of physical absence.
      // A still-live, sole owner File row establishes ONLY that cleanup remains
      // pending; the next scoped exclusive-file check must reseal its paths.
      const live = await fileState(fileId, new Set());
      need(live.rows.length === 1 && id(live.rows[0].user) === ownerId &&
        !live.unsupportedStorage &&
        (!live.vectorDeleteRequired || live.vectorOwnerAvailable) &&
        (!live.codeEnvDeleteRequired || live.codeEnvOwnerAvailable),
      'C5_SEALED_FILE_STATE_REQUIRED');
      return {
        authoritative: true, fileRecordAbsent: false, blobAbsent: false,
        vectorAbsent: false, codeEnvAbsent: false,
        agentReferencesAbsent: false, sourceReferencesAbsent: false,
      };
    }
    const current = await fileState(fileId, new Set());
    let pathsAbsent = true;
    for (const value of prior.paths) {
      try { await fs.lstat(value); pathsAbsent = false; }
      catch (error) { if (error?.code !== 'ENOENT') throw error; }
    }
    return {
      authoritative: true,
      fileRecordAbsent: current.rows.length === 0,
      blobAbsent: pathsAbsent && !prior.unsupportedStorage,
      // Native /api/files removes metadata only after its configured storage
      // strategy succeeds. Gate 2 additionally reads the isolated RAG/Code
      // owners directly; production keeps this fail-closed source contract.
      vectorAbsent: !prior.vectorDeleteRequired ||
        prior.vectorOwnerAvailable && current.rows.length === 0,
      codeEnvAbsent: (!prior.codeEnvDeleteRequired ||
        prior.codeEnvOwnerAvailable && current.rows.length === 0) &&
        !current.refs.some((ref) => ref.kind === 'code-env'),
      agentReferencesAbsent: !current.refs.some((ref) => ['agent', 'assistant'].includes(ref.kind)),
      sourceReferencesAbsent: !current.refs.some((ref) =>
        ['chat', 'native-message', 'run-file'].includes(ref.kind)),
    };
  }

  async function verifyRetainedFileBytesPresent({ projectId: p, ownerId: u, fileId }) {
    need(p === projectId && u === ownerId, 'C5_RETAINED_FILE_OWNER_SCOPE_CHANGED');
    const prior = sealed.get(fileId);
    need(prior, 'C5_RETAINED_FILE_SEALED_STATE_REQUIRED');
    const current = await fileState(fileId, new Set());
    let bytesPresent = current.rows.length > 0;
    if (prior.paths.length > 0) {
      bytesPresent = false;
      for (const value of prior.paths) {
        try { if ((await fs.lstat(value)).isFile()) bytesPresent = true; }
        catch (error) { if (error?.code !== 'ENOENT') throw error; }
      }
    }
    return {
      authoritative: true,
      retained: current.refs.length > 0 || current.rows.length > 0,
      bytesPresent,
      legalOtherReferenceStillPresent: current.refs.some((ref) => ref.kind !== 'chat') ||
        current.rows.length > 0,
    };
  }

  async function verifyCrossPlaneNoReferences({ projectId: p, ownerId: u, plan }) {
    need(p === projectId && u === ownerId && plan?.projectId === p,
      'C5_FINAL_REFERENCE_OWNER_SCOPE_CHANGED');
    const runtime = await adapterJson('GET', '/v1/runtime-project-c5-source-ref-inventory');
    const runtimeClear = runtime.runtimeProjectStatus === 'RETIRED' &&
      runtime.sourceRefsProvenComplete === true && runtime.sourceRefCount === 0 &&
      runtime.visibleMemoryCount === 0 && runtime.projectInstructionsCurrentEmpty === true;
    return {
      authoritative: true,
      allOwnedReferencesCleared: runtimeClear,
      allRetainedReferencesIntact: true,
      unknownReferences: runtimeClear ? 0 : 1,
    };
  }

  const admissionOwner = {
    currentOperationId: () => currentLeaseId,
    async proveInventoryFence({ projectId: p, ownerId: u, chatIds, phase = 'C5_INVENTORY' }) {
      need(p === projectId && u === ownerId, 'C5_ADMISSION_OWNER_SCOPE_CHANGED');
      const requestPath = request?.originalUrl?.split('?')[0] || request?.path || '';
      if (request?.method === 'POST' &&
          requestPath === `/api/projects/${projectId}/c5-whole-delete/prepare`) {
        need(isConfirmedPrepareRequest(), 'C5_DIRECT_DELETE_POLICY_CONFIRMATION_REQUIRED');
      }
      try {
        const firstDirectGuard = isConfirmedPrepareRequest() && !directForwardGuardPrepared;
        if (firstDirectGuard) {
          writeFence.acquirePrepare({ request, projectId, ownerId });
          prepareFenceHeld = true;
        }
        const before = await nativeMembership(chatIds);
        const counters = await mongoWriteCounters();
        const result = await admission(phase, {
          chatIds,
          projectMembershipSha256: before,
          mongoWriteCounters: counters,
        });
        if (firstDirectGuard) {
          need(result.forwardRecoveryReady === true && result.permitted === true &&
            result.backupCreated === false && result.protectionMode ===
              'FORWARD_ONLY_DURABLE_RECEIPT_R001',
          'C5_DIRECT_FORWARD_RECOVERY_GUARD_NOT_READY');
          const bound = writeFence.bindPrepareOperation({
            request, projectId, ownerId, operationId: result.leaseId,
          });
          need(bound.operationId === result.leaseId && bound.sameFence === true,
            'C5_DIRECT_FORWARD_RECOVERY_FENCE_BIND_FAILED');
          directForwardGuardPrepared = true;
        }
        const after = await nativeMembership(chatIds);
        need(after === before && result.projectMembershipSha256 === before &&
          result.projectMembershipSealed === true &&
          result.forwardRecoveryReady === true &&
          result.mongoWriteCountersAdmitted === true,
        'C5_NATIVE_PROJECT_MEMBERSHIP_NOT_SEALED');
        return result;
      } catch (error) {
        if (prepareFenceHeld) await abortPreEffectAdmission({ projectId, ownerId });
        throw error;
      }
    },
    async recheckEffectFence({ projectId: p, ownerId: u, revision, phase, plan }) {
      need(p === projectId && u === ownerId &&
        Number.isInteger(revision) && revision > 0 && Array.isArray(plan?.chats),
      'C5_ADMISSION_REVISION_CHANGED');
      const recoveryBootstrap = currentRevision === null &&
        ['RECOVERY_READINESS', 'CONTINUE_PARTIAL'].includes(phase);
      need(currentRevision === null ? recoveryBootstrap : revision === currentRevision,
        'C5_ADMISSION_REVISION_CHANGED');
      if (phase === 'BEFORE_C5') {
        writeFence.acquire({ request, projectId, ownerId });
      } else if (['NATIVE_FILE_EFFECT', 'CONTINUE_PARTIAL',
        'C5_FINAL_ABSENCE_VERIFY'].includes(phase)) {
        writeFence.assertHeld({ request, projectId, ownerId });
      }
      const postEffect = ['RECOVERY_READINESS', 'NATIVE_FILE_EFFECT',
        'CONTINUE_PARTIAL', 'C5_FINAL_ABSENCE_VERIFY'].includes(phase);
      const membership = await nativeMembership(plan.chats, { postEffect });
      need(currentMembershipSha256 === null ? recoveryBootstrap :
        membership === currentMembershipSha256,
      'C5_NATIVE_PROJECT_MEMBERSHIP_CHANGED_AFTER_PREPARE');
      const counters = await mongoWriteCounters();
      const result = await admission(phase, {
        revision,
        planSha256: plan?.planSha256 ?? null,
        projectMembershipSha256: membership,
        mongoWriteCounters: counters,
      });
      need(result.projectRevision === revision &&
        result.projectMembershipSha256 === membership &&
        result.projectMembershipSealed === true &&
        result.forwardRecoveryReady === true &&
        result.mongoWriteCountersAdmitted === true,
      'C5_NATIVE_PROJECT_EFFECT_MEMBERSHIP_NOT_SEALED');
      return result;
    },
  };

  async function abortPreEffectAdmission({ projectId: p, ownerId: u }) {
    need(p === projectId && u === ownerId,
      'C5_PRE_EFFECT_ABORT_SCOPE_CHANGED');
    if (currentLeaseId !== null) {
      need(typeof currentMembershipSha256 === 'string' &&
        /^[0-9a-f]{64}$/.test(currentMembershipSha256) &&
        Number.isInteger(currentRevision) && currentRevision > 0,
      'C5_PRE_EFFECT_ABORT_LEASE_STATE_INVALID');
      const expectedLease = currentLeaseId;
      const counters = await mongoWriteCounters();
      const released = await admission('C5_PRE_EFFECT_ABORT_RELEASE', {
        revision: currentRevision,
        projectMembershipSha256: currentMembershipSha256,
        mongoWriteCounters: counters,
      });
      need(released.permitted === true && released.leaseReleased === true &&
        released.leaseId === expectedLease,
      'C5_PRE_EFFECT_ABORT_LEASE_RELEASE_UNCONFIRMED');
      currentLeaseId = null;
      currentMembershipSha256 = null;
      currentRevision = null;
      knownMissing = new Set();
    }
    writeFence.release({ projectId, ownerId });
    prepareFenceHeld = false;
    directForwardGuardPrepared = false;
    return true;
  }

  async function releaseEffectAdmission({ projectId: p, ownerId: u }) {
    need(p === projectId && u === ownerId,
      'C5_WRITE_FENCE_RELEASE_SCOPE_CHANGED');
    need(typeof currentLeaseId === 'string' && currentLeaseId.length >= 16 &&
      typeof currentMembershipSha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(currentMembershipSha256) &&
      Number.isInteger(currentRevision) && currentRevision > 0,
    'C5_RUNTIME_ADMISSION_LEASE_NOT_HELD_AT_COMPLETION');
    writeFence.assertHeld({ request, projectId, ownerId });
    const expectedLease = currentLeaseId;
    const counters = await mongoWriteCounters();
    const released = await admission('C5_COMPLETE_RELEASE', {
      revision: currentRevision,
      projectMembershipSha256: currentMembershipSha256,
      mongoWriteCounters: counters,
    });
    need(released.permitted === true && released.leaseReleased === true &&
      released.leaseId === expectedLease,
    'C5_RUNTIME_JOB_AUTHORITY_LEASE_RELEASE_UNCONFIRMED');
    currentLeaseId = null;
    prepareFenceHeld = false;
    directForwardGuardPrepared = false;
    return writeFence.release({ projectId, ownerId });
  }

  const referenceOwner = {
    readCompleteProjectFileGraph,
    restoreDurableFileSeals,
    readSealedNativeFileDeleteDescriptor,
    recheckExclusiveFile,
    verifyFileBytesAndDerivativesAbsent,
    verifyRetainedFileBytesPresent,
    verifyCrossPlaneNoReferences,
  };
  return { admissionOwner, referenceOwner, abortPreEffectAdmission, releaseEffectAdmission };
}

module.exports = { createC5WholeProjectDeleteOwners, C5OwnerStop, safeLocalPath };
