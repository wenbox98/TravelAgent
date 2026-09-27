// Production template with synthetic structural differences; no live data.
import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/RevisionReview.vue',import.meta.url),'utf8'))
const compiled=compileTemplate({source:descriptor.template.content,filename:'RevisionReview.vue',id:'revision',ssr:true,cssVars:[]})
assert.deepEqual(compiled.errors,[])
const code=compiled.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
async function render(job){return renderToString(createSSRApp({ssrRender,data:()=>({job,busy:false,name:()=>'<script>自编园</script>',field:()=> '停留下界',reason:()=> '目标停留没有按要求增加'})}))}
const job={protocol_version:3,generated_count:2,accepted_count:1,rejected_count:1,isolated_count:0,can_preview:true,rule_version:'revision-test',base_revision:4,returned:true,parsed:true,local_diagnostic:{replayable:true},proposals:[{title:'第一项停留增加',first_start:'10:00',changes:[{activity_id:'a',field:'stay_min',before:40,after:60}]}],decisions:[{proposal_id:'p1',status:'REJECTED',reason:'REVISION_NOT_LONGER',field:'proposals[1].activities[0].stay_min',stage:'INTENT',rule_id:'REVISION_NOT_LONGER'}]}
const html=await render(job)
assert(html.includes('40 → 60 分钟') && html.includes('10:00') && html.includes('到达时间待交通核实'))
assert(html.includes('&lt;script&gt;') && !html.includes('<script>'))
assert(html.includes('本次修改诊断') && html.includes('proposals[1].activities[0].stay_min'))
assert(!(html.match(/button[^>]*disabled/)))
assert((await render({...job,can_preview:false})).match(/button[^>]*disabled/))
const failed=await render({...job,reason:'REVISION_ALL_REJECTED',proposals:[],accepted_count:0,local_diagnostic:{replayable:false}})
assert(failed.includes('这次修改未采用，原版保留') && failed.includes('不可用，不保存不安全内容'))
console.log('PASS RevisionReview: computed deltas, fixed anchor, escaped text, stored preview, safe diagnostics')
