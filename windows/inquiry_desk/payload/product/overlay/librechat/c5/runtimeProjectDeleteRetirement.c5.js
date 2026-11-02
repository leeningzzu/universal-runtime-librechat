const crypto = require('crypto');

function stableRetirementId(projectId, runtimeRevision) {
  return 'RETIRE_' + crypto
    .createHash('sha256')
    .update(String(projectId) + '|' + String(runtimeRevision))
    .digest('hex')
    .slice(0, 24)
    .toUpperCase();
}

function createProjectDeleteRetirementHandler({
  getRuntimeProject,
  prepareRuntimeRetirement,
  confirmRuntimeLibreChatDeleted,
  abortRuntimeRetirement,
  commitRuntimeRetirement,
  deleteLibreChatProject,
  isNativeOwnerAuthorized,
  verifyNativeDeletionComplete,
}) {
  return async function deleteProjectWithRetirement(req, res) {
    const projectId = String(req.params?.projectId || '');
    const ownerId = String(req.user?.id || req.user?._id || '');
    if (!ownerId) return res.status(401).json({ error: 'Authenticated user required' });
    const runtime = await getRuntimeProject(projectId);
    // A canonical Runtime absence is a positive read-only result from
    // existing Runtime state readers, not an API outage or guessed 404.
    // In that case keep the exact stable LibreChat native Project Delete UX.
    if (runtime?.found === false && runtime.native_only_verified === true) {
      if (!(await isNativeOwnerAuthorized(req))) {
        return res.status(404).json({ error: 'Project not found' });
      }
      const refreshed = await getRuntimeProject(projectId);
      if (refreshed?.found !== false || refreshed.native_only_verified !== true) {
        return res.status(409).json({ error: 'Project Runtime state changed' });
      }
      let deleted;
      try {
        deleted = await deleteLibreChatProject(req);
      } catch (error) {
        return res.status(error?.c5_pre_effect_proven === true
          ? (error?.status || 503) : 202).json({
          error: 'Native Project delete outcome unverified',
          native_delete_outcome: 'UNKNOWN',
          retry_required: true,
        });
      }
      try {
        const verified = await verifyNativeDeletionComplete(req);
        if (verified?.complete !== true) throw new Error('NATIVE_DELETE_INCOMPLETE');
      } catch (_) {
        return res.status(202).json({
          error: 'Native Project deletion cannot yet be confirmed',
          native_delete_outcome: 'INCOMPLETE',
          retry_required: true,
        });
      }
      return res.json({ ...deleted, native_only: true, runtime_retirement: 'NOT_APPLICABLE' });
    }
    if (!runtime || !Number.isInteger(runtime.project_revision)) {
      return res.status(409).json({ error: 'Runtime Project state unavailable' });
    }

    if (runtime.status === 'ACTIVE') {
      if (!(await isNativeOwnerAuthorized(req))) {
        return res.status(404).json({ error: 'Project not found' });
      }
    } else {
      const retirement = runtime.retirement || {};
      const preparedRevision = retirement.prepared_from_project_revision;
      if (!Number.isInteger(preparedRevision) ||
          retirement.retirement_id !== stableRetirementId(projectId + '|' + ownerId, preparedRevision)) {
        return res.status(404).json({ error: 'Project not found' });
      }
    }
    if (runtime.status === 'RETIRED') {
      return res.json({
        retirement_id: runtime.retirement?.retirement_id || null,
        retirement_state: 'RETIRED',
        already_retired: true,
      });
    }

    const pending = runtime.status === 'RETIRE_PENDING' ? runtime.retirement : null;
    const retirementId =
      pending?.retirement_id || stableRetirementId(projectId + '|' + ownerId, runtime.project_revision);

    if (!pending) {
      try {
        await prepareRuntimeRetirement({
          projectId,
          retirementId,
          expectedProjectRevision: runtime.project_revision,
        });
      } catch (error) {
        return res.status(error?.status || 409).json({
          error: error?.message || 'Project retirement prepare failed',
        });
      }
    } else if (pending.phase === 'LIBRECHAT_DELETED') {
      try {
        const verified = await verifyNativeDeletionComplete(req);
        if (verified?.complete !== true) {
          return res.status(202).json({
            retirement_id: retirementId,
            retirement_state: 'RETIRE_PENDING',
            retry_required: true,
            native_delete_outcome: 'INCOMPLETE',
          });
        }
        const committed = await commitRuntimeRetirement({ projectId, retirementId });
        return res.json({
          retirement_id: retirementId,
          retirement_state: committed?.project?.status || 'RETIRED',
          resumed_commit: true,
        });
      } catch (error) {
        return res.status(202).json({
          retirement_id: retirementId,
          retirement_state: 'RETIRE_PENDING',
          retry_required: true,
          error: error?.message || 'Runtime retirement commit incomplete',
        });
      }
    } else if (pending.phase !== 'PREPARED') {
      return res.status(409).json({
        error: 'Runtime Project retirement state is unsupported',
        retirement_id: retirementId,
        retirement_state: runtime.status,
      });
    }

    let deleted = {};
    try {
      deleted = await deleteLibreChatProject(req);
    } catch (error) {
      if (error?.status !== 404) {
        // The native stable delete updates Conversation and Project in
        // concurrent operations. A generic 5xx/transport error cannot prove
        // that neither side effect occurred. Never ABORT an unknown outcome.
        if (error?.c5_pre_effect_proven !== true) {
          return res.status(202).json({
            retirement_id: retirementId,
            retirement_state: 'RETIRE_PENDING',
            retry_required: true,
            native_delete_outcome: 'UNKNOWN',
          });
        }
        try {
          await abortRuntimeRetirement({
            projectId,
            retirementId,
            reasonCode: 'LIBRECHAT_DELETE_FAILED',
          });
        } catch (_) {
          return res.status(503).json({
            error: 'Project delete failed and Runtime retirement abort could not be confirmed',
            retirement_id: retirementId,
            retirement_state: 'RETIRE_PENDING',
          });
        }
        return res.status(error?.status || 500).json({
          error: error?.message || 'Project delete failed',
          retirement_id: retirementId,
          retirement_state: 'ACTIVE_RESTORED',
        });
      }
      deleted = { already_deleted: true };
    }

    // A native 200 or retry 404 alone is insufficient: the other side of
    // upstream Promise.all could have failed. Verify native Project absence
    // AND all owner-scoped conversations unassigned before CONFIRM/COMMIT.
    try {
      const verified = await verifyNativeDeletionComplete(req);
      if (verified?.complete !== true) throw new Error('NATIVE_DELETE_INCOMPLETE');
    } catch (_) {
      return res.status(202).json({
        retirement_id: retirementId,
        retirement_state: 'RETIRE_PENDING',
        retry_required: true,
        native_delete_outcome: 'INCOMPLETE',
      });
    }

    try {
      await confirmRuntimeLibreChatDeleted({ projectId, retirementId });
    } catch (error) {
      return res.status(202).json({
        ...deleted,
        retirement_id: retirementId,
        retirement_state: 'RETIRE_PENDING',
        retry_required: true,
        error: error?.message || 'LibreChat deletion confirmation incomplete',
      });
    }

    try {
      const committed = await commitRuntimeRetirement({ projectId, retirementId });
      return res.json({
        ...deleted,
        retirement_id: retirementId,
        retirement_state: committed?.project?.status || 'RETIRED',
      });
    } catch (error) {
      return res.status(202).json({
        ...deleted,
        retirement_id: retirementId,
        retirement_state: 'RETIRE_PENDING',
        retry_required: true,
        error: error?.message || 'Runtime retirement commit incomplete',
      });
    }
  };
}

module.exports = {
  stableRetirementId,
  createProjectDeleteRetirementHandler,
};

