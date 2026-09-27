// Render the real template with authored mentions; no real content or requests.
import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse, compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/PlaceDiscovery.vue',import.meta.url),'utf8'))
const result=compileTemplate({source:descriptor.template.content,filename:'PlaceDiscovery.vue',id:'discovery',ssr:true,cssVars:[]})
assert.deepEqual(result.errors,[])
const code=result.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
const lead={lead_id:'local-lead',public_name:'自编公共街',identity_status:'UNKNOWN',identity_origin:'UNKNOWN',spatial_status:'UNKNOWN',quarantined:false,quarantine_reasons:[],start:1,end:6,parent_blocks:[{block_index:0,text:'自编上下文'}],context_flags:['AUTHOR_ROLE_UNVERIFIED'],claim_references:[{context_status:'PENDING'},{context_status:'REJECTED'}]}
async function render(leads){return renderToString(createSSRApp({ssrRender,components:{PlanPlaces:{render:()=>null}},data:()=>({plan:{place_leads:leads,discovery_available:true},selected:[],busy:false,reason:v=>v,emit:()=>{}})}))}
const unknown=await render([lead])
assert(unknown.includes('地点身份待检查') && unknown.includes('1 待审 / 1 拒绝 / 0 已接纳'))
assert(unknown.includes('市区范围待核实') && /checkbox[^>]*disabled/.test(unknown))
const checked=await render([{...lead,identity_status:'CHECKED',identity_origin:'PROGRAM_SUGGESTED_MATCH'}])
assert(checked.includes('程序建议') && !/checkbox[^>]*disabled/.test(checked))
const quarantined=await render([{...lead,quarantined:true,quarantine_reasons:['ACCESS_RESTRICTION']}])
assert(quarantined.includes('已隔离') && quarantined.includes('不发送查询'))
assert((await render([])).includes('从当前缓存识别公共地点（本地）'))
console.log('PASS PlaceDiscovery: independent mention/claim states, identity gating, UNKNOWN meaning, quarantine, cache action')
