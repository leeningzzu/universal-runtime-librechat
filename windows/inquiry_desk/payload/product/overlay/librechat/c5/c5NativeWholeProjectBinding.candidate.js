'use strict';
/**
 * Aides P1 C5: bind the ACCEPTED full Project-delete cascade to current native
 * LibreChat Mongo owners and the accepted Runtime/SourceRef owners.
 *
 * ISOLATED RELEASE CANDIDATE, NOT PRODUCTION WIRED. No new backend/database,
 * scheduler, message store, native File strategy, or rollback engine.
 *
 * All fourteen accepted hook contracts have concrete bindings below. The
 * Runtime admission, operation receipt, cross-consumer reference graph and
 * blob/vector attestation MUST come from their existing authoritative owners.
 * No invented fallback; missing one owner fails closed before any mutation.
 *
 * Never substitute this Project hard-delete for standalone Chat/File 30-day
 * restorable Trash. This only handles explicit delete of ONE owned Project.
 */
const { createNativeChatFileDeleteConsumers } =
  require('./c5NativeChatFileConsumers.candidate.js');
const { buildProjectCascadeHandler } =
  require('./projectDeleteOwnedCascade.c5.product.candidate.js');
const { processDeleteRequest } = require('~/server/services/Files/process');
const { getAppConfig } = require('~/server/services/Config');

class C5BindingStop extends Error {
  constructor(code) { super(code); this.code = code; this.name = 'C5BindingStop'; }
}
const requireProof = (ok, code) => { if (!ok) throw new C5BindingStop(code); };
const nonempty = (x) => typeof x === 'string' && x.length > 0 && x.length <= 256;
const idString = (x) => String(x == null ? '' : x);
const codeDigestShape = (x) => x && typeof x === 'object' && !Array.isArray(x);
const hookNames = Object.freeze([
  'readNativeInventory', 'verifyPreEffectBoundary',
  'loadRuntimeOperationReceipt', 'saveRuntimeOperationReceipt',
  'runAcceptedC5NativeDelete', 'deleteNativeChat', 'verifyNativeChatAbsent',
  'assertNativeFileExclusivityNow', 'deleteNativeExclusiveFile',
  'verifyNativeFileAndDerivativesAbsent', 'verifyNativeRetainedFilePresent',
  'verifyNativeProjectAndRuntimeRetired', 'prepareNativeProjectFileCascade',
  'restoreDurableFileSeals', 'retireRuntimeProjectSourceContents',
  'verifyRuntimeProjectSourceContentsRetired', 'verifyNoDeletedObjectReferences',
]);

function createC5CurrentNativeWholeProjectDelete({
  request, models, nativeDb, runtimeOwner, admissionOwner,
  referenceOwner, nativeFetch, prepareNativeProjectFileCascade,
  retireRuntimeProjectSourceContents, verifyRuntimeProjectSourceContentsRetired,
}) {
  const ownerId = idString(request?.user?.id ?? request?.user?._id);
  const projectId = idString(request?.params?.projectId);
  requireProof(nonempty(ownerId) && /^[a-f0-9]{24}$/i.test(projectId),
    'C5_AUTHENTICATED_ROUTE_PROJECT_REQUIRED');
  requireProof(models && nativeDb && runtimeOwner && admissionOwner && referenceOwner,
    'C5_REQUIRED_NATIVE_OWNER_MISSING');
  requireProof(
    typeof prepareNativeProjectFileCascade === 'function',
    'C5_NATIVE_PROJECT_SOURCE_CLEANUP_OWNER_MISSING',
  );
  requireProof(
    typeof retireRuntimeProjectSourceContents === 'function',
    'C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_OWNER_MISSING',
  );
  requireProof(
    typeof verifyRuntimeProjectSourceContentsRetired === 'function',
    'C5_RUNTIME_SOURCE_CONTENT_VERIFIER_MISSING',
  );
  const neededModels = ['ChatProject', 'Conversation', 'Message', 'ToolCall',
    'SharedLink', 'File', 'Assistant'];
  for (const k of neededModels) {
    requireProof(models[k] && typeof models[k].countDocuments === 'function',
      'C5_NATIVE_MODEL_MISSING_' + k);
  }
  for (const [owner, methods] of [
    [nativeDb, ['getChatProject','getSharedResourceFileIds']],
    [runtimeOwner, ['loadOperationReceipt','persistOperationReceipt',
      'executeAcceptedRetirement', 'readRetirementState']],
    [admissionOwner, ['proveInventoryFence', 'recheckEffectFence']],
    [referenceOwner, ['readCompleteProjectFileGraph', 'restoreDurableFileSeals',
      'readSealedNativeFileDeleteDescriptor', 'recheckExclusiveFile',
      'verifyFileBytesAndDerivativesAbsent', 'verifyRetainedFileBytesPresent',
      'verifyCrossPlaneNoReferences']],
  ]) {
    for (const k of methods) requireProof(typeof owner[k] === 'function',
      'C5_MATURE_NATIVE_OWNER_METHOD_MISSING_' + k);
  }
  const local = { ownerId, projectId };

  // Native File.user cannot establish exclusive Project ownership. Scan native
  // File rows and Message attachments across owners; Runtime/Library/Agent
  // references and Blob/vector attestations remain separate authority checks.
  async function assertNoOtherNativeFileConsumers({
    fileId, userId, chatIds, requireRow, sealedNativeChatAnchor = false,
  }) {
    requireProof(nonempty(fileId) && userId === ownerId &&
      Array.isArray(chatIds) && chatIds.every(nonempty),
      'C5_NATIVE_FILE_REFERENCE_SCAN_SCOPE_INVALID');    requireProof(typeof sealedNativeChatAnchor==='boolean' &&
      (!requireRow || sealedNativeChatAnchor===false),
      'C5_NATIVE_FILE_ANCHOR_SCOPE_INVALID');

    const allowedChats = new Set(chatIds);
    // The real LibreChat v0.8.8 File schema also records cross-run source
    // FileIDs and Code Environment references (including dynamic route keys).
    // Reuse those FIRST-PARTY rows; do not build a second reference store.
    const [rows, attached, runDependents, codeDependents, dynamicCodeRefs] =
      await Promise.all([
        models.File.find({file_id:fileId})
          .select('file_id user conversationId').lean(),
        models.Message.find({'files.file_id':fileId})
          .select('user conversationId files').lean(),
        models.File.find({$or:[
          {'metadata.runFile.sourceFileId':fileId},
          {'metadata.runFile.inputFileIds':fileId},
        ]}).limit(1).select('file_id').lean(),
        models.File.find({'metadata.codeEnvRef.file_id':fileId})
          .limit(1).select('file_id').lean(),
        models.File.find({'metadata.codeEnvRefs':{$exists:true}})
          .limit(2001).select('metadata.codeEnvRefs').lean(),
      ]);
    requireProof(
      [rows,attached,runDependents,codeDependents,dynamicCodeRefs]
        .every(Array.isArray),
      'C5_NATIVE_FILE_REFERENCE_SCAN_UNVERIFIED');
    requireProof(runDependents.length===0,
      'C5_NATIVE_RUN_ARTIFACT_REFERENCES_FILE');
    requireProof(codeDependents.length===0,
      'C5_NATIVE_CODE_ENVIRONMENT_REFERENCES_FILE');
    requireProof(dynamicCodeRefs.length<=2000,
      'C5_NATIVE_DYNAMIC_CODE_REFERENCES_UNBOUNDED');
    for(const file of dynamicCodeRefs) {
      const refs=file?.metadata?.codeEnvRefs;
      requireProof(refs && typeof refs==='object' && !Array.isArray(refs),
        'C5_NATIVE_DYNAMIC_CODE_REFERENCE_MAP_INVALID');
      for(const item of Object.values(refs)) {
        if(item==null) continue;
        requireProof(item && typeof item==='object' &&
          nonempty(item.file_id),
          'C5_NATIVE_DYNAMIC_CODE_REFERENCE_ITEM_INVALID');
        requireProof(item.file_id!==fileId,
          'C5_NATIVE_DYNAMIC_CODE_ENVIRONMENT_REFERENCES_FILE');
      }
    }
    requireProof(rows.length <= 1 && (!requireRow || rows.length === 1),
      'C5_NATIVE_FILE_RECORD_ABSENT_OR_AMBIGUOUS');
    // First verify EVERY Message owner. LibreChat's current File rows may
    // have no conversationId at all; a first-party Message.files FileID is
    // the actual Chat attachment, not an inferred filename or user match.
    let currentNativeChatAnchor = false;
    for (const message of attached) {
      requireProof(Array.isArray(message?.files) &&
        message.files.some((item) => item && item.file_id === fileId),
        'C5_NATIVE_ATTACHMENT_QUERY_AMBIGUOUS');
      requireProof(idString(message.user) === userId &&
        allowedChats.has(message.conversationId),
        'C5_NATIVE_MESSAGE_FILE_USED_OUTSIDE_TARGET_PROJECT');
      currentNativeChatAnchor = true;
    }
    for (const row of rows) {
      requireProof(row?.file_id === fileId && idString(row.user) === userId,
        'C5_NATIVE_FILE_RECORD_OWNER_CHANGED');
      if (row.conversationId == null || row.conversationId === '') {
        // During readiness require an observed target Message anchor. After
        // native Chat deletion the Message is gone, so only the immutable
        // C5 sealed plan's original first-party anchor can replace it.
        requireProof(currentNativeChatAnchor || sealedNativeChatAnchor,
          'C5_UNBOUND_FILE_REQUIRES_NATIVE_SEALED_CHAT_ANCHOR');
      } else {
        requireProof(allowedChats.has(row.conversationId),
          'C5_NATIVE_FILE_RECORD_USED_OUTSIDE_TARGET_PROJECT');
        currentNativeChatAnchor = true;
      }
    }
    return {nativeChatAnchor:currentNativeChatAnchor};
  }

  async function deleteSealedStorageFile(file) {
    requireProof(file?.c5SealedStorageOnly === true &&
      file.user === ownerId && nonempty(file.file_id) &&
      typeof file.filepath === 'string' &&
      (file.filepath.startsWith(`/uploads/${ownerId}/`) ||
        file.filepath.startsWith(`/images/${ownerId}/`)),
    'C5_SEALED_STORAGE_DELETE_DESCRIPTOR_INVALID');
    // This C5 route is outside the native /api/files middleware chain. Reuse
    // LibreChat's own actor-scoped config loader before invoking the mature
    // storage/RAG/metadata delete service; never manufacture paths or a second
    // storage deletion implementation.
    const config = request.config ?? await getAppConfig({
      role: request.user?.role,
      tenantId: request.user?.tenantId,
      userId: ownerId,
    });
    requireProof(config?.paths && typeof config.paths === 'object',
      'C5_NATIVE_FILE_CONFIG_UNAVAILABLE');
    const scopedRequest = Object.assign(Object.create(request), {
      config,
      body: request.body ?? {},
    });
    const result = await processDeleteRequest({ req: scopedRequest, files:[file] });
    requireProof(result && Array.isArray(result.deletedFileIds) &&
      Array.isArray(result.failedFileIds),
    'C5_SEALED_STORAGE_DELETE_RESULT_INVALID');
    return result;
  }

  const native = createNativeChatFileDeleteConsumers({
    request,
    nativeFetch,
    deleteSealedStorageFile,
    readCurrentC5Operation: ({ projectId: p, ownerId: u }) =>
      runtimeOwner.loadOperationReceipt({projectId:p,ownerId:u}),
    readOwnedNativeFile: async ({ownerId:u, fileId}) => {
      requireProof(u === ownerId, 'C5_OWNER_CHANGED');
      const existing = await models.File.findOne({file_id:fileId}).lean();
      if (existing != null) {
        requireProof(idString(existing.user) === u,
          'C5_FILE_NATIVE_OWNER_CHANGED');
        return existing;
      }
      return await referenceOwner.readSealedNativeFileDeleteDescriptor({
        projectId, ownerId:u, fileId,
      });
    },
    reconfirmExclusiveFile: async ({projectId:p, ownerId:u, fileId, plan}) => {
      requireProof(p === projectId && u === ownerId, 'C5_IDENTITY_CHANGED');
      const fence = await admissionOwner.recheckEffectFence({
        projectId:p, ownerId:u, revision:plan.revision,
        phase:'NATIVE_FILE_EFFECT', plan,
      });
      requireProof(fence?.permitted === true &&
        fence.projectId === p && fence.ownerId === u &&
        fence.jobScope === 'TARGET_PROJECT_CURRENT_EFFECTS' &&
        fence.exclusiveWriter === true &&
        fence.mongoWriteCountersAdmitted === true && fence.activePinnedJobs === 0,
      'C5_FILE_EFFECT_ADMISSION_LOST');
      const refs = await referenceOwner.recheckExclusiveFile({
        projectId:p, ownerId:u, fileId, plan,
      });
      requireProof(refs?.authoritative === true &&
        refs.ownerAuthorized === true && refs.refsComplete === true &&
        refs.noOtherConsumers === true, 'C5_CURRENT_FILE_GRAPH_UNPROVEN');
      // Recheck global native consumers immediately before File DELETE.
      const sealedNativeChatAnchor = Array.isArray(plan.exclusive) &&
        plan.exclusive.some(file=>file.id===fileId &&
          file.nativeChatAnchor===true);
      await assertNoOtherNativeFileConsumers({
        fileId, userId:u, chatIds:plan.chats, requireRow:false,
        sealedNativeChatAnchor,
      });
      // Final native Agent-reference check before each File effect. The
      // previously accepted C5 owner already rechecks all other consumers.
      const activeAgentRefs=await nativeDb.getSharedResourceFileIds({
        file_ids:[fileId],
      });
      requireProof(Array.isArray(activeAgentRefs) &&
        activeAgentRefs.length===0,
        'C5_NATIVE_AGENT_FILE_REF_BECAME_ACTIVE');
      // Native Assistant.file_ids references are outside Agent resource
      // tool_resources; the existing Agent lookup cannot prove their absence.
      const assistantRefs=await models.Assistant.countDocuments({file_ids:fileId});
      requireProof(Number.isInteger(assistantRefs) && assistantRefs===0,
        'C5_NATIVE_ASSISTANT_FILE_REF_BECAME_ACTIVE');

      return refs;
    },
  });

  async function readNativeInventory({projectId:p, ownerId:u}) {
    requireProof(p === projectId && u === ownerId,
      'C5_INVENTORY_REQUEST_OWNER_CHANGED');
    const ownedProject = await nativeDb.getChatProject(u, p);
    requireProof(ownedProject != null && idString(ownedProject.user) === u &&
      idString(ownedProject._id) === p, 'C5_NATIVE_PROJECT_OWNER_NOT_CONFIRMED');

    // Direct native model query deliberately covers archived chats too.
    // getConvosByCursor excludes archive by default and is NOT an inventory.
    const rows = await models.Conversation.find({
      user:u, chatProjectId:p,
    }).select('conversationId user chatProjectId').lean();
    requireProof(Array.isArray(rows), 'C5_NATIVE_PROJECT_CHATS_UNREADABLE');
    const ids = new Set();
    const chats = [];
    for (const row of rows) {
      const id = row?.conversationId;
      requireProof(nonempty(id) && idString(row.user) === u &&
        row.chatProjectId === p && !ids.has(id),
        'C5_CONVERSATION_OWNER_OR_MEMBERSHIP_AMBIGUOUS');
      ids.add(id);
      chats.push({id, ownerId:u, projectId:p, boundAtSnapshot:true});
    }

    const gate = await admissionOwner.proveInventoryFence({
      projectId:p, ownerId:u, chatIds:[...ids],
    });
    requireProof(gate?.permitted === true &&
      gate.projectId === p && gate.ownerId === u &&
      gate.jobScope === 'TARGET_PROJECT_CURRENT_EFFECTS' &&
      gate.exclusiveWriter === true && gate.forwardRecoveryReady === true &&
      gate.activePinnedJobs === 0 &&
      Number.isInteger(gate.projectRevision) && gate.projectRevision > 0 &&
      gate.projectMembershipSealed === true,
      'C5_WRITER_JOB_BACKUP_OR_MEMBERSHIP_FENCE_NOT_PROVEN');

    // Only native reference owners can supply all refs across Project,
    // moved Chats, global Library, Agents, other Projects, Runtime SourceRefs.
    // Never guess ownership from filepath, SourceRef or File.user alone.
    const graph = await referenceOwner.readCompleteProjectFileGraph({
      projectId:p, ownerId:u, chatIds:[...ids],
      expectedProjectRevision:gate.projectRevision,
    });
    requireProof(graph?.authoritative === true && graph.complete === true &&
      graph.projectId === p && graph.ownerId === u &&
      graph.projectRevision === gate.projectRevision &&
      graph.runtimeCurrentReferences?.schema ===
        'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001' &&
      typeof graph.protectedAssetCensusSha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(graph.protectedAssetCensusSha256) &&
      Array.isArray(graph.files) && Array.isArray(graph.runtimeSources),
    'C5_CROSS_CONSUMER_GRAPH_INCOMPLETE');

    // Native cross-check against actual first-party File/Message owners.
    // File has no Project ID field. A purportedly complete graph omitting a
    // directly attached FileID must be rejected before any Delete.
    // The external Runtime/Library/Agent reference owner remains responsible
    // for indirect/global/shared refs; do not infer exclusivity here.
    if (ids.size > 0) {
      const boundFiles = await models.File.find({
        user:u, conversationId:{$in:[...ids]},
      }).select('user conversationId file_id').lean();
      const attachedMessages = await models.Message.find({
        user:u, conversationId:{$in:[...ids]},
      }).select('user conversationId files').lean();
      requireProof(Array.isArray(boundFiles) && Array.isArray(attachedMessages),
        'C5_NATIVE_FILE_OR_MESSAGE_READ_UNPROVEN');
      const knownNativeIds = new Set();
      for (const file of boundFiles) {
        requireProof(idString(file.user)===u && ids.has(file.conversationId) &&
          nonempty(file.file_id), 'C5_NATIVE_FILE_ATTACHMENT_MALFORMED');
        knownNativeIds.add(file.file_id);
      }
      for (const message of attachedMessages) {
        requireProof(idString(message.user)===u &&
          ids.has(message.conversationId) &&
          (message.files===undefined || Array.isArray(message.files)),
          'C5_NATIVE_MESSAGE_FILES_MALFORMED');
        for (const link of message.files||[]) {
          requireProof(link && typeof link==='object' &&
            nonempty(link.file_id), 'C5_NATIVE_MESSAGE_FILE_ID_AMBIGUOUS');
          knownNativeIds.add(link.file_id);
        }
      }
      const covered = new Set(graph.files.map(f=>f?.id));
      for (const fileId of knownNativeIds) {
        requireProof(covered.has(fileId),
          'C5_NATIVE_FILE_REFERENCE_OMITTED_FROM_AUTHORITY_GRAPH');
      }
    }

    // Reuse LibreChat's exact cross-tenant Agent resource-reference checker.
    // Its result must never be narrowed to just the current user or one Agent:
    // duplicated Agents can legitimately share the same FileID and vectors.
    const idsInGraph = graph.files.map(x=>x?.id);
    requireProof(idsInGraph.every(nonempty) &&
      new Set(idsInGraph).size===idsInGraph.length &&
      idsInGraph.length<=2000,
      'C5_FILE_GRAPH_IDS_MALFORMED_OR_UNBOUNDED');
    const nativeChatAnchoredFiles = new Set();
    if (idsInGraph.length>0) {

      for (const file of graph.files) {
        const onlyThisProject = file.ownerId === u &&
          Array.isArray(file.refs) && file.refs.length > 0 &&
          file.refs.every((ref) => ref && (
            (ref.kind === 'project' && ref.id === p) ||
            (ref.kind === 'chat' && ids.has(ref.id))
          )) && !file.protected && !file.backupProtected &&
          !file.independentLibrary;
        if (onlyThisProject) {
          // A historical Message can still refer to a known-missing original
          // whose native File row and physical bytes are already absent.
          // NEVER fabricate/recreate the original. Permit this narrow case
          // only with an exact cross-plane owner claim plus actual global
          // File/Blob/vector/CodeEnv/Agent/Source absence, and a live Message
          // anchor in this Project. Bytes reclaimed from an already-missing
          // original are zero; protected backup/audit records remain intact.
          const knownMissing = file.knownMissingOriginal === true;
          if (knownMissing) {
            requireProof(file.originalRecoveryState ===
              'KNOWN_MISSING_NOT_RESTORED' && file.bytes === 0,
              'C5_KNOWN_MISSING_ORIGINAL_OWNER_RECEIPT_INVALID');
            const nativeCount = await models.File.countDocuments({
              file_id:file.id,
            });
            requireProof(nativeCount === 0,
              'C5_KNOWN_MISSING_ORIGINAL_NATIVE_RECORD_STILL_EXISTS');
            const absent = await referenceOwner.verifyFileBytesAndDerivativesAbsent({
              projectId:p, ownerId:u, fileId:file.id,
            });
            requireProof(absent?.authoritative === true &&
              absent.fileRecordAbsent === true &&
              absent.blobAbsent === true &&
              absent.vectorAbsent === true &&
              absent.codeEnvAbsent === true &&
              absent.agentReferencesAbsent === true &&
              absent.sourceReferencesAbsent === true,
              'C5_KNOWN_MISSING_ORIGINAL_PHYSICAL_ABSENCE_UNPROVEN');
          }
          const nativeProof = await assertNoOtherNativeFileConsumers({
            fileId:file.id, userId:u, chatIds:[...ids],
            requireRow:file.seal?.rowPresent === true,
          });
          requireProof(nativeProof.nativeChatAnchor === true,
            'C5_EXCLUSIVE_FILE_NATIVE_CHAT_ANCHOR_NOT_ATTESTED');
          nativeChatAnchoredFiles.add(file.id);
          const assistantRefs=await models.Assistant.countDocuments({
            file_ids:file.id,
          });
          requireProof(Number.isInteger(assistantRefs) && assistantRefs===0,
            'C5_NATIVE_ASSISTANT_FILE_SHARED_OUTSIDE_TARGET_PROJECT');
        }
      }
      const agentHeld=await nativeDb.getSharedResourceFileIds({
        file_ids:idsInGraph,
      });
      requireProof(Array.isArray(agentHeld) &&
        agentHeld.every(id=>idsInGraph.includes(id)),
        'C5_NATIVE_AGENT_REFERENCE_LOOKUP_UNPROVEN');
      const held=new Set(agentHeld);
      for(const file of graph.files) {
        if(!held.has(file.id)) continue;
        const stillExclusive= file.ownerId===u &&
          Array.isArray(file.refs) && file.refs.length>0 &&
          file.refs.every(ref=>ref && (
            (ref.kind==='project' && ref.id===p) ||
            (ref.kind==='chat' && ids.has(ref.id))
          )) && !file.protected && !file.backupProtected &&
          !file.independentLibrary;
        requireProof(!stillExclusive,
          'C5_AGENT_REFERENCE_MISSING_FROM_CASCADE_GRAPH');
      }
    }
    return {
      projectId:p,ownerId:u,revision:gate.projectRevision,
      authoritative:true,complete:true,legalOwner:true,
      uniqueWriter:true,durableForwardRecoveryReady:true,activePinnedJobs:0,
      chats,
      runtimeCurrentReferences:graph.runtimeCurrentReferences,
      runtimeSources:graph.runtimeSources,
      protectedAssetCensusSha256:graph.protectedAssetCensusSha256,
      files:graph.files.map(file=>nativeChatAnchoredFiles.has(file.id)
        ? {...file,nativeChatAnchor:true} : file),
    };
  }

  async function verifyPreEffectBoundary({projectId:p,ownerId:u,plan,phase}) {
    requireProof(p===projectId && u===ownerId &&
      plan?.projectId===p && plan.ownerId===u &&
      Number.isInteger(plan.revision) && plan.revision>0,
    'C5_EFFECT_BOUNDARY_SCOPE_CHANGED');
    requireProof(['BEFORE_EFFECT','RECOVERY_READINESS','BEFORE_C5',
      'CONTINUE_PARTIAL'].includes(phase),
      'C5_EFFECT_BOUNDARY_PHASE_UNKNOWN');
    const result=await admissionOwner.recheckEffectFence({
      projectId:p,ownerId:u,revision:plan.revision,phase,plan,
    });
    const postEffect = ['RECOVERY_READINESS','CONTINUE_PARTIAL'].includes(phase);
    return result?.permitted === true &&
      result.projectId === p && result.ownerId === u &&
      result.jobScope === 'TARGET_PROJECT_CURRENT_EFFECTS' &&
      result.exclusiveWriter === true &&
      (postEffect ? result.mongoWriteCountersAdmitted === true :
        result.forwardRecoveryReady === true) &&
      result.activePinnedJobs === 0 &&
      result.projectMembershipSealed === true;
  }

  async function loadRuntimeOperationReceipt({projectId:p,ownerId:u}) {
    requireProof(p===projectId && u===ownerId,'C5_RECEIPT_OWNER_SCOPE_CHANGED');
    const result=await runtimeOwner.loadOperationReceipt({projectId:p,ownerId:u});
    requireProof(result == null || (codeDigestShape(result) &&
      result.projectId===p && result.ownerId===u &&
      Number.isInteger(result.c5_receipt_revision) && result.c5_receipt_revision>0),
    'C5_RUNTIME_RECEIPT_SCOPE_INVALID');
    return result;
  }
  async function saveRuntimeOperationReceipt(op) {
    requireProof(codeDigestShape(op) &&
      op.projectId===projectId && op.ownerId===ownerId &&
      op.schema==='C5_PROJECT_CASCADE_R001',
      'C5_RECEIPT_WRITE_SCOPE_INVALID');
    const result=await runtimeOwner.persistOperationReceipt(op);
    const confirmed=result?.durable === true && result?.projectId===projectId &&
      result?.ownerId===ownerId && Number.isInteger(result?.revision) &&
      result.revision>(op.c5_receipt_revision||0);
    if (confirmed) op.c5_receipt_revision=result.revision;
    return confirmed;
  }

  async function runAcceptedC5NativeDelete(req) {
    requireProof(req === request,'C5_NATIVE_DELETE_REQUEST_SWITCH');
    const result=await runtimeOwner.executeAcceptedRetirement(req);
    requireProof(result?.status===200 &&
      result.nativeAndRuntimeConfirmed===true,
      'C5_NATIVE_RETIREMENT_OWNER_UNCONFIRMED');
    return result;
  }

  async function prepareNativeProjectFileCascadeBound({
    projectId:p, ownerId:u, plan,
  }) {
    requireProof(
      p === projectId && u === ownerId && plan?.projectId === p,
      'C5_NATIVE_PROJECT_SOURCE_CLEANUP_SCOPE_CHANGED',
    );
    const receipt = await prepareNativeProjectFileCascade({
      projectId:p, ownerId:u, plan,
    });
    requireProof(
      receipt?.verified === true && receipt.project_id === p &&
        receipt.remaining_reference_count === 0,
      'C5_NATIVE_PROJECT_SOURCE_CLEANUP_UNVERIFIED',
    );
    return receipt;
  }

  async function restoreDurableFileSealsBound({
    projectId:p, ownerId:u, plan, snapshot,
  }) {
    requireProof(p === projectId && u === ownerId && plan?.projectId === p,
      'C5_DURABLE_FILE_SEAL_RESTORE_SCOPE_CHANGED');
    return await referenceOwner.restoreDurableFileSeals({
      projectId:p, ownerId:u, plan, snapshot,
    });
  }

  async function retireRuntimeProjectSourceContentsBound({
    projectId:p, ownerId:u, plan, snapshot,
  }) {
    requireProof(
      p === projectId && u === ownerId && plan?.projectId === p &&
        typeof plan.planSha256 === 'string' && /^[0-9a-f]{64}$/.test(plan.planSha256),
      'C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_SCOPE_CHANGED',
    );
    const receipt = await retireRuntimeProjectSourceContents({
      projectId:p, ownerId:u, plan, snapshot,
    });
    requireProof(
      receipt?.verified === true && receipt.project_id === p &&
        Number.isInteger(receipt.source_count) && receipt.source_count >= 0,
      'C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_UNVERIFIED',
    );
    return receipt;
  }

  async function verifyRuntimeProjectSourceContentsRetiredBound({
    projectId:p, ownerId:u, plan, snapshot,
  }) {
    requireProof(p === projectId && u === ownerId && plan?.projectId === p,
      'C5_RUNTIME_SOURCE_CONTENT_VERIFY_SCOPE_CHANGED');
    return await verifyRuntimeProjectSourceContentsRetired({
      projectId:p, ownerId:u, plan, snapshot,
    });
  }

  async function verifyNativeChatAbsent({ownerId:u,chatId}) {
    requireProof(u===ownerId && nonempty(chatId),
      'C5_VERIFY_CHAT_SCOPE_INVALID');
    const q={user:u,conversationId:chatId};
    const [convo,messages,tools,links,descendants] = await Promise.all([
      models.Conversation.countDocuments(q),
      models.Message.countDocuments(q),
      models.ToolCall.countDocuments(q),
      models.SharedLink.countDocuments(q),
      models.Conversation.countDocuments({
        user:u,'subagentThread.rootConversationId':chatId,
      }),
    ]);
    return {
      conversationAbsent:convo===0 && descendants===0,
      messagesAbsent:messages===0,
      toolCallsAbsent:tools===0,
      sharedLinksAbsent:links===0,
    };
  }

  async function assertNativeFileExclusivityNow({projectId:p,ownerId:u,fileId,plan}) {
    requireProof(p===projectId && u===ownerId && nonempty(fileId) &&
      plan?.projectId===p,'C5_NATIVE_FILE_SCOPE_CHANGED');
    const gate=await admissionOwner.recheckEffectFence({
      projectId:p,ownerId:u,revision:plan.revision,
      phase:'NATIVE_FILE_EFFECT',plan,
    });
    if (!(gate?.permitted===true &&
      gate.projectId===p && gate.ownerId===u &&
      gate.jobScope==='TARGET_PROJECT_CURRENT_EFFECTS' &&
      gate.exclusiveWriter===true &&
      gate.mongoWriteCountersAdmitted===true && gate.activePinnedJobs===0))
      return {refsComplete:false,noOtherConsumers:false,ownerAuthorized:false};
    const proof=await referenceOwner.recheckExclusiveFile({
      projectId:p,ownerId:u,fileId,plan,
    });
    const liveAgentRefs=await nativeDb.getSharedResourceFileIds({
      file_ids:[fileId],
    });
    requireProof(Array.isArray(liveAgentRefs) &&
      liveAgentRefs.length===0, 'C5_NATIVE_AGENT_RESOURCE_STILL_REFERENCES_FILE');
    const assistantRefs=await models.Assistant.countDocuments({file_ids:fileId});
    requireProof(Number.isInteger(assistantRefs) && assistantRefs===0,
      'C5_NATIVE_ASSISTANT_RESOURCE_STILL_REFERENCES_FILE');

    return proof?.authoritative===true
      ? {refsComplete:proof.refsComplete===true,
        noOtherConsumers:proof.noOtherConsumers===true,
        ownerAuthorized:proof.ownerAuthorized===true}
      : {refsComplete:false,noOtherConsumers:false,ownerAuthorized:false};
  }

  async function verifyNativeFileAndDerivativesAbsent({ownerId:u,fileId}) {
    requireProof(u===ownerId && nonempty(fileId),
      'C5_VERIFY_FILE_SCOPE_INVALID');
    // This independent AFTER-EFFECT native readback must not trust a
    // cross-plane receipt's "complete" claim if LibreChat still has a
    // Message, Agent, Assistant, run-file or CodeEnv reference to this ID.
    // Query all users, not only the deleted Project or the original owner.
    const [rowCount,assistantRefs,messageRefs,runRefs,codeRefs,
      dynamicCodeRefs,agentHeld] = await Promise.all([
      models.File.countDocuments({file_id:fileId}),
      models.Assistant.countDocuments({file_ids:fileId}),
      models.Message.countDocuments({'files.file_id':fileId}),
      models.File.countDocuments({$or:[
        {'metadata.runFile.sourceFileId':fileId},
        {'metadata.runFile.inputFileIds':fileId},
      ]}),
      models.File.countDocuments({'metadata.codeEnvRef.file_id':fileId}),
      models.File.find({'metadata.codeEnvRefs':{$exists:true}})
        .limit(2001).select('metadata.codeEnvRefs').lean(),
      nativeDb.getSharedResourceFileIds({file_ids:[fileId]}),
    ]);
    requireProof([rowCount,assistantRefs,messageRefs,runRefs,codeRefs]
      .every(n=>Number.isSafeInteger(n) && n>=0) &&
      Array.isArray(dynamicCodeRefs) &&
      dynamicCodeRefs.length<=2000 && Array.isArray(agentHeld) &&
      agentHeld.every(id=>nonempty(id)),
      'C5_NATIVE_POST_EFFECT_REFERENCE_READ_UNVERIFIED');
    let dynamicCodeReferencePresent=false;
    for(const entry of dynamicCodeRefs) {
      const refs=entry?.metadata?.codeEnvRefs;
      requireProof(refs && typeof refs==='object' && !Array.isArray(refs),
        'C5_NATIVE_POST_EFFECT_CODE_REF_MAP_INVALID');
      for(const item of Object.values(refs)) {
        if(item==null) continue;
        requireProof(item && typeof item==='object' &&
          nonempty(item.file_id),
          'C5_NATIVE_POST_EFFECT_CODE_REF_ITEM_INVALID');
        if(item.file_id===fileId) dynamicCodeReferencePresent=true;
      }
    }
    const x=await referenceOwner.verifyFileBytesAndDerivativesAbsent({
      projectId,ownerId:u,fileId,
    });
    return {
      fileRecordAbsent:rowCount===0 && x?.fileRecordAbsent===true,
      blobAbsent:x?.blobAbsent===true,
      vectorAbsent:x?.vectorAbsent===true,
      codeEnvAbsent:codeRefs===0 && !dynamicCodeReferencePresent &&
        x?.codeEnvAbsent===true,
      agentReferencesAbsent:agentHeld.length===0 && assistantRefs===0 &&
        x?.agentReferencesAbsent===true,
      sourceReferencesAbsent:messageRefs===0 && runRefs===0 &&
        x?.sourceReferencesAbsent===true,
    };
  }
  async function verifyNativeRetainedFilePresent({ownerId:u,fileId,projectId:p}) {
    requireProof(u===ownerId && p===projectId && nonempty(fileId),
      'C5_VERIFY_RETAINED_SCOPE_CHANGED');
    const proof=await referenceOwner.verifyRetainedFileBytesPresent({
      projectId:p,ownerId:u,fileId,
    });
    return proof?.authoritative===true && proof.retained===true &&
      proof.bytesPresent===true && proof.legalOtherReferenceStillPresent===true;
  }
  async function verifyNativeProjectAndRuntimeRetired({projectId:p,ownerId:u}) {
    requireProof(p===projectId && u===ownerId,
      'C5_VERIFY_RETIREMENT_SCOPE_CHANGED');
    // Project global ID lookup, not just owner-scoped 404.
    const [nativeCount,assignedCount,runtime]=await Promise.all([
      models.ChatProject.countDocuments({_id:p}),
      models.Conversation.countDocuments({chatProjectId:p}),
      runtimeOwner.readRetirementState({projectId:p,ownerId:u}),
    ]);
    return nativeCount===0 && assignedCount===0 &&
      runtime?.authoritative===true && runtime?.status==='RETIRED' &&
      runtime?.projectId===p;
  }
  async function verifyNoDeletedObjectReferences({ownerId:u,projectId:p,plan}) {
    requireProof(p===projectId && u===ownerId &&
      plan?.projectId===p && plan.ownerId===u &&
      Array.isArray(plan.chats) && plan.chats.length<=2000 &&
      plan.chats.every(nonempty) &&
      new Set(plan.chats).size===plan.chats.length &&
      Array.isArray(plan.exclusive) && Array.isArray(plan.retained),
      'C5_FINAL_REFERENCE_SCOPE_CHANGED');
    const gate=await admissionOwner.recheckEffectFence({
      projectId:p,ownerId:u,revision:plan.revision,
      phase:'C5_FINAL_ABSENCE_VERIFY',plan,
    });
    if (!(gate?.permitted===true && gate.projectId===p &&
      gate.ownerId===u &&
      gate.jobScope==='TARGET_PROJECT_CURRENT_EFFECTS' &&
      gate.exclusiveWriter===true &&
      gate.mongoWriteCountersAdmitted===true && gate.activePinnedJobs===0 &&
      gate.projectMembershipSealed===true)) return false;
    // Read first-party Mongo globally, even when an orphan has changed user.
    const [projects,assigned]=await Promise.all([
      models.ChatProject.countDocuments({_id:p}),
      models.Conversation.countDocuments({chatProjectId:p}),
    ]);
    if (![projects,assigned].every(n=>
      Number.isSafeInteger(n)&&n===0)) return false;
    for(const chatId of plan.chats) {
      const [convos,msgs,tools,links,threads]=await Promise.all([
        models.Conversation.countDocuments({conversationId:chatId}),
        models.Message.countDocuments({conversationId:chatId}),
        models.ToolCall.countDocuments({conversationId:chatId}),
        models.SharedLink.countDocuments({conversationId:chatId}),
        models.Conversation.countDocuments({
          'subagentThread.rootConversationId':chatId,
        }),
      ]);
      if (![convos,msgs,tools,links,threads].every(n=>
        Number.isSafeInteger(n)&&n===0)) return false;
    }
    for(const file of plan.exclusive){
      requireProof(nonempty(file?.id),'C5_FINAL_EXCLUSIVE_FILE_ID_INVALID');
      const state=await verifyNativeFileAndDerivativesAbsent({
        ownerId:u,fileId:file.id,
      });
      if(!(state.fileRecordAbsent&&state.blobAbsent&&state.vectorAbsent&&
        state.codeEnvAbsent&&state.agentReferencesAbsent&&
        state.sourceReferencesAbsent)) return false;
    }
    for(const file of plan.retained){
      requireProof(nonempty(file?.id),'C5_FINAL_RETAINED_FILE_ID_INVALID');
      if(!await verifyNativeRetainedFilePresent({
        ownerId:u,projectId:p,fileId:file.id,
      })) return false;
    }
    // Mongo's positive evidence never stands in for Runtime, Library or
    // physical Blob/vector owner and protected cross-plane verification.
    const verified=await referenceOwner.verifyCrossPlaneNoReferences({
      projectId:p,ownerId:u,plan,
    });
    return verified?.authoritative===true &&
      verified.allOwnedReferencesCleared===true &&
      verified.allRetainedReferencesIntact===true &&
      verified.unknownReferences===0;
  }

  const hooks={
    readNativeInventory,verifyPreEffectBoundary,
    loadRuntimeOperationReceipt,saveRuntimeOperationReceipt,
    runAcceptedC5NativeDelete,
    deleteNativeChat:native.deleteNativeChat,verifyNativeChatAbsent,
    assertNativeFileExclusivityNow,
    deleteNativeExclusiveFile:native.deleteNativeExclusiveFile,
    verifyNativeFileAndDerivativesAbsent,verifyNativeRetainedFilePresent,
    verifyNativeProjectAndRuntimeRetired,
    prepareNativeProjectFileCascade:prepareNativeProjectFileCascadeBound,
    restoreDurableFileSeals:restoreDurableFileSealsBound,
    retireRuntimeProjectSourceContents:retireRuntimeProjectSourceContentsBound,
    verifyRuntimeProjectSourceContentsRetired:
      verifyRuntimeProjectSourceContentsRetiredBound,
    verifyNoDeletedObjectReferences,
  };
  requireProof(hookNames.every(k=>typeof hooks[k]==='function') &&
    Object.keys(hooks).length===hookNames.length,'C5_HOOK_BINDING_INCOMPLETE');
  return { hookNames, hooks,
    // Exact existing orchestrator, no second Project-delete engine.
    handler: buildProjectCascadeHandler(hooks),
  };
}
module.exports={createC5CurrentNativeWholeProjectDelete,C5BindingStop,hookNames};
