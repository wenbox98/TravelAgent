import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {parse,compileScript} from 'vue/compiler-sfc'
import ts from 'typescript'
import {createRenderer,h,ref,nextTick} from 'vue'

const requests=[],events=[]
let finish
globalThis.__mapRequest=(...args)=>{requests.push(args);return new Promise(resolve=>{finish=resolve})}
globalThis.localStorage={values:new Map(),getItem(k){return this.values.get(k)||null},setItem(k,v){this.values.set(k,v)},removeItem(k){this.values.delete(k)}}
const {descriptor}=parse(readFileSync(new URL('../src/components/CriticalMap.vue',import.meta.url),'utf8'))
let source=compileScript(descriptor,{id:'critical-map-test',genDefaultAs:'component'}).content
source=source.replace(/import \{request\} from ['"]\.\.\/api['"]/, 'const request=(...args)=>globalThis.__mapRequest(...args)')
source=source.replace(/import \{mapLabel\} from ['"]\.\.\/route-api['"]/, 'const mapLabel=v=>v')
source=source.replace(/import PlaceChoices from ['"]\.\/PlaceChoices.vue['"]/, 'const PlaceChoices={render:()=>null}')
source+='\ncomponent.render=()=>null; export default component'
source=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ESNext,module:ts.ModuleKind.ESNext}}).outputText
source=source.replace(/from ["']vue["']/g,`from "${import.meta.resolve('vue')}"`)
const {default:Component}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},parentNode:()=>null,nextSibling:()=>null,patchProp(){}})
const plan=ref({session_id:'synthetic',revision:1,draft:{inputs:{mode:'WALKING'},activities:[]},critical_map:{intent_key:null,pairs:[{leg_id:'a--b',names:['甲园','乙园']}],configured:true,ready:true,active:false}})
const parentBusy=ref(false)
let child
const app=renderer.createApp({render:()=>h(Component,{ref:v=>{child=v},plan:plan.value,busy:parentBusy.value,onPending:value=>{events.push(value);parentBusy.value=value},onUpdated:value=>{plan.value=value}})})
app.mount({})
await nextTick()
const state=child.$.setupState
state.confirmed=true
plan.value={...plan.value,revision:2}
await nextTick()
assert.equal(state.confirmed,true,'unrelated saved revision must not withdraw an unchanged route confirmation')
state.pair='b--c'
await nextTick()
assert.equal(state.confirmed,false,'changing the selected pair must require confirmation again')
state.pair='a--b';await nextTick();state.confirmed=true
const pending=state.act('start',{leg_id:'a--b',consent:'PRIVATE_KEY_LEG_V1'})
await nextTick()
assert.equal(parentBusy.value,true,'map request must block parent polling and competing edits')
await state.act('start',{leg_id:'a--b'})
assert.equal(requests.length,1,'a pending request must not dispatch a second query')
assert.equal(requests[0][3].timeoutMs,120000,'two 25-second provider waits cannot use the normal 15-second read deadline')
finish({...plan.value,critical_map:{...plan.value.critical_map,active:true}})
await pending;await nextTick()
assert.deepEqual(events,[true,false])
assert.equal(parentBusy.value,false)
assert.equal(localStorage.getItem('ta-key-leg-intent'),null)
plan.value={...plan.value,draft:{...plan.value.draft,inputs:{mode:'TRANSIT'}}}
await nextTick()
assert.equal(state.confirmed,false,'changed transport must invalidate the previous consent')
app.unmount()
delete globalThis.__mapRequest
console.log('PASS CriticalMap: stable consent, changed-order/mode invalidation, one pending request, parent lock, finite provider deadline')
