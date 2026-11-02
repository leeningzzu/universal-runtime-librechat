'use strict';

/** R242 ISOLATED native C5 Project DELETE composition.
 * Never changes normal Project CRUD, never falls back to unassign-only Delete.
 * The mature R006 C5 owner must independently prove all real permissions,
 * exact Source/Memory/File/Vector ownership and protected recovery before effect.
 * This is NOT currently installed in Daily or in the NONSHIPPING EXE. */
const express=require('express');
const {createProjectHandlers}=require('@librechat/api');
const requireJwtAuth=require('~/server/middleware/requireJwtAuth');
const runtimeProjects=require('./runtimeProjects');
const db=require('~/models');
const mongoose=require('mongoose');
const {createC5NativeWholeProjectProductRoute}=
  require('./c5WholeProjectProductNativeRoute.candidate.js');

const router=express.Router();
const handlers=createProjectHandlers({
  listChatProjects:db.listChatProjects,createChatProject:db.createChatProject,
  getChatProject:db.getChatProject,updateChatProject:db.updateChatProject,
  deleteChatProject:db.deleteChatProject,
  assignConversationToProject:db.assignConversationToProject,
});
router.use(requireJwtAuth);
router.use('/',runtimeProjects);
router.get('/',handlers.listProjects);
router.post('/',handlers.createProject);
router.put('/conversations/:conversationId',handlers.assignConversationToProject);
router.get('/:projectId',handlers.getProject);
router.patch('/:projectId',handlers.updateProject);
const NATIVE_ID=/^[a-f0-9]{24}$/i;
const EXPLICIT_CONFIRMATION='C5_EXPLICIT_USER_CONFIRM_R242';
const refuse=(res,code)=>res.status(409).json({
  status:'C5_WHOLE_PROJECT_DELETE_UNVERIFIED',code,
  verified:false,retryAutomatically:false,
});
function confirmed(req,kind) {
  if(kind==='prepare') return req?.body?.confirmedIrreversibleProjectDelete===true;
  if(kind!=='deleteProject') return true;
  const token=typeof req?.get==='function'
    ? req.get('X-C5-Irreversible-Confirmed')
    : req?.headers?.['x-c5-irreversible-confirmed'];
  return token===EXPLICIT_CONFIRMATION;
}
async function currentOwners(req) {
  const bind=req?.app?.locals?.aidesC5WholeProjectDeleteOwners;
  if(typeof bind!=='function') return null;
  const owners=await bind(req);
  if(!owners || typeof owners!=='object' ||
      !owners.admissionOwner || !owners.referenceOwner) return null;
  return {admissionOwner:owners.admissionOwner,referenceOwner:owners.referenceOwner};
}
async function c5(req,res,kind) {
  if(!NATIVE_ID.test(String(req?.params?.projectId||'')) ||
      !NATIVE_ID.test(String(req?.user?.id??req?.user?._id??''))) {
    return refuse(res,'C5_AUTHENTICATED_NATIVE_PROJECT_REQUIRED');
  }
  if(!confirmed(req,kind)) {
    return refuse(res,'C5_EXPLICIT_IRREVERSIBLE_CONFIRMATION_REQUIRED');
  }
  try {
    // Lazy C5 constructor: missing optional owners cannot break Core Project
    // list/create/read/edit or become an implicit permission grant.
    const native=createC5NativeWholeProjectProductRoute({
      nativeDb:db,getNativeModels:()=>mongoose.models,
      upstreamProjectHandlers:handlers,
      resolveCurrentOwnerBindings:currentOwners,
    });
    if(typeof native?.[kind]!=='function') return refuse(res,'C5_NATIVE_ROUTE_NOT_INSTALLED');
    return await native[kind](req,res);
  }catch(_error){
    // Outcome after an effect can be UNKNOWN. Never replay, never run the
    // original upstream Delete as compensation, and never assert COMPLETE.
    if(res.headersSent) return;
    return refuse(res,'C5_CURRENT_NATIVE_OWNER_OR_EFFECT_OUTCOME_UNVERIFIED');
  }
}
router.get('/:projectId/c5-whole-delete/readiness',(req,res)=>c5(req,res,'readiness'));
router.post('/:projectId/c5-whole-delete/prepare',(req,res)=>c5(req,res,'prepare'));
router.delete('/:projectId',(req,res)=>c5(req,res,'deleteProject'));
module.exports=router;
// Source-only consumer contract; not an HTTP permission or login credential.
module.exports.R242_EXPLICIT_CONFIRMATION=EXPLICIT_CONFIRMATION;
