'use strict';
const crypto = require('crypto');

/* Owner-scoped pre-delete admissibility check over the EXISTING native
 * LibreChat models. This is not a new File store/delete engine. All evidence
 * is queried live immediately before the existing processDeleteRequest call.
 * Fail closed on a missing consumer, malformed metadata or unknown result. */
const MAX_NATIVE_DELETE_BATCH = 2000;
const DYNAMIC_REF_SCAN_LIMIT = 2000;

class NativeFileDeleteReferenceStop extends Error {
  constructor(code) {
    super(code);
    this.name = 'NativeFileDeleteReferenceStop';
    this.code = code;
    this.status = 409;
  }
}
const stop = (code) => { throw new NativeFileDeleteReferenceStop(code); };
const validCount = (n) => Number.isSafeInteger(n) && n >= 0;

async function requireNativeFileDeleteUnreferenced({
  files,
  userId,
  models,
  nativeDb,
  allowedProjectSourceRefsByFileId = {},
}) {
  if (!Array.isArray(files) || files.length < 1 || files.length > MAX_NATIVE_DELETE_BATCH ||
      !userId || !models || !nativeDb ||
      typeof nativeDb.getSharedResourceFileIds !== 'function') {
    stop('NATIVE_FILE_DELETE_SCOPE_UNPROVEN');
  }
  const ids = files.map((file) => file?.file_id);
  if (ids.some((id) => typeof id !== 'string' || !id) ||
      new Set(ids).size !== ids.length ||
      files.some((file) => String(file?.user ?? '') !== String(userId) ||
        typeof file?.filepath !== 'string' || !file.filepath)) {
    stop('NATIVE_FILE_DELETE_OWNER_OR_IDENTITY_UNPROVEN');
  }
  if (!allowedProjectSourceRefsByFileId || typeof allowedProjectSourceRefsByFileId !== 'object' || Array.isArray(allowedProjectSourceRefsByFileId)) {
    stop('NATIVE_FILE_DELETE_ALLOWED_PROJECT_REF_SCOPE_UNKNOWN');
  }
  for (const file of files) {
    const metadata = file?.metadata ?? {};
    if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata) ||
        (metadata.projectSourceRefs != null && !Array.isArray(metadata.projectSourceRefs))) {
      stop('NATIVE_FILE_DELETE_PROJECT_REF_METADATA_UNKNOWN');
    }
    if (metadata.pendingLibreChatProjectId != null) {
      stop('NATIVE_FILE_DELETE_PROJECT_REFERENCES_ACTIVE');
    }
    const actual = metadata.projectSourceRefs || [];
    const allowed = allowedProjectSourceRefsByFileId[file.file_id] || [];
    if (!Array.isArray(allowed) || allowed.some((row) =>
      !row || typeof row !== 'object'
      || typeof row.librechat_project_id !== 'string'
      || typeof row.runtime_project_id !== 'string'
      || typeof row.source_ref_id !== 'string'
    )) stop('NATIVE_FILE_DELETE_ALLOWED_PROJECT_REF_SCOPE_UNKNOWN');
    const key = (row) => `${row.librechat_project_id}\u0000${row.runtime_project_id}\u0000${row.source_ref_id}`;
    const actualKeys = actual.map(key).sort();
    const allowedKeys = allowed.map(key).sort();
    if (
      actualKeys.length !== allowedKeys.length
      || actualKeys.some((value, index) => value !== allowedKeys[index])
    ) stop('NATIVE_FILE_DELETE_PROJECT_REFERENCES_ACTIVE');
  }
  const wanted = ['File', 'Message', 'Conversation', 'Assistant', 'SharedLink', 'ToolCall'];
  for (const key of wanted) {
    if (!models[key] || typeof models[key].countDocuments !== 'function') {
      stop('NATIVE_FILE_DELETE_REFERENCE_OWNER_MISSING');
    }
  }
  const q = { $in: ids };
  const [
    messageRefs, conversationRefs, assistantRefs, sharedLinks,
    toolCallRefs, runFileRefs, codeEnvRefs, dynamicCodeRefs, agentHeld,
  ] = await Promise.all([
    models.Message.countDocuments({ 'files.file_id': q }),
    // LibreChat's resendFiles is Boolean; file_ids is the native String[] ref.
    // Keep older files refs checked, never cast FileIDs into Boolean settings.
    models.Conversation.countDocuments({ $or: [
      { files: q }, { file_ids: q },
    ] }),
    models.Assistant.countDocuments({ $or: [
      { file_ids: q },
      { 'tool_resources.file_search.file_ids': q },
      { 'tool_resources.code_interpreter.file_ids': q },
    ] }),
    models.SharedLink.countDocuments({ $or: [
      { 'messages.files.file_id': q },
      { 'message.files.file_id': q },
      { 'files.file_id': q },
      { 'file_ids': q },
    ] }),
    models.ToolCall.countDocuments({ $or: [
      { 'files.file_id': q }, { 'file_ids': q },
    ] }),
    models.File.countDocuments({ $or: [
      { 'metadata.runFile.sourceFileId': q },
      { 'metadata.runFile.inputFileIds': q },
    ] }),
    models.File.countDocuments({ 'metadata.codeEnvRef.file_id': q }),
    models.File.find({ 'metadata.codeEnvRefs': { $exists: true } })
      .limit(DYNAMIC_REF_SCAN_LIMIT + 1).select('metadata.codeEnvRefs').lean(),
    nativeDb.getSharedResourceFileIds({ file_ids: ids }),
  ]);
  const counts = [
    messageRefs, conversationRefs, assistantRefs, sharedLinks,
    toolCallRefs, runFileRefs, codeEnvRefs,
  ];
  if (!counts.every(validCount) || !Array.isArray(dynamicCodeRefs) ||
      dynamicCodeRefs.length > DYNAMIC_REF_SCAN_LIMIT || !Array.isArray(agentHeld)) {
    stop('NATIVE_FILE_DELETE_REFERENCE_SCAN_INCOMPLETE');
  }
  if (counts.some((n) => n > 0) || agentHeld.length > 0) {
    stop('NATIVE_FILE_DELETE_ACTIVE_NATIVE_CONSUMER');
  }
  for (const row of dynamicCodeRefs) {
    const refs = row?.metadata?.codeEnvRefs;
    if (!refs || typeof refs !== 'object' || Array.isArray(refs)) {
      stop('NATIVE_FILE_DELETE_CODE_ENV_MAP_UNKNOWN');
    }
    for (const item of Object.values(refs)) {
      if (item == null) continue;
      if (!item || typeof item !== 'object' || typeof item.file_id !== 'string') {
        stop('NATIVE_FILE_DELETE_CODE_ENV_REF_UNKNOWN');
      }
      if (ids.includes(item.file_id)) stop('NATIVE_FILE_DELETE_CODE_ENV_REFERENCED');
    }
  }
  const evidence = {
    schema: 'LC_NATIVE_FILE_DELETE_REFERENCE_EVIDENCE_R001',
    checked_file_ids: [...ids].sort(),
    message_reference_count: messageRefs,
    conversation_reference_count: conversationRefs,
    assistant_reference_count: assistantRefs,
    shared_link_reference_count: sharedLinks,
    tool_call_reference_count: toolCallRefs,
    run_file_reference_count: runFileRefs,
    code_env_reference_count: codeEnvRefs,
    dynamic_code_env_rows_scanned: dynamicCodeRefs.length,
    agent_held_file_ids: [...agentHeld].sort(),
  };
  const referenceEvidenceSha256 = crypto
    .createHash('sha256')
    .update(JSON.stringify(evidence))
    .digest('hex');
  return {
    permitted: true,
    checkedFileIds: ids,
    externalRefCounts: {
      current_chat: messageRefs + conversationRefs,
      agents: agentHeld.length,
      assistants: assistantRefs,
      shared_links: sharedLinks,
      native_other_files: runFileRefs + codeEnvRefs,
      external_consumers: toolCallRefs,
    },
    referenceEvidence: evidence,
    referenceEvidenceSha256,
  };
}

module.exports = { requireNativeFileDeleteUnreferenced, NativeFileDeleteReferenceStop };
