// Actual shared Vue template, no map persistence or external requests.
import {readFileSync} from 'node:fs'
import assert from 'node:assert/strict'
import {parse, compileTemplate} from 'vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'
const source=readFileSync(new URL('../src/components/PlaceChoices.vue',import.meta.url),'utf8')
const {descriptor}=parse(source)
const result=compileTemplate({source:descriptor.template.content,filename:'PlaceChoices.vue',id:'place',ssr:true,cssVars:[]})
assert.deepEqual(result.errors,[])
const code=result.code.replace(/from "([^"]+)"/g,(_,name)=>`from "${import.meta.resolve(name)}"`)
const {ssrRender}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
const candidates=Array.from({length:4},(_,i)=>({candidate_id:String(i),name:'虚构云台园'+i,cityname:i<2?'地区甲':'地区乙',adname:'虚构分区',object_type:'SCENIC',type:'合成',address:'虚构位置'}))
const place={place_id:'origin',name:'云台园',region:'地区甲',candidates,confirmed:null}
const render=(places,expanded={})=>renderToString(createSSRApp({ssrRender,data:()=>({places,expanded,busy:false,canQuery:true,sameReturn:true,synthetic:true,mapLabel:v=>v,recommended:()=>false,relation:()=> 'SAME_OBJECT',emit:()=>{}})}))
const before=await render([place])
assert.equal((before.match(/选择这个地点/g)||[]).length,4)
const confirmed={...place,confirmed:candidates[0]}
const after=await render([confirmed,{...confirmed,place_id:'return'}])
assert(after.includes('重新选择') && !after.includes('虚构云台园1'))
assert(after.includes('返程路段保留') && !after.includes('选择这个地点'))
const opened=await render([confirmed],{origin:true})
assert.equal((opened.match(/选择这个地点/g)||[]).length,4)
assert(!opened.includes('https://') && !source.includes('localStorage'))
console.log('PASS PlaceChoices: 4 choices, confirmation collapse, zero-query reopen, shared return identity, no map persistence')
