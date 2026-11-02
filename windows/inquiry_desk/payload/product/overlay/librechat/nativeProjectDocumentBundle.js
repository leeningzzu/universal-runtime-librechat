'use strict';

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const JSZip = require('jszip');
const { parseDocument } = require('@librechat/api');

const PDF_MIME = 'application/pdf';
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const XLS_MIME = 'application/vnd.ms-excel';
const ODS_MIME = 'application/vnd.oasis.opendocument.spreadsheet';
const ODT_MIME = 'application/vnd.oasis.opendocument.text';
const MAX_NATIVE_DOCUMENT_BYTES = 15 * 1024 * 1024;
const FIXED_ZIP_DATE = new Date(Date.UTC(1980, 0, 1, 0, 0, 0));

function packageVersion(packageName, resolvedName = packageName) {
  let cursor = path.dirname(require.resolve(resolvedName));
  while (true) {
    const packagePath = path.join(cursor, 'package.json');
    if (fs.existsSync(packagePath)) {
      const metadata = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
      if (metadata?.name === packageName && typeof metadata.version === 'string' && metadata.version) {
        return metadata.version;
      }
    }
    const parent = path.dirname(cursor);
    if (parent === cursor) {
      throw new Error('PACKAGE_VERSION_UNRESOLVED:' + packageName);
    }
    cursor = parent;
  }
}

const LIBRECHAT_API_VERSION = packageVersion('@librechat/api');
const MAMMOTH_VERSION = packageVersion('mammoth');
const PDFJS_VERSION = packageVersion('pdfjs-dist', 'pdfjs-dist/legacy/build/pdf.mjs');
const JSZIP_VERSION = packageVersion('jszip');

const structuredFormat = ({ inputFormat, mediaType, mediaTypeAliases = [], parserEngine, parserEngineVersion, warning }) =>
  Object.freeze({
    extractor: 'document_parser',
    inputFormat,
    mediaType,
    mediaTypeAliases: Object.freeze([mediaType, ...mediaTypeAliases]),
    parserEngine,
    parserEngineVersion,
    warning,
  });
const textFormat = ({ inputFormat, mediaType, mediaTypeAliases = [] }) =>
  Object.freeze({
    extractor: 'strict_utf8',
    inputFormat,
    mediaType,
    mediaTypeAliases: Object.freeze([mediaType, ...mediaTypeAliases]),
    parserEngine: 'node-textdecoder',
    parserEngineVersion: process.versions.node,
    warning: 'STRICT_UTF8_TEXT_ONLY_NO_EXECUTION_OR_MARKUP_RENDERING',
  });

const NATIVE_DOCUMENT_FORMATS = Object.freeze({
  '.docx': structuredFormat({
    inputFormat: 'docx', mediaType: DOCX_MIME, parserEngine: 'mammoth',
    parserEngineVersion: MAMMOTH_VERSION,
    warning: 'TEXT_ONLY_EXTRACTION_LAYOUT_AND_OMML_FORMULA_FIDELITY_NOT_PROVEN',
  }),
  '.pdf': structuredFormat({
    inputFormat: 'pdf', mediaType: PDF_MIME, parserEngine: 'pdfjs-dist',
    parserEngineVersion: PDFJS_VERSION,
    warning: 'TEXT_ONLY_EXTRACTION_LAYOUT_IMAGE_AND_OCR_FIDELITY_NOT_PROVEN',
  }),
  '.xlsx': structuredFormat({
    inputFormat: 'xlsx', mediaType: XLSX_MIME, parserEngine: '@librechat/api.parseDocument:xlsx',
    parserEngineVersion: LIBRECHAT_API_VERSION,
    warning: 'TABULAR_TEXT_EXTRACTION_FORMATTING_FORMULAS_AND_CHART_FIDELITY_NOT_PROVEN',
  }),
  '.xls': structuredFormat({
    inputFormat: 'xls', mediaType: XLS_MIME, parserEngine: '@librechat/api.parseDocument:xls',
    parserEngineVersion: LIBRECHAT_API_VERSION,
    warning: 'LEGACY_TABULAR_TEXT_EXTRACTION_FORMATTING_FORMULAS_AND_CHART_FIDELITY_NOT_PROVEN',
  }),
  '.ods': structuredFormat({
    inputFormat: 'ods', mediaType: ODS_MIME, parserEngine: '@librechat/api.parseDocument:ods',
    parserEngineVersion: LIBRECHAT_API_VERSION,
    warning: 'TABULAR_TEXT_EXTRACTION_FORMATTING_FORMULAS_AND_CHART_FIDELITY_NOT_PROVEN',
  }),
  '.odt': structuredFormat({
    inputFormat: 'odt', mediaType: ODT_MIME, parserEngine: '@librechat/api.parseDocument',
    parserEngineVersion: LIBRECHAT_API_VERSION,
    warning: 'TEXT_ONLY_EXTRACTION_LAYOUT_AND_EMBEDDED_OBJECT_FIDELITY_NOT_PROVEN',
  }),
  '.txt': textFormat({ inputFormat: 'txt', mediaType: 'text/plain' }),
  '.md': textFormat({ inputFormat: 'markdown', mediaType: 'text/markdown', mediaTypeAliases: ['text/plain'] }),
  '.markdown': textFormat({ inputFormat: 'markdown', mediaType: 'text/markdown', mediaTypeAliases: ['text/plain'] }),
  '.csv': textFormat({ inputFormat: 'csv', mediaType: 'text/csv', mediaTypeAliases: ['text/plain'] }),
  '.tsv': textFormat({ inputFormat: 'tsv', mediaType: 'text/tab-separated-values', mediaTypeAliases: ['text/plain'] }),
  '.json': textFormat({ inputFormat: 'json', mediaType: 'application/json', mediaTypeAliases: ['text/json', 'text/plain'] }),
  '.jsonl': textFormat({ inputFormat: 'jsonl', mediaType: 'application/x-ndjson', mediaTypeAliases: ['application/json', 'text/plain'] }),
  '.ndjson': textFormat({ inputFormat: 'ndjson', mediaType: 'application/x-ndjson', mediaTypeAliases: ['application/json', 'text/plain'] }),
  '.yaml': textFormat({ inputFormat: 'yaml', mediaType: 'application/yaml', mediaTypeAliases: ['text/yaml', 'text/plain'] }),
  '.yml': textFormat({ inputFormat: 'yaml', mediaType: 'application/yaml', mediaTypeAliases: ['text/yaml', 'text/plain'] }),
  '.xml': textFormat({ inputFormat: 'xml', mediaType: 'application/xml', mediaTypeAliases: ['text/xml', 'text/plain'] }),
  '.html': textFormat({ inputFormat: 'html', mediaType: 'text/html', mediaTypeAliases: ['text/plain'] }),
  '.htm': textFormat({ inputFormat: 'html', mediaType: 'text/html', mediaTypeAliases: ['text/plain'] }),
  '.css': textFormat({ inputFormat: 'css', mediaType: 'text/css', mediaTypeAliases: ['text/plain'] }),
  '.js': textFormat({ inputFormat: 'javascript', mediaType: 'text/javascript', mediaTypeAliases: ['application/javascript', 'text/plain'] }),
  '.jsx': textFormat({ inputFormat: 'jsx', mediaType: 'text/jsx', mediaTypeAliases: ['text/javascript', 'text/plain'] }),
  '.mjs': textFormat({ inputFormat: 'javascript', mediaType: 'text/javascript', mediaTypeAliases: ['application/javascript', 'text/plain'] }),
  '.cjs': textFormat({ inputFormat: 'javascript', mediaType: 'text/javascript', mediaTypeAliases: ['application/javascript', 'text/plain'] }),
  '.ts': textFormat({ inputFormat: 'typescript', mediaType: 'text/typescript', mediaTypeAliases: ['text/plain'] }),
  '.tsx': textFormat({ inputFormat: 'tsx', mediaType: 'text/tsx', mediaTypeAliases: ['text/typescript', 'text/plain'] }),
  '.py': textFormat({ inputFormat: 'python', mediaType: 'text/x-python', mediaTypeAliases: ['text/plain'] }),
  '.java': textFormat({ inputFormat: 'java', mediaType: 'text/x-java-source', mediaTypeAliases: ['text/plain'] }),
  '.c': textFormat({ inputFormat: 'c', mediaType: 'text/x-c', mediaTypeAliases: ['text/plain'] }),
  '.h': textFormat({ inputFormat: 'c-header', mediaType: 'text/x-c', mediaTypeAliases: ['text/plain'] }),
  '.cpp': textFormat({ inputFormat: 'cpp', mediaType: 'text/x-c++', mediaTypeAliases: ['text/plain'] }),
  '.hpp': textFormat({ inputFormat: 'cpp-header', mediaType: 'text/x-c++', mediaTypeAliases: ['text/plain'] }),
  '.cs': textFormat({ inputFormat: 'csharp', mediaType: 'text/x-csharp', mediaTypeAliases: ['text/plain'] }),
  '.go': textFormat({ inputFormat: 'go', mediaType: 'text/x-go', mediaTypeAliases: ['text/plain'] }),
  '.rs': textFormat({ inputFormat: 'rust', mediaType: 'text/x-rust', mediaTypeAliases: ['text/plain'] }),
  '.sql': textFormat({ inputFormat: 'sql', mediaType: 'application/sql', mediaTypeAliases: ['text/plain'] }),
  '.sh': textFormat({ inputFormat: 'shell', mediaType: 'application/x-sh', mediaTypeAliases: ['text/x-shellscript', 'text/plain'] }),
  '.bash': textFormat({ inputFormat: 'shell', mediaType: 'application/x-sh', mediaTypeAliases: ['text/x-shellscript', 'text/plain'] }),
  '.ps1': textFormat({ inputFormat: 'powershell', mediaType: 'text/x-powershell', mediaTypeAliases: ['text/plain'] }),
  '.toml': textFormat({ inputFormat: 'toml', mediaType: 'application/toml', mediaTypeAliases: ['text/plain'] }),
  '.ini': textFormat({ inputFormat: 'ini', mediaType: 'text/plain' }),
  '.cfg': textFormat({ inputFormat: 'config', mediaType: 'text/plain' }),
  '.log': textFormat({ inputFormat: 'log', mediaType: 'text/plain' }),
  '.tex': textFormat({ inputFormat: 'tex', mediaType: 'application/x-tex', mediaTypeAliases: ['text/plain'] }),
  '.r': textFormat({ inputFormat: 'r', mediaType: 'text/x-r', mediaTypeAliases: ['text/plain'] }),
  '.rb': textFormat({ inputFormat: 'ruby', mediaType: 'text/x-ruby', mediaTypeAliases: ['text/plain'] }),
  '.php': textFormat({ inputFormat: 'php', mediaType: 'application/x-httpd-php', mediaTypeAliases: ['text/plain'] }),
  '.swift': textFormat({ inputFormat: 'swift', mediaType: 'text/x-swift', mediaTypeAliases: ['text/plain'] }),
  '.kt': textFormat({ inputFormat: 'kotlin', mediaType: 'text/x-kotlin', mediaTypeAliases: ['text/plain'] }),
  '.kts': textFormat({ inputFormat: 'kotlin', mediaType: 'text/x-kotlin', mediaTypeAliases: ['text/plain'] }),
  '.scala': textFormat({ inputFormat: 'scala', mediaType: 'text/x-scala', mediaTypeAliases: ['text/plain'] }),
  '.lua': textFormat({ inputFormat: 'lua', mediaType: 'text/x-lua', mediaTypeAliases: ['text/plain'] }),
  '.dart': textFormat({ inputFormat: 'dart', mediaType: 'text/x-dart', mediaTypeAliases: ['text/plain'] }),
  '.vue': textFormat({ inputFormat: 'vue', mediaType: 'text/x-vue', mediaTypeAliases: ['text/plain'] }),
  '.svelte': textFormat({ inputFormat: 'svelte', mediaType: 'text/x-svelte', mediaTypeAliases: ['text/plain'] }),
  '.ics': textFormat({ inputFormat: 'ics', mediaType: 'text/calendar', mediaTypeAliases: ['text/plain'] }),
  '.vtt': textFormat({ inputFormat: 'vtt', mediaType: 'text/vtt', mediaTypeAliases: ['text/plain'] }),
});

const PROJECT_SOURCE_ACCEPT = Object.freeze(
  Object.keys(NATIVE_DOCUMENT_FORMATS).sort().join(','),
);

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return '[' + value.map(canonicalJson).join(',') + ']';
  }
  if (value && typeof value === 'object') {
    return (
      '{' +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key]))
        .join(',') +
      '}'
    );
  }
  return JSON.stringify(value);
}

function canonicalJsonBuffer(value) {
  return Buffer.from(canonicalJson(value), 'utf8');
}

function nativeDocumentFormatForFilename(filename) {
  if (
    typeof filename !== 'string' ||
    !filename ||
    filename.length > 255 ||
    /[\r\n\0/\\]/.test(filename)
  ) {
    return null;
  }
  return NATIVE_DOCUMENT_FORMATS[path.extname(filename).toLowerCase()] || null;
}

function nativeDocumentMediaTypeAccepted(format, mediaType) {
  if (!format || typeof mediaType !== 'string') {
    return false;
  }
  const normalized = mediaType.split(';', 1)[0].trim().toLowerCase();
  return normalized === '' || normalized === 'application/octet-stream' || format.mediaTypeAliases.includes(normalized);
}

function nativeDocumentFormatsCatalog() {
  return Object.keys(NATIVE_DOCUMENT_FORMATS)
    .sort()
    .map((extension) => ({
      extension,
      input_format: NATIVE_DOCUMENT_FORMATS[extension].inputFormat,
      media_type: NATIVE_DOCUMENT_FORMATS[extension].mediaType,
      extraction: NATIVE_DOCUMENT_FORMATS[extension].extractor,
    }));
}

function strictUtf8Text(originalBytes) {
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(originalBytes);
  } catch (_) {
    const error = new Error('NATIVE_TEXT_NOT_VALID_UTF8');
    error.status = 422;
    throw error;
  }
  if (text.charCodeAt(0) === 0xfeff) {
    text = text.slice(1);
  }
  text = text.replace(/\r\n?/g, '\n');
  if (/\0/.test(text) || /[\x01-\x08\x0B\x0C\x0E-\x1F]/.test(text)) {
    const error = new Error('NATIVE_TEXT_UNSAFE_CONTROL_BYTES');
    error.status = 422;
    throw error;
  }
  if (!text.trim()) {
    const error = new Error('NATIVE_DOCUMENT_TEXT_EMPTY');
    error.status = 422;
    throw error;
  }
  return text;
}

async function buildNativeDocumentRuntimeBundle({ filename, originalBytes }) {
  const format = nativeDocumentFormatForFilename(filename);
  if (!format) {
    const error = new Error('NATIVE_DOCUMENT_FILENAME_OR_TYPE_INVALID');
    error.status = 415;
    throw error;
  }
  if (
    !Buffer.isBuffer(originalBytes) ||
    originalBytes.length < 1 ||
    originalBytes.length > MAX_NATIVE_DOCUMENT_BYTES
  ) {
    const error = new Error('NATIVE_DOCUMENT_SIZE_INVALID');
    error.status = originalBytes?.length > MAX_NATIVE_DOCUMENT_BYTES ? 413 : 400;
    throw error;
  }

  const suffix = path.extname(filename).toLowerCase();
  const tempRoot = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'librechat-project-document-'));
  const tempPath = path.join(tempRoot, 'source' + suffix);
  try {
    await fs.promises.writeFile(tempPath, originalBytes);
    let text;
    if (format.extractor === 'strict_utf8') {
      text = strictUtf8Text(originalBytes);
    } else {
      const parsed = await parseDocument({
        file: {
          path: tempPath,
          size: originalBytes.length,
          mimetype: format.mediaType,
          originalname: filename,
        },
      });
      text = typeof parsed?.text === 'string' ? parsed.text : '';
      if (!text.trim()) {
        const error = new Error('NATIVE_DOCUMENT_TEXT_EMPTY');
        error.status = 422;
        throw error;
      }
    }
    const inputSha256 = sha256(originalBytes);
    const markdownBytes = Buffer.from(text, 'utf8');
    const markdownSha256 = sha256(markdownBytes);
    const jsonBytes = canonicalJsonBuffer({
      schema: 'UR_LIBRECHAT_NATIVE_DOCUMENT_TEXT_R001',
      source_filename: filename,
      text,
      text_sha256: markdownSha256,
    });
    const jsonSha256 = sha256(jsonBytes);
    const provenanceBytes = canonicalJsonBuffer({
      authority: {
        derived_json: 'RUNTIME_OWNED_DERIVED_BYTES',
        derived_markdown: 'RUNTIME_OWNED_DERIVED_BYTES',
        external_parser_output: 'VALIDATED_PROPOSAL_CONSUMED_BY_RUNTIME',
        original_bytes: 'RUNTIME_BUNDLE_MEMBER_EXACT_SOURCE_BYTES',
      },
      bundle_schema: 'UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_R001',
      input_format: format.inputFormat,
      input_sha256: inputSha256,
      json_sha256: jsonSha256,
      markdown_sha256: markdownSha256,
      parser_binding: {
        authority_class: 'NON_AUTHORITY_NATIVE_PARSER_PROPOSAL',
        bundle_writer: 'jszip',
        bundle_writer_version: JSZIP_VERSION,
        component:
          format.extractor === 'strict_utf8' ? 'node:TextDecoder' : '@librechat/api.parseDocument',
        component_version:
          format.extractor === 'strict_utf8' ? process.versions.node : LIBRECHAT_API_VERSION,
        delivery_path: format.extractor,
        output_contract: 'plain_text',
        parser_engine: format.parserEngine,
        parser_engine_version: format.parserEngineVersion,
      },
      schema: 'UR_PLANE_C_C1_DOCUMENT_ARTIFACT_PROVENANCE_R001',
      source_filename: filename,
      warnings: [format.warning],
    });

    const members = {
      'document.json': jsonBytes,
      'document.md': markdownBytes,
      ['original' + suffix]: originalBytes,
      'provenance.json': provenanceBytes,
    };
    const memberRows = Object.keys(members)
      .sort()
      .map((name) => ({
        bytes: members[name].length,
        path: name,
        sha256: sha256(members[name]),
      }));
    const manifestBytes = canonicalJsonBuffer({
      bundle_schema: 'UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_R001',
      member_count: memberRows.length,
      members: memberRows,
      schema: 'UR_PLANE_C_C1_DOCUMENT_ARTIFACT_BUNDLE_MANIFEST_R001',
    });

    const finalMembers = {
      '00_DOCUMENT_BUNDLE_MANIFEST.json': manifestBytes,
      ...members,
    };
    const zip = new JSZip();
    for (const name of Object.keys(finalMembers).sort()) {
      zip.file(name, finalMembers[name], {
        compression: 'STORE',
        createFolders: false,
        date: FIXED_ZIP_DATE,
        unixPermissions: 0o600,
      });
    }
    const bundleBytes = await zip.generateAsync({
      compression: 'STORE',
      platform: 'UNIX',
      streamFiles: false,
      type: 'nodebuffer',
    });

    return {
      bundleBytes,
      bundleSha256: sha256(bundleBytes),
      inputFormat: format.inputFormat,
      inputSha256,
      inputSize: originalBytes.length,
      mediaType: format.mediaType,
      extractedTextSha256: markdownSha256,
      extractedTextUtf8Bytes: markdownBytes.length,
    };
  } finally {
    await fs.promises.rm(tempRoot, { recursive: true, force: true });
  }
}

module.exports = {
  DOCX_MIME,
  PDF_MIME,
  NATIVE_DOCUMENT_FORMATS,
  PROJECT_SOURCE_ACCEPT,
  MAX_NATIVE_DOCUMENT_BYTES,
  buildNativeDocumentRuntimeBundle,
  nativeDocumentFormatForFilename,
  nativeDocumentFormatsCatalog,
  nativeDocumentMediaTypeAccepted,
};