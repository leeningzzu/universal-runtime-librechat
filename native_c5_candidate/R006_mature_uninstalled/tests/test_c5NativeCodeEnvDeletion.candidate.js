'use strict';
/* Source-backed native Code Environment cleanup protection; no real network. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const SOURCE=fs.readFileSync(path.join(__dirname,
  'codeEnv.c5.native_owner_fail_closed.candidate.js'),'utf8');
let cases=0,checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++};
function build({reply,configured=false}={}){
  const events=[],logs=[];
  const client=async (options)=>{
    events.push(options);
    return reply?await reply(options):{status:200};
  };
  client.post=async()=>{throw Error('UNEXPECTED_UPLOAD')};
  const deps={
    'form-data':class {constructor(){throw Error('UNEXPECTED_FORM_UPLOAD')}},
    '@librechat/data-schemas':{logger:{warn:(msg)=>logs.push(String(msg))}},
    '@librechat/agents':{getCodeBaseURL:()=>{throw Error('NO_EXTERNAL_SERVICE')}},
    'librechat-data-provider':{
      EModelEndpoint:{agents:'agents'},
      getCodeEnvRefs:(metadata)=>metadata?.refs??[],
    },
    '@librechat/api':{
      logAxiosError:({message})=>{logs.push(String(message));return 'safe'},
      wrapCodeApiUploadError:()=>{},
      appendCodeEnvFile:()=>{},
      createAxiosInstance:()=>client,
      codeServerHttpAgent:null,
      codeServerHttpsAgent:null,
      appendCodeEnvFileIdentity:()=>{},
      buildCodeEnvDownloadQuery:()=>'?synthetic=1',
      getCodeApiAuthHeaders:async()=>({'X-Synthetic':'1'}),
      getCodeExecutionBaseUrl:(profile,env)=>{
        if(profile==='stateful'&&!env)throw Error('NO_STATEFUL_CURRENT_ROUTE');
        return 'http://synthetic-code.invalid';
      },
      createCodeExecutionRouteKey:(_profile,env)=>env?.routeKey,
      codeExecutionHeaders:()=>({}),
    },
  };
  const context={
    require:(module)=>{if(!(module in deps))throw Error('UNEXPECTED_MODULE_'+module);return deps[module]},
    module:{exports:{}},
  };
  vm.runInNewContext(SOURCE,context,{filename:'C5_NATIVE_CODE_ENV_FIRST_PARTY_SOURCE'});
  const request={user:{id:'synthetic-user'},
    config:{endpoints:{agents:{statefulCodeSessions:{
      environments:configured?[{routeKey:'stateful:current'}]:[],
    }}}}};
  return {deleteCodeEnvFile:context.module.exports.deleteCodeEnvFile,request,events,logs};
}
const meta=(route,profile='stateful')=>({refs:[[route,{
  executionProfile:profile,kind:'user',id:'synthetic-user',
  storage_session_id:'synthetic-session',file_id:'synthetic-code-file',
}]]});
async function expectStop(action,message){
  await assert.rejects(action,e=>e?.message===message);checks++;
}
(async()=>{
  {
    const x=build();
    await x.deleteCodeEnvFile(x.request,{metadata:{refs:[]}});
    eq(x.events.length,0);cases++;
  }
  {
    const x=build();
    await expectStop(()=>x.deleteCodeEnvFile(x.request,{metadata:meta('stateful:retired')}),
      'C5_CODE_ENV_OWNER_ROUTE_UNAVAILABLE');
    eq(x.events.length,0);cases++;
  }
  {
    const x=build();
    await expectStop(()=>x.deleteCodeEnvFile(x.request,{metadata:meta('stateful')}),
      'C5_CODE_ENV_RETIRED_ROUTE_UNAVAILABLE');
    eq(x.events.length,0);cases++;
  }
  {
    const x=build({configured:true});
    await x.deleteCodeEnvFile(x.request,{metadata:meta('stateful:current')});
    eq(x.events.length,1);
    eq(x.events[0].method,'delete');
    eq(x.events[0].url.startsWith('http://synthetic-code.invalid/files/'),true);
    cases++;
  }
  // Wrong base URL 404 does not imply bytes absent; preserve File record.
  {
    const x=build({configured:true,reply:async()=>{throw Object.assign(
      new Error('not found'),{response:{status:404}})}});
    await expectStop(()=>x.deleteCodeEnvFile(x.request,
      {metadata:meta('stateful:current')}),
      'C5_CODE_ENV_DELETE_UNVERIFIED');
    eq(x.events.length,1);eq(x.logs.length>=1,true);cases++;
  }
  {
    const x=build({configured:true,reply:async()=>{throw Object.assign(
      new Error('network timeout'),{code:'ETIMEDOUT'})}});
    await assert.rejects(()=>x.deleteCodeEnvFile(x.request,
      {metadata:meta('stateful:current')}));
    checks++;eq(x.events.length,1);cases++;
  }
  console.log('C5_NATIVE_CODE_ENV_ORPHAN_PREVENTION=PASS');
  console.log('SCENARIOS='+cases);
  console.log('ASSERTIONS='+checks);
  console.log('MISSING_LEGACY_ROUTE_AND_AMBIGUOUS_404_KEEP_METADATA=PASS');
  console.log('REAL_CODE_WORKSPACE_NETWORK_OR_STORAGE_EFFECT=0');
  console.log('PROOF_CEILING=STAGED_NATIVE_SOURCE_ONLY_NOT_PRODUCT_DELETE');
})().catch(e=>{console.error('C5_NATIVE_CODE_ENV_STOP',String(e.stack||e));process.exitCode=1});
