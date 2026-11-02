'use strict';
/**
 * P1 C5: One native LibreChat Project Delete user-consumer contract.
 * ISOLATED PRODUCT INTEGRATION CANDIDATE — NOT INSTALLED IN DAILY.
 *
 * Replace only the existing DELETE /api/projects/:projectId consumer after
 * the accepted Runtime Authority/admission and native 13-hook cascade owners
 * are legitimately bound. Readiness GET protects the UI from mistakenly
 * calling today's upstream unassign-only Delete; it is not the mutation fence.
 * Project-as-a-whole is irrevocable by user after verified completion;
 * standalone Chat/File 30-day restorable Trash is a different lifecycle.
 *
 * There is no new DB, search, scheduler, local executor or second shell.
 */
const PROJECT_ID = /^[a-f0-9]{24}$/i;

function stop(res, code, status = 409) {
  return res.status(status).json({
    status: 'C5_WHOLE_PROJECT_DELETE_UNVERIFIED',
    code,
    verified: false,
    retryAutomatically: false,
  });
}
function scope(req) {
  const projectId = String(req?.params?.projectId || '');
  const ownerId = String(req?.user?.id ?? req?.user?._id ?? '');
  if (!PROJECT_ID.test(projectId) || !ownerId || ownerId.length > 256) return null;
  return { projectId, ownerId };
}
// Client confirmation distinguishes irreversible C5 from the historic
// upstream DELETE that only unassigned Chats. These are intent markers,
// NOT authentication or permission; current native ownership plus the
// target-Project writer, Job, backup and reference fences remain mandatory.
const C5_DELETE_INTENT = 'CONFIRMED_C5_WHOLE_PROJECT_DELETE_R001';
const C5_DIRECT_POLICY = 'FORWARD_ONLY_DURABLE_RECEIPT_R001';
function confirmedWholeProjectDelete(req, ids) {
  return req?.headers?.['x-c5-irrevocable-project-delete'] === C5_DELETE_INTENT &&
    req?.body?.confirmedIrreversibleProjectDelete === true &&
    req?.body?.projectId === ids.projectId &&
    req?.body?.deleteProtectionPolicy === C5_DIRECT_POLICY &&
    req?.headers?.['x-c5-delete-protection-policy'] === C5_DIRECT_POLICY;
}
function confirmedDirectPrepare(req, ids) {
  return req?.body?.confirmedIrreversibleProjectDelete === true &&
    req?.body?.projectId === ids.projectId &&
    req?.body?.deleteProtectionPolicy === C5_DIRECT_POLICY &&
    req?.headers?.['x-c5-delete-protection-policy'] === C5_DIRECT_POLICY;
}

function currentReadiness(proof, ids) {
  return proof != null &&
    proof.scope === 'C5_WHOLE_PROJECT_IRREVERSIBLE' &&
    proof.projectId === ids.projectId &&
    proof.ownerId === ids.ownerId &&
    proof.sourceClass === 'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES' &&
    proof.nativeCascadeInstalled === true &&
    proof.exclusiveWriter === true &&
    proof.durableForwardRecoveryReady === true &&
    proof.projectMembershipSealed === true &&
    proof.activePinnedJobs === 0 &&
    /^C5LEASE_[A-Za-z0-9_-]{16,128}$/.test(String(proof.operationId || '')) &&
    Number.isInteger(proof.projectRevision) && proof.projectRevision > 0;
}
function completeProductProof(proof, ids) {
  return proof != null &&
    proof.projectId === ids.projectId &&
    proof.ownerId === ids.ownerId &&
    proof.sourceClass === 'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES' &&
    proof.projectAndRuntimeRetired === true &&
    proof.allOwnedChatsMessagesRemoved === true &&
    proof.sourceMemoryAndOwnedFileReferencesCleared === true &&
    proof.sourceContentsRetired === true &&
    proof.exclusiveBlobsAndIndexesVerified === true &&
    proof.movedChatAndSharedFilesRetained === true &&
    proof.allCrossPlaneReferencesVerified === true &&
    proof.userRecoverable === false &&
    Number.isInteger(proof.receiptRevision) && proof.receiptRevision > 0;
}
function createC5WholeProjectProductEndpoints({
  verifyNativeOwner, proveWholeProjectReadiness,
  verifyPointOfEffectAdmission, executeAcceptedC5Cascade,
  readCurrentDeletionStatus, verifyFinalProductDeletion, abortPreEffectAdmission,
}) {
  const methods = {
    verifyNativeOwner, proveWholeProjectReadiness,
    verifyPointOfEffectAdmission, executeAcceptedC5Cascade,
    readCurrentDeletionStatus, verifyFinalProductDeletion, abortPreEffectAdmission,
  };
  for (const [method, fn] of Object.entries(methods)) {
    if (typeof fn !== 'function') {
      throw new Error('C5_CURRENT_PRODUCT_OWNER_CALLBACK_MISSING_' + method);
    }
  }
  async function authorized(req) {
    const ids = scope(req);
    if (!ids) return null;
    // Must be the existing LibreChat native owner; never infer from Project name.
    const nativeOwner = await verifyNativeOwner(ids);
    if (nativeOwner?.owned !== true || nativeOwner.projectId !== ids.projectId ||
        nativeOwner.ownerId !== ids.ownerId) return null;
    return ids;
  }
  const boundedCode = (error, fallback) => {
    const candidate = String(error?.code || error?.message || '');
    return /^C5_[A-Z0-9_]{1,120}$/.test(candidate) ? candidate : fallback;
  };
  async function abortBeforeEffect(ids) {
    if (!ids) return true;
    return await abortPreEffectAdmission(ids);
  }

  async function readiness(req, res) {
    let ids = null;
    try {
      ids = await authorized(req);
      if (!ids) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
      if (!confirmedDirectPrepare(req, ids))
        return stop(res, 'C5_DIRECT_DELETE_POLICY_CONFIRMATION_REQUIRED');
      const proof = await proveWholeProjectReadiness(ids);
      if (!currentReadiness(proof, ids)) {
        await abortBeforeEffect(ids);
        return stop(res, 'C5_FULL_NATIVE_CASCADE_NOT_READY');
      }
      return res.status(200).json({
        status: 'C5_WHOLE_PROJECT_DELETE_READY',
        projectId: ids.projectId,
        wholeProjectCascadeReady: true,
        operationId: proof.operationId,
        protectionMode: C5_DIRECT_POLICY,
        backupCreated: false,
      });
    } catch (error) {
      try { await abortBeforeEffect(ids); }
      catch { return stop(res, 'C5_PRE_EFFECT_ABORT_RELEASE_UNCONFIRMED'); }
      return stop(res, boundedCode(error, 'C5_PROJECT_READINESS_OUTCOME_UNKNOWN'));
    }
  }
  async function status(req, res) {
    try {
      const ids = await authorized(req);
      if (!ids) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
      const state = await readCurrentDeletionStatus(ids);
      if (
        !state || state.projectId !== ids.projectId ||
        typeof state.projectRemoved !== 'boolean' ||
        typeof state.runtimeRetired !== 'boolean' ||
        typeof state.cleanupComplete !== 'boolean' ||
        (state.status !== 'C5_PROJECT_DELETE_NOT_STARTED' &&
          typeof state.sourceContentsRetired !== 'boolean') ||
        state.retryAutomatically === true
      ) return stop(res, 'C5_PROJECT_DELETE_STATUS_UNVERIFIED');
      return res.status(200).json({ ...state, retryAutomatically:false });
    } catch (error) {
      return stop(res, boundedCode(error, 'C5_PROJECT_DELETE_STATUS_UNAVAILABLE'));
    }
  }

  async function del(req, res) {
    const ids = scope(req);
    if (!ids) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
    if (!confirmedWholeProjectDelete(req, ids)) {
      // Old LibreChat Project Delete clients must never acquire irrevocable
      // Chat/File deletion semantics merely because the server was upgraded.
      return stop(res, 'C5_EXPLICIT_WHOLE_PROJECT_DELETE_CONFIRMATION_REQUIRED');
    }
    let effectMayHaveHappened = false;
    try {
      const owner = await authorized(req);
      if (!owner) {
        await abortBeforeEffect(ids);
        return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
      }
      const proof = await proveWholeProjectReadiness(ids);
      if (req.body?.c5PrepareOperationId !== proof.operationId) {
        await abortBeforeEffect(ids);
        return stop(res, 'C5_DIRECT_DELETE_OPERATION_CHANGED');
      }
      if (!currentReadiness(proof, ids)) {
        await abortBeforeEffect(ids);
        return stop(res, 'C5_FULL_NATIVE_CASCADE_NOT_READY');
      }
      // UI readiness is NOT authority. Recheck at the actual mutation point.
      const gate = await verifyPointOfEffectAdmission({ ...ids, proof });
      if (gate?.permitted !== true ||
          gate.projectId !== ids.projectId ||
          gate.ownerId !== ids.ownerId ||
          gate.projectRevision !== proof.projectRevision ||
          gate.exclusiveWriter !== true ||
          gate.durableForwardRecoveryReady !== true ||
          gate.operationId !== proof.operationId ||
          gate.activePinnedJobs !== 0) {
        await abortBeforeEffect(ids);
        return stop(res, 'C5_POINT_OF_EFFECT_SAFETY_UNPROVEN');
      }
      effectMayHaveHappened = true;
      const result = await executeAcceptedC5Cascade(req);
      // Native upstream deletedCount, PARTIAL, or a synthetic-only success
      // marker is not enough to show the user irreversible success.
      if (result?.httpStatus !== 200 ||
          result?.c5OperationPhase !== 'COMPLETE' ||
          result?.cascadeResultComplete !== true) {
        const candidate=String(result?.failureCode||'');
        return stop(res, /^C5_[A-Z0-9_]{1,120}$/.test(candidate)
          ? candidate : 'C5_PROJECT_DELETE_PARTIAL_OR_BLOCKED');
      }
      const verified = await verifyFinalProductDeletion({ ...ids, result });
      if (!completeProductProof(verified, ids))
        return stop(res, 'C5_PROJECT_DELETE_FINAL_VERIFICATION_UNPROVEN');
      return res.status(200).json({
        status: 'COMPLETE_VERIFIED_PROJECT_DELETE',
        projectId: ids.projectId,
        verified: true,
        cleanupComplete: true,
        sourceContentsRetired: verified.sourceContentsRetired === true,
        userRecoverable: false,
        retryAutomatically: false,
        receiptRevision: verified.receiptRevision,
      });
    } catch (error) {
      if (effectMayHaveHappened)
        return stop(res, 'C5_PROJECT_DELETE_EFFECT_OUTCOME_UNKNOWN');
      try { await abortBeforeEffect(ids); }
      catch { return stop(res, 'C5_PRE_EFFECT_ABORT_RELEASE_UNCONFIRMED'); }
      return stop(res, boundedCode(error, 'C5_PROJECT_DELETE_NO_EFFECT_CONFIRMED'));
    }
  }
  return { readiness, status, deleteProject: del };
}
module.exports = {
  createC5WholeProjectProductEndpoints, scope,
  currentReadiness, completeProductProof,
};
