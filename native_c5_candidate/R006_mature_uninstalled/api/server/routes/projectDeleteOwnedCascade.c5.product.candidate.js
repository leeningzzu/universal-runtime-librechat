'use strict';
// C5 scoped additive wrapper; the accepted C5 native handler, LibreChat native
// delete consumers and Runtime Project operation ledger remain the only owners.
// No general garbage collector, second database or alternate native route.
const crypto = require('node:crypto');

class CascadeStop extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = 'CascadeStop';
    this.code = code;
  }
}
const requireProof = (condition, code) => {
  if (!condition) throw new CascadeStop(code);
};
const digest = (value) =>
  crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const unique = (values) => new Set(values).size === values.length;

function classifyInventory(raw, projectId, ownerId) {
  requireProof(raw && raw.complete === true && raw.authoritative === true,
    'INVENTORY_NOT_AUTHORITATIVE');
  requireProof(raw.projectId === projectId && raw.ownerId === ownerId,
    'INVENTORY_OWNER_SCOPE');
  requireProof(Number.isInteger(raw.revision) && raw.revision > 0,
    'PROJECT_REVISION_INVALID');
  requireProof(raw.legalOwner === true && raw.uniqueWriter === true &&
    raw.consistentBackup === true && raw.activePinnedJobs === 0,
    'LEGAL_OWNER_BACKUP_OR_JOBS_NOT_CLEAR');
  requireProof(Array.isArray(raw.chats) && Array.isArray(raw.files),
    'INVENTORY_ENTRIES_INVALID');
  const chats = raw.chats.map((chat) => {
    requireProof(chat && typeof chat.id === 'string' && chat.id &&
      chat.ownerId === ownerId && chat.projectId === projectId &&
      chat.boundAtSnapshot === true, 'CHAT_OWNER_OR_PROJECT_UNPROVEN');
    return chat.id;
  });
  requireProof(unique(chats), 'DUPLICATE_CHAT_ID');
  const targetChats = new Set(chats);
  const exclusive = [];
  const retained = [];
  const ids = [];
  for (const f of raw.files) {
    requireProof(f && typeof f.id === 'string' && f.id &&
      Array.isArray(f.refs) && f.refsComplete === true,
      'FILE_REFERENCE_INVENTORY_INCOMPLETE');
    ids.push(f.id);
    const owned = f.ownerId === ownerId;
    const onlyTarget = f.refs.length > 0 && f.refs.every((ref) =>
      ref && ((ref.kind === 'project' && ref.id === projectId) ||
        (ref.kind === 'chat' && targetChats.has(ref.id))));
    const protectedFile = f.protected === true || f.backupProtected === true ||
      f.independentLibrary === true || !owned;
    const exclusiveEligible = owned && onlyTarget && !protectedFile;
    if (exclusiveEligible) {
      requireProof(Number.isSafeInteger(f.bytes) && f.bytes >= 0,
        'OWNED_FILE_BYTE_COUNT_INVALID');
      requireProof(f.vectorRefsProven === true && f.agentRefsProven === true &&
        f.runtimeSourceRefsProven === true, 'DERIVED_REFERENCE_OWNER_UNPROVEN');
      exclusive.push({ id: f.id, bytes: f.bytes,
        ...(f.nativeChatAnchor===true?{nativeChatAnchor:true}:{}) });
    } else {
      retained.push({ id: f.id });
    }
  }
  requireProof(unique(ids), 'DUPLICATE_FILE_ID');
  const plan = { projectId, ownerId, revision: raw.revision, chats,
    exclusive, retained };
  return { ...plan, planSha256: digest(plan) };
}
function buildProjectCascadeHandler(deps) {
  const hookNames = ['readNativeInventory', 'verifyPreEffectBoundary',
    'loadRuntimeOperationReceipt', 'saveRuntimeOperationReceipt',
    'runAcceptedC5NativeDelete', 'deleteNativeChat', 'verifyNativeChatAbsent',
    'assertNativeFileExclusivityNow', 'deleteNativeExclusiveFile',
    'verifyNativeFileAndDerivativesAbsent', 'verifyNativeRetainedFilePresent',
    'verifyNativeProjectAndRuntimeRetired', 'verifyNoDeletedObjectReferences'];
  for (const name of hookNames) {
    requireProof(typeof deps?.[name] === 'function', 'MISSING_OWNER_HOOK_' + name);
  }
  return async function projectCascade(req, res) {
    const ownerId = String(req?.user?.id || '');
    const projectId = String(req?.params?.projectId || '');
    const reply = (status, body) => res.status(status).json(body);
    if (!ownerId || !projectId) {
      return reply(401, { status: 'STOP', code: 'AUTHENTICATED_OWNER_REQUIRED' });
    }
    let op = null;
    let effectMayHaveHappened = false;
    try {
      op = await deps.loadRuntimeOperationReceipt({ projectId, ownerId });
      if (!op) {
        const inventory = await deps.readNativeInventory({ projectId, ownerId });
        const plan = classifyInventory(inventory, projectId, ownerId);
        requireProof(await deps.verifyPreEffectBoundary({ projectId, ownerId,
          plan, phase: 'BEFORE_EFFECT' }) === true,
          'EFFECT_ADMISSION_NOT_PROVEN');
        op = { schema: 'C5_PROJECT_CASCADE_R001', projectId, ownerId,
          plan, phase: 'PREPARED', c5Confirmed: false, deletedChats: [],
          deletedFiles: [] };
        requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
          'CANNOT_DURABLY_PREPARE_EXISTING_RUNTIME_RECEIPT');
      } else {
        requireProof(op.schema === 'C5_PROJECT_CASCADE_R001' &&
          op.projectId === projectId && op.ownerId === ownerId &&
          op.plan && op.plan.planSha256 === digest({
            projectId, ownerId, revision: op.plan.revision,
            chats: op.plan.chats, exclusive: op.plan.exclusive,
            retained: op.plan.retained,
          }), 'PRIOR_OPERATION_RECEIPT_MISMATCH');
      }
      const plan = op.plan;
      if (op.phase !== 'COMPLETE') {
        requireProof(await deps.verifyPreEffectBoundary({ projectId, ownerId,
          plan, phase: op.c5Confirmed || op.nativeEffectOutcomeUnknown === true ||
            op.phase === 'PARTIAL_OR_BLOCKED' ? 'CONTINUE_PARTIAL' : 'BEFORE_C5' }) === true,
          'CURRENT_OWNER_OR_WRITER_FENCE_LOST');
      }
      if (!op.c5Confirmed) {
        // Persist unknown-effect intent BEFORE native mutation, so lost HTTP
        // responses can never cause a second blind native Project DELETE.
        const unknownPriorEffect = op.nativeEffectOutcomeUnknown === true ||
          op.phase === 'PARTIAL_OR_BLOCKED';
        if (unknownPriorEffect) {
          requireProof(await deps.verifyNativeProjectAndRuntimeRetired({
            projectId, ownerId, plan }) === true,
            'C5_NATIVE_UNKNOWN_EFFECT_REQUIRES_OWNER_RECONCILIATION');
          op.c5Confirmed = true;
          op.nativeEffectOutcomeUnknown = false;
          op.phase = 'CASCADE_PENDING';
          requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
            'C5_NATIVE_RECONCILIATION_RECEIPT_NOT_DURABLE');
        } else {
          op.nativeEffectOutcomeUnknown = true;
          op.phase = 'PARTIAL_OR_BLOCKED';
          requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
            'C5_NATIVE_EFFECT_INTENT_RECEIPT_NOT_DURABLE');
          effectMayHaveHappened = true;
          const result = await deps.runAcceptedC5NativeDelete(req);
          requireProof(result && result.status === 200 &&
            result.nativeAndRuntimeConfirmed === true,
            'C5_NATIVE_RUNTIME_DELETE_NOT_CONFIRMED');
          op.c5Confirmed = true;
          op.nativeEffectOutcomeUnknown = false;
          op.phase = 'CASCADE_PENDING';
          requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
            'POST_C5_RECEIPT_NOT_PERSISTED');
        }
      }
      requireProof(await deps.verifyNativeProjectAndRuntimeRetired({ projectId,
        ownerId, plan }) === true, 'PROJECT_OR_RUNTIME_NOT_RETIRED');
      for (const chatId of plan.chats) {
        if (op.deletedChats.includes(chatId)) continue;
        const existing = await deps.verifyNativeChatAbsent({ ownerId, chatId });
        if (existing?.conversationAbsent === true) {
          requireProof(existing.messagesAbsent === true &&
            existing.toolCallsAbsent === true &&
            existing.sharedLinksAbsent === true,
            'C5_NATIVE_CHAT_ORPHANED_DERIVATIVES_REQUIRE_REPAIR');
          op.deletedChats.push(chatId);
          op.phase = 'CASCADE_PENDING';
          requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
            'C5_CHAT_RECOVERY_RECEIPT_NOT_DURABLE');
          continue;
        }
        effectMayHaveHappened = true;
        await deps.deleteNativeChat({ projectId, ownerId, chatId,
          source: 'C5_NATIVE_CONVERSATION_DELETE_OWNER' });
        const proved = await deps.verifyNativeChatAbsent({ ownerId, chatId });
        requireProof(proved && proved.conversationAbsent === true &&
          proved.messagesAbsent === true && proved.toolCallsAbsent === true &&
          proved.sharedLinksAbsent === true, 'NATIVE_CHAT_DERIVATIVES_REMAIN');
        op.deletedChats.push(chatId);
        op.phase = 'CASCADE_PENDING';
        requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
          'CHAT_DELETE_RECEIPT_NOT_DURABLE');
      }
      for (const file of plan.exclusive) {
        if (op.deletedFiles.includes(file.id)) continue;
        const existing = await deps.verifyNativeFileAndDerivativesAbsent({
          ownerId, fileId: file.id });
        if (existing?.fileRecordAbsent === true) {
          requireProof(existing.blobAbsent === true &&
            existing.vectorAbsent === true &&
            existing.codeEnvAbsent === true &&
            existing.agentReferencesAbsent === true &&
            existing.sourceReferencesAbsent === true,
            'C5_NATIVE_FILE_ORPHANED_DERIVATIVES_REQUIRE_REPAIR');
          op.deletedFiles.push(file.id);
          op.phase = 'CASCADE_PENDING';
          requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
            'C5_FILE_RECOVERY_RECEIPT_NOT_DURABLE');
          continue;
        }
        const admitted = await deps.assertNativeFileExclusivityNow({
          projectId, ownerId, fileId: file.id, plan });
        requireProof(admitted && admitted.refsComplete === true &&
          admitted.noOtherConsumers === true &&
          admitted.ownerAuthorized === true,
          'FILE_NOW_SHARED_OR_UNVERIFIED');
        effectMayHaveHappened = true;
        await deps.deleteNativeExclusiveFile({ ownerId, fileId: file.id,
          nativeStrategyRequired: true });
        const proved = await deps.verifyNativeFileAndDerivativesAbsent({
          ownerId, fileId: file.id });
        requireProof(proved && proved.fileRecordAbsent === true &&
          proved.blobAbsent === true && proved.vectorAbsent === true &&
          proved.codeEnvAbsent === true &&
          proved.agentReferencesAbsent === true &&
          proved.sourceReferencesAbsent === true,
          'FILE_METADATA_BLOB_OR_DERIVATIVES_REMAIN');
        op.deletedFiles.push(file.id);
        op.phase = 'CASCADE_PENDING';
        requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
          'FILE_DELETE_RECEIPT_NOT_DURABLE');
      }
      for (const file of plan.retained) {
        requireProof(await deps.verifyNativeRetainedFilePresent({
          ownerId, fileId: file.id, projectId }) === true,
          'SHARED_OR_PROTECTED_FILE_DAMAGED');
      }
      // Reverify even entries already marked complete in the existing Runtime
      // receipt: an earlier success marker cannot prove bytes never reappeared.
      for (const chatId of plan.chats) {
        const p = await deps.verifyNativeChatAbsent({ ownerId, chatId });
        requireProof(p && p.conversationAbsent === true &&
          p.messagesAbsent === true && p.toolCallsAbsent === true &&
          p.sharedLinksAbsent === true, 'PREVIOUS_CHAT_REMOVAL_NOT_CURRENT');
      }
      for (const file of plan.exclusive) {
        const p = await deps.verifyNativeFileAndDerivativesAbsent({
          ownerId, fileId: file.id });
        requireProof(p && p.fileRecordAbsent === true &&
          p.blobAbsent === true && p.vectorAbsent === true &&
          p.codeEnvAbsent === true &&
          p.agentReferencesAbsent === true &&
          p.sourceReferencesAbsent === true,
          'PREVIOUS_FILE_REMOVAL_NOT_CURRENT');
      }
      requireProof(await deps.verifyNoDeletedObjectReferences({
        ownerId, projectId, plan }) === true, 'CROSS_PLANE_ORPHANS_UNVERIFIED');
      op.phase = 'COMPLETE';
      requireProof(await deps.saveRuntimeOperationReceipt(op) === true,
        'COMPLETE_RECEIPT_NOT_DURABLE');
      // Source object bytes come from sealed PRE-DELETE inventory. They are
      // not measured host free-space; Mongo/disk can retain allocated blocks.
      const formerObjectBytes = plan.exclusive.reduce((a, f) => a + f.bytes, 0);
      return reply(200, { status: 'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE',
        removedNativeChats: plan.chats.length,
        verifiedExclusiveFileObjectsAbsent: plan.exclusive.length,
        formerlyRecordedExclusiveObjectBytesEstimate: formerObjectBytes,
        hostDiskBytesFreedProven: null,
        preservedNonExclusiveFiles: plan.retained.length,
        note: 'Verified File/Blob/vector/CodeEnv absence, not actual host free-space delta or protected-backup expiry' });
    } catch (error) {
      const code = error instanceof CascadeStop ? error.code : 'NATIVE_CONSUMER_EXCEPTION';
      if (op) {
        op.phase = 'PARTIAL_OR_BLOCKED';
        op.lastFailureCode = code;
        try { await deps.saveRuntimeOperationReceipt(op); } catch (_) {}
      }
      return reply(effectMayHaveHappened || op?.c5Confirmed ? 202 : 409, {
        status: effectMayHaveHappened || op?.c5Confirmed ? 'PARTIAL' : 'STOP',
        code, success: false, retryAutomatically: false });
    }
  };
}
module.exports = { buildProjectCascadeHandler, classifyInventory, CascadeStop };
