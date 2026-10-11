import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {parse,compileScript} from 'vue/compiler-sfc'
import ts from 'typescript'
import {createRenderer,h,ref,nextTick} from 'vue'

const requests=[],downloads=[],revoked=[],timers=[]
let resolveRequest,rejectRequest
globalThis.__guideRequest=(...args)=>{requests.push(args);return new Promise((resolve,reject)=>{resolveRequest=resolve;rejectRequest=reject})}
const realDocument=globalThis.document,realTimeout=globalThis.setTimeout
const realCreate=URL.createObjectURL,realRevoke=URL.revokeObjectURL
globalThis.document={createElement:()=>({href:'',download:'',click(){downloads.push({href:this.href,filename:this.download})}})}
URL.createObjectURL=blob=>{assert(blob instanceof Blob);return 'blob:synthetic-guide'}
URL.revokeObjectURL=url=>revoked.push(url)
globalThis.setTimeout=(callback,milliseconds)=>{timers.push({callback,milliseconds});return 1}
const {descriptor}=parse(readFileSync(new URL('../src/components/AdvisoryGuide.vue',import.meta.url),'utf8'))
let source=compileScript(descriptor,{id:'guide-export-test',genDefaultAs:'component'}).content
source=source.replace(/import \{ request \} from ['"]\.\.\/api['"]/, 'const request=(...args)=>globalThis.__guideRequest(...args)')
source+='\ncomponent.render=()=>null; export default component'
source=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ESNext,module:ts.ModuleKind.ESNext}}).outputText
source=source.replace(/from ["']vue["']/g,`from "${import.meta.resolve('vue')}"`)
const {default:Component}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},parentNode:()=>null,nextSibling:()=>null,patchProp(){}})
const draft={activities:[],days:3}
const plan=ref({session_id:'synthetic-A',revision:4,draft,adopted:draft})
let child
const app=renderer.createApp({render:()=>h(Component,{ref:v=>{child=v},plan:plan.value,busy:false})})
app.mount({});await nextTick()
const state=child.$.setupState
const payload={filename:'travel-guide.md',markdown:'# Synthetic adopted guide',revision:4,adopted_version:2}
let pending=state.exportGuide();await nextTick()
assert(state.exportPending && state.exportNotice.includes('正在核对'))
await state.exportGuide();assert.equal(requests.length,1,'double click must not dispatch another local request')
assert.equal(requests[0][0],'/api/v1/preview/planning/synthetic-A/guide-export')
assert.equal(requests[0][1],undefined,'export must remain a read, not a research mutation')
assert.equal(requests[0][3].timeoutMs,60000)
resolveRequest(payload);await pending
assert.deepEqual(downloads,[{href:'blob:synthetic-guide',filename:'travel-guide.md'}])
assert.equal(state.exportPending,false)
assert(state.exportNotice.includes('不代表磁盘保存已完成'))
assert.equal(revoked.length,0,'do not revoke before the browser can start saving')
assert.equal(timers[0].milliseconds,60000);timers[0].callback();assert.deepEqual(revoked,['blob:synthetic-guide'])
pending=state.exportGuide();rejectRequest(new Error('来源已变化'));await pending
assert.equal(state.exportError,'来源已变化');assert.equal(state.exportNotice,'');assert.equal(downloads.length,1)
pending=state.exportGuide();plan.value={...plan.value,session_id:'synthetic-B'};await nextTick();resolveRequest(payload);await pending
assert(state.exportError.includes('状态已变化'));assert.equal(downloads.length,1)
plan.value={...plan.value,session_id:'synthetic-A'};await nextTick()
pending=state.exportGuide();plan.value={...plan.value,adopted:{...draft,days:5}};await nextTick();resolveRequest(payload);await pending
assert(state.exportError.includes('状态已变化'));assert.equal(downloads.length,1)
pending=state.exportGuide();resolveRequest({...payload,revision:3});await pending
assert(state.exportError.includes('状态已变化'));assert.equal(downloads.length,1)
pending=state.exportGuide();resolveRequest({...payload,markdown:''});await pending
assert(state.exportError.includes('内容不完整'));assert.equal(downloads.length,1)
plan.value={...plan.value,adopted:null};await nextTick();const count=requests.length;await state.exportGuide();assert.equal(requests.length,count)
app.unmount()
globalThis.document=realDocument;globalThis.setTimeout=realTimeout;URL.createObjectURL=realCreate;URL.revokeObjectURL=realRevoke;delete globalThis.__guideRequest
console.log('PASS guide export: one read, pending/error feedback, native handoff, delayed cleanup, trip/adoption/revision fence, no research calls')
