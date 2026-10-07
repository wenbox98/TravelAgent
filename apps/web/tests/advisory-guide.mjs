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

const reviewedPlan={...plan,job:{status:'FAILED',generated_count:1,accepted_count:0,rejected_count:1,reason:'OLD_FAILURE',proposals:[],decisions:[],protocol_version:4,local_diagnostic:{replayable:true}},local_guide_review:{rule_version:'fixture-rule',can_preview:true,summary:{accepted_count:1,rejected_count:0,proposals:[{title:'原回复的派生建议',reason:'空住宿金额仍未知'}],decisions:[]}}}
const reviewed=await renderToString(createSSRApp({ssrRender,data:()=>({guide:{...guide,local_revalidation:true},form,plan:reviewedPlan,busy:false,editing:false,composing:false,selected:[],error:'',exported:'',money:()=> '未知'})}))
assert(reviewed.includes('当时校验接纳 0，拒绝 1') && reviewed.includes('接纳 1，拒绝 0'))
assert(reviewed.includes('不是模型重新回答') && reviewed.includes('LOCAL_REVALIDATION'))
assert(!reviewed.includes('只规范化') && !reviewed.includes('LOCAL_REVALIDATION / NORMALIZED'))
assert(reviewed.includes('预览本地复核建议') && reviewed.includes('用已保存回复本地复核（不联网）'))
console.log('PASS AdvisoryGuide: original failure and independent local revalidation remain distinguishable')

const assessment={status:'PARTIAL',label:'局部建议：天数覆盖尚不完整',content_limited:true,coverage:{status:'PARTIAL',missing_days:[2],outside_days:[],warnings:['轻松需求仍集中在一天'],meaning:'逐日覆盖不表示现实可行性已核实',days:[{day:1,kind:'ACTIVITIES',label:'已有项目建议',reason:'',activity_ids:['fixture']},{day:2,kind:'GAP',label:'资料或安排待补',reason:'尚未决定如何安排，不是完整的一天',activity_ids:[]}]},materials:[{activity_id:'fixture',level:'NAME_ONLY',label:'只有名称线索，具体玩法不足',roles:[],excerpts:[]}]}
const partial=await renderToString(createSSRApp({ssrRender,data:()=>({guide:{...guide,assessment},form,plan,busy:false,editing:false,composing:false,selected:[],error:'',exported:'',money:()=> '未知'})}))
assert(partial.includes('局部建议：天数覆盖尚不完整') && partial.includes('第 2 天：资料或安排待补'))
assert(partial.includes('只有名称线索，具体玩法不足') && partial.includes('轻松需求仍集中在一天'))
assert(partial.includes('说明这一天的取舍') && partial.includes('资料缺口不会自动算作完整安排'))
const resting={...assessment,coverage:{...assessment.coverage,status:'COVERED',missing_days:[],days:[assessment.coverage.days[0],{day:2,kind:'REST',label:'留作休息',reason:'留给恢复体力，不增加项目',activity_ids:[]}]}}
const rested=await renderToString(createSSRApp({ssrRender,data:()=>({guide:{...guide,assessment:resting},form,plan,busy:false,editing:false,composing:false,selected:[],error:'',exported:'',money:()=> '未知'})}))
assert(rested.includes('第 2 天：留作休息') && !rested.includes('第 2 天：资料或安排待补'))
assert(rested.includes('只有名称线索，具体玩法不足'))
console.log('PASS AdvisoryGuide: missing days, deliberate rest and name-only material remain distinct')

const context={backgrounds:[{context_id:'authored',scope:'GROUP_BACKGROUND',subject:'东桥片区',text:'适合慢逛，但雨天不推荐',reference_kind:'AUTHOR_PROPOSED_PLAN',conditions:['春季；作者未亲历'],activity_names:['甲巷','乙步道'],limitation:'不证明每站特色',citation_id:'fixture-reference'}],uses:[{context_id:'authored',reason:'按兴趣二选一，停留可调整'}],supplements:[{citation_id:'supplement',text:'关系未明',reference_kind:'UNKNOWN',conditions:[],reason:'不作地点特色依据'}],source_count:1}
const scoped=await renderToString(createSSRApp({ssrRender,data:()=>({guide:{...guide,context,assessment},form,plan,busy:false,editing:false,composing:false,selected:[],error:'',exported:'',money:()=> '未知'})}))
for(const text of ['这组玩法的背景与取舍','整体背景','春季；作者未亲历','雨天不推荐','不证明每站特色','未关联的来源补充','AI取舍建议','只有名称线索，具体玩法不足','来自 1 个来源']) assert(scoped.includes(text),text)
console.log('PASS AdvisoryGuide: scoped background, conditions, independent name-only support and AI advice remain separate')
