import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/OperationPanel.vue',import.meta.url),'utf8'))
const compiled=compileTemplate({source:descriptor.template.content,filename:'OperationPanel.vue',id:'operation',ssr:true,cssVars:[]})
assert.deepEqual(compiled.errors,[])
const code=compiled.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
async function render(operation, editing=false){return renderToString(createSSRApp({ssrRender,data:()=>({plan:{operation,reuse_options:[]},busy:false,editing,unlimitedModel:true,planning:true,research:false,maps:true,limits:{model:2,map_place:2,map_route:1,hours:24},names:{model:'模型',map_place:'地点'},configuration:s=>s,availability:s=>s,permitState:s=>s,chosen:null})}))}
const empty={history:[],current:null,active:false,status:'NOT_AUTHORIZED',model_configuration:'CONFIGURED_NOT_VERIFIED',map_configuration:'NOT_CONFIGURED',research_status:'NOT_AUTHORIZED',map_status:'NOT_CONFIGURED'}
const html=await render(empty,true)
assert(html.includes('尚未授权') && html.includes('确认以上用途与调用上限'))
assert(html.includes('不会立刻发送') && html.includes('api.deepseek.com') && html.includes('restapi.amap.com'))
assert(!html.includes('P06') && !html.includes('continuation_id'))
const grant={used:{model:2,map_place:2},remaining:{model:0,map_place:0},limits:{model:2,map_place:2},current:true,closed:true,expired:false,recipients:['<script>authored</script>']}
const closed=await render({...empty,history:[grant],current:grant,cumulative_used:grant.used,status:'CLOSED'},true)
assert(closed.includes('明确追加额度') && closed.includes('模型累计 2') && closed.includes('可用 0'))
assert(closed.includes('失败或超时') && !closed.includes('关闭本次许可，保留记录'))
assert(closed.includes('&lt;script&gt;') && !closed.includes('<script>'))
console.log('PASS OperationPanel: explicit consent, recipients, quotas, append, closed history, safe text')
