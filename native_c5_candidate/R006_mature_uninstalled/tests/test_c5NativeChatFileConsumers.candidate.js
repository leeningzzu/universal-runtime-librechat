'use strict';
const assert = require('node:assert/strict');
const { createNativeChatFileDeleteConsumers } = require('./c5NativeChatFileConsumers.candidate.js');

const OWNER = 'fixture-owner';
const OTHER = 'fixture-foreign';
const PROJECT = 'fixture-project';
const CHAT = 'fixture-chat';
const FILE = 'file-fixture-001';
const token = 'Bearer synthetic.jwt.only';
let cases = 0, checks = 0;
const eq = (a,b) => { assert.deepEqual(a,b); checks += 1; };
const present = (v) => { assert.ok(v); checks += 1; };

function scenario(overrides = {}) {
  const calls = [];
  const op = {
    schema: 'C5_PROJECT_CASCADE_R001', ownerId: OWNER,
    projectId: PROJECT, c5Confirmed: true,
    plan: {
      ownerId: OWNER, projectId: PROJECT, revision: 4,
      chats: [CHAT], exclusive: [{ id: FILE }],
    },
  };
  const params = {
    request: { user: { id: OWNER }, params: { projectId: PROJECT }, headers: { authorization: token } },
    readCurrentC5Operation: async () => op,
    readOwnedNativeFile: async () => ({
      file_id: FILE, user: OWNER, filepath: '/synthetic/fixture.bin', source: 'local',
    }),
    reconfirmExclusiveFile: async () => ({
      ownerAuthorized: true, refsComplete: true, noOtherConsumers: true,
    }),
    nativeFetch: async (url, options) => {
      calls.push({ url, options });
      return { status: url.endsWith('/api/convos') ? 201 : 200,
        json: async () => url.endsWith('/api/convos') ? {} : ({
          message:'Files deleted successfully',deletedFileIds:[FILE],failedFileIds:[],
        })};
    },
    ...overrides,
  };
  const consumers = createNativeChatFileDeleteConsumers(params);
  return { consumers, calls, op };
}

async function failWith(action, code) {
  try { await action(); assert.fail('EXPECTED_C5_STOP_' + code); }
  catch (e) { eq(e.code, code); }
}

(async () => {
  {
    const { consumers, calls } = scenario();
    const chatResult = await consumers.deleteNativeChat({
      projectId: PROJECT, ownerId: OWNER, chatId: CHAT,
    });
    present(chatResult.needsPostDeleteVerification);
    eq(calls.length, 1);
    eq(calls[0].url, 'http://127.0.0.1:3080/api/convos');
    eq(calls[0].options.method, 'DELETE');
    eq(JSON.parse(calls[0].options.body).arg.conversationId, CHAT);
    cases++;
  }
  {
    const { consumers, calls } = scenario();
    await failWith(() => consumers.deleteNativeChat({
      projectId: 'wrong-project', ownerId: OWNER, chatId: CHAT,
    }), 'C5_ROUTE_PROJECT_BINDING_MISMATCH');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario();
    // Match the native argument shape used by buildProjectCascadeHandler.
    const result = await consumers.deleteNativeExclusiveFile({
      ownerId: OWNER, fileId: FILE, nativeStrategyRequired: true,
    });
    present(result.needsPostDeleteVerification);
    eq(calls.length, 1);
    eq(calls[0].url, 'http://127.0.0.1:3080/api/files');
    eq(JSON.parse(calls[0].options.body).files[0].file_id, FILE);
    cases++;
  }
  {
    const { consumers, calls } = scenario();
    await failWith(() => consumers.deleteNativeChat({
      projectId: PROJECT, ownerId: OTHER, chatId: CHAT,
    }), 'C5_OTHER_OWNER_TARGET_BLOCK');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario();
    await failWith(() => consumers.deleteNativeChat({
      projectId: PROJECT, ownerId: OWNER, chatId: 'other-chat',
    }), 'C5_TARGET_NOT_IN_SEALED_OWNERSHIP_PLAN');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({
      readCurrentC5Operation: async () => ({
        schema: 'C5_PROJECT_CASCADE_R001', ownerId: OWNER, projectId: PROJECT,
        c5Confirmed: false, plan: { ownerId: OWNER, projectId: PROJECT,
          revision: 4, chats: [CHAT], exclusive: [{id: FILE}] },
      }),
    });
    await failWith(() => consumers.deleteNativeChat({
      projectId: PROJECT, ownerId: OWNER, chatId: CHAT,
    }), 'C5_DURABLE_NATIVE_RETIREMENT_NOT_CONFIRMED');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({
      reconfirmExclusiveFile: async () => ({
        ownerAuthorized: true, refsComplete: true, noOtherConsumers: false,
      }),
    });
    await failWith(() => consumers.deleteNativeExclusiveFile({
      projectId: PROJECT, ownerId: OWNER, fileId: FILE,
    }), 'C5_FILE_REFS_NOW_SHARED_OR_UNPROVEN');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({
      readOwnedNativeFile: async () => ({
        file_id: FILE, user: OTHER, filepath: '/synthetic/fixture.bin',
      }),
    });
    await failWith(() => consumers.deleteNativeExclusiveFile({
      projectId: PROJECT, ownerId: OWNER, fileId: FILE,
    }), 'C5_FILE_CURRENT_NATIVE_OWNERSHIP_UNPROVEN');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({readOwnedNativeFile: async () => null});
    const result = await consumers.deleteNativeExclusiveFile({
      projectId: PROJECT, ownerId: OWNER, fileId: FILE,
    });
    present(result.fileMetadataAlreadyAbsent);
    present(result.needsPostDeleteVerification);
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({
      nativeFetch: async () => { throw Error('simulated unknown-after-effect'); },
    });
    await failWith(() => consumers.deleteNativeChat({
      projectId: PROJECT, ownerId: OWNER, chatId: CHAT,
    }), 'C5_NATIVE_EFFECT_OUTCOME_UNKNOWN');
    eq(calls.length, 0);
    cases++;
  }
  {
    const { consumers, calls } = scenario({
      nativeFetch: async (url, opts) => {
        calls.push({url,opts});
        return { status: 200, json: async () => ({ deletedFileIds:[],failedFileIds:[FILE] }) };
      },
    });
    await failWith(() => consumers.deleteNativeExclusiveFile({
      projectId: PROJECT, ownerId: OWNER, fileId: FILE,
    }), 'C5_NATIVE_FILE_DELETE_REPORTED_FAILURE');
    eq(calls.length, 1);
    cases++;
  }
  // An HTTP 200 may mean no deletion or partial deletion in upstream.
  // The native result MUST acknowledge exactly this File ID.
  for (const malformed of [
    {}, {deletedFileIds:[],failedFileIds:[]},
    {deletedFileIds:[OTHER],failedFileIds:[]},
    {deletedFileIds:[FILE,OTHER],failedFileIds:[]},
    {deletedFileIds:[FILE],failedFileIds:null},
    {deletedFileIds:[FILE],failedFileIds:['unrelated-failure']},
    {deletedFileIds:[FILE],failedFileIds:[FILE]},
  ]) {
    const {consumers,calls}=scenario({nativeFetch:async(url,opts)=>{
      calls.push({url,opts}); return {status:200,json:async()=>malformed};
    }});
    const shapeOK=Array.isArray(malformed.deletedFileIds) &&
      Array.isArray(malformed.failedFileIds);
    const expected = !shapeOK
      ? 'C5_NATIVE_FILE_DELETE_RESPONSE_UNVERIFIED'
      : malformed.failedFileIds.length
        ? 'C5_NATIVE_FILE_DELETE_REPORTED_FAILURE'
        : 'C5_NATIVE_FILE_DELETE_TARGET_NOT_ACKNOWLEDGED';
    await failWith(()=>consumers.deleteNativeExclusiveFile({
      projectId:PROJECT,ownerId:OWNER,fileId:FILE,
    }),expected);
    eq(calls.length,1);cases++;
  }
  {
    await failWith(async () => createNativeChatFileDeleteConsumers({
      ...scenario().consumers,
      request: { user: {id: OWNER}, headers: {authorization: token} },
      readCurrentC5Operation: async()=>({}),
      readOwnedNativeFile: async()=>({}),
      reconfirmExclusiveFile: async()=>({}),
      nativeFetch: async()=>({status:200,json:async()=>({})}),
      origin: 'https://external.example.org',
    }), 'C5_LOOPBACK_ORIGIN_MUST_BE_FIXED');
    cases++;
  }
  {
    await failWith(async () => createNativeChatFileDeleteConsumers({
      request: {user:{id:OWNER},params:{projectId:PROJECT},headers:{}},
      readCurrentC5Operation:async()=>({}),
      readOwnedNativeFile:async()=>({}),
      reconfirmExclusiveFile:async()=>({}),
      nativeFetch:async()=>({status:200,json:async()=>({})}),
    }), 'C5_NATIVE_AUTH_TOKEN_MUST_BE_PRESENT');
    cases++;
  }
  console.log('C5_NATIVE_CHAT_FILE_LOOOPBACK_CONSUMERS=PASS');
  console.log('CASES=' + cases);
  console.log('ASSERTIONS=' + checks);
  console.log('PRODUCTION_DB_CALLS=0');
  console.log('ACTUAL_NETWORK_REQUESTS=0');
  console.log('USER_DATA_OR_REAL_TOKENS=0');
})().catch(e=>{console.error('C5_NATIVE_CONSUMER_CANDIDATE=STOP',String(e.stack||e).slice(0,1400));process.exitCode=1});
