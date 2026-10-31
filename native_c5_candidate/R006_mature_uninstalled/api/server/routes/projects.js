const express = require('express');
const { createProjectHandlers } = require('@librechat/api');
const requireJwtAuth = require('~/server/middleware/requireJwtAuth');
const runtimeProjects = require('./runtimeProjects');
const db = require('~/models');
const mongoose = require('mongoose');
const {
  createC5NativeWholeProjectProductRoute,
} = require('./c5WholeProjectProductNativeRoute.candidate.js');

const router = express.Router();
const handlers = createProjectHandlers({
  listChatProjects: db.listChatProjects,
  createChatProject: db.createChatProject,
  getChatProject: db.getChatProject,
  updateChatProject: db.updateChatProject,
  deleteChatProject: db.deleteChatProject,
  assignConversationToProject: db.assignConversationToProject,
});

router.use(requireJwtAuth);
router.use('/', runtimeProjects);

router.get('/', handlers.listProjects);
router.post('/', handlers.createProject);
router.put('/conversations/:conversationId', handlers.assignConversationToProject);
router.get('/:projectId', handlers.getProject);
router.patch('/:projectId', handlers.updateProject);
// Replace the OLD upstream unassign-only Delete route. No second route or
// fallback; the current Runtime SourceRef/Job/backup binding must be installed
// and admitted by the existing product owner before the operation is enabled.
const c5Delete = createC5NativeWholeProjectProductRoute({
  nativeDb:db,
  getNativeModels:()=>mongoose.models,
  upstreamProjectHandlers:handlers,
  resolveCurrentOwnerBindings:async(req)=>{
    const bind = req.app?.locals?.aidesC5WholeProjectDeleteOwners;
    if (typeof bind !== 'function') return null;
    const owners=await bind(req);
    // App Runtime/native retirement is bound below from the actual LibreChat
    // upstream controller. This remaining owner supplies ONLY the current
    // cross-plane reference and writer/Job/coherent-backup admissions.
    if (!owners?.admissionOwner || !owners?.referenceOwner) return null;
    return {admissionOwner:owners.admissionOwner,referenceOwner:owners.referenceOwner};
  },
});
router.get('/:projectId/c5-whole-delete/readiness', c5Delete.readiness);
router.post('/:projectId/c5-whole-delete/prepare', c5Delete.prepare);
router.delete('/:projectId', c5Delete.deleteProject);

module.exports = router;
