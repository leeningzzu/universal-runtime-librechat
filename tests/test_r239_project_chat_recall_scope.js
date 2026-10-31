'use strict';
// Test actual packaged LibreChat project-chat-recall code without installing a
// second chat store, accessing any user's history or starting Docker.
const assert = require('assert');
const path = require('path');
const Module = require('module');
const realLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === '@librechat/agents/langchain/tools') {
    return { tool: (fn, config) => ({ fn, config }) };
  }
  return realLoad.apply(this, arguments);
};
const actual = require(path.join(
  __dirname, '..', 'windows', 'inquiry_desk', 'payload', 'product',
  'overlay', 'librechat', 'projectChatRecall.js'
));
Module._load = realLoad;

const conversations = [
  { conversationId:'current', chatProjectId:'P-A',title:'Current Chat',user:'u',createdAt:'2026-10-30',updatedAt:'2026-10-30'},
  { conversationId:'previous',chatProjectId:'P-A',title:'Earlier alpha notes',user:'u',createdAt:'2026-10-29',updatedAt:'2026-10-29'},
  { conversationId:'other',chatProjectId:'P-B',title:'Other Project alpha private',user:'u',createdAt:'2026-10-28',updatedAt:'2026-10-28'},
  { conversationId:'foreign',chatProjectId:'P-A',title:'Another account alpha',user:'v',createdAt:'2026-10-27',updatedAt:'2026-10-27'},
];
const messages = [
  {conversationId:'previous',messageId:'m-old',isCreatedByUser:true,text:'Project Alpha exact old note R239',createdAt:'2026-10-29'},
  {conversationId:'other',messageId:'m-other',isCreatedByUser:true,text:'Other Project alpha secret',createdAt:'2026-10-28'},
  {conversationId:'foreign',messageId:'m-foreign',isCreatedByUser:true,text:'Another account alpha secret',createdAt:'2026-10-27'},
];
const methods = {
  getConvosByCursor: async(user,opts) => ({
    conversations:conversations.filter(x=>x.user===user),nextCursor:null
  }),
  getConvosQueried:async(user,items)=>({
    conversations:conversations.filter(x=>x.user===user && items.some(y=>y.conversationId===x.conversationId))
  }),
  getMessages:async(filter,fields,opts)=>{
    let rows=messages.slice();
    if (filter.conversationId && filter.conversationId.$in) {
      rows=rows.filter(m=>filter.conversationId.$in.includes(m.conversationId));
    } else if (typeof filter.conversationId==='string') {
      rows=rows.filter(m=>m.conversationId===filter.conversationId);
    }
    if(filter.messageId)rows=rows.filter(m=>m.messageId===filter.messageId);
    if(filter.parentMessageId)rows=rows.filter(m=>m.parentMessageId===filter.parentMessageId);
    return rows;
  },
};
async function test() {
  const args={userId:'u',chatProjectId:'P-A',currentConversationId:'current',methods};
  const search=await actual.projectChatSearch({...args,query:'alpha',topK:8,selection:'relevance'});
  assert.strictEqual(search.candidates.length,1);
  assert.strictEqual(search.candidates[0].conversation_id,'previous');
  assert.strictEqual(search.candidates[0].match.message_id,'m-old');
  const read=await actual.projectChatRead({...args,conversationId:'previous',messageId:'m-old'});
  assert.strictEqual(read.messages.length,1);
  assert.ok(read.messages[0].text.includes('R239'));
  const wrong=await actual.projectChatRead({...args,conversationId:'other'});
  assert.strictEqual(wrong.error,'PROJECT_CHAT_SCOPE_MISMATCH');
  assert.deepStrictEqual(wrong.messages,[]);
  const same=await actual.projectChatRead({...args,conversationId:'current'});
  assert.strictEqual(same.error,'CURRENT_CHAT_NOT_HISTORY');
  const tools=actual.createProjectChatRecallTools(args);
  assert.deepStrictEqual(tools.map(x=>x.config.name),['project_chat_search','project_chat_read']);
  console.log(JSON.stringify({status:'PASS_R239_NATIVE_LIBRECHAT_PROJECT_CHAT_SCOPE_POS_NEG',
    old_chat_search:true,exact_message_read:true,cross_project_rejected:true,
    current_chat_rejected:true,tools_available:2,real_model_chat_e2e:false}));
}
test().catch(error=>{console.error(error.message);process.exit(1);});
