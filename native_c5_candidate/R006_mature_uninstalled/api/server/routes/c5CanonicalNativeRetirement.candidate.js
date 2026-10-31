'use strict';
/**
 * C5 hard Project-delete owner composition. Reuse the previously accepted
 * native LibreChat/Runtime retirement handler, but forbid its legacy
 * "Runtime absent => unassign chats" branch at EVERY point-of-use read.
 *
 * This is a tiny C5 policy adapter around the same native handler. It does
 * not own a DB, runner, scheduler, retry service or deletion algorithm.
 * A trusted application controller must provide the actual authenticated
 * LibreChat handlers and existing Runtime Adapter request functions.
 */
const { createProjectDeleteRetirementHandler } =
  require('./runtimeProjectDeleteRetirement.c5.js');

const canonicalHandlers = new WeakSet();
const methods = Object.freeze([
  'getRuntimeProject','prepareRuntimeRetirement',
  'confirmRuntimeLibreChatDeleted','abortRuntimeRetirement',
  'commitRuntimeRetirement','deleteLibreChatProject',
  'isNativeOwnerAuthorized','verifyNativeDeletionComplete',
]);
class C5CanonicalRetirementStop extends Error {
  constructor(code) { super(code); this.code=code;this.name='C5CanonicalRetirementStop'; }
}
function createC5CanonicalNativeRetirementHandler(owners) {
  if (!owners || methods.some(name => typeof owners[name] !== 'function')) {
    throw new C5CanonicalRetirementStop('C5_CANONICAL_NATIVE_OWNER_METHOD_UNAVAILABLE');
  }
  const guarded = createProjectDeleteRetirementHandler({
    ...Object.fromEntries(methods.map(name => [name,owners[name]])),
    getRuntimeProject: async (projectId) => {
      const status = await owners.getRuntimeProject(projectId);
      if (status?.found !== true ||
          !Number.isInteger(status.project_revision) ||
          status.project_revision < 1 ||
          !['ACTIVE','RETIRE_PENDING','RETIRED'].includes(status.status)) {
        // Never allow a Runtime absence to trigger upstream native-only delete,
        // even if it appears AFTER an earlier admission/preflight.
        throw new C5CanonicalRetirementStop('C5_CANONICAL_RUNTIME_OWNER_MISSING_NO_NATIVE_ONLY_DELETE');
      }
      return status;
    },
  });
  canonicalHandlers.add(guarded);
  return guarded;
}
const isC5CanonicalNativeRetirementHandler = fn =>
  typeof fn === 'function' && canonicalHandlers.has(fn);
module.exports = {
  createC5CanonicalNativeRetirementHandler,
  isC5CanonicalNativeRetirementHandler,
  C5CanonicalRetirementStop,
};
