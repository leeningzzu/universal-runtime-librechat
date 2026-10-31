'use strict';
/* Bounded source-backed first-party RAG deletion tests. No network/files/DB effect. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const SOURCE=fs.readFileSync(
  path.join(__dirname,'vectorDB.c5.native_owner_fail_closed.candidate.js'),'utf8',
);
const FILE='synthetic-file-id';
let cases=0,checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++};
function owner(ragUrl='http://synthetic-rag.invalid',reply=async()=>({status:200})){
  const events=[],logs=[];
  const deps={
    'fs':{createReadStream:()=>{throw Error('UNEXPECTED_REAL_FILE_ACCESS')}},
    'axios':{delete:async(url,options)=>{events.push({url,options});return reply(url,options,events.length)}},
    'form-data':class {constructor(){throw Error('UNEXPECTED_UPLOAD')}},
    '@librechat/data-schemas':{logger:{warn:(s)=>logs.push(String(s)),debug(){}}},
    'librechat-data-provider':{FileSources:{vectordb:'vectordb'}},
    '@librechat/api':{
      logAxiosError:({message})=>logs.push(String(message)),
      generateShortLivedToken:()=>'synthetic-no-provider-call',
    },
  };
  const ctx={
    require:(name)=>{if(!(name in deps))throw Error('UNEXPECTED_IMPORT_'+name);return deps[name]},
    module:{exports:{}},process:{env:ragUrl?{RAG_API_URL:ragUrl}:{RAG_API_URL:undefined}},
  };
  vm.runInNewContext(SOURCE,ctx,{filename:'LIBRECHAT_C5_VECTOR_NATIVE_CANDIDATE'});
  const req={user:{id:'synthetic-user'}};
  return {deleteVectors:ctx.module.exports.deleteVectors,req,events,logs};
}
async function rejects(operation,code){
  await assert.rejects(operation,(error)=>error?.message===code);
  checks++;
}
(async()=>{
  // A file that never had vectors must NOT invoke a RAG resource.
  {
    const x=owner(undefined);
    await x.deleteVectors(x.req,{file_id:FILE,embedded:false});
    eq(x.events.length,0);cases++;
  }
  // A previously embedded file with no active RAG owner is NOT success.
  {
    const x=owner(null);
    await rejects(()=>x.deleteVectors(x.req,{file_id:FILE,embedded:true}),
      'C5_VECTOR_STORE_UNAVAILABLE');
    eq(x.events.length,0);cases++;
  }
  // Current user-owned namespaces reuse the native caller scope.
  {
    const x=owner();
    await x.deleteVectors(x.req,{file_id:FILE,embedded:true,metadata:{}});
    eq(x.events.length,1);
    eq(x.events[0].url,'http://synthetic-rag.invalid/documents');
    eq(x.events[0].options.data[0],FILE);
    eq(x.events[0].options.params,undefined);cases++;
  }
  // Server-persisted first-party embeddedEntities are sent as entity_id.
  {
    const x=owner();
    await x.deleteVectors(x.req,{file_id:FILE,embedded:true,
      metadata:{embeddedEntities:['synthetic-agent-one','synthetic-agent-two']}});
    eq(x.events.length,2);
    eq(x.events.map(e=>e.options.params.entity_id),
      ['synthetic-agent-one','synthetic-agent-two']);
    eq(x.events.every(e=>e.options.headers.Authorization==='Bearer synthetic-no-provider-call'),
      true);cases++;
  }
  // 404 from the wrong owner namespace and RAG outages CANNOT become
  // success or permit native processDeleteRequest to erase Mongo metadata.
  for(const scenario of [
    Object.assign(new Error('wrong owner namespace'),{response:{status:404}}),
    Object.assign(new Error('rag refused request'),{response:{status:503}}),
    Object.assign(new Error('network deadline'),{code:'ETIMEDOUT'}),
  ]){
    const x=owner('http://synthetic-rag.invalid',async()=>{throw scenario});
    await rejects(()=>x.deleteVectors(x.req,{file_id:FILE,embedded:true,
      metadata:{embeddedEntities:['synthetic-agent-one']}}),
      'C5_VECTOR_DELETE_INCOMPLETE');
    eq(x.events.length,1);eq(x.logs.length>=1,true);cases++;
  }
  // A partial multi-entity result must remain PARTIAL, not COMPLETE.
  {
    const x=owner('http://synthetic-rag.invalid',
      async(_url,_options,index)=>{
        if(index===2)throw Object.assign(new Error('secondary owner unavailable'),{response:{status:404}});
        return {status:200};
      });
    await rejects(()=>x.deleteVectors(x.req,{file_id:FILE,embedded:true,
      metadata:{embeddedEntities:['synthetic-agent-one','synthetic-agent-two']}}),
      'C5_VECTOR_DELETE_INCOMPLETE');
    eq(x.events.length,2);cases++;
  }
  // Native references are a bounded exact identity set, never an unbounded
  // external operation or caller-supplied raw query string.
  for(const ids of [null,'synthetic-agent-one',[''],['duplicate','duplicate'],new Array(65).fill('x')]){
    const x=owner();
    await rejects(()=>x.deleteVectors(x.req,{file_id:FILE,embedded:true,
      metadata:{embeddedEntities:ids}}),
      'C5_VECTOR_EMBEDDED_OWNER_GRAPH_UNVERIFIED');
    eq(x.events.length,0);cases++;
  }
  {
    const x=owner();
    await rejects(()=>x.deleteVectors({user:null},{file_id:FILE,embedded:true}),
      'C5_VECTOR_NATIVE_OWNER_MISSING');
    eq(x.events.length,0);cases++;
  }
  {
    const x=owner('http://synthetic-rag.invalid',async()=>({status:undefined}));
    await rejects(()=>x.deleteVectors(x.req,{file_id:FILE,embedded:true}),
      'C5_VECTOR_DELETE_INCOMPLETE');cases++;
  }
  console.log('C5_NATIVE_RAG_VECTOR_DELETE_NOT_FALSE_SUCCESS=PASS');
  console.log('SCENARIOS='+cases);
  console.log('ASSERTIONS='+checks);
  console.log('FIRST_PARTY_EMBEDDED_ENTITIES_OWNER_SCOPES=REUSED');
  console.log('404_NETWORK_ERROR_AND_NO_RAG_PRESERVE_FILE_METADATA=PASS_CONTRACT');
  console.log('PRODUCTION_REAL_FILES_VECTORS_NETWORK_EFFECT=0');
  console.log('PROOF_CEILING=STAGED_NATIVE_FILE_STRATEGY_SOURCE_ONLY');
})().catch(err=>{console.error('C5_VECTOR_SOURCE_STOP',String(err.stack||err));process.exitCode=1});
