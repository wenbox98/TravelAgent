import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse,compileTemplate,compileScript} from 'vue/compiler-sfc'
import ts from 'typescript'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const read=name=>readFileSync(new URL('../src/components/'+name+'.vue',import.meta.url),'utf8')
assert(read('PlanningPanel').includes('knowledge_first: !demo'))
assert(read('PlanningPanel').includes('<LocalMaterials'))
assert(!read('OperationPanel').includes('reuse_options'))
const {descriptor}=parse(read('LocalMaterials'))
const compiled=compileTemplate({source:descriptor.template.content,filename:'LocalMaterials.vue',id:'materials',ssr:true,cssVars:[]})
assert.deepEqual(compiled.errors,[])
const code=compiled.code.replace(/from ['"]([^'"]+)['"]/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
async function render(options=[],can_select=true,opened=true){return renderToString(createSSRApp({ssrRender,components:{KnowledgeLibrary:{template:'<p>资料卡入口</p>'}},data:()=>({plan:{session_id:'authored',local_materials:{can_select,include_test:false,message:'本地选择'},draft:{activities:[]},reuse_options:options},busy:false,opened,chosen:options[0],choice:'',selected:[]})}))}
const empty=await render()
assert(empty.includes('先用已有资料')&&empty.includes('资料卡入口')&&empty.includes('没有符合当前目的地'))
assert(empty.includes('主动查找新玩法')&&empty.includes('不需要外部许可'))
assert(!empty.includes('knowledge_mode'))
const option={key:'fixture',test_input:true,activities:[{activity_id:'same-name',name:'合成园',timing_origin:'AI_PROPOSED',spatial_status:'UNKNOWN',stay_min:30,stay_max:60}]}
const found=await render([option])
assert(found.includes('预览所选历史活动')&&found.includes('历史 AI 建议')&&found.includes('范围待确认'))
assert(found.includes('开发测试资料')&&found.includes('不复制旧偏好'))
const nonempty=await render([option],false)
assert(nonempty.includes('已有草稿不会被选材覆盖')&&!nonempty.includes('预览所选历史活动'))
const collapsed=await render([],false,false)
assert(collapsed.includes('查看或修改选材')&&!collapsed.includes('资料卡入口'))
// Mount the actual setup too: a restored nonempty trip starts collapsed.
const setup=compileScript(descriptor,{id:'materials',inlineTemplate:true,templateOptions:{ssr:true}})
const script=ts.transpileModule(setup.content.replace(/import KnowledgeLibrary from '\.\/KnowledgeLibrary.vue'/,"const KnowledgeLibrary={template:'<p>资料卡入口</p>'}"),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace(/from ['"]([^'"]+)['"]/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const component=(await import('data:text/javascript;base64,'+Buffer.from(script).toString('base64'))).default
const restored=await renderToString(createSSRApp(component,{plan:{session_id:'restored',draft:{activities:[option.activities[0]]},local_materials:{can_select:false}},busy:false}))
assert(restored.includes('查看或修改选材')&&!restored.includes('资料卡入口'))
console.log('PASS LocalMaterials: real default create contract, three paths, no permit, empty/history/locked/collapsed states')
