import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileScript} from 'vue/compiler-sfc'
import ts from 'typescript'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const {descriptor}=parse(readFileSync(new URL('../src/components/AutomaticPlanning.vue',import.meta.url),'utf8'))
const setup=compileScript(descriptor,{id:'automatic',inlineTemplate:true,templateOptions:{ssr:true,cssVars:[]}})
const script=ts.transpileModule(setup.content,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace(/from ['"]([^'"]+)['"]/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const component=(await import('data:text/javascript;base64,'+Buffer.from(script).toString('base64'))).default
const task={status:'RUNNING',stage:'LOGIN_CHECK',login_state:'LOGIN_CHECK',research_attempted:false,changes:[],sources:[],limits:{search:3,detail:6,model:13,connect:1},search_count:0,candidate_count:0,unique_candidate_count:0,new_body_count:0,body_attempts:0,cache_source_count:0,accepted_source_count:0,duplicate_body_count:0,query_progress:[],generated:false,coverage:null}
async function render(t){return renderToString(createSSRApp(component,{plan:{destination:'合成北区',session_id:'fixture',draft:{days:7,activities:[]},combination_candidates:[],automatic_task:{...task,...t},job:{can_preview:true,proposals:[{title:'来源有限的玩法',reason:'合成参考',activities:[],unknowns:['交通未知']}]}},busy:false}))}
assert((await render({})).includes('正在检查小红书登录'))
const login=await render({stage:'LOGIN_REQUIRED',login_state:'LOGIN_REQUIRED'})
assert(login.includes('小红书官方页面完成正常登录')&&login.includes('同一个任务'))
const result=await render({status:'PARTIAL',stage:'RESULT',generated:true,login_state:'LOGIN_AUTHENTICATED',research_attempted:true,new_body_count:2,body_attempts:2,search_count:3,candidate_count:6,unique_candidate_count:2,accepted_source_count:1,duplicate_body_count:1,coverage:{meaning:'材料覆盖不证明可行性',activity_count:2,gaps:[{key:'TRANSPORT',label:'交通衔接未知'}]},query_progress:[{search_number:1,observed_candidates:2,body_reads:2,new_facts:2}]})
assert(result.includes('资料有限，先看局部建议')&&result.includes('采用这版建议'))
assert(result.includes('搜索 3 次')&&result.includes('观察候选 6 条')&&result.includes('去重后 2 个'))
assert(result.includes('继续补充研究')&&result.includes('交通衔接未知')&&result.includes('独立作者仍未核实'))
assert(result.includes('每轮研究进展')&&result.includes('新增2条去重后的合格引用'))
const ready=await render({status:'COMPLETED',generated:true,stage:'RESULT',coverage:{meaning:'仅材料覆盖',activity_count:8,gaps:[]}})
assert(ready.includes('先看看这几种玩法')&&!ready.includes('继续补充研究'))
console.log('PASS AutomaticPlanning: local/login/progress, partial proposal, actual counts, gaps, explicit supplement')
