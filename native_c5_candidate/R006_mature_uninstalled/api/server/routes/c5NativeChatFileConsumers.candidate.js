'use strict';
/**
 * C5 bounded Native LibreChat Chat/File deletion adapters — SOURCE CANDIDATE.
 *
 * The accepted C5 orchestrator remains the only Project-delete/receipt owner.
 * This module does not enumerate Projects, establish a writer/backup fence,
 * retire Runtime, create any database, or install a Production route.
 * It calls existing authenticated LibreChat DELETE /api/convos and /api/files
 * only for exact targets from an already-prepared Runtime C5 operation.
 * Final absence of conversations, messages, tool calls, links, blobs,
 * file rows, vectors and all references is still checked by the C5 owner.
 *
 * SECURITY: fixed same-process loopback only; no untrusted origin, no token
 * logging, no internal proxy or credential fallback. No native call without
 * project owner plus confirmed C5 retirement and sealed target membership.
 */

const LOOPBACK_ORIGIN = 'http://127.0.0.1:3080';

class C5NativeStop extends Error {
  constructor(code) {
    super(code);
    this.name = 'C5NativeStop';
    this.code = code;
  }
}

function demand(ok, code) {
  if (!ok) throw new C5NativeStop(code);
}

function plainString(v) {
  return typeof v === 'string' && v.trim() !== '' && v.length <= 2048;
}

function createNativeChatFileDeleteConsumers({
  request,
  readCurrentC5Operation,
  readOwnedNativeFile,
  reconfirmExclusiveFile,
  nativeFetch = globalThis.fetch,
  origin = LOOPBACK_ORIGIN,
}) {
  demand(request && typeof request === 'object', 'C5_REQUEST_REQUIRED');
  demand(origin === LOOPBACK_ORIGIN, 'C5_LOOPBACK_ORIGIN_MUST_BE_FIXED');
  demand(typeof nativeFetch === 'function', 'C5_NATIVE_FETCH_REQUIRED');
  for (const [key, fn] of Object.entries({
    readCurrentC5Operation, readOwnedNativeFile, reconfirmExclusiveFile,
  })) {
    demand(typeof fn === 'function', 'C5_OWNER_CALLBACK_MISSING_' + key);
  }
  const signedUser = String(request.user?.id || request.user?._id || '');
  const boundProjectId = String(request.params?.projectId || '');
  demand(plainString(boundProjectId), 'C5_ROUTE_PROJECT_ID_REQUIRED');
  const auth = request.headers?.authorization;
  demand(plainString(signedUser), 'C5_NATIVE_AUTHENTICATED_OWNER_REQUIRED');
  demand(
    typeof auth === 'string' && /^Bearer [A-Za-z0-9._~-]+$/.test(auth),
    'C5_NATIVE_AUTH_TOKEN_MUST_BE_PRESENT',
  );

  async function sealedPlan(projectId, ownerId, kind, targetId) {
    demand(plainString(projectId) && plainString(targetId),
      'C5_PROJECT_TARGET_INVALID');
    demand(projectId === boundProjectId, 'C5_ROUTE_PROJECT_BINDING_MISMATCH');
    demand(ownerId === signedUser, 'C5_OTHER_OWNER_TARGET_BLOCK');
    const op = await readCurrentC5Operation({ projectId, ownerId });
    demand(
      op?.schema === 'C5_PROJECT_CASCADE_R001' &&
      op.projectId === projectId &&
      op.ownerId === ownerId &&
      op.c5Confirmed === true &&
      op.plan?.projectId === projectId &&
      op.plan?.ownerId === ownerId &&
      op.plan?.revision > 0,
      'C5_DURABLE_NATIVE_RETIREMENT_NOT_CONFIRMED',
    );
    const members = kind === 'chat'
      ? op.plan.chats
      : op.plan.exclusive?.map((x) => x.id);
    demand(Array.isArray(members) && members.includes(targetId),
      'C5_TARGET_NOT_IN_SEALED_OWNERSHIP_PLAN');
    return op;
  }

  async function invokeNative(path, payload, expectedHttpCode) {
    let response;
    try {
      response = await nativeFetch(LOOPBACK_ORIGIN + path, {
        method: 'DELETE',
        headers: {
          Authorization: auth,
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
        redirect: 'error',
        cache: 'no-store',
      });
    } catch {
      // A transport failure might follow an actual native mutation.
      throw new C5NativeStop('C5_NATIVE_EFFECT_OUTCOME_UNKNOWN');
    }
    demand(response && response.status === expectedHttpCode,
      'C5_NATIVE_DELETE_HTTP_RESULT_NOT_CONFIRMED');
    let body;
    try {
      body = await response.json();
    } catch {
      // For an already-performed deletion, unreadable confirmation is partial.
      throw new C5NativeStop('C5_NATIVE_DELETE_RESPONSE_UNKNOWN');
    }
    demand(body && typeof body === 'object' && !Array.isArray(body),
      'C5_NATIVE_DELETE_RESPONSE_INVALID');
    return body;
  }

  async function deleteNativeChat({ projectId, ownerId, chatId }) {
    await sealedPlan(projectId, ownerId, 'chat', chatId);
    // Native router performs its own authenticated per-user deletion,
    // agent-generation drain, checkpoint, tool-call, and shared-link cleanup.
    await invokeNative('/api/convos', {
      arg: { conversationId: chatId, source: 'button' },
    }, 201);
    // A 201 is NOT complete Project deletion. Caller re-reads every derivative.
    return { nativeRouteAccepted: true, needsPostDeleteVerification: true };
  }

  // The existing C5 orchestrator supplies ownerId/fileId, but not projectId;
  // bind to the already-authorized current DELETE /api/projects/:projectId.
  async function deleteNativeExclusiveFile({ projectId = boundProjectId, ownerId, fileId }) {
    const op = await sealedPlan(projectId, ownerId, 'file', fileId);
    const eligibility = await reconfirmExclusiveFile({
      projectId, ownerId, fileId, plan: op.plan,
    });
    demand(
      eligibility?.ownerAuthorized === true &&
      eligibility.refsComplete === true &&
      eligibility.noOtherConsumers === true,
      'C5_FILE_REFS_NOW_SHARED_OR_UNPROVEN',
    );
    const row = await readOwnedNativeFile({ ownerId, fileId });
    if (row == null) {
      // Partial resume: native metadata may already be removed.
      // Caller MUST still confirm Blob/vector/reference absence.
      return { fileMetadataAlreadyAbsent: true, needsPostDeleteVerification: true };
    }
    demand(
      row.file_id === fileId &&
      String(row.user ?? '') === ownerId &&
      plainString(row.filepath) &&
      (row.source === undefined || plainString(row.source)),
      'C5_FILE_CURRENT_NATIVE_OWNERSHIP_UNPROVEN',
    );
    const deleted = await invokeNative('/api/files', {
      files: [{
        file_id: row.file_id, filepath: row.filepath,
        ...(row.source ? { source: row.source } : {}),
      }],
    }, 200);
    // Native buildDeleteFilesResponse returns BOTH result arrays. HTTP 200
    // can also report a partial or zero-file delete. Require the exact
    // expected acknowledgement, then separately verify physical absence.
    demand(Array.isArray(deleted.deletedFileIds) &&
      Array.isArray(deleted.failedFileIds) &&
      deleted.deletedFileIds.every(plainString) &&
      deleted.failedFileIds.every(plainString),
      'C5_NATIVE_FILE_DELETE_RESPONSE_UNVERIFIED');
    demand(deleted.failedFileIds.length === 0,
      'C5_NATIVE_FILE_DELETE_REPORTED_FAILURE');
    demand(deleted.deletedFileIds.length === 1 &&
      deleted.deletedFileIds[0] === fileId,
      'C5_NATIVE_FILE_DELETE_TARGET_NOT_ACKNOWLEDGED');
    // Blob/Vector/CodeEnv/File record cleanup still requires independent
    // owner-scoped readback; the native acknowledgement is not that proof.
    return { nativeRouteAccepted: true, needsPostDeleteVerification: true };
  }

  return { deleteNativeChat, deleteNativeExclusiveFile };
}

module.exports = { createNativeChatFileDeleteConsumers, C5NativeStop, LOOPBACK_ORIGIN };
