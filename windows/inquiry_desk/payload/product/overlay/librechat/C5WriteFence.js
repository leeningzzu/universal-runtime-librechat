'use strict';
/**
 * One in-process LibreChat write fence for an admitted C5 Project delete.
 *
 * It is not a lock service or second Job engine. It briefly rejects new HTTP
 * mutations while the existing C5 route calls first-party Chat/File owners.
 * Reads stay available. Unknown/partial effects expire fail-safe rather than
 * silently falling back to the legacy Project-unassign route.
 */
const crypto = require('node:crypto');

const PROJECT_ID = /^[a-f0-9]{24}$/i;
const C5_INTENT = 'CONFIRMED_C5_WHOLE_PROJECT_DELETE_R001';
const C5_DIRECT_POLICY = 'FORWARD_ONLY_DURABLE_RECEIPT_R001';
const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const INTERNAL_PATHS = new Set(['/api/convos', '/api/files']);
const REQUEST_ID = Symbol('aidesC5WriteFenceRequestId');
const PREPARE_OP = /^C5LEASE_[A-Za-z0-9_-]{16,128}$/;

class C5WriteFenceStop extends Error {
  constructor(code) {
    super(code);
    this.name = 'C5WriteFenceStop';
    this.code = code;
  }
}
const need = (condition, code) => {
  if (!condition) throw new C5WriteFenceStop(code);
};
const exact = (a, b) => {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && crypto.timingSafeEqual(left, right);
};

function createC5WriteFence({ ttlMs = 600_000 } = {}) {
  need(Number.isInteger(ttlMs) && ttlMs >= 30_000 && ttlMs <= 600_000,
    'C5_WRITE_FENCE_TTL_INVALID');
  let fence = null;
  let sequence = 0;
  const inflight = new Map();

  function isExplicitDelete(req, projectId = null) {
    // Express child routers rewrite req.path; originalUrl keeps the full authenticated route.
    const fullPath = req.originalUrl?.split('?')[0] || req.path || '';
    const match = /^\/api\/projects\/([a-f0-9]{24})$/i.exec(fullPath);
    return req.method === 'DELETE' && match != null &&
      (projectId == null || match[1] === projectId) &&
      req.headers?.['x-c5-irrevocable-project-delete'] === C5_INTENT &&
      req.body?.confirmedIrreversibleProjectDelete === true &&
      req.body?.projectId === match[1] &&
      req.body?.deleteProtectionPolicy === C5_DIRECT_POLICY &&
      req.headers?.['x-c5-delete-protection-policy'] === C5_DIRECT_POLICY;
  }

  function recoveryPrepareProject(req) {
    const fullPath = req.originalUrl?.split('?')[0] || req.path || '';
    const match = /^\/api\/projects\/([a-f0-9]{24})\/c5-whole-delete\/(?:prepare|prepare-start)$/i.exec(fullPath);
    if (req.method !== 'POST' || match == null ||
        req.body?.confirmedIrreversibleProjectDelete !== true ||
        req.body?.deleteProtectionPolicy !== C5_DIRECT_POLICY ||
        req.headers?.['x-c5-delete-protection-policy'] !== C5_DIRECT_POLICY) return null;
    return match[1];
  }

  function isInternalCascade(req) {
    return fence != null && INTERNAL_PATHS.has(req.path) &&
      exact(req.headers?.['x-c5-internal-cascade'], fence.internalKey);
  }

  function clear(reason = 'RELEASED') {
    if (fence == null) return false;
    clearTimeout(fence.timer);
    fence = null;
    return reason;
  }

  function middleware() {
    return (req, res, next) => {
      if (!MUTATING.has(req.method)) return next();
      const prepareProject = recoveryPrepareProject(req);
      const sameProjectRecovery = fence != null && prepareProject != null &&
        prepareProject === fence.projectId;
      if (fence != null && !isExplicitDelete(req, fence.projectId) &&
          !isInternalCascade(req) && !sameProjectRecovery) {
        res.set('Retry-After', '3');
        return res.status(503).json({
          code: 'C5_PROJECT_DELETE_WRITE_FENCE_ACTIVE',
          retryAutomatically: false,
        });
      }
      const requestId = ++sequence;
      req[REQUEST_ID] = requestId;
      inflight.set(requestId, {
        method: req.method,
        path: req.path,
        c5Delete: isExplicitDelete(req),
        c5Prepare: prepareProject != null,
        c5PrepareStart: prepareProject != null &&
          (req.originalUrl || '').split('?')[0].endsWith('/c5-whole-delete/prepare-start'),
        c5RecoveryPrepare: sameProjectRecovery,
        internalCascade: isInternalCascade(req),
      });
      let ended = false;
      const done = () => {
        if (ended) return;
        ended = true;
        inflight.delete(requestId);
      };
      res.once('finish', done);
      res.once('close', done);
      return next();
    };
  }

  function armTimer() {
    need(fence != null, 'C5_WRITE_FENCE_NOT_ACTIVE');
    if (fence.timer != null) clearTimeout(fence.timer);
    fence.timer = setTimeout(() => clear('EXPIRED'), ttlMs);
    fence.timer.unref?.();
  }

  function ensureFence({ projectId, ownerId }) {
    if (fence == null) {
      fence = {
        projectId,
        ownerId,
        internalKey: crypto.randomBytes(32).toString('base64url'),
        createdAt: Date.now(),
        operationId: null,
        prepareRequestId: null,
        fenceSha256: null,
        timer: null,
      };
    } else {
      need(fence.projectId === projectId && fence.ownerId === ownerId,
        'C5_WRITE_FENCE_OWNED_BY_DIFFERENT_PROJECT');
    }
    armTimer();
    return fence;
  }

  function acquire({ request, projectId, ownerId }) {
    need(PROJECT_ID.test(projectId) && PROJECT_ID.test(ownerId),
      'C5_WRITE_FENCE_OWNER_SCOPE_INVALID');
    need(request?.[REQUEST_ID] != null && isExplicitDelete(request, projectId),
      'C5_WRITE_FENCE_EXPLICIT_DELETE_REQUEST_REQUIRED');
    const current = inflight.get(request[REQUEST_ID]);
    need(current?.c5Delete === true,
      'C5_WRITE_FENCE_REQUEST_NOT_CURRENT');
    // An explicit asynchronous DELETE must reuse the exact original
    // PREPARE operation. Never silently create a replacement fence.
    const requestedOp = request?.body?.c5PrepareOperationId;
    need(PREPARE_OP.test(String(requestedOp || '')) &&
      fence != null && fence.operationId === requestedOp &&
      fence.projectId === projectId && fence.ownerId === ownerId,
    'C5_PREPARE_FENCE_CONTINUITY_REQUIRED');
    const admitted = ensureFence({ projectId, ownerId });
    request.c5InternalCascadeKey = admitted.internalKey;
    return {
      projectId,
      ownerId,
      internalKey: admitted.internalKey,
      inflightMutations: inflight.size,
      fenced: true,
    };
  }

  function acquirePrepare({ request, projectId, ownerId }) {
    need(PROJECT_ID.test(projectId) && PROJECT_ID.test(ownerId),
      'C5_WRITE_FENCE_OWNER_SCOPE_INVALID');
    const preparedProject = recoveryPrepareProject(request);
    need(request?.[REQUEST_ID] != null && preparedProject === projectId,
      'C5_WRITE_FENCE_CONFIRMED_PREPARE_REQUIRED');
    const current = inflight.get(request[REQUEST_ID]);
    need(current?.c5Prepare === true,
      'C5_WRITE_FENCE_PREPARE_NOT_CURRENT');
    if (fence == null) {
      // Freeze all other HTTP mutations before protected snapshot creation.
      need(inflight.size === 1,
        'C5_OTHER_LIBRECHAT_WRITES_IN_FLIGHT');
    } else if (fence.operationId != null) {
      // A duplicate authenticated START may reuse the same live fence:
      // Runtime uses the sealed hash/counters to return the same operation.
      // This cannot resurrect an expired fence or create a new one silently.
      const route = request?.originalUrl?.split('?')[0] || request?.path || '';
      const sameRequest = fence.prepareRequestId === request[REQUEST_ID];
      need(sameRequest || request?.body?.c5PrepareOperationId === fence.operationId,
        'C5_PREPARE_OPERATION_MUST_REUSE_ORIGINAL_FENCE');
    }
    const admitted = ensureFence({ projectId, ownerId });
    if (admitted.prepareRequestId == null) admitted.prepareRequestId = request[REQUEST_ID];
    request.c5InternalCascadeKey = admitted.internalKey;
    return {
      projectId,
      ownerId,
      internalKey: admitted.internalKey,
      inflightMutations: inflight.size,
      fenced: true,
      phase: 'DIRECT_FORWARD_RECOVERY_ADMISSION',
    };
  }

  function assertHeld({ request, projectId, ownerId }) {
    need(fence != null && fence.projectId === projectId && fence.ownerId === ownerId &&
      request?.[REQUEST_ID] != null && isExplicitDelete(request, projectId) &&
      PREPARE_OP.test(String(request?.body?.c5PrepareOperationId || '')) &&
      fence.operationId === request.body.c5PrepareOperationId,
    'C5_WRITE_FENCE_NOT_HELD');
    request.c5InternalCascadeKey = fence.internalKey;
    return true;
  }

  // Bind the exact first-party Runtime operation to the current in-memory
  // LibreChat writer fence. Only the authenticated original POST may bind.
  function bindPrepareOperation({ request, projectId, ownerId, operationId }) {
    need(PREPARE_OP.test(String(operationId || '')) &&
      PROJECT_ID.test(projectId) && PROJECT_ID.test(ownerId),
      'C5_PREPARE_OPERATION_ID_INVALID');
    const fullPath = request?.originalUrl?.split('?')[0] || request?.path || '';
    need(request?.method === 'POST' &&
      fullPath === '/api/projects/' + projectId + '/c5-whole-delete/prepare' &&
      request?.body?.confirmedIrreversibleProjectDelete === true &&
      request?.[REQUEST_ID] != null,
      'C5_PREPARE_BIND_INITIAL_CONFIRMED_REQUEST_REQUIRED');
    const row = inflight.get(request[REQUEST_ID]);
    need(row?.c5Prepare === true || row?.c5PrepareStart === true,
      'C5_PREPARE_BIND_REQUEST_NOT_ADMITTED');
    need(fence && fence.projectId === projectId &&
      fence.ownerId === ownerId && (fence.operationId == null ||
       fence.operationId === operationId),
      'C5_PREPARE_OPERATION_FENCE_OWNER_CHANGED');
    if (fence.operationId === null) {
      fence.operationId = operationId;
      fence.fenceSha256 = crypto.createHash('sha256')
        .update(fence.internalKey).digest('hex');
    }
    armTimer();
    return {operationId, fenceSha256: fence.fenceSha256, sameFence: true};
  }

  // Do not re-acquire a lost/expired fence in a GET status call. The
  // authenticated same-owner Project status reader may renew ONLY the same
  // in-process operation. The actual Runtime status/backup is checked before
  // permitting final DELETE.
  function heartbeatPrepareOperation({ request, projectId, ownerId, operationId }) {
    need(PREPARE_OP.test(String(operationId || '')),
      'C5_PREPARE_OPERATION_ID_INVALID');
    const fullPath = request?.originalUrl?.split('?')[0] || request?.path || '';
    need(request?.method === 'GET' &&
      fullPath === '/api/projects/' + projectId + '/c5-whole-delete/prepare-status' &&
      String(request?.user?.id ?? request?.user?._id ?? '') === ownerId,
      'C5_PREPARE_POLL_JWT_OWNER_REQUIRED');
    need(fence && fence.projectId === projectId &&
      fence.ownerId === ownerId && fence.operationId === operationId &&
      typeof fence.fenceSha256 === 'string',
      'C5_PREPARE_ORIGINAL_FENCE_EXPIRED_OR_LOST');
    armTimer();
    return {operationId, fenceSha256: fence.fenceSha256, sameFence: true};
  }

  function assertPrepareOperation({ projectId, ownerId, operationId }) {
    need(PREPARE_OP.test(String(operationId || '')) &&
      fence && fence.projectId === projectId &&
      fence.ownerId === ownerId && fence.operationId === operationId &&
      typeof fence.fenceSha256 === 'string',
      'C5_PREPARE_ORIGINAL_FENCE_EXPIRED_OR_LOST');
    return {operationId, fenceSha256: fence.fenceSha256, sameFence: true};
  }

  function release({ projectId, ownerId }) {
    need(fence == null ||
      fence.projectId === projectId && fence.ownerId === ownerId,
    'C5_WRITE_FENCE_RELEASE_SCOPE_INVALID');
    clear('COMPLETE');
    return true;
  }

  function snapshot() {
    return {
      fenced: fence != null,
      projectId: fence?.projectId ?? null,
      inflightMutations: inflight.size,
    };
  }

  return { middleware, acquire, acquirePrepare, assertHeld,
    bindPrepareOperation, heartbeatPrepareOperation, assertPrepareOperation,
    release, snapshot };
}

module.exports = { createC5WriteFence, C5WriteFenceStop, C5_INTENT };
