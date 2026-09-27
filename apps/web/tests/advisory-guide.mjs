import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/AdvisoryGuide.vue',import.meta.url),'utf8'))
const compiled=compileTemplate({source:descriptor.template.content,filename:'AdvisoryGuide.vue',id:'guide',ssr:true,cssVars:[]})
assert.deepEqual(compiled.errors,[])
const code=compiled.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
const budget={known_total:{min_fen:94000,max_fen:138000},per_person:null,lines:[],missing_categories:['往返交通'],paid_fen:0,target_note:null}
const activity={activity_id:'fixture',day:1,period:'时段自定',name:'<script>合成A</script>',highlight:'只核对名称提及',stay:'停留待选',rest:'休息自定',conditions:['仅测试'],locked_start:null}
const guide={walking:{state:'UNKNOWN',label:'步行意愿未定'},walking_suggestion:null,budget_context:{known_conditions:['2人','2天','1晚','1间房'],pending_conditions:[]},summary:'交通未定',available:true,title:'有限建议',reason:'一个项目也可开始',activities:[activity],dining:[{day:1,window:'午餐',text:'在已选片区解决'}],lodging:{text:'不适用，不是免费酒店',areas:[]},budget,budget_difference:null,assumptions:[],tradeoffs:[],unknowns:['路程未核实']}
const form={inputs:{activity_start:null},start_constraint:'FLEXIBLE',activities:[activity],guide:{lodging:{strategy:'NOT_APPLICABLE'}},trip_budget:{lines:[],target_fen:null},spatial:{intent:'UNDECIDED'}}
const plan={draft:form,combination_candidates:[activity],model_available:false,model_reason:'本次额度已用完',adopted:form,job:null,timeline:[],gaps:[],differences:[]}
const html=await renderToString(createSSRApp({ssrRender,data:()=>({guide,form,plan,busy:false,editing:false,composing:false,selected:[],error:'',exported:'',money:v=>v.min_fen===null?'未知':`${v.min_fen/100}–${v.max_fen/100} 元`})}))
assert(html.includes('首项钟点未定也可以先看建议') && html.includes('940–1380 元'))
assert(html.includes('停留待选') && html.includes('休息自定') && html.includes('尚未计入类别：往返交通'))
assert(html.includes('不适用，不是免费酒店') && html.includes('本地修改和导出仍可使用'))
assert(html.includes('&lt;script&gt;合成A&lt;/script&gt;') && !html.includes('<script>合成A'))
assert.match(html, /<button class="quiet">导出采用版 Markdown<\/button>/)
assert.match(html, /<button>采用这版建议攻略<\/button>/)
console.log('PASS AdvisoryGuide: no required clock, unknown cost, limited knowledge, usable local actions, safe rendering')

assert(html.includes('步行意愿未定') && html.includes('已知条件：2人、2天、1晚、1间房'))
assert(html.includes('人数、天数与房晚条件已明确；实际价格仍待核实'))
