'use strict';
// Isolated real ProjectAssistantProfile first-party adapter consumer.
// No Docker, network, model provider, secrets or real Project data.
const assert=require('node:assert/strict');
const Module=require('node:module');
const crypto=require('node:crypto');
const path=require('node:path');
const sha=t=>crypto.createHash('sha256').update(t).digest('hex');
const P='507f1f77bcf86cd799439011';
const OTHER='507f1f77bcf86cd799439012';
const previousLoad=Module._load;
const previousFetch=global.fetch;
const previousKey=process.env.UR_SHELL_ADAPTER_KEY;
process.env.UR_SHELL_ADAPTER_KEY='synthetic-not-a-real-access-secret';
let warned=0;
try {
  Module._load=function(req,parent,isMain) {
    if(req==='@librechat/data-schemas') return {logger:{warn:()=>warned++}};
    return previousLoad.apply(this,arguments);
  };
  const profile=require(path.join(__dirname,'../../windows/inquiry_desk/payload/product/overlay/librechat/ProjectAssistantProfile.js'));
  assert.equal(typeof profile.fetchProjectRuntimeContext,'function');
  assert.equal(typeof profile.buildProjectRuntimeContextBinding,'function');
  assert.equal(typeof profile.searchProjectSources,'function');
  assert.equal(typeof profile.fetchProjectLocalWorkBinding,'function');

  let calls=[];
  const rev=4;
  const good={
    '/v1/runtime-project-context-policy':{
      schema:'UR_WEB_R004_PROJECT_CONTEXT_POLICY_PRESENTATION_R001',
      authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
      initialized:true,project_revision:rev,context_policy:'PROJECT_ONLY',explicit:true,
    },
    '/v1/runtime-project-instructions':{
      initialized:true,project_revision:rev,
      instructions:'Do not use other Projects',instruction_sha256:sha('Do not use other Projects'),
    },
    '/v1/runtime-project-memory/context':{
      schema:'UR_WEB_R004_PROJECT_MEMORY_CONTEXT_PRESENTATION_R001',
      authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
      initialized:true,project_revision:rev,active_memory_count:1,
      project_memory_context:{schema:'UR_WEB_PROJECT_MEMORY_CONTEXT_R001',
        project_id:'PRJ_SYNTHETIC_PROJECT',items:[{
          memory_id:'MEM_SYNTHETIC_1',memory_revision:1,content:'Only for this Project'
        }]},
      project_memory_context_sha256:'a'.repeat(64),
      project_memory_state_guard:{project_id:'PRJ_SYNTHETIC_PROJECT'},
      project_memory_state_guard_sha256:'b'.repeat(64),state_binding:{revision:1},
    },
    '/v1/runtime-project-library':{
      schema:'UR_WEB_R004_PROJECT_LIBRARY_PRESENTATION_R001',
      authority_class:'NON_AUTHORITY_PRESENTATION_PROJECTION',
      initialized:true,project_revision:rev,source_count:0,sources:[],
    },
  };
  const responder=fixture=>async(uri,options)=>{
    const u=new URL(uri);
    calls.push({uri:u.toString(),options});
    assert.equal(u.hostname,'ur-runtime-adapter');
    assert.equal(u.port,'9000');
    assert.equal(options.method,'GET');
    assert.equal(options.headers['X-LibreChat-Project-ID'],P);
    assert.equal(options.headers.Authorization,'Bearer synthetic-not-a-real-access-secret');
    assert.equal(Object.hasOwn(fixture,u.pathname),true,'no unapproved source');
    return {ok:true,status:200,text:async()=>JSON.stringify(fixture[u.pathname])};
  };

  (async()=>{
    global.fetch=responder(good);
    const context=await profile.fetchProjectRuntimeContext(P);
    assert.equal(context.projectRevision,rev);
    assert.equal(context.contextPolicy,'PROJECT_ONLY');
    assert.equal(context.projectMemoryContext.items[0].content,'Only for this Project');
    const block=profile.formatProjectRuntimeContext(context);
    assert.equal(block.includes('Only for this Project'),true);
    assert.equal(block.includes('Do not use other Projects'),true);
    assert.equal(block.includes('No active Project Sources.'),true);
    const binding=profile.buildProjectRuntimeContextBinding(P,context);
    assert.equal(profile.projectRuntimeContextBindingEquals(binding,{...binding}),true);
    assert.equal(profile.projectRuntimeContextBindingEquals({...binding,librechat_project_id:OTHER},binding),false);
    assert.equal(profile.buildProjectRuntimeSharedContext('valid agent scope',block).includes('valid agent scope'),true);
    assert.equal(calls.length,4);

    calls=[];
    const wrong={...good,
      '/v1/runtime-project-library':{...good['/v1/runtime-project-library'],project_revision:rev+1}};
    global.fetch=responder(wrong);
    await assert.rejects(profile.fetchProjectRuntimeContext(P),/revision mismatch/);
    assert.equal(calls.length,4);

    const tampered={...binding,project_sources_context_sha256:'f'.repeat(64)};
    assert.equal(profile.projectRuntimeContextBindingEquals(tampered,binding),false);
    assert.equal(warned,0);
    console.log('P4A_GATE2_REAL_R195_PROJECT_ASSISTANT_PROFILE=PASS_OWNED_CONTEXT_MODEL_BOUND_SHAPES');
    console.log('P4A_GATE2_POSITIVE_MEMORY_AND_INSTRUCTIONS=PASS');
    console.log('P4A_GATE2_FOREIGN_PROJECT_AND_CHANGED_REVISION=BLOCKED');
    console.log('P4A_GATE2_EXTERNAL_NETWORK_MODEL_CALL=ZERO');
  })().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{
    global.fetch=previousFetch;
    if(previousKey===undefined)delete process.env.UR_SHELL_ADAPTER_KEY;
    else process.env.UR_SHELL_ADAPTER_KEY=previousKey;
  });
}finally{Module._load=previousLoad;}
