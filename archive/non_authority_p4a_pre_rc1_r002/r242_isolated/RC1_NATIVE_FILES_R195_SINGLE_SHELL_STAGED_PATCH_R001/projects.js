const express = require('express');
const { createProjectHandlers } = require('@librechat/api');
const { configMiddleware, requireJwtAuth } = require('~/server/middleware');
const db = require('~/models');
const mongoose = require('mongoose');
const runtimeProjects = require('./runtimeProjects');
const {
  createC5NativeWholeProjectProductRoute,
} = require('./c5/c5WholeProjectProductNativeRoute.candidate.js');
const {
  createC5WholeProjectDeleteOwners,
} = require('~/server/services/C5WholeProjectDeleteOwners');
const {
  unbindAllNativeFileSourcesForProject,
} = require('~/server/services/ProjectNativeFile');

const router = express.Router();
const handlers = createProjectHandlers({
  listChatProjects: db.listChatProjects,
  createChatProject: db.createChatProject,
  getChatProject: db.getChatProject,
  updateChatProject: db.updateChatProject,
  deleteChatProject: db.deleteChatProject,
  assignConversationToProject: db.assignConversationToProject,
  addChatProjectFile: db.addChatProjectFile,
  removeChatProjectFile: db.removeChatProjectFile,
  getProjectFiles: db.getProjectFiles,
  getAvailableProjectFiles: db.getAvailableProjectFiles,
});
router.use(requireJwtAuth);
router.get('/', handlers.listProjects);
router.post('/', configMiddleware, handlers.createProject);
router.put('/conversations/:conversationId', handlers.assignConversationToProject);
router.get('/:projectId/files/available', handlers.listAvailableProjectFiles);
router.get('/:projectId/files', handlers.listProjectFiles);
router.post('/:projectId/files', configMiddleware, handlers.addProjectFile);
router.delete('/:projectId/files/:fileId', handlers.removeProjectFile);
router.get('/:projectId', handlers.getProject);
router.patch('/:projectId', configMiddleware, handlers.updateProject);
// Native LibreChat deleteChatProject only unassigns conversations. Never use it
// as a fallback for the user-approved whole-Project permanent deletion contract.
// Reuse the previously accepted C5 owner, lease, owner proofs, and receipts.
const c5Delete = createC5NativeWholeProjectProductRoute({
  nativeDb: db,
  getNativeModels: () => mongoose.models,
  upstreamProjectHandlers: handlers,
  resolveCurrentOwnerBindings: async (req) =>
    createC5WholeProjectDeleteOwners({
      request: req,
      models: mongoose.models,
      nativeDb: db,
    }),
  afterVerifiedProjectDeletion: async ({ projectId, ownerId }) =>
    unbindAllNativeFileSourcesForProject({
      userId: ownerId,
      libreChatProjectId: projectId,
    }),
});
router.get('/:projectId/c5-whole-delete/readiness', c5Delete.readiness);
router.get('/:projectId/c5-whole-delete/status', c5Delete.status);
router.post('/:projectId/c5-whole-delete/prepare', c5Delete.prepare);
router.delete('/:projectId', c5Delete.deleteProject);

// Native Project create/edit/file actions MUST win before this legacy prefix.
// The existing Runtime router serves only its specialized Source/Memory/history
// suffixes here; its historical POST '/' must never shadow native creation.
router.use('/', runtimeProjects);

module.exports = router;
