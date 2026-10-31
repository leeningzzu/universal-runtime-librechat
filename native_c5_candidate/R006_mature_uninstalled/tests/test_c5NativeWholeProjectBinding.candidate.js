'use strict';
const assert = require('node:assert/strict');
const { createC5CurrentNativeWholeProjectDelete,hookNames } =
  require('./c5NativeWholeProjectBinding.candidate.js');

const P='507f1f77bcf86cd799439011';
const U='synthetic-owner';
const C='synthetic-project-chat';
const ARCHIVED='synthetic-archived-chat';
const MOVED='moved-out-chat';
const F='file-only-this-project';
const S='file-with-other-project-reference';
let cases=0, assertions=0;
const eq=(a,b)=>{assert.deepEqual(a,b);assertions++};
const yes=(x)=>{assert.ok(x);assertions++};
const res=()=>({code:200,body:null,status(v){this.code=v;return this},json(v){this.body=v;return this}});

function fixture(opts={}){
  let projectExists=true,runtimeStatus='ACTIVE',receipt=null,revision=4,locked=0;
  let sourceRefs=true,memory=true,fileExists=true,blobExists=true,vectorExists=true;
  const codeEnvExists=Boolean(opts.codeEnvResidualAfterDelete);
  let sharedExists=true,foreignFileExists=true;
  let newShare=Boolean(opts.shareAfterSnapshot), faultAlready=false;
  let outsideMessageReference=Boolean(opts.foreignMessageReference);
  const chats=new Map([
    [C,{user:U,chatProjectId:P,isArchived:false}],
    [ARCHIVED,{user:U,chatProjectId:P,isArchived:true}],
    [MOVED,{user:U,chatProjectId:'a'.repeat(24),isArchived:false}],
  ]);
  const calls=[];
  const targets=[C,ARCHIVED];
  let activeAgentRefs=Boolean(opts.agentReferences);
  let activeAssistantRefs=Boolean(opts.assistantReferences);
  const FileIndex=new Map([
    [F,{file_id:F,user:U,conversationId:opts.unboundFileRow?undefined:C,filepath:'/synthetic/owned.bin',source:'local'}],
    [S,{file_id:S,user:U,filepath:'/synthetic/shared.bin',source:'local'}],
    ['foreign-file',{file_id:'foreign-file',user:'other',filepath:'/synthetic/foreign.bin',source:'local'}],
  ]);
  if(opts.otherNativeFileRow) FileIndex.set('other-reference', {
    file_id:F,user:'other',conversationId:'other-chat',
    filepath:'/synthetic/other-owned.bin',source:'local',
  });
  if(opts.runArtifactReference) FileIndex.set('run-dependent',{
    file_id:'run-dependent',user:'other',conversationId:'other-chat',
    metadata:{runFile:{sourceFileId:F,inputFileIds:[F]}},
  });
  if(opts.singularCodeReference) FileIndex.set('code-dependent',{
    file_id:'code-dependent',user:'other',conversationId:'other-chat',
    metadata:{codeEnvRef:{file_id:F}},
  });
  if(opts.dynamicCodeReference || opts.malformedDynamicCodeReference)
    FileIndex.set('dynamic-dependent',{
      file_id:'dynamic-dependent',user:'other',conversationId:'other-chat',
      metadata:{codeEnvRefs:{'stateful:synthetic':
        opts.malformedDynamicCodeReference?{file_id:27}:{file_id:F}}},
    });

  function matching(collection,q){
    if(collection==='Conversation'){
      return [...chats.entries()].filter(([id,v])=>{
        if(q.conversationId!=null && id!==q.conversationId)return false;
        if(q.chatProjectId!=null && v.chatProjectId!==q.chatProjectId)return false;
        if(q.user!=null && v.user!==q.user)return false;
        if(q['subagentThread.rootConversationId']!=null)return false;
        return true;
      }).map(([conversationId,v])=>({conversationId,...v}));
    }
    if(collection==='ChatProject')return projectExists&&q._id===P?[{_id:P,user:U}]:[];

    if(collection==='Assistant')return activeAssistantRefs &&
      (q.file_ids===F || q.file_ids?.$in?.includes(F))
      ? [{user:'other-user',assistant_id:'other-assistant',file_ids:[F]}]:[];
    if(collection==='File')return [...FileIndex.values()].filter(v=>{
      if(q.$or && !q.$or.some(item=>
        (item['metadata.runFile.sourceFileId']!=null &&
          v.metadata?.runFile?.sourceFileId===item['metadata.runFile.sourceFileId']) ||
        (item['metadata.runFile.inputFileIds']!=null &&
          v.metadata?.runFile?.inputFileIds?.includes(item['metadata.runFile.inputFileIds']))
      ))return false;
      if(q['metadata.codeEnvRef.file_id']!=null &&
        v.metadata?.codeEnvRef?.file_id!==q['metadata.codeEnvRef.file_id'])
        return false;
      if(q['metadata.codeEnvRefs']?.$exists===true &&
        v.metadata?.codeEnvRefs===undefined)return false;
      return(q.file_id==null||v.file_id===q.file_id||
        (Array.isArray(q.file_id?.$in)&&q.file_id.$in.includes(v.file_id)))&&
        (q.user==null||v.user===q.user)&&
        (q.conversationId?.$in==null||q.conversationId.$in.includes(v.conversationId));
    });
    if(collection==='Message'){
      const rows=[...chats.entries()].map(([conversationId,v])=>({
        user:v.user,conversationId,
        files: conversationId===C && opts.nativeMessageRefs
          ? [{file_id:F}] : conversationId===C && opts.ambiguousMessageRef
            ? [{filename:'no file ID'}] : undefined,
      }));
      if(outsideMessageReference) rows.push({
        user:'other',conversationId:'other-chat',files:[{file_id:F}],
      });
      return rows.filter(row=>
        (q.user==null||q.user===row.user)&&
        (q.conversationId==null||q.conversationId===row.conversationId||
          q.conversationId?.$in?.includes(row.conversationId))&&
        (q['files.file_id']==null||
          row.files?.some(link=>link.file_id===q['files.file_id'])));
    }
    if(['ToolCall','SharedLink'].includes(collection))
      return chats.has(q.conversationId)?[{user:U,conversationId:q.conversationId}]:[];
    throw Error('UNRECOGNIZED_NATIVE_COLLECTION_'+collection);
  }
  const models={};
  for(const name of ['ChatProject','Conversation','Message','ToolCall','SharedLink','File','Assistant']){
    models[name]={
      countDocuments:async(q)=>matching(name,q).length,
      find:(q)=>({
        select(){return this},
        lean:async()=>matching(name,q),        limit(){return this},
      }),
      findOne:(q)=>({
        lean:async()=>matching(name,q)[0]||null,
      }),
    };
  }
  let saveCount=0,projectDeleteCount=0,filesDeleted=0,chatDeleted=0;
  const req={user:{id:opts.crossUser||U},params:{projectId:P},
    headers:{authorization:'Bearer synthetic.jwt.testing-only'}};
  const guards={
    proveInventoryFence:async()=>({
      projectId:opts.foreignAdmissionProject?'f'.repeat(24):P,
      ownerId:opts.foreignAdmissionOwner?'foreign-owner':U,
      jobScope:opts.globalOnlyJobProof?
        'GLOBAL_HISTORICAL_JOB_COUNT':'TARGET_PROJECT_CURRENT_EFFECTS',
      historicalGlobalJobRecords:113,
      permitted:!opts.blockWriter&&!opts.blockJobs&&!opts.blockBackup,
      exclusiveWriter:!opts.blockWriter,
      protectedBackupReady:!opts.blockBackup,
      activePinnedJobs:opts.blockJobs?1:0,
      projectRevision:revision,
      projectMembershipSealed:true,
    }),
    recheckEffectFence:async()=>({
      projectId:opts.foreignAdmissionProject?'f'.repeat(24):P,
      ownerId:opts.foreignAdmissionOwner?'foreign-owner':U,
      jobScope:opts.globalOnlyJobProof?
        'GLOBAL_HISTORICAL_JOB_COUNT':'TARGET_PROJECT_CURRENT_EFFECTS',
      permitted:!opts.blockWriter&&!opts.blockBackup,
      exclusiveWriter:!opts.blockWriter,
      protectedBackupReady:!opts.blockBackup,
      activePinnedJobs:opts.blockJobs?1:0,
      projectMembershipSealed:true,
    }),
  };
  const runtime={
    loadOperationReceipt:async()=>receipt&&JSON.parse(JSON.stringify(receipt)),
    persistOperationReceipt:async(x)=>{
      const next=(receipt?.c5_receipt_revision||0)+1;
      receipt=JSON.parse(JSON.stringify({...x,c5_receipt_revision:next}));saveCount++;
      return {durable:true,projectId:P,ownerId:U,revision:next};
    },
    executeAcceptedRetirement:async()=>{
      if(opts.nativeFailure)return{status:503,nativeAndRuntimeConfirmed:false};
      if(opts.unknownNativeBeforeEffect)throw Error('synthetic pre-effect response unknown');
      projectExists=false;projectDeleteCount++;
      if(opts.agentAppearsAfterPrepare) activeAgentRefs=true;
      if(opts.assistantAppearsAfterRetirement) activeAssistantRefs=true;
      if(opts.dynamicCodeReferenceAppearsAfterRetirement)
        FileIndex.get('foreign-file').metadata={
          codeEnvRefs:{'stateful:late':{file_id:F}},
        };

      if(opts.foreignMessageAppearsAfterRetirement) outsideMessageReference=true;
      runtimeStatus='RETIRED';
      sourceRefs=false;memory=false;
      for(const v of chats.values())if(v.chatProjectId===P)v.chatProjectId=null;
      if(opts.nativeReplyLostAfterEffect)throw Error('synthetic response lost AFTER real retirement');
      return{status:200,nativeAndRuntimeConfirmed:true};
    },
    readRetirementState:async()=>({
      authoritative:true,status:runtimeStatus,projectId:P,
    }),
  };
  const refs={
    readCompleteProjectFileGraph:async()=>({
      authoritative:true,complete:!opts.partialGraph,
      projectId:P,ownerId:U,projectRevision:revision,
      files:[
        {id:F,ownerId:U,refs:[{kind:'project',id:P},{kind:'chat',id:C}],
          refsComplete:true,bytes:31,vectorRefsProven:true,
          agentRefsProven:true,runtimeSourceRefsProven:true},
        {id:S,ownerId:U,refs:[{kind:'project',id:P},{kind:'project',id:'other-project'}],
          refsComplete:true,bytes:54,vectorRefsProven:true,
          agentRefsProven:true,runtimeSourceRefsProven:true},
      ].filter(f=>!(opts.omitNativeRef&&f.id===F)),
    }),
    recheckExclusiveFile:async()=>({
      authoritative:true,ownerAuthorized:true,refsComplete:true,
      noOtherConsumers:!newShare,
    }),
    verifyFileBytesAndDerivativesAbsent:async()=>({
      fileRecordAbsent:!fileExists,blobAbsent:!blobExists,
      vectorAbsent:!vectorExists,
      codeEnvAbsent:opts.omitCodeEnvProof?undefined:!codeEnvExists,
      agentReferencesAbsent:!fileExists,sourceReferencesAbsent:!sourceRefs,
    }),
    verifyRetainedFileBytesPresent:async()=>({
      authoritative:true,retained:true,bytesPresent:sharedExists,
      legalOtherReferenceStillPresent:true,
    }),
    verifyCrossPlaneNoReferences:async()=>({
      authoritative:true,
      allOwnedReferencesCleared:!projectExists&&!sourceRefs&&!fileExists&&!memory,
      allRetainedReferencesIntact:sharedExists&&foreignFileExists&&chats.has(MOVED),
      unknownReferences:0,
    }),
  };
  const nativeFetch=async(url,options)=>{
    calls.push({url,options});
    if(opts.throwAfterEffect&&!faultAlready){
      faultAlready=true;
      chats.delete(JSON.parse(options.body).arg?.conversationId);
      throw Error('synthetic lost reply after effect');
    }
    if(url.endsWith('/api/convos')){
      eq(options.method,'DELETE');
      eq(options.headers.Authorization,req.headers.authorization);
      const id=JSON.parse(options.body).arg.conversationId;
      yes(targets.includes(id));
      chats.delete(id);chatDeleted++;
      return{status:201,json:async()=>({conversationIds:[id]})};
    }
    if(url.endsWith('/api/files')){
      eq(options.method,'DELETE');
      const id=JSON.parse(options.body).files[0].file_id;
      eq(id,F);
      FileIndex.delete(F);fileExists=false;blobExists=false;vectorExists=false;filesDeleted++;
      return{status:200,json:async()=>({deletedFileIds:[F],failedFileIds:[]})};
    }
    throw Error('UNKNOWN_NATIVE_ROUTE');
  };
  const nativeDb={
    getChatProject:async(user,id)=>
      projectExists&&user===U&&id===P?{_id:P,user:U}:null,
    getSharedResourceFileIds:async({file_ids})=>
      activeAgentRefs?file_ids.filter(id=>id===F):[],
  };
  const run=()=>{
    const bound=createC5CurrentNativeWholeProjectDelete({
      request:req,models,nativeDb,runtimeOwner:runtime,
      admissionOwner:guards,referenceOwner:refs,nativeFetch,
    });
    return bound;
  };
  return{run,req,call:async()=>{
    const z=run(),reply=res();
    await z.handler(req,reply);
    return{reply,z};
  },inspect:()=>({calls,projectExists,runtimeStatus,sourceRefs,memory,
    chats,FileIndex,receipt,saveCount,projectDeleteCount,filesDeleted,
    chatDeleted,fileExists,blobExists,vectorExists,sharedExists,
    foreignFileExists}),
  permitSharedAgain:()=>{newShare=false},
  };
}
async function testHappy(){
  const f=fixture();const {reply,z}=await f.call();const v=f.inspect();
  eq(reply.code,200);eq(reply.body.status,'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE');
  eq(z.hookNames.length,13);eq(Object.keys(z.hooks).length,13);
  eq(v.projectDeleteCount,1);eq(v.chatDeleted,2);eq(v.filesDeleted,1);
  eq(v.runtimeStatus,'RETIRED');
  yes(!v.projectExists&&!v.sourceRefs&&!v.memory);
  yes(!v.chats.has(C)&&!v.chats.has(ARCHIVED));
  yes(v.chats.has(MOVED)&&v.FileIndex.has(S)&&v.foreignFileExists);
  yes(!v.fileExists&&!v.blobExists&&!v.vectorExists);
  eq(v.receipt.phase,'COMPLETE');
  eq(reply.body.hostDiskBytesFreedProven,null);
  eq(reply.body.formerlyRecordedExclusiveObjectBytesEstimate,31);
  eq(reply.body.verifiedExclusiveFileObjectsAbsent,1);
  yes(!Object.hasOwn(reply.body,'reclaimedOwnedBlobBytes'));
  yes(v.receipt.c5_receipt_revision>=4);
  eq(v.calls.length,3);
  cases++;
}
async function testBlock(mode){
  const f=fixture({[mode]:true});
  const {reply}=await f.call();const v=f.inspect();
  eq(reply.code,409);eq(reply.body.status,'STOP');
  eq(v.projectDeleteCount,0);eq(v.filesDeleted,0);
  eq(v.chatDeleted,0);eq(v.calls.length,0);
  yes(v.projectExists&&v.fileExists&&v.chats.has(C));
  cases++;
}
async function testPartialAndRecovery(){
  const f=fixture({shareAfterSnapshot:true});
  const first=await f.call();let v=f.inspect();
  eq(first.reply.code,202);eq(first.reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.chatDeleted,2);eq(v.filesDeleted,0);
  yes(v.fileExists&&v.blobExists&&v.FileIndex.has(S));
  // The independent reference owner now certifies no new shared reference.
  f.permitSharedAgain();
  const second=await f.call();v=f.inspect();
  eq(second.reply.code,200);
  eq(second.reply.body.status,'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE');
  eq(v.projectDeleteCount,1);eq(v.filesDeleted,1);
  yes(v.receipt.phase==='COMPLETE'&&!v.fileExists);
  cases++;
}
async function testNativeFileCoverage() {
  for(const option of [
    {nativeFileRefs:true}, {nativeMessageRefs:true},
    {nativeFileRefs:true,nativeMessageRefs:true},
    {unboundFileRow:true,nativeMessageRefs:true},
  ]){
    const f=fixture(option);const {reply}=await f.call();const v=f.inspect();
    eq(reply.code,200);eq(reply.body.status,'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE');
    yes(!v.fileExists && v.chats.has(MOVED) && v.FileIndex.has(S));cases++;
  }
  for(const option of [
    {nativeFileRefs:true,omitNativeRef:true},
    {nativeMessageRefs:true,omitNativeRef:true},
    {ambiguousMessageRef:true},
  ]){
    const f=fixture(option);const {reply}=await f.call();const v=f.inspect();
    eq(reply.code,409);eq(reply.body.status,'STOP');
    eq(v.projectDeleteCount,0);eq(v.chatDeleted,0);eq(v.filesDeleted,0);
    yes(v.fileExists && v.chats.has(C) && v.FileIndex.has(S));
    cases++;
  }
}


async function testNativeGlobalReferences() {
  for(const option of [
    {unboundFileRow:true},
    {otherNativeFileRow:true},
    {foreignMessageReference:true},
    {unboundFileRow:true,nativeMessageRefs:true,foreignMessageReference:true},
  ]){
    const f=fixture(option),{reply}=await f.call(),v=f.inspect();
    eq(reply.code,409);eq(reply.body.status,'STOP');
    eq(v.projectDeleteCount,0);eq(v.filesDeleted,0);eq(v.chatDeleted,0);
    yes(v.projectExists&&v.fileExists&&v.chats.has(C));cases++;
  }
  // Recheck cross-owner Message refs AFTER Chat deletion, even for files
  // whose File row never recorded a conversationId. Sealed native anchors
  // authorize only the original target, never a newly shared consumer.
  for (const option of [
    {foreignMessageAppearsAfterRetirement:true},
    {unboundFileRow:true,nativeMessageRefs:true,
     foreignMessageAppearsAfterRetirement:true},
  ]) {
    const f=fixture(option),{reply}=await f.call(),v=f.inspect();
    eq(reply.code,202);eq(reply.body.status,'PARTIAL');
    eq(v.projectDeleteCount,1);eq(v.filesDeleted,0);
    yes(v.chats.has(MOVED)&&v.fileExists);cases++;
  }
}


async function testNativeDerivedFileReferences(){
  for(const option of [
    {runArtifactReference:true},
    {singularCodeReference:true},
    {dynamicCodeReference:true},
    {malformedDynamicCodeReference:true},
  ]){
    const f=fixture(option),{reply}=await f.call(),v=f.inspect();
    eq(reply.code,409);eq(reply.body.status,'STOP');
    eq(v.projectDeleteCount,0);eq(v.chatDeleted,0);
    yes(v.fileExists && v.chats.has(C) && v.chats.has(MOVED));cases++;
  }
  const f=fixture({dynamicCodeReferenceAppearsAfterRetirement:true});
  const {reply}=await f.call(),v=f.inspect();
  eq(reply.code,202);eq(reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.filesDeleted,0);
  yes(v.fileExists && v.chats.has(MOVED));cases++;
}
async function testAssistantReferenceAppearsAfterRetirement() {
  const f=fixture({assistantAppearsAfterRetirement:true});
  const {reply}=await f.call(),v=f.inspect();
  eq(reply.code,202);eq(reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.filesDeleted,0);
  yes(v.fileExists && v.blobExists && v.FileIndex.has(F) &&
    v.FileIndex.has(S) && v.chats.has(MOVED));
  cases++;
}
async function testAgentReferenceAppearsAfterRetirement() {
  const f=fixture({agentAppearsAfterPrepare:true});
  const {reply}=await f.call();const v=f.inspect();
  eq(reply.code,202);eq(reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.chatDeleted,2);eq(v.filesDeleted,0);
  yes(v.fileExists && v.blobExists && v.FileIndex.has(F) &&
    v.FileIndex.has(S) && v.chats.has(MOVED));
  yes(v.receipt.phase==='PARTIAL_OR_BLOCKED');
  cases++;
}
async function testLostReply(){
  const f=fixture({throwAfterEffect:true});
  const first=await f.call();let v=f.inspect();
  eq(first.reply.code,202);eq(first.reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.filesDeleted,0);
  yes(v.projectExists===false&&v.chats.has(MOVED));
  const second=await f.call();v=f.inspect();
  eq(second.reply.code,200);
  eq(second.reply.body.status,'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE');
  eq(v.projectDeleteCount,1);eq(v.filesDeleted,1);
  eq(v.chatDeleted,1); // original response-lost deletion not repeated
  cases++;
}
async function testNativeUnknownEffectReconcile(){
  const f=fixture({nativeReplyLostAfterEffect:true});
  const first=await f.call();let v=f.inspect();
  eq(first.reply.code,202);eq(first.reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,1);eq(v.chatDeleted,0);
  yes(v.receipt.nativeEffectOutcomeUnknown===true);
  const second=await f.call();v=f.inspect();
  eq(second.reply.code,200);
  eq(second.reply.body.status,'COMPLETE_VERIFIED_OWNER_ATTESTED_CASCADE');
  eq(v.projectDeleteCount,1);eq(v.chatDeleted,2);
  yes(!v.receipt.nativeEffectOutcomeUnknown);
  cases++;
}
async function testNativeUnknownCannotBlindRetry(){
  const f=fixture({unknownNativeBeforeEffect:true});
  const first=await f.call();let v=f.inspect();
  eq(first.reply.code,202);eq(first.reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,0);
  const second=await f.call();v=f.inspect();
  eq(second.reply.code,409);eq(v.projectDeleteCount,0);
  yes(v.projectExists&&v.fileExists);
  cases++;
}
async function testCodeEnvResidualCannotClaimComplete(){
  for(const flags of [{codeEnvResidualAfterDelete:true},{omitCodeEnvProof:true}]){
    const f=fixture(flags);const {reply}=await f.call();const v=f.inspect();
    eq(reply.code,202);eq(reply.body.status,'PARTIAL');
    eq(v.projectDeleteCount,1);eq(v.filesDeleted,1);
    yes(v.receipt?.phase==='PARTIAL_OR_BLOCKED');
    yes(v.chats.has(MOVED)&&v.FileIndex.has(S));cases++;
  }
}
async function testNativeFailureUnknown(){
  const f=fixture({nativeFailure:true});
  const {reply}=await f.call();const v=f.inspect();
  eq(reply.code,202);eq(reply.body.status,'PARTIAL');
  eq(v.projectDeleteCount,0);eq(v.chatDeleted,0);
  yes(v.projectExists&&v.fileExists);cases++;
}
(async()=>{
 await testHappy();
 await testNativeFileCoverage();
  await testNativeGlobalReferences();
  await testNativeDerivedFileReferences();
 for(const x of ['blockWriter','blockJobs','blockBackup','partialGraph','crossUser','agentReferences','assistantReferences','globalOnlyJobProof','foreignAdmissionOwner','foreignAdmissionProject'])
  await testBlock(x);
 await testPartialAndRecovery();
  await testAgentReferenceAppearsAfterRetirement();
  await testAssistantReferenceAppearsAfterRetirement();
 await testLostReply();
 await testNativeUnknownEffectReconcile();
 await testNativeUnknownCannotBlindRetry();
 await testCodeEnvResidualCannotClaimComplete();
 await testNativeFailureUnknown();
 console.log('C5_PROJECT_WHOLE_DELETE_COMPLETE_THIRTEEN_HOOKS=PASS');
 console.log('CASES='+cases);
 console.log('ASSERTIONS='+assertions);
 console.log('ARCHIVED_CHAT_DELETED_AND_MOVED_CHAT_PRESERVED=PASS');
 console.log('SHARED_FILE_RETAINED_AND_PARTIAL_RECOVERED=PASS');
 console.log('LIVE_NETWORK_MODEL_MONGO_PRODUCTION_EFFECTS=0');
 console.log('PROOF_CEILING=ISOLATED_SYNTHETIC_HOST_NOT_DEPLOYED');
})().catch(e=>{console.error('C5_FULL_CANDIDATE_STOP',String(e.stack||e).slice(0,1200));process.exitCode=1});
