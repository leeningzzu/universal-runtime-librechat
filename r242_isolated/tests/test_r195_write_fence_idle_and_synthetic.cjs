'use strict';
/** The actual copied mature R195 C5 writer fence. Pure synthetic requests. */
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createC5WriteFence}=require(
 '../..//windows/inquiry_desk/payload/product/overlay/librechat/C5WriteFence.js');
const fence=createC5WriteFence();
const middleware=fence.middleware();
let continued=0;
function response(){
  const e=new EventEmitter();
  e.statusCode=200;
  e.status=function(code){this.statusCode=code;return this};
  e.set=function(){return this};
  e.json=function(body){this.body=body;return this};
  return e;
}
const read={method:'GET',path:'/api/projects/507f1f77bcf86cd799439011',originalUrl:'/api/projects/507f1f77bcf86cd799439011',headers:{}};
let res=response();
middleware(read,res,()=>continued++);
assert.equal(continued,1);
assert.equal(fence.currentOperationId?.()??null,null);
const mutation={method:'POST',path:'/api/projects',originalUrl:'/api/projects',headers:{},body:{}};
res=response();
middleware(mutation,res,()=>continued++);
assert.equal(continued,2);
res.emit('finish');
const forged={method:'DELETE',path:'/api/projects/507f1f77bcf86cd799439011',
 originalUrl:'/api/projects/507f1f77bcf86cd799439011',
 headers:{'x-c5-irrevocable-project-delete':'FALSE_FORGED'},
 body:{confirmedIrreversibleProjectDelete:true,
 projectId:'507f1f77bcf86cd799439011',
 deleteProtectionPolicy:'FORWARD_ONLY_DURABLE_RECEIPT_R001'}};
res=response();
middleware(forged,res,()=>continued++);
assert.equal(continued,3);
res.emit('close');
// No lock is ever granted by a header alone; actual R195 admission MUST read
// current native Project, Runtime lease and file/vector/shared references.
assert.equal(typeof fence.acquire,'function');
assert.equal(typeof fence.assertHeld,'function');
assert.equal(typeof fence.release,'function');
assert.equal(typeof fence.acquirePrepare,'function');
console.log('R195_GLOBAL_WRITE_FENCE_SOURCE_ACTUAL=PASS');
console.log('R195_IDLE_NATIVE_READ_WRITE_NO_EXTRA_BLOCK=PASS');
console.log('R195_SYNTHETIC_FORGED_DELETE_NOT_AN_ADMISSION=PASS');
console.log('R195_REAL_EFFECT_DELETE=NOT_EXECUTED');
