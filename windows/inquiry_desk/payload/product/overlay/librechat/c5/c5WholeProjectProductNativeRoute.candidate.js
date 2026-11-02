'use strict';
const crypto = require('node:crypto');
/**
 * C5 bounded current-Project product entry. Reuses LibreChat Project/Chat/File/
 * Agent Mongo methods, the existing Runtime owner and one C5 14-hook cascade.
 *
 * This source is NOT installed. The real current Runtime/SourceRef reference
 * owner and writer/forward-recovery admission must be supplied by the current app.
 * No fallback to upstream unassign-only delete and no fake readiness.
 */
const { createC5WholeProjectProductEndpoints } =
  require('./c5WholeProjectProductEndpoints.candidate.js');
const { createC5CurrentNativeWholeProjectDelete } =
  require('./c5NativeWholeProjectBinding.candidate.js');
const {
  retireRuntimeProjectSourcesForC5,
  verifyRuntimeProjectSourcesRetiredForC5,
} = require('~/server/services/Files/crossStorePermanentDelete');
const { classifyInventory } =
  require('./projectDeleteOwnedCascade.c5.product.candidate.js');
const { validateDurableDeleteSnapshot } =
  require('./c5DurableDeleteSnapshot.candidate.js');
const { createC5CurrentNativeRetirementCallbacks } =
  require('./c5CurrentNativeRetirementCallbacks.candidate.js');
const { createC5CanonicalNativeRetirementHandler } =
  require('./c5CanonicalNativeRetirement.candidate.js');
const { createC5RuntimeOwnerNativeBridge } =
  require('./c5RuntimeOwnerNativeBridge.candidate.js');


class C5ProductEntryStop extends Error {
  constructor(code) { super(code); this.code = code; this.name = 'C5ProductEntryStop'; }
}
const need = (ok, code) => {
  if (!ok) throw new C5ProductEntryStop(code);
};
const positive = (p) => Number.isInteger(p) && p > 0;
const ownerId = (req) => String(req?.user?.id ?? req?.user?._id ?? '');
const projectId = (req) => String(req?.params?.projectId || '');

function createC5NativeWholeProjectProductRoute({
  nativeDb, getNativeModels, resolveCurrentOwnerBindings,
  upstreamProjectHandlers, nativeFetch, afterVerifiedProjectDeletion,
}) {
  need(nativeDb && typeof nativeDb.getChatProject === 'function' &&
       typeof nativeDb.getSharedResourceFileIds === 'function',
       'C5_REAL_NATIVE_PROJECT_AND_AGENT_OWNER_REQUIRED');
  need(typeof getNativeModels === 'function' &&
       typeof resolveCurrentOwnerBindings === 'function',
       'C5_REAL_NATIVE_RUNTIME_OWNER_RESOLVER_REQUIRED');
  need(
    typeof afterVerifiedProjectDeletion === 'function',
    'C5_PROJECT_NATIVE_FILE_CLEANUP_REQUIRED',
  );

  async function construct(req,enrollNativeOnly=false) {
    const project = projectId(req), actor = ownerId(req);
    need(/^[a-f0-9]{24}$/i.test(project) && /^[a-f0-9]{24}$/i.test(actor),
      'C5_AUTHENTICATED_PROJECT_REQUIRED');
    const owners = await resolveCurrentOwnerBindings(req);
    need(owners && owners.admissionOwner && owners.referenceOwner &&
      typeof owners.abortPreEffectAdmission === 'function' &&
      typeof owners.releaseEffectAdmission === 'function',
      'C5_CURRENT_REFERENCE_WRITER_OR_BACKUP_OWNER_MISSING');
    try {
      const models = getNativeModels();
    // The installed native router supplies its exact upstream Project handler,
    // so the Runtime and native retirement owner come from existing services.
    // Only direct isolated tests without an upstream handler may use a
    // contained synthetic runtimeOwner; Production never takes that branch.
    const runtimeOwner = upstreamProjectHandlers
      ? createC5RuntimeOwnerNativeBridge({
          request:req,
          nativeC5RetirementHandler:createC5CanonicalNativeRetirementHandler(
            createC5CurrentNativeRetirementCallbacks({
              request:req, nativeDb, nativeModels:models,
              upstreamProjectHandlers,
              doFetch:nativeFetch,
            }),
          ),
          doFetch:nativeFetch,
        })
      : owners.runtimeOwner;
    need(runtimeOwner,'C5_CURRENT_CANONICAL_RUNTIME_OWNER_UNAVAILABLE');
    // Project identity is native LibreChat. Enroll a native-only Project
    // in the EXISTING Runtime owner only on confirmed user DELETE prep,
    // never on GET readiness or via an alternate native-only deletion.
    if(enrollNativeOnly && upstreamProjectHandlers){
      need(req?.body?.confirmedIrreversibleProjectDelete===true,
        'C5_EXPLICIT_PROJECT_DELETE_CONFIRMATION_REQUIRED');
      // Recovery may legitimately start after native Project removal. Resolve
      // the existing Runtime state/receipt before requiring a live native row;
      // the native row is mandatory only for first-time native-only enrollment.
      const current=await runtimeOwner.readNativeProjectBoundState({
        projectId:project,ownerId:actor,
      });
      if(current.found===false){
        need(current.native_only_verified===true,
          'C5_NATIVE_ONLY_RUNTIME_PROVENANCE_NOT_CONFIRMED');
        const owned=await nativeDb.getChatProject(actor,project);
        need(owned!=null && String(owned._id)===project &&
          String(owned.user)===actor,
          'C5_NATIVE_PROJECT_OWNER_UNVERIFIED_BEFORE_ENROLLMENT');
        const active=await models.Conversation.find({
          user:actor,chatProjectId:project,
        }).select('conversationId user chatProjectId').lean();
        need(Array.isArray(active) && active.length<=2000 &&
          active.every(row=>typeof row.conversationId==='string' &&
            row.conversationId.length>0 && String(row.user)===actor &&
            row.chatProjectId===project),
          'C5_CURRENT_PROJECT_MEMBERSHIP_BEFORE_ENROLLMENT_UNVERIFIED');
        const chats=active.map(row=>row.conversationId);
        need(new Set(chats).size===chats.length,
          'C5_CURRENT_PROJECT_MEMBERSHIP_DUPLICATE_BEFORE_ENROLLMENT');
        const gate=await owners.admissionOwner.proveInventoryFence({
          projectId:project,ownerId:actor,chatIds:chats,
          phase:'C5_NATIVE_RUNTIME_IDEMPOTENT_BINDING',
        });
        need(gate?.permitted===true && gate.projectId===project &&
          gate.ownerId===actor &&
          gate.jobScope==='TARGET_PROJECT_CURRENT_EFFECTS' &&
          gate.exclusiveWriter===true && gate.forwardRecoveryReady===true &&
          gate.activePinnedJobs===0 && gate.projectMembershipSealed===true,
          'C5_NATIVE_RUNTIME_ENROLLMENT_WRITER_FORWARD_RECOVERY_JOB_FENCE_REQUIRED');
        const bound=await runtimeOwner.ensureNativeProjectBoundForDelete({
          projectId:project,ownerId:actor,admissionProven:true,
        });
        need(bound.found===true && bound.newly_bound===true &&
          bound.project_id===current.project_id && bound.status==='ACTIVE',
          'C5_RUNTIME_PROJECT_ENROLLMENT_NOT_CONFIRMED');
      }
    }
    const native = createC5CurrentNativeWholeProjectDelete({
      request:req, models, nativeDb,
      runtimeOwner,
      admissionOwner:owners.admissionOwner,
      referenceOwner:owners.referenceOwner,
      nativeFetch,
      prepareNativeProjectFileCascade: async ({ projectId:p, ownerId:u }) => {
        need(
          p === project && u === actor,
          'C5_NATIVE_PROJECT_SOURCE_CLEANUP_SCOPE_CHANGED',
        );
        const receipt = await afterVerifiedProjectDeletion({
          projectId:p,
          ownerId:u,
          phase:'BEFORE_OWNED_FILE_CASCADE',
        });
        need(
          receipt?.verified === true && receipt.project_id === p &&
            receipt.remaining_reference_count === 0,
          'C5_NATIVE_PROJECT_SOURCE_CLEANUP_UNVERIFIED',
        );
        return receipt;
      },
      retireRuntimeProjectSourceContents: async ({
        projectId:p, ownerId:u, plan:currentPlan, snapshot,
      }) => {
        need(
          p === project && u === actor && currentPlan?.projectId === p &&
            snapshot?.projectId === p && snapshot?.ownerId === u &&
            snapshot.planSha256 === currentPlan.planSha256 &&
            typeof currentPlan.planSha256 === 'string' &&
            /^[0-9a-f]{64}$/.test(currentPlan.planSha256),
          'C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_SCOPE_CHANGED',
        );
        const receipt = await retireRuntimeProjectSourcesForC5({
          projectId:p,
          ownerId:u,
          expectedSourceSnapshot:snapshot.runtimeSources,
          planSha256:currentPlan.planSha256,
          protectedAssetCensusSha256:snapshot.protectedAssetCensusSha256,
        });
        need(
          receipt?.verified === true && receipt.project_id === p &&
            Number.isInteger(receipt.source_count) &&
            receipt.source_count === snapshot.runtimeSources.length,
          'C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_UNVERIFIED',
        );
        return receipt;
      },
      verifyRuntimeProjectSourceContentsRetired: async ({
        projectId:p, ownerId:u, plan:currentPlan, snapshot,
      }) => verifyRuntimeProjectSourcesRetiredForC5({
        projectId:p, ownerId:u, plan:currentPlan, snapshot,
      }),
    });
    const hooks = native.hooks;
    let plan = null;
    let acceptedAtEffectPlan = null;
    let runtimeSourcesAtReadiness = null;
    let runtimeSourcesLastRead = null;
    let recoveryPending = false;
    const runtimeSourceIdentity = (snapshot) => crypto.createHash('sha256')
      .update(JSON.stringify({
        runtimeProjectId:snapshot.runtimeProjectId,
        runtimeProjectRevision:snapshot.runtimeProjectRevision,
        runtimeProjectStatus:snapshot.runtimeProjectStatus,
        sources:snapshot.sources.map(row=>[row.source_ref_id,row.source_sha256]),
        memoryStateRevision:snapshot.memoryStateRevision,
        instructionsCurrentEmpty:snapshot.projectInstructionsCurrentEmpty,
        // Historical JobAuthority is NOT a SourceRef/Memory input.
        // The live target-Project Job fence is checked by admissionOwner.
        visibleMemoryCount:snapshot.visibleMemoryCount,
      })).digest('hex');


    const idsMatch = (ids) =>
      ids.projectId === project && ids.ownerId === actor;


    // Restore exact ownership from the authenticated Runtime operation
    // receipt after native Project removal; never derive it from a 404.
    function sealedReceiptPlan(op, ids) {
      need(idsMatch(ids) && op?.schema === 'C5_PROJECT_CASCADE_R001' &&
        op.projectId === project && op.ownerId === actor &&
        ['PREPARED','CASCADE_PENDING','PARTIAL_OR_BLOCKED','COMPLETE'].includes(op.phase) &&
        positive(op.c5_receipt_revision) && op.plan &&
        op.plan.projectId === project && op.plan.ownerId === actor &&
        positive(op.plan.revision) && Array.isArray(op.plan.chats) &&
        Array.isArray(op.plan.exclusive) && Array.isArray(op.plan.retained) &&
        Array.isArray(op.deletedChats) && Array.isArray(op.deletedFiles) &&
        Array.isArray(op.retiredSources) && op.durableSnapshot,
        'C5_RECOVERY_RECEIPT_OWNER_OR_SHAPE_UNVERIFIED');
      const plan = op.plan;
      const exactKeys = (value, allowed) => value && typeof value === 'object' &&
        !Array.isArray(value) &&
        Object.keys(value).sort().join('\0') === [...allowed].sort().join('\0');
      need(exactKeys(plan, ['projectId','ownerId','revision','chats',
        'exclusive','retained','planSha256']) &&
        plan.chats.every(chatId => typeof chatId === 'string' && chatId.length > 0) &&
        plan.exclusive.every(file => exactKeys(file,
          file?.nativeChatAnchor === true ? ['id','bytes','nativeChatAnchor'] : ['id','bytes']) &&
          typeof file.id === 'string' && file.id.length > 0 &&
          Number.isSafeInteger(file.bytes) && file.bytes >= 0) &&
        plan.retained.every(file => exactKeys(file, ['id']) &&
          typeof file.id === 'string' && file.id.length > 0),
        'C5_RECOVERY_RECEIPT_PLAN_SHAPE_UNVERIFIED');
      validateDurableDeleteSnapshot(op.durableSnapshot, plan, project, actor);
      need(op.retiredSources.every((sourceRefId) =>
        typeof sourceRefId === 'string' && /^SRC_[A-Z0-9]{8,64}$/.test(sourceRefId)),
      'C5_RECOVERY_RETIRED_SOURCE_RECEIPT_INVALID');
      // Runtime JSON persistence sorts object keys. Rebuild the exact original
      // classifyInventory structure before hashing; do not trust persisted key order.
      const canonicalPlan = {
        projectId:plan.projectId, ownerId:plan.ownerId, revision:plan.revision,
        chats:[...plan.chats],
        exclusive:plan.exclusive.map(file => ({
          id:file.id, bytes:file.bytes,
          ...(file.nativeChatAnchor === true ? {nativeChatAnchor:true} : {}),
        })),
        retained:plan.retained.map(file => ({id:file.id})),
      };
      const currentHash = crypto.createHash('sha256')
        .update(JSON.stringify(canonicalPlan)).digest('hex');
      need(currentHash === plan.planSha256,
        'C5_RECOVERY_RECEIPT_PLAN_INTEGRITY_UNVERIFIED');
      return plan;
    }
    function acceptRuntimeReferenceProjection(sources, expectedStatus = null) {
      need(
        sources?.schema==='AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001' &&
        sources.authority_class==='CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY' &&
        sources.nativeProjectId===project && sources.actorId===actor &&
        positive(sources.runtimeProjectRevision) &&
        ['ACTIVE','RETIRE_PENDING','RETIRED'].includes(sources.runtimeProjectStatus) &&
        (expectedStatus == null || sources.runtimeProjectStatus===expectedStatus) &&
        sources.sourceRefsProvenComplete===true &&
        typeof sources.projectInstructionsCurrentEmpty==='boolean' &&
        (sources.runtimeProjectStatus!=='RETIRED' ||
          sources.projectInstructionsCurrentEmpty===true) &&
        sources.sourceRefCount===sources.sources?.length &&
        Number.isInteger(sources.memoryStateRevision) &&
        Number.isInteger(sources.visibleMemoryCount),
        'C5_CURRENT_RUNTIME_PROJECT_SOURCES_AND_MEMORY_UNVERIFIED');
      runtimeSourcesLastRead = sources;
      return sources;
    }

    async function preparedPlan(ids) {
      need(idsMatch(ids), 'C5_CURRENT_NATIVE_SCOPE_CHANGED');
      const pending = await hooks.loadRuntimeOperationReceipt(ids);
      recoveryPending = pending != null;
      if (pending) {
        // Recovery cannot replay a native inventory after the Project row is
        // gone. Bind the durable receipt to current canonical Runtime state.
        const [runtime, sources] = await Promise.all([
          runtimeOwner.readRetirementState(ids),
          runtimeOwner.readCurrentRuntimeReferences(ids),
        ]);
        need(runtime?.authoritative === true && runtime.projectId === project,
          'C5_CANONICAL_RUNTIME_PROJECT_READ_UNVERIFIED');
        acceptRuntimeReferenceProjection(sources, runtime.status);
        need(['ACTIVE','RETIRE_PENDING','RETIRED'].includes(runtime.status) &&
          (!pending.c5Confirmed || runtime.status === 'RETIRED'),
          'C5_RECOVERY_RUNTIME_STATE_CONFLICT');
        return sealedReceiptPlan(pending,ids);
      }

      // The native file-graph owner already reads the exact Runtime Project,
      // Sources, Memory and Instructions projection. Reuse that one projection
      // instead of repeating two serial Adapter/Runtime round trips.
      const inventory = await hooks.readNativeInventory(ids);
      const sources = acceptRuntimeReferenceProjection(
        inventory?.runtimeCurrentReferences, 'ACTIVE',
      );
      const result = classifyInventory(inventory, project, actor);
      need(result.planSha256 && positive(result.revision),
        'C5_CURRENT_NATIVE_OWNERSHIP_PLAN_UNVERIFIED');
      need(result.revision===sources.runtimeProjectRevision,
        'C5_NATIVE_AND_RUNTIME_PROJECT_REVISION_CHANGED');
      return result;
    }
    const endpoints = createC5WholeProjectProductEndpoints({
      verifyNativeOwner: async (ids) => {
        need(idsMatch(ids), 'C5_CURRENT_NATIVE_SCOPE_CHANGED');
        const row = await nativeDb.getChatProject(actor,project);
        const liveOwned = row != null &&
          String(row.user) === actor && String(row._id) === project;
        if (liveOwned) return {projectId:project,ownerId:actor,owned:true};
        // A missing owner-scoped row is not proof that no other user owns
        // the native Project. A still-existing same-ID Project forbids
        // recovery using a stale prior owner's Runtime receipt.
        const currentProjectCount=await models.ChatProject.countDocuments({_id:project});
        need(Number.isInteger(currentProjectCount)&&currentProjectCount>=0,
          'C5_NATIVE_GLOBAL_PROJECT_IDENTITY_READ_UNVERIFIED');
        if(currentProjectCount!==0) return {projectId:project,ownerId:actor,owned:false};

        const prior = await hooks.loadRuntimeOperationReceipt(ids);
        if (prior == null) return {projectId:project,ownerId:actor,owned:false};
        sealedReceiptPlan(prior,ids);
        return {projectId:project,ownerId:actor,owned:true,recoveryOnly:true};
      },
      proveWholeProjectReadiness: async (ids) => {
        const prepared = await preparedPlan(ids);
        const fence = await hooks.verifyPreEffectBoundary({
          ...ids, plan:prepared,
          phase:recoveryPending?'RECOVERY_READINESS':'BEFORE_EFFECT',
        });
        need(fence === true, 'C5_CURRENT_WRITER_JOB_FORWARD_RECOVERY_ADMISSION_MISSING');
        const operationId = owners.admissionOwner.currentOperationId();
        need(/^C5LEASE_[A-Za-z0-9_-]{16,128}$/.test(String(operationId || '')),
          'C5_DIRECT_DELETE_OPERATION_ID_MISSING');
        plan = prepared;
        runtimeSourcesAtReadiness=runtimeSourceIdentity(runtimeSourcesLastRead);

        return {
          ...ids, scope:'C5_WHOLE_PROJECT_IRREVERSIBLE',
          sourceClass:'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES',
          nativeCascadeInstalled:true, exclusiveWriter:true,
          durableForwardRecoveryReady:true, projectMembershipSealed:true,
          activePinnedJobs:0, projectRevision:prepared.revision,
          operationId, protectionMode:'FORWARD_ONLY_DURABLE_RECEIPT_R001',
        };
      },
      verifyPointOfEffectAdmission: async (args) => {
        need(idsMatch(args) && plan != null &&
          args.proof.projectRevision === plan.revision,
          'C5_CURRENT_DELETE_PLAN_NOT_PREPARED');
        const fresh = await preparedPlan(args);
        need(runtimeSourcesAtReadiness != null &&
          runtimeSourceIdentity(runtimeSourcesLastRead)===runtimeSourcesAtReadiness,
          'C5_RUNTIME_SOURCE_REF_OR_MEMORY_CHANGED_BEFORE_DELETE');

        need(fresh.planSha256 === plan.planSha256,
          'C5_PROJECT_MEMBERSHIP_OR_SHARED_REFERENCES_CHANGED');
        const fenced = await hooks.verifyPreEffectBoundary({
          projectId:project, ownerId:actor, plan:fresh,
          phase:recoveryPending?'CONTINUE_PARTIAL':'BEFORE_C5',
        });
        need(fenced === true, 'C5_CURRENT_EFFECT_ADMISSION_LOST');
        acceptedAtEffectPlan=fresh;
        return {
          projectId:project, ownerId:actor, permitted:true,
          projectRevision:fresh.revision, exclusiveWriter:true,
          durableForwardRecoveryReady:true, activePinnedJobs:0,
          operationId:owners.admissionOwner.currentOperationId(),
        };
      },
      abortPreEffectAdmission: async (ids) => owners.abortPreEffectAdmission(ids),
      executeAcceptedC5Cascade: async (actualReq) => {
        need(actualReq === req && acceptedAtEffectPlan != null,
          'C5_REQUEST_OR_EFFECT_PLAN_SWITCH');
        const capture = {
          statusCode:200, body:null,
          status(n){this.statusCode=n;return this;},
          json(v){this.body=v;return this;},
        };
        await native.handler(req,capture);
        if (capture.statusCode !== 200 ||
            capture.body?.status !== 'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE') {
          const candidate=String(capture.body?.code||'');
          const failureCode=/^C5_[A-Z0-9_]{1,120}$/.test(candidate)
            ? candidate : 'C5_NATIVE_CASCADE_PARTIAL_OR_BLOCKED';
          return {
            httpStatus:capture.statusCode,
            c5OperationPhase:'PARTIAL',
            failureCode,
          };
        }
        const receipt = await hooks.loadRuntimeOperationReceipt({
          projectId:project,ownerId:actor,
        });
        need(receipt?.c5Confirmed === true && receipt.phase === 'COMPLETE' &&
          receipt.plan?.planSha256 === acceptedAtEffectPlan.planSha256 &&
          positive(receipt.c5_receipt_revision),
          'C5_DURABLE_CURRENT_CASCADE_COMPLETION_UNVERIFIED');
        return {
          httpStatus:200, c5OperationPhase:'COMPLETE',
          cascadeResultComplete:true,
          receiptRevision:receipt.c5_receipt_revision,
        };
      },
      readCurrentDeletionStatus: async (ids) => {
        need(idsMatch(ids), 'C5_DELETE_STATUS_SCOPE_CHANGED');
        const receipt = await hooks.loadRuntimeOperationReceipt(ids);
        if (receipt == null) {
          return {
            status:'C5_PROJECT_DELETE_NOT_STARTED', projectId:project,
            projectRemoved:false, runtimeRetired:false, cleanupComplete:false,
            receiptPhase:null, receiptRevision:null, code:null,
          };
        }
        const [nativeCount, assignedCount, runtime] = await Promise.all([
          models.ChatProject.countDocuments({_id:project}),
          models.Conversation.countDocuments({chatProjectId:project}),
          runtimeOwner.readRetirementState(ids),
        ]);
        const projectRemoved = nativeCount === 0 && assignedCount === 0;
        const runtimeRetired = runtime?.authoritative === true && runtime.status === 'RETIRED';
        let sourceContentsRetired = false;
        let snapshotValid = false;
        let statusCode = receipt.lastFailureCode ?? null;
        try {
          const snapshot = validateDurableDeleteSnapshot(
            receipt.durableSnapshot, receipt.plan, project, actor,
          );
          snapshotValid = true;
          sourceContentsRetired = await hooks.verifyRuntimeProjectSourceContentsRetired({
            projectId:project, ownerId:actor, plan:receipt.plan, snapshot,
          });
        } catch (error) {
          const candidate = String(error?.code || error?.message || '');
          statusCode = /^C5_[A-Z0-9_]{1,120}$/.test(candidate)
            ? candidate : 'C5_DELETE_STATUS_SOURCE_VERIFICATION_UNAVAILABLE';
        }
        const cleanupComplete = receipt.phase === 'COMPLETE' && projectRemoved &&
          runtimeRetired && snapshotValid && sourceContentsRetired;
        return {
          status: cleanupComplete
            ? 'COMPLETE_VERIFIED_PROJECT_DELETE'
            : projectRemoved && runtimeRetired
              ? 'C5_PROJECT_REMOVED_CLEANUP_PENDING'
              : 'C5_PROJECT_DELETE_PARTIAL_OR_BLOCKED',
          projectId:project,
          projectRemoved,
          runtimeRetired,
          cleanupComplete,
          sourceContentsRetired,
          receiptPhase:receipt.phase,
          receiptRevision:receipt.c5_receipt_revision,
          code:cleanupComplete ? null : statusCode,
          retryAutomatically:false,
        };
      },
      verifyFinalProductDeletion: async (args) => {
        need(idsMatch(args) && acceptedAtEffectPlan != null &&
          args.result?.receiptRevision > 0,
          'C5_FINAL_COMPLETION_SCOPE_UNVERIFIED');
        const finalReceipt = await hooks.loadRuntimeOperationReceipt({
          projectId:project,ownerId:actor,
        });
        need(finalReceipt?.phase === 'COMPLETE' &&
          finalReceipt?.c5Confirmed === true &&
          finalReceipt?.plan?.planSha256 === acceptedAtEffectPlan.planSha256 &&
          finalReceipt.c5_receipt_revision === args.result.receiptRevision,
          'C5_FINAL_DURABLE_RECEIPT_CHANGED');
        const finalSnapshot = validateDurableDeleteSnapshot(
          finalReceipt.durableSnapshot, acceptedAtEffectPlan, project, actor,
        );
        const sourceContentsRetired = await hooks.verifyRuntimeProjectSourceContentsRetired({
          projectId:project,
          ownerId:actor,
          plan:acceptedAtEffectPlan,
          snapshot:finalSnapshot,
        });
        const nativeProjectAbsent = await models.ChatProject.countDocuments({_id:project}) === 0;
        const unassignedAbsent = await models.Conversation.countDocuments({
          chatProjectId:project,
        }) === 0;
        let nativeChatsAbsent = true;
        for (const chatId of acceptedAtEffectPlan.chats) {
          const result = await hooks.verifyNativeChatAbsent({ownerId:actor,chatId});
          if (!(result?.conversationAbsent && result.messagesAbsent &&
            result.toolCallsAbsent && result.sharedLinksAbsent)) {
            nativeChatsAbsent=false; break;
          }
        }
        let allOwnedFilesAbsent = true;
        for (const file of acceptedAtEffectPlan.exclusive) {
          const proof = await hooks.verifyNativeFileAndDerivativesAbsent({
            ownerId:actor,fileId:file.id,
          });
          if (!(proof?.fileRecordAbsent && proof.blobAbsent &&
            proof.vectorAbsent && proof.codeEnvAbsent &&
            proof.agentReferencesAbsent && proof.sourceReferencesAbsent)) {
            allOwnedFilesAbsent=false; break;
          }
        }
        let retainedFileRefsIntact = true;
        for (const file of acceptedAtEffectPlan.retained) {
          if (await hooks.verifyNativeRetainedFilePresent({
            ownerId:actor,projectId:project,fileId:file.id,
          }) !== true) {
            retainedFileRefsIntact=false; break;
          }
        }
        const runtimeRetired = await hooks.verifyNativeProjectAndRuntimeRetired({
          projectId:project,ownerId:actor,plan:acceptedAtEffectPlan,
        });
        const crossPlaneVerified = await hooks.verifyNoDeletedObjectReferences({
          projectId:project,ownerId:actor,plan:acceptedAtEffectPlan,
        });
        // Final Runtime source/memory check is independent from the cascade's
        // own receipt and from File/Blob/vector verifier flags.
        const finalRuntimeRefs=await runtimeOwner.readCurrentRuntimeReferences({
          projectId:project,ownerId:actor,
        });
        const canonicalSourcesCleared=
          finalRuntimeRefs?.sourceRefsProvenComplete===true &&
          finalRuntimeRefs.nativeProjectId===project &&
          finalRuntimeRefs.actorId===actor &&
          finalRuntimeRefs.runtimeProjectStatus==='RETIRED' &&
          finalRuntimeRefs.sourceRefCount===0 &&
          finalRuntimeRefs.visibleMemoryCount===0 &&
          finalRuntimeRefs.projectInstructionsCurrentEmpty===true &&
          Array.isArray(finalRuntimeRefs.sources) &&
          finalRuntimeRefs.sources.length===0;

        const baseComplete = nativeProjectAbsent && unassignedAbsent &&
          runtimeRetired === true && nativeChatsAbsent && canonicalSourcesCleared &&
          sourceContentsRetired === true && crossPlaneVerified === true &&
          allOwnedFilesAbsent && retainedFileRefsIntact;
        let nativeFileProjectBindingsCleared = afterVerifiedProjectDeletion == null;
        let nativeFileProjectBindingReceipt = null;
        if (baseComplete && afterVerifiedProjectDeletion) {
          nativeFileProjectBindingReceipt = await afterVerifiedProjectDeletion({
            projectId:project, ownerId:actor,
            receiptRevision:finalReceipt.c5_receipt_revision,
          });
          nativeFileProjectBindingsCleared =
            nativeFileProjectBindingReceipt?.verified === true &&
            nativeFileProjectBindingReceipt.project_id === project &&
            nativeFileProjectBindingReceipt.remaining_reference_count === 0;
        }

        const proof = {
          projectId:project, ownerId:actor,
          sourceClass:'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES',
          projectAndRuntimeRetired:nativeProjectAbsent && unassignedAbsent &&
            runtimeRetired === true,
          allOwnedChatsMessagesRemoved:nativeChatsAbsent,
          sourceMemoryAndOwnedFileReferencesCleared:
            canonicalSourcesCleared && sourceContentsRetired === true &&
            crossPlaneVerified === true && nativeFileProjectBindingsCleared,
          sourceContentsRetired:sourceContentsRetired === true,
          exclusiveBlobsAndIndexesVerified:allOwnedFilesAbsent,
          movedChatAndSharedFilesRetained:retainedFileRefsIntact &&
            crossPlaneVerified === true,
          allCrossPlaneReferencesVerified:crossPlaneVerified === true &&
            nativeFileProjectBindingsCleared,
          nativeFileProjectBindingsCleared,
          nativeFileProjectBindingReceipt,
          userRecoverable:false, receiptRevision:finalReceipt.c5_receipt_revision,
        };
        const complete = proof.projectAndRuntimeRetired &&
          proof.allOwnedChatsMessagesRemoved &&
          proof.sourceMemoryAndOwnedFileReferencesCleared &&
          proof.exclusiveBlobsAndIndexesVerified &&
          proof.movedChatAndSharedFilesRetained &&
          proof.allCrossPlaneReferencesVerified;
        if (complete) {
          need(await owners.releaseEffectAdmission({
            projectId:project, ownerId:actor,
          }) === true, 'C5_COMPLETED_WRITE_FENCE_RELEASE_UNCONFIRMED');
        }
        return proof;
      },
    });
      return endpoints;
    } catch (error) {
      if (enrollNativeOnly) {
        try { await owners.abortPreEffectAdmission({ projectId:project, ownerId:actor }); }
        catch { throw new C5ProductEntryStop('C5_PRE_EFFECT_ABORT_RELEASE_UNCONFIRMED'); }
      }
      throw error;
    }
  }


  async function dispatch(req,res,op) {
    try {
      const handlers = await construct(req,op==='prepare');
      return await handlers[op==='prepare'?'readiness':op](req,res);
    } catch (error) {
      // Preserve only one bounded C5 control code. Never expose paths, data,
      // stack traces, arbitrary provider errors, or fall back to unassign-only.
      const candidate=String(error?.code||error?.message||'');
      const code=/^C5_[A-Z0-9_]{1,120}$/.test(candidate)
        ? candidate : 'C5_CURRENT_NATIVE_PRODUCT_OWNER_OR_OUTCOME_UNAVAILABLE';
      return res.status(409).json({
        status:'C5_WHOLE_PROJECT_DELETE_UNVERIFIED',
        code,verified:false,retryAutomatically:false,
      });
    }
  }
  return {
    readiness:(req,res)=>dispatch(req,res,'readiness'),
    status:(req,res)=>dispatch(req,res,'status'),
    prepare:(req,res)=>dispatch(req,res,'prepare'),
    deleteProject:(req,res)=>dispatch(req,res,'deleteProject'),
  };
}
module.exports={createC5NativeWholeProjectProductRoute,C5ProductEntryStop};
