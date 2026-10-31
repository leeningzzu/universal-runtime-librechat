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
function currentReadiness(proof, ids) {
  return proof != null &&
    proof.scope === 'C5_WHOLE_PROJECT_IRREVERSIBLE' &&
    proof.projectId === ids.projectId &&
    proof.ownerId === ids.ownerId &&
    proof.sourceClass === 'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES' &&
    proof.nativeCascadeInstalled === true &&
    proof.exclusiveWriter === true &&
    proof.coherentProtectedBackup === true &&
    proof.projectMembershipSealed === true &&
    proof.activePinnedJobs === 0 &&
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
    proof.exclusiveBlobsAndIndexesVerified === true &&
    proof.movedChatAndSharedFilesRetained === true &&
    proof.allCrossPlaneReferencesVerified === true &&
    proof.userRecoverable === false &&
    Number.isInteger(proof.receiptRevision) && proof.receiptRevision > 0;
}
function createC5WholeProjectProductEndpoints({
  verifyNativeOwner, proveWholeProjectReadiness,
  verifyPointOfEffectAdmission, executeAcceptedC5Cascade,
  verifyFinalProductDeletion,
}) {
  const methods = {
    verifyNativeOwner, proveWholeProjectReadiness,
    verifyPointOfEffectAdmission, executeAcceptedC5Cascade,
    verifyFinalProductDeletion,
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
  async function readiness(req, res) {
    try {
      const ids = await authorized(req);
      if (!ids) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
      const proof = await proveWholeProjectReadiness(ids);
      if (!currentReadiness(proof, ids))
        return stop(res, 'C5_FULL_NATIVE_CASCADE_NOT_READY');
      return res.status(200).json({
        status: 'C5_WHOLE_PROJECT_DELETE_READY',
        projectId: ids.projectId,
        wholeProjectCascadeReady: true,
      });
    } catch {
      return stop(res, 'C5_PROJECT_READINESS_OUTCOME_UNKNOWN');
    }
  }
  async function del(req, res) {
    const ids = scope(req);
    if (!ids) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
    let effectMayHaveHappened = false;
    try {
      const owner = await authorized(req);
      if (!owner) return stop(res, 'C5_PROJECT_OWNER_UNVERIFIED', 404);
      const proof = await proveWholeProjectReadiness(ids);
      if (!currentReadiness(proof, ids))
        return stop(res, 'C5_FULL_NATIVE_CASCADE_NOT_READY');
      // UI readiness is NOT authority. Recheck at the actual mutation point.
      const gate = await verifyPointOfEffectAdmission({ ...ids, proof });
      if (gate?.permitted !== true ||
          gate.projectId !== ids.projectId ||
          gate.ownerId !== ids.ownerId ||
          gate.projectRevision !== proof.projectRevision ||
          gate.exclusiveWriter !== true ||
          gate.coherentProtectedBackup !== true ||
          gate.activePinnedJobs !== 0)
        return stop(res, 'C5_POINT_OF_EFFECT_SAFETY_UNPROVEN');
      effectMayHaveHappened = true;
      const result = await executeAcceptedC5Cascade(req);
      // Native upstream deletedCount, PARTIAL, or a synthetic-only success
      // marker is not enough to show the user irreversible success.
      if (result?.httpStatus !== 200 ||
          result?.c5OperationPhase !== 'COMPLETE' ||
          result?.cascadeResultComplete !== true)
        return stop(res, 'C5_PROJECT_DELETE_PARTIAL_OR_BLOCKED');
      const verified = await verifyFinalProductDeletion({ ...ids, result });
      if (!completeProductProof(verified, ids))
        return stop(res, 'C5_PROJECT_DELETE_FINAL_VERIFICATION_UNPROVEN');
      return res.status(200).json({
        status: 'COMPLETE_VERIFIED_PROJECT_DELETE',
        projectId: ids.projectId,
        verified: true,
        userRecoverable: false,
        receiptRevision: verified.receiptRevision,
      });
    } catch {
      return stop(res, effectMayHaveHappened
        ? 'C5_PROJECT_DELETE_EFFECT_OUTCOME_UNKNOWN'
        : 'C5_PROJECT_DELETE_NO_EFFECT_CONFIRMED');
    }
  }
  return { readiness, deleteProject: del };
}
module.exports = {
  createC5WholeProjectProductEndpoints, scope,
  currentReadiness, completeProductProof,
};
