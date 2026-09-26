// Actual Vue template, authored synthetic inputs, no browser/external calls.
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import { parse, compileTemplate } from 'vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
const source = readFileSync(new URL('../src/components/RoutePanel.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileTemplate({source: descriptor.template.content, filename: 'RoutePanel.vue', id: 'route-panel', ssr: true})
assert.deepEqual(compiled.errors, [])
const code = compiled.code.replace(/from "([^"]+)"/g, (_,name) => `from "${import.meta.resolve(name)}"`)
const { ssrRender } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))
const inputs = {places: [], charter:'UNKNOWN', mode:'TRANSIT', origin:'', destination:'', depart_at:null, return_by:null}
const data = {interest:'合成日段 <img onerror="danger()">', evidence_count:8, inherited:{days:5,driving:'NO'},
  source_reference_kinds:['AUTHOR_PROPOSED_PLAN'], configured:false, inputs, adopted_inputs:null, source_route_fragments:[],
  has_changes:true,budget:{used:{map_place:0,map_route:0},remaining:{map_place:8,map_route:8},total_used:0},places:[],legs:[],
  time_check:{completeness:'PARTIAL',scenario:'UNKNOWN',known_movement_minutes:0,available_minutes:null,missing_inputs:['停留未知'],assumptions:[],checked_scope:'LOCAL_DAY_SEGMENT'},
  message:'地图结果需显式重新核实', map_result_state:'EXPIRED_OR_NOT_QUERIED'}
const render = changes => renderToString(createSSRApp({ssrRender,data:()=>({data,form:inputs,edited:false,busy:false,error:'',status:'',relations:{},times:{},consent:false,privateConsent:false,objectTypes:['UNKNOWN'],mapLabel:v=>v,roleLabel:v=>v,localDate:()=>'',...changes})}))
const html = await render()
assert(html.includes('AMAP_LIVE_BLOCKED_NOT_CONFIGURED') && html.includes('继承 5 天'))
assert(html.includes('停留未知') && html.includes('采用当前条件') && html.includes('取消本次条件修改'))
assert(html.includes('&lt;img') && !html.includes('<img'))
assert(html.includes('不代表行程耗时为0') && html.includes('不会自动读取 .env'))
const stale = await render({data:{...data,map_result_state:'STALE'},error:'<script>bad</script>'})
assert(stale.includes('旧地图计算已失效') && !stale.includes('<script>'))
assert(!source.includes('localStorage') && !source.includes('sessionStorage'))
assert(!source.includes('https://restapi.amap.com'))
console.log('PASS RoutePanel: inheritance, unknowns, missing Key, input adoption, stale, escaped text, no persistent map cache')
