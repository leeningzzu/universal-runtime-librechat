'use strict';
const crypto = require('crypto');
const { projectSourceRefs, retiredProjectSourceRefs } = require('~/server/services/ProjectNativeFile');

const RUNTIME_ADAPTER_BASE = String(
  process.env.UR_RUNTIME_ADAPTER_BASE || 'http://ur-runtime-adapter:9000',
).replace(/\/$/, '');
const runtimeKey = () => String(process.env.UR_SHELL_ADAPTER_KEY || '');
const SHA256_RE = /^[0-9a-f]{64}$/;

class CrossStorePermanentDeleteStop extends Error {
  constructor(code, message = code, status = 409) {
    super(message);
    this.name = 'CrossStorePermanentDeleteStop';
    this.code = code;
    this.status = status;
  }
}
const stop = (code, message, status) => { throw new CrossStorePermanentDeleteStop(code, message, status); };
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const stable = (value) => {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
};
const digestJson = (value) => sha256(JSON.stringify(stable(value)));

async function adapterJson(method, path, projectId, payload, actorId = null) {
  const key = runtimeKey();
  if (!key) stop('CROSS_STORE_RUNTIME_ADAPTER_KEY_MISSING', 'Runtime Adapter authorization unavailable', 503);
  const headers = {
    Accept: 'application/json',
    Authorization: `Bearer ${key}`,
    'X-LibreChat-Project-ID': projectId,
  };
  if (actorId !== null) {
    if (typeof actorId !== 'string' || !/^[a-f0-9]{24}$/i.test(actorId)) {
      stop('CROSS_STORE_RUNTIME_ACTOR_IDENTITY_INVALID');
    }
    headers['X-LibreChat-Authenticated-User-ID'] = actorId;
  }
  const options = { method, headers };
  if (payload !== undefined) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(RUNTIME_ADAPTER_BASE + path, options);
  const raw = await response.text();
  let body = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = { raw }; }
  return { ok: response.ok, status: response.status, body, raw };
}

async function fetchRuntimeSourceRetirementCandidates(projectId) {
  const result = await adapterJson(
    'GET', '/v1/runtime-project-library/source-retirement-candidates', projectId,
  );
  if (!result.ok) {
    stop(
      result.body?.error?.code || result.body?.detail?.code || result.body?.code || 'CROSS_STORE_RUNTIME_CANDIDATES_FAILED',
      result.body?.error?.message || result.body?.detail?.message || result.body?.message || 'Runtime Source retirement candidates unavailable',
      result.status,
    );
  }
  const body = result.body;
  if (
    body?.schema !== 'RUNTIME_PROJECT_SOURCE_RETIREMENT_CANDIDATES_R001'
    || !Number.isInteger(body.project_revision)
    || !Array.isArray(body.sources)
    || body.candidate_count !== body.sources.length
  ) {
    stop('CROSS_STORE_RUNTIME_CANDIDATES_SCHEMA_UNKNOWN');
  }
  for (const row of body.sources) {
    if (
      !row || typeof row !== 'object'
      || typeof row.source_ref_id !== 'string' || !row.source_ref_id
      || typeof row.filename !== 'string' || !row.filename
      || typeof row.origin_input_sha256 !== 'string' || !SHA256_RE.test(row.origin_input_sha256)
      || !Number.isInteger(row.origin_input_byte_size) || row.origin_input_byte_size < 1
      || typeof row.active_project_binding !== 'boolean'
      || !['ACTIVE', 'DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(row.retirement_state)
    ) stop('CROSS_STORE_RUNTIME_CANDIDATE_ROW_UNKNOWN');
    if (row.retirement_state === 'CONTENT_RETIRED') {
      const binding = row.completed_native_binding;
      if (
        !binding || typeof binding !== 'object'
        || !['EXACT_NATIVE_FILE_SOURCE_REF', 'EXACT_LEGACY_COHORT_SET', 'EXACT_RUNTIME_SOURCE_ONLY'].includes(binding.binding_class)
        || !Array.isArray(binding.native_file_ids)
        || !Array.isArray(binding.source_ref_ids)
        || !binding.source_ref_ids.includes(row.source_ref_id)
        || typeof binding.binding_evidence_sha256 !== 'string'
        || !SHA256_RE.test(binding.binding_evidence_sha256)
      ) stop('CROSS_STORE_RUNTIME_COMPLETED_BINDING_UNKNOWN');
    } else if (row.completed_native_binding != null) {
      stop('CROSS_STORE_RUNTIME_COMPLETED_BINDING_STATE_MISMATCH');
    }
  }
  return body;
}

async function fetchC5RuntimeSourceRetirementCandidates(projectId, ownerId) {
  const result = await adapterJson(
    'GET', '/v1/runtime-project-c5-source-ref-inventory', projectId, undefined, ownerId,
  );
  if (!result.ok) {
    stop(
      result.body?.error?.code || result.body?.detail?.code || result.body?.code ||
        'C5_RUNTIME_SOURCE_CANDIDATES_FAILED',
      result.body?.error?.message || result.body?.detail?.message || result.body?.message ||
        'C5 Runtime Source retirement candidates unavailable',
      result.status,
    );
  }
  const body = result.body;
  if (
    body?.schema !== 'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001'
    || body.nativeProjectId !== projectId
    || body.actorId !== ownerId
    || !Number.isInteger(body.runtimeProjectRevision)
    || !Array.isArray(body.retirementSources)
    || body.retirementSourceCount !== body.retirementSources.length
    || body.retirementSources.length > 20000
    || typeof body.protectedAssetCensusSha256 !== 'string'
    || !SHA256_RE.test(body.protectedAssetCensusSha256)
  ) stop('C5_RUNTIME_SOURCE_CANDIDATES_SCHEMA_UNKNOWN');
  const ids = new Set();
  for (const row of body.retirementSources) {
    if (
      !row || typeof row !== 'object'
      || typeof row.source_ref_id !== 'string' || !row.source_ref_id
      || ids.has(row.source_ref_id)
      || typeof row.filename !== 'string' || !row.filename
      || typeof row.origin_input_sha256 !== 'string' || !SHA256_RE.test(row.origin_input_sha256)
      || !Number.isInteger(row.origin_input_byte_size) || row.origin_input_byte_size < 1
      || !Number.isInteger(row.shared_content_artifact_count) || row.shared_content_artifact_count < 0
      || typeof row.active_project_binding !== 'boolean'
      || !['ACTIVE', 'DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(row.retirement_state)
    ) stop('C5_RUNTIME_SOURCE_CANDIDATE_ROW_UNKNOWN');
    ids.add(row.source_ref_id);
    if (row.retirement_state === 'CONTENT_RETIRED') {
      const binding = row.completed_native_binding;
      if (
        !binding || typeof binding !== 'object'
        || binding.binding_class !== 'EXACT_RUNTIME_SOURCE_ONLY'
        || !Array.isArray(binding.native_file_ids)
        || binding.native_file_ids.length !== 0
        || !Array.isArray(binding.source_ref_ids)
        || binding.source_ref_ids.length !== 1
        || binding.source_ref_ids[0] !== row.source_ref_id
        || typeof binding.binding_evidence_sha256 !== 'string'
        || !SHA256_RE.test(binding.binding_evidence_sha256)
      ) stop('C5_RUNTIME_SOURCE_COMPLETED_BINDING_UNKNOWN');
    } else if (row.completed_native_binding != null) {
      stop('C5_RUNTIME_SOURCE_COMPLETED_BINDING_STATE_MISMATCH');
    }
  }
  return {
    project_revision: body.runtimeProjectRevision,
    runtime_project_status: body.runtimeProjectStatus,
    protected_asset_census_sha256: body.protectedAssetCensusSha256,
    sources: body.retirementSources,
  };
}

function nativeFileRow(file) {
  const digest = file?.metadata?.nativeSha256;
  if (
    !file || typeof file.file_id !== 'string' || !file.file_id
    || typeof file.filename !== 'string' || !file.filename
    || !Number.isInteger(file.bytes) || file.bytes < 1
    || typeof digest !== 'string' || !SHA256_RE.test(digest)
  ) stop('CROSS_STORE_NATIVE_FILE_IDENTITY_UNKNOWN');
  return { file_id: file.file_id, filename: file.filename, bytes: file.bytes, sha256: digest };
}

function inferCrossStoreProjectId(files, requestedProjectId) {
  if (typeof requestedProjectId === 'string' && requestedProjectId) return requestedProjectId;
  const projects = new Set();
  for (const file of files ?? []) {
    for (const ref of retiredProjectSourceRefs(file?.metadata)) {
      if (typeof ref.librechat_project_id === 'string' && ref.librechat_project_id) {
        projects.add(ref.librechat_project_id);
      }
    }
  }
  return projects.size === 1 ? [...projects][0] : null;
}

function buildCrossStoreRetirementPlan({ files, projectId, runtimeCandidates, nativeReferenceEvidence }) {
  if (!Array.isArray(files) || files.length < 1 || !projectId) {
    stop('CROSS_STORE_DELETE_SCOPE_INVALID', 'Select one or more exact owned files');
  }
  if (
    !nativeReferenceEvidence?.permitted
    || typeof nativeReferenceEvidence.referenceEvidenceSha256 !== 'string'
    || !SHA256_RE.test(nativeReferenceEvidence.referenceEvidenceSha256)
  ) stop('CROSS_STORE_NATIVE_REFERENCE_EVIDENCE_MISSING');
  const rows = files.map(nativeFileRow).sort((a, b) => a.file_id.localeCompare(b.file_id));
  if (new Set(rows.map((row) => row.file_id)).size !== rows.length) {
    stop('CROSS_STORE_NATIVE_FILE_IDS_DUPLICATED');
  }
  if (files.some((file) => projectSourceRefs(file.metadata).length > 0)) {
    stop('CROSS_STORE_ACTIVE_PROJECT_SOURCE_REQUIRES_PROJECT_PERMANENT_DELETE');
  }
  const candidates = runtimeCandidates.sources;
  const bySource = new Map(candidates.map((row) => [row.source_ref_id, row]));
  let bindingClass;
  let sourceRows;
  const exactRefs = files.map((file) =>
    retiredProjectSourceRefs(file.metadata).filter(
      (ref) => ref.librechat_project_id === projectId && ref.binding_class === 'EXACT_NATIVE_FILE_SOURCE_REF',
    ),
  );
  if (exactRefs.every((refs) => refs.length === 1)) {
    const sourceIds = exactRefs.map((refs) => refs[0].source_ref_id);
    if (new Set(sourceIds).size !== sourceIds.length) {
      stop('CROSS_STORE_EXACT_SOURCE_IDS_DUPLICATED');
    }
    sourceRows = sourceIds.map((sourceId) => {
      const row = bySource.get(sourceId);
      if (
        !row || row.active_project_binding
        || !['DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(row.retirement_state)
      ) {
        stop('CROSS_STORE_EXACT_SOURCE_CURRENTNESS_CHANGED');
      }
      return row;
    }).sort((a, b) => a.source_ref_id.localeCompare(b.source_ref_id));
    bindingClass = 'EXACT_NATIVE_FILE_SOURCE_REF';
  } else if (exactRefs.every((refs) => refs.length === 0)) {
    const names = new Set(rows.map((row) => row.filename));
    const hashes = new Set(rows.map((row) => row.sha256));
    const sizes = new Set(rows.map((row) => row.bytes));
    if (names.size !== 1 || hashes.size !== 1 || sizes.size !== 1) {
      stop('CROSS_STORE_LEGACY_COHORT_NATIVE_SET_NOT_EXACT');
    }
    sourceRows = candidates.filter(
      (row) => !row.active_project_binding
        && ['DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(row.retirement_state)
        && row.filename === rows[0].filename
        && row.origin_input_sha256 === rows[0].sha256
        && row.origin_input_byte_size === rows[0].bytes,
    ).sort((a, b) => a.source_ref_id.localeCompare(b.source_ref_id));
    const uniqueSourceIds = new Set(sourceRows.map((row) => row.source_ref_id));
    const allCompleted = sourceRows.length > 0 && sourceRows.every(
      (row) => row.retirement_state === 'CONTENT_RETIRED',
    );
    if (
      uniqueSourceIds.size !== sourceRows.length
      || (!allCompleted && sourceRows.length !== rows.length)
    ) {
      stop('CROSS_STORE_LEGACY_COHORT_CARDINALITY_AMBIGUOUS');
    }
    bindingClass = 'EXACT_LEGACY_COHORT_SET';
  } else {
    stop('CROSS_STORE_MIXED_EXACT_AND_LEGACY_BINDING_BLOCKED');
  }
  let sourceIds = sourceRows.map((row) => row.source_ref_id).sort();
  const selectedFileIds = rows.map((row) => row.file_id).sort();
  let nativeFileIds = selectedFileIds;
  let bindingEvidence;
  let bindingEvidenceSha256;
  const completedRows = sourceRows.filter((row) => row.retirement_state === 'CONTENT_RETIRED');
  if (completedRows.length > 0) {
    if (completedRows.length !== sourceRows.length) {
      stop('CROSS_STORE_PARTIAL_RUNTIME_RETIREMENT_STATE_UNKNOWN');
    }
    const first = completedRows[0].completed_native_binding;
    const exact = JSON.stringify(first);
    if (completedRows.some((row) => JSON.stringify(row.completed_native_binding) !== exact)) {
      stop('CROSS_STORE_COMPLETED_BINDING_COHORT_MISMATCH');
    }
    nativeFileIds = [...first.native_file_ids].sort();
    sourceIds = [...first.source_ref_ids].sort();
    if (
      first.binding_class !== bindingClass
      || sourceIds.length !== sourceRows.length
      || sourceIds.some((id, index) => id !== sourceRows[index].source_ref_id)
      || selectedFileIds.some((id) => !nativeFileIds.includes(id))
    ) stop('CROSS_STORE_COMPLETED_BINDING_SELECTION_MISMATCH');
    bindingEvidenceSha256 = first.binding_evidence_sha256;
    bindingEvidence = {
      schema: 'LC_RUNTIME_COMPLETED_BINDING_REPLAY_R001',
      project_id: projectId,
      binding_class: bindingClass,
      native_file_ids: nativeFileIds,
      source_ref_ids: sourceIds,
      binding_evidence_sha256: bindingEvidenceSha256,
    };
  } else {
    bindingEvidence = {
      schema: 'LC_RUNTIME_FILE_SOURCE_BINDING_EVIDENCE_R001',
      project_id: projectId,
      project_revision: runtimeCandidates.project_revision,
      binding_class: bindingClass,
      native_files: rows,
      runtime_sources: sourceRows.map((row) => ({
        source_ref_id: row.source_ref_id,
        filename: row.filename,
        bytes: row.origin_input_byte_size,
        sha256: row.origin_input_sha256,
      })),
      native_reference_evidence_sha256: nativeReferenceEvidence.referenceEvidenceSha256,
    };
    bindingEvidenceSha256 = digestJson(bindingEvidence);
  }
  return {
    schema: 'LC_CROSS_STORE_PERMANENT_DELETE_PLAN_R001',
    projectId,
    expectedProjectRevision: runtimeCandidates.project_revision,
    bindingClass,
    nativeFileIds,
    selectedNativeFileIds: selectedFileIds,
    sourceRefIds: sourceIds,
    bindingEvidence,
    bindingEvidenceSha256,
    externalRefCounts: {
      ...nativeReferenceEvidence.externalRefCounts,
      protected_rollbacks: 0,
    },
  };
}

async function retireRuntimeSourcesForPlan({ plan, userId }) {
  if (!plan || !userId || typeof plan.bindingEvidenceSha256 !== 'string') {
    stop('CROSS_STORE_RETIREMENT_COMMAND_SCOPE_INVALID', 'Explicit delete selection required', 400);
  }
  if (plan.bindingEvidence?.schema === 'LC_RUNTIME_COMPLETED_BINDING_REPLAY_R001') {
    return [...plan.sourceRefIds].sort().map((sourceRefId) => ({
      source_ref_id: sourceRefId,
      response: {
        content_retirement: { state: 'COMPLETED', replayed_from_current_receipt: true },
      },
    }));
  }
  const ownerId = sha256(String(userId));
  const cohortCommand = sha256(
    `${ownerId}\u0000${plan.projectId}\u0000${plan.bindingEvidenceSha256}`,
  );
  const receipts = [];
  for (const sourceRefId of [...plan.sourceRefIds].sort()) {
    const perSourceCommand = 'native-file-delete-' + sha256(`${cohortCommand}\u0000${sourceRefId}`).slice(0, 48);
    const result = await adapterJson(
      'POST',
      '/v1/runtime-project-library/source/' + encodeURIComponent(sourceRefId) + '/retire-content',
      plan.projectId,
      {
        command_id: perSourceCommand,
        expected_project_revision: plan.expectedProjectRevision,
        owner_id: ownerId,
        external_ref_counts: plan.externalRefCounts,
        protected_asset_census_sha256: null,
        binding_class: plan.bindingClass,
        native_file_ids: plan.nativeFileIds,
        source_ref_ids: plan.sourceRefIds,
        binding_evidence_sha256: plan.bindingEvidenceSha256,
      },
    );
    if (!result.ok || result.body?.content_retirement?.state !== 'COMPLETED') {
      stop(
        result.body?.error?.code || result.body?.detail?.code || result.body?.code || 'CROSS_STORE_RUNTIME_RETIREMENT_FAILED',
        result.body?.error?.message || result.body?.detail?.message || result.body?.message || 'Runtime Source content retirement failed',
        result.status,
      );
    }
    receipts.push({ source_ref_id: sourceRefId, response: result.body });
  }
  return receipts;
}

async function retireRuntimeProjectSourcesForC5({
  projectId,
  ownerId,
  expectedSourceSnapshot,
  planSha256,
  protectedAssetCensusSha256,
}) {
  if (
    typeof projectId !== 'string' || !projectId
    || typeof ownerId !== 'string' || !ownerId
    || typeof planSha256 !== 'string' || !SHA256_RE.test(planSha256)
    || typeof protectedAssetCensusSha256 !== 'string'
    || !SHA256_RE.test(protectedAssetCensusSha256)
    || !Array.isArray(expectedSourceSnapshot)
  ) stop('C5_RUNTIME_SOURCE_RETIREMENT_SCOPE_INVALID');
  const expected = [...expectedSourceSnapshot].map((row) => {
        if (
          !row || typeof row !== 'object'
          || typeof row.source_ref_id !== 'string' || !row.source_ref_id
          || typeof row.source_sha256 !== 'string' || !SHA256_RE.test(row.source_sha256)
        ) stop('C5_RUNTIME_SOURCE_RETIREMENT_SNAPSHOT_INVALID');
        return { source_ref_id: row.source_ref_id, source_sha256: row.source_sha256 };
      }).sort((a, b) => a.source_ref_id.localeCompare(b.source_ref_id));
  if (new Set(expected.map((row) => row.source_ref_id)).size !== expected.length) {
    stop('C5_RUNTIME_SOURCE_RETIREMENT_SNAPSHOT_DUPLICATE');
  }
  const candidates = await fetchC5RuntimeSourceRetirementCandidates(projectId, ownerId);
  if (candidates.protected_asset_census_sha256 !== protectedAssetCensusSha256) {
    stop('C5_PROTECTED_BACKUP_MANIFEST_CENSUS_CHANGED');
  }
  const byId = new Map(candidates.sources.map((row) => [row.source_ref_id, row]));
  if (byId.size !== candidates.sources.length) {
    stop('C5_RUNTIME_SOURCE_RETIREMENT_CANDIDATES_DUPLICATED');
  }
  const current = expected.map((row) => byId.get(row.source_ref_id));
  if (
    current.length > 2000
    || current.some((row, index) =>
      !row
      || row.source_ref_id !== expected[index].source_ref_id
      || row.origin_input_sha256 !== expected[index].source_sha256
      || row.active_project_binding !== false
      || !['DETACHED_RETAINED', 'CONTENT_RETIRED'].includes(row.retirement_state)
    )
  ) stop('C5_RUNTIME_SOURCE_RETIREMENT_CURRENTNESS_CHANGED');
  const ownerHash = sha256(ownerId);
  const snapshotEvidence = {
    schema: 'C5_RUNTIME_PROJECT_SOURCE_CONTENT_RETIREMENT_EVIDENCE_R001',
    project_id: projectId,
    project_revision: candidates.project_revision,
    plan_sha256: planSha256,
    protected_asset_census_sha256: protectedAssetCensusSha256,
    sources: current.map((row) => ({
      source_ref_id: row.source_ref_id,
      source_sha256: row.origin_input_sha256,
    })),
    readiness_snapshot_provided: true,
  };
  const snapshotEvidenceSha256 = digestJson(snapshotEvidence);
  const receipts = [];
  for (const row of current) {
    const perSourceEvidence = {
      ...snapshotEvidence,
      source_ref_id: row.source_ref_id,
      filename: row.filename,
      origin_input_byte_size: row.origin_input_byte_size,
      shared_content_artifact_count: row.shared_content_artifact_count,
    };
    const bindingEvidenceSha256 = digestJson(perSourceEvidence);
    const commandId = 'c5-project-source-delete-' + sha256(
      `${ownerHash}\u0000${projectId}\u0000${planSha256}\u0000${row.source_ref_id}`,
    ).slice(0, 48);
    const result = await adapterJson(
      'POST',
      '/v1/runtime-project-library/source/' + encodeURIComponent(row.source_ref_id) + '/retire-content',
      projectId,
      {
        command_id: commandId,
        expected_project_revision: candidates.project_revision,
        owner_id: ownerHash,
        external_ref_counts: {
          current_chat: 0,
          agents: 0,
          assistants: 0,
          shared_links: 0,
          native_other_files: 0,
          protected_rollbacks: 0,
          external_consumers: 0,
        },
        protected_asset_census_sha256: protectedAssetCensusSha256,
        binding_class: 'EXACT_RUNTIME_SOURCE_ONLY',
        native_file_ids: [],
        source_ref_ids: [row.source_ref_id],
        binding_evidence_sha256: bindingEvidenceSha256,
      },
      ownerId,
    );
    if (!result.ok || result.body?.content_retirement?.state !== 'COMPLETED') {
      const rawCode =
        result.body?.error?.code || result.body?.detail?.code || result.body?.code ||
        result.body?.error?.message || result.body?.detail?.message || result.body?.message;
      const safeCode = /^(?:C5|RUNTIME|SOURCE|CROSS_STORE)_[A-Z0-9_]{1,120}$/.test(String(rawCode || ''))
        ? String(rawCode) : 'C5_RUNTIME_SOURCE_RETIREMENT_FAILED';
      stop(
        safeCode,
        result.body?.error?.message || result.body?.detail?.message || result.body?.message || 'Runtime Source content retirement failed',
        result.status,
      );
    }
    receipts.push({
      source_ref_id: row.source_ref_id,
      binding_evidence_sha256: bindingEvidenceSha256,
      retired_payload_count: result.body.content_retirement.retired_payload_count,
      retained_shared_payload_count: result.body.content_retirement.retained_shared_payload_count,
    });
  }
  return {
    schema: 'C5_RUNTIME_PROJECT_SOURCE_CONTENT_RETIREMENT_RESULT_R001',
    project_id: projectId,
    source_count: receipts.length,
    snapshot_evidence_sha256: snapshotEvidenceSha256,
    protected_asset_census_sha256: protectedAssetCensusSha256,
    sources: receipts,
    verified: true,
  };
}

async function verifyRuntimeProjectSourcesRetiredForC5({
  projectId,
  ownerId,
  plan,
  snapshot,
}) {
  if (
    typeof projectId !== 'string' || !projectId
    || typeof ownerId !== 'string' || !ownerId
    || plan?.projectId !== projectId
    || snapshot?.projectId !== projectId
    || snapshot?.ownerId !== ownerId
    || snapshot?.planSha256 !== plan?.planSha256
    || !Array.isArray(snapshot?.runtimeSources)
  ) stop('C5_RUNTIME_SOURCE_CONTENT_VERIFY_SCOPE_INVALID');
  const expected = [...snapshot.runtimeSources].map((row) => {
    if (
      !row || typeof row !== 'object'
      || typeof row.source_ref_id !== 'string' || !row.source_ref_id
      || typeof row.source_sha256 !== 'string' || !SHA256_RE.test(row.source_sha256)
    ) stop('C5_RUNTIME_SOURCE_CONTENT_VERIFY_SNAPSHOT_INVALID');
    return { source_ref_id: row.source_ref_id, source_sha256: row.source_sha256 };
  }).sort((a, b) => a.source_ref_id.localeCompare(b.source_ref_id));
  if (new Set(expected.map((row) => row.source_ref_id)).size !== expected.length) {
    stop('C5_RUNTIME_SOURCE_CONTENT_VERIFY_SNAPSHOT_DUPLICATED');
  }
  const candidates = await fetchC5RuntimeSourceRetirementCandidates(projectId, ownerId);
  const byId = new Map(candidates.sources.map((row) => [row.source_ref_id, row]));
  if (byId.size !== candidates.sources.length) {
    stop('C5_RUNTIME_SOURCE_CONTENT_VERIFY_CANDIDATES_DUPLICATED');
  }
  for (const row of expected) {
    const current = byId.get(row.source_ref_id);
    const binding = current?.completed_native_binding;
    if (
      !current
      || current.active_project_binding !== false
      || current.origin_input_sha256 !== row.source_sha256
      || current.retirement_state !== 'CONTENT_RETIRED'
      || !binding
      || binding.binding_class !== 'EXACT_RUNTIME_SOURCE_ONLY'
      || !Array.isArray(binding.native_file_ids)
      || binding.native_file_ids.length !== 0
      || !Array.isArray(binding.source_ref_ids)
      || binding.source_ref_ids.length !== 1
      || binding.source_ref_ids[0] !== row.source_ref_id
      || typeof binding.binding_evidence_sha256 !== 'string'
      || !SHA256_RE.test(binding.binding_evidence_sha256)
    ) stop('C5_RUNTIME_SOURCE_CONTENT_RETIREMENT_NOT_CURRENT');
  }
  return true;
}

async function executeCrossStorePermanentDelete({
  files,
  projectId,
  runtimeCandidates,
  nativeReferenceEvidence,
  userId,
  recheckNativeReferences,
  deleteNativeFiles,
}) {
  if (typeof recheckNativeReferences !== 'function' || typeof deleteNativeFiles !== 'function') {
    stop('CROSS_STORE_DELETE_DEPENDENCIES_MISSING', 'Delete dependencies unavailable', 503);
  }
  const plan = buildCrossStoreRetirementPlan({
    files,
    projectId,
    runtimeCandidates,
    nativeReferenceEvidence,
  });
  const runtimeRetirementReceipts = await retireRuntimeSourcesForPlan({ plan, userId });
  // Runtime erasure may take time. Re-run all native reference families before
  // destroying the File row/blob so a newly-created Chat/Agent reference wins.
  const postRuntimeReferenceEvidence = await recheckNativeReferences(files);
  if (
    !postRuntimeReferenceEvidence?.permitted
    || typeof postRuntimeReferenceEvidence.referenceEvidenceSha256 !== 'string'
    || !SHA256_RE.test(postRuntimeReferenceEvidence.referenceEvidenceSha256)
  ) stop('CROSS_STORE_POST_RUNTIME_NATIVE_REFERENCE_EVIDENCE_MISSING');
  const nativeDeleteResult = await deleteNativeFiles(files);
  return {
    plan,
    runtimeRetirementReceipts,
    postRuntimeReferenceEvidenceSha256: postRuntimeReferenceEvidence.referenceEvidenceSha256,
    nativeDeleteResult,
  };
}

module.exports = {
  CrossStorePermanentDeleteStop,
  fetchRuntimeSourceRetirementCandidates,
  fetchC5RuntimeSourceRetirementCandidates,
  inferCrossStoreProjectId,
  buildCrossStoreRetirementPlan,
  retireRuntimeSourcesForPlan,
  retireRuntimeProjectSourcesForC5,
  verifyRuntimeProjectSourcesRetiredForC5,
  executeCrossStorePermanentDelete,
  digestJson,
};
