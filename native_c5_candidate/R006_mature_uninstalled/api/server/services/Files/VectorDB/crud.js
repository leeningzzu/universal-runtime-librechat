const fs = require('fs');
const axios = require('axios');
const FormData = require('form-data');
const { logger } = require('@librechat/data-schemas');
const { FileSources } = require('librechat-data-provider');
const { logAxiosError, generateShortLivedToken } = require('@librechat/api');

/**
 * Deletes a file from the vector database. This function takes a file object, constructs the full path, and
 * verifies the path's validity before deleting the file. If the path is invalid, an error is thrown.
 *
 * @param {ServerRequest} req - The request object from Express.
 * @param {MongoFile} file - The file object to be deleted. It should have a `filepath` property that is
 *                           a string representing the path of the file relative to the publicPath.
 *
 * @returns {Promise<void>}
 *          A promise that resolves when the file has been successfully deleted, or throws an error if the
 *          file path is invalid or if there is an error in deletion.
 */
const deleteVectors = async (req, file) => {
  if (!file?.embedded) { return; }
  // Missing RAG transport is not proof of physical vector removal.
  if (!process.env.RAG_API_URL) { throw new Error('C5_VECTOR_STORE_UNAVAILABLE'); }
  if (!req?.user?.id || !file.file_id) { throw new Error('C5_VECTOR_NATIVE_OWNER_MISSING'); }
  // Reuse native File.metadata.embeddedEntities. Actual Agent/Project/Library
  // exclusivity remains with the existing C5 reference owner before DELETE.
  const recorded = file.metadata?.embeddedEntities;
  if (recorded !== undefined && (!Array.isArray(recorded) ||
      recorded.length > 64 ||
      recorded.some((id) => typeof id !== 'string' || !id.trim() || id.length > 256) ||
      new Set(recorded).size !== recorded.length)) {
    throw new Error('C5_VECTOR_EMBEDDED_OWNER_GRAPH_UNVERIFIED');
  }
  const namespaces = recorded?.length ? recorded : [null];
  const jwtToken = generateShortLivedToken(req.user.id);
  for (const entity_id of namespaces) {
    try {
      const response = await axios.delete(process.env.RAG_API_URL + '/documents', {
        headers: {
          Authorization: 'Bearer ' + jwtToken,
          'Content-Type': 'application/json',
          accept: 'application/json',
        },
        ...(entity_id ? { params: { entity_id } } : {}),
        data: [file.file_id],
      });
      if (!response || typeof response.status !== 'number' ||
          response.status < 200 || response.status >= 300) {
        throw new Error('C5_VECTOR_NATIVE_STORAGE_RESPONSE_UNVERIFIED');
      }
    } catch (error) {
      // 404 may identify a wrong entity namespace, not an absent vector.
      // A network failure must also retain File metadata for reconciliation.
      logAxiosError({ error, message: 'Vector deletion not confirmed' });
      logger.warn('Vector deletion incomplete; File metadata retained');
      throw new Error('C5_VECTOR_DELETE_INCOMPLETE');
    }
  }
};

/**
 * Uploads a file to the configured Vector database
 *
 * @param {Object} params - The params object.
 * @param {Object} params.req - The request object from Express. It should have a `user` property with an `id` representing the user
 * @param {Express.Multer.File} params.file - The file object, which is part of the request. The file object should
 *                                     have a `path` property that points to the location of the uploaded file.
 * @param {string} params.file_id - The file ID.
 * @param {string} [params.entity_id] - The entity ID for shared resources.
 * @param {Object} [params.storageMetadata] - Storage metadata for dual storage pattern.
 *
 * @returns {Promise<{ filepath: string, bytes: number }>}
 *          A promise that resolves to an object containing:
 *            - filepath: The path where the file is saved.
 *            - bytes: The size of the file in bytes.
 */
async function uploadVectors({ req, file, file_id, entity_id, storageMetadata, signal }) {
  if (!process.env.RAG_API_URL) {
    throw new Error('RAG_API_URL not defined');
  }

  try {
    const jwtToken = generateShortLivedToken(req.user.id);
    const formData = new FormData();
    formData.append('file_id', file_id);
    formData.append('file', fs.createReadStream(file.path));
    if (entity_id != null && entity_id) {
      formData.append('entity_id', entity_id);
    }

    // Include storage metadata for RAG API to store with embeddings
    if (storageMetadata) {
      formData.append('storage_metadata', JSON.stringify(storageMetadata));
    }

    const formHeaders = formData.getHeaders();

    const response = await axios.post(`${process.env.RAG_API_URL}/embed`, formData, {
      ...(signal ? { signal } : {}),
      headers: {
        Authorization: `Bearer ${jwtToken}`,
        accept: 'application/json',
        ...formHeaders,
      },
    });

    const responseData = response.data;
    logger.debug('Response from embedding file', responseData);

    if (responseData.known_type === false) {
      throw new Error(`File embedding failed. The filetype ${file.mimetype} is not supported`);
    }

    if (!responseData.status) {
      throw new Error('File embedding failed.');
    }

    return {
      bytes: file.size,
      filename: file.originalname,
      filepath: FileSources.vectordb,
      embedded: Boolean(responseData.known_type),
    };
  } catch (error) {
    logAxiosError({
      error,
      message: 'Error uploading vectors',
    });
    throw new Error(error.message || 'An error occurred during file upload.');
  }
}

module.exports = {
  deleteVectors,
  uploadVectors,
};