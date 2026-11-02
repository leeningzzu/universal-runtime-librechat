'use strict';
const crypto = require('node:crypto');

const SNAPSHOT_SCHEMA = 'C5_PROJECT_DELETE_DURABLE_SNAPSHOT_R001';
const FILE_SEAL_SCHEMA = 'C5_NATIVE_FILE_SEAL_R001';
const SHA256 = /^[0-9a-f]{64}$/;
const SOURCE_REF = /^SRC_[A-Z0-9]{8,64}$/;
const MAX_FILES = 2000;
const MAX_SOURCES = 2000;

class C5SnapshotStop extends Error {
  constructor(code) {
    super(code);
    this.name = 'C5SnapshotStop';
    this.code = code;
  }
}
const need = (value, code) => {
  if (!value) throw new C5SnapshotStop(code);
};
const stable = (value) => {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
};
const digest = (value) => crypto.createHash('sha256').update(JSON.stringify(stable(value))).digest('hex');
const exactKeys = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
const safeText = (value, max = 256) => typeof value === 'string' && value.length > 0 && value.length <= max;
const safeLogicalPath = (value) => typeof value === 'string' && value.length > 0 && value.length <= 2048 &&
  (value.startsWith('/uploads/') || value.startsWith('/images/')) &&
  !value.includes('\0') && !value.split('/').includes('..');

function canonicalRef(ref) {
  need(exactKeys(ref, ['kind', 'id']) && safeText(ref.kind, 64) && safeText(ref.id, 512),
    'C5_DURABLE_FILE_REFERENCE_INVALID');
  return { kind: ref.kind, id: ref.id };
}

function canonicalSeal(seal) {
  const keys = [
    'schema', 'rowPresent', 'ownedTargetStorage', 'messageOnlyTargetOwned',
    'knownMissingOriginal', 'bytes', 'logicalPaths', 'source', 'vectorDeleteRequired',
    'vectorOwnerAvailable', 'codeEnvDeleteRequired', 'codeEnvOwnerAvailable',
    'unsupportedStorage', 'refs',
  ];
  need(exactKeys(seal, keys) && seal.schema === FILE_SEAL_SCHEMA,
    'C5_DURABLE_FILE_SEAL_SHAPE_INVALID');
  for (const key of [
    'rowPresent', 'ownedTargetStorage', 'messageOnlyTargetOwned',
    'knownMissingOriginal', 'vectorDeleteRequired', 'vectorOwnerAvailable', 'codeEnvDeleteRequired',
    'codeEnvOwnerAvailable', 'unsupportedStorage',
  ]) need(typeof seal[key] === 'boolean', 'C5_DURABLE_FILE_SEAL_BOOLEAN_INVALID');
  need(Number.isSafeInteger(seal.bytes) && seal.bytes >= 0,
    'C5_DURABLE_FILE_SEAL_BYTES_INVALID');
  need(Array.isArray(seal.logicalPaths) && seal.logicalPaths.length <= 8 &&
    seal.logicalPaths.every(safeLogicalPath) &&
    new Set(seal.logicalPaths).size === seal.logicalPaths.length,
  'C5_DURABLE_FILE_SEAL_PATHS_INVALID');
  need(seal.source == null || safeText(seal.source, 128),
    'C5_DURABLE_FILE_SEAL_SOURCE_INVALID');
  need(Array.isArray(seal.refs) && seal.refs.length <= 2000,
    'C5_DURABLE_FILE_SEAL_REFS_INVALID');
  const refs = seal.refs.map(canonicalRef).sort((a, b) =>
    `${a.kind}\0${a.id}`.localeCompare(`${b.kind}\0${b.id}`));
  need(new Set(refs.map((ref) => `${ref.kind}\0${ref.id}`)).size === refs.length,
    'C5_DURABLE_FILE_SEAL_REFS_DUPLICATED');
  need(!(seal.messageOnlyTargetOwned && seal.rowPresent),
    'C5_DURABLE_FILE_SEAL_MESSAGE_ONLY_ROW_CONFLICT');
  need(!seal.messageOnlyTargetOwned || seal.ownedTargetStorage,
    'C5_DURABLE_FILE_SEAL_MESSAGE_ONLY_OWNERSHIP_MISSING');
  need(!seal.knownMissingOriginal || (!seal.rowPresent && seal.logicalPaths.length === 0),
    'C5_DURABLE_FILE_SEAL_KNOWN_MISSING_CONFLICT');
  return {
    schema: FILE_SEAL_SCHEMA,
    rowPresent: seal.rowPresent,
    ownedTargetStorage: seal.ownedTargetStorage,
    messageOnlyTargetOwned: seal.messageOnlyTargetOwned,
    knownMissingOriginal: seal.knownMissingOriginal,
    bytes: seal.bytes,
    logicalPaths: [...seal.logicalPaths].sort(),
    source: seal.source ?? null,
    vectorDeleteRequired: seal.vectorDeleteRequired,
    vectorOwnerAvailable: seal.vectorOwnerAvailable,
    codeEnvDeleteRequired: seal.codeEnvDeleteRequired,
    codeEnvOwnerAvailable: seal.codeEnvOwnerAvailable,
    unsupportedStorage: seal.unsupportedStorage,
    refs,
  };
}

function canonicalRuntimeSource(row) {
  need(exactKeys(row, ['source_ref_id', 'source_sha256']) &&
    SOURCE_REF.test(row.source_ref_id) && SHA256.test(row.source_sha256),
  'C5_DURABLE_RUNTIME_SOURCE_SNAPSHOT_INVALID');
  return { source_ref_id: row.source_ref_id, source_sha256: row.source_sha256 };
}

function snapshotBody(snapshot) {
  const keys = [
    'schema', 'projectId', 'ownerId', 'planSha256', 'runtimeSources',
    'protectedAssetCensusSha256', 'files', 'snapshotSha256',
  ];
  need(exactKeys(snapshot, keys) && snapshot.schema === SNAPSHOT_SCHEMA,
    'C5_DURABLE_DELETE_SNAPSHOT_SHAPE_INVALID');
  need(safeText(snapshot.projectId) && safeText(snapshot.ownerId) &&
    SHA256.test(snapshot.planSha256) &&
    SHA256.test(snapshot.protectedAssetCensusSha256) &&
    SHA256.test(snapshot.snapshotSha256),
  'C5_DURABLE_DELETE_SNAPSHOT_IDENTITY_INVALID');
  need(Array.isArray(snapshot.runtimeSources) && snapshot.runtimeSources.length <= MAX_SOURCES,
    'C5_DURABLE_RUNTIME_SOURCE_SNAPSHOT_UNBOUNDED');
  const runtimeSources = snapshot.runtimeSources.map(canonicalRuntimeSource)
    .sort((a, b) => a.source_ref_id.localeCompare(b.source_ref_id));
  need(new Set(runtimeSources.map((row) => row.source_ref_id)).size === runtimeSources.length,
    'C5_DURABLE_RUNTIME_SOURCE_SNAPSHOT_DUPLICATED');
  need(Array.isArray(snapshot.files) && snapshot.files.length <= MAX_FILES,
    'C5_DURABLE_FILE_SNAPSHOT_UNBOUNDED');
  const files = snapshot.files.map((file) => {
    need(exactKeys(file, ['id', 'classification', 'retentionReason', 'seal']) &&
      safeText(file.id) && ['EXCLUSIVE', 'RETAINED'].includes(file.classification),
    'C5_DURABLE_FILE_SNAPSHOT_ROW_INVALID');
    if (file.classification === 'EXCLUSIVE') {
      need(file.retentionReason === null, 'C5_EXCLUSIVE_FILE_RETENTION_REASON_CONFLICT');
    } else {
      need(safeText(file.retentionReason, 120), 'C5_RETAINED_FILE_REASON_MISSING');
    }
    return {
      id: file.id,
      classification: file.classification,
      retentionReason: file.retentionReason,
      seal: canonicalSeal(file.seal),
    };
  }).sort((a, b) => a.id.localeCompare(b.id));
  need(new Set(files.map((file) => file.id)).size === files.length,
    'C5_DURABLE_FILE_SNAPSHOT_DUPLICATED');
  return {
    schema: SNAPSHOT_SCHEMA,
    projectId: snapshot.projectId,
    ownerId: snapshot.ownerId,
    planSha256: snapshot.planSha256,
    runtimeSources,
    protectedAssetCensusSha256: snapshot.protectedAssetCensusSha256,
    files,
  };
}

function validateDurableDeleteSnapshot(snapshot, plan, projectId, ownerId) {
  const body = snapshotBody(snapshot);
  need(body.projectId === projectId && body.ownerId === ownerId &&
    body.planSha256 === plan?.planSha256,
  'C5_DURABLE_DELETE_SNAPSHOT_SCOPE_CHANGED');
  need(digest(body) === snapshot.snapshotSha256,
    'C5_DURABLE_DELETE_SNAPSHOT_DIGEST_MISMATCH');
  const expected = new Map([
    ...(plan?.exclusive ?? []).map((file) => [file.id, 'EXCLUSIVE']),
    ...(plan?.retained ?? []).map((file) => [file.id, 'RETAINED']),
  ]);
  need(expected.size === (plan?.exclusive?.length ?? 0) + (plan?.retained?.length ?? 0) &&
    body.files.length === expected.size &&
    body.files.every((file) => expected.get(file.id) === file.classification),
  'C5_DURABLE_FILE_SNAPSHOT_PLAN_MISMATCH');
  return { ...body, snapshotSha256: snapshot.snapshotSha256 };
}

function buildDurableDeleteSnapshot(raw, plan, projectId, ownerId) {
  need(raw && Array.isArray(raw.files) && Array.isArray(raw.runtimeSources),
    'C5_DURABLE_DELETE_SNAPSHOT_INPUT_MISSING');
  const classification = new Map([
    ...plan.exclusive.map((file) => [file.id, 'EXCLUSIVE']),
    ...plan.retained.map((file) => [file.id, 'RETAINED']),
  ]);
  const files = raw.files.map((file) => {
    const kind = classification.get(file.id);
    need(kind && file.seal, 'C5_DURABLE_FILE_SNAPSHOT_INPUT_INCOMPLETE');
    return {
      id: file.id,
      classification: kind,
      retentionReason: kind === 'RETAINED'
        ? String(file.retentionReason || 'SHARED_OR_INDEPENDENT_REFERENCE')
        : null,
      seal: file.seal,
    };
  });
  const body = snapshotBody({
    schema: SNAPSHOT_SCHEMA,
    projectId,
    ownerId,
    planSha256: plan.planSha256,
    runtimeSources: raw.runtimeSources,
    protectedAssetCensusSha256: raw.protectedAssetCensusSha256,
    files,
    snapshotSha256: '0'.repeat(64),
  });
  const snapshot = { ...body, snapshotSha256: digest(body) };
  return validateDurableDeleteSnapshot(snapshot, plan, projectId, ownerId);
}

module.exports = {
  SNAPSHOT_SCHEMA,
  FILE_SEAL_SCHEMA,
  C5SnapshotStop,
  buildDurableDeleteSnapshot,
  validateDurableDeleteSnapshot,
};
