import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/KnowledgeLibrary.vue',import.meta.url),'utf8'))
const compiled=compileTemplate({source:descriptor.template.content,filename:'KnowledgeLibrary.vue',id:'knowledge',ssr:true,cssVars:[]})
assert.deepEqual(compiled.errors,[])
const code=compiled.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
const card={card_id:'fixture',kind:'PLACE_LEAD',title:'<script>自编地点</script>',text:'仅提及',conditions:['仅国庆自驾参考'],unknowns:['当前开放未知'],review_method:'MENTION_LOCATED_ONLY',review_scope:'NAME_ONLY',test_input:true,spatial_status:'UNKNOWN',attested_at:'2026-01-01',raw_availability:'USER_CLEARED',sources:[]}
const html=await renderToString(createSSRApp({ssrRender,data:()=>({retention:'PERSISTENT',opened:true,result:{cards:[card],source_count:1,bounded:false},plan:{adopted:null,draft:{activities:[]}},busy:false,waiting:false,query:'',region:'',kind:'',since:'',includeTest:false,selected:[],options:[],sourceTrip:'',preview:null,pending:'',ack:false,message:'',labels:{PLACE_LEAD:'地点线索'},roles:{MENTION_LOCATED_ONLY:'仅核对名称提及'}})}))
assert(html.includes('仅国庆自驾参考') && html.includes('原文已由用户清理') && html.includes('开发测试资料'))
assert(html.includes('删除所选旅行知识') && html.includes('预览清理所选原文缓存') && html.includes('向量检索未实现'))
assert(html.includes('&lt;script&gt;') && !html.includes('<script>自编'))
console.log('PASS KnowledgeLibrary: separate cleanup, provenance, conditions, no vector claim, safe text')
