<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import {transportLabel,type Draft,type PlanView} from '../planning-api'
const props=defineProps<{plan:PlanView;busy:boolean}>()
const emit=defineEmits<{save:[extra:{draft:Draft}];editing:[value:boolean]}>()
const copy=<T,>(v:T):T=>JSON.parse(JSON.stringify(v)) as T
const editing=ref(false),submitted=ref(false),base=ref(0),draft=ref(copy(props.plan.draft))
const storage=()=>`ta-condition-draft:${props.plan.session_id}`
const values=(d:Draft)=>({days:d.days,transport:d.transport,driving:d.driving,pace:d.pace,people:d.trip_budget.people,target_fen:d.trip_budget.target_fen})
function remember(){if(editing.value)localStorage.setItem(storage(),JSON.stringify({revision:base.value,values:values(draft.value)}))}
function cancel(){localStorage.removeItem(storage());editing.value=false;submitted.value=false}
function restore(){try{const saved=JSON.parse(localStorage.getItem(storage())||'null');if(saved){draft.value=copy(props.plan.draft);Object.assign(draft.value,{days:saved.values.days,transport:saved.values.transport,driving:saved.values.driving,pace:saved.values.pace});draft.value.trip_budget.people=saved.values.people;draft.value.trip_budget.target_fen=saved.values.target_fen;transport();base.value=saved.revision;editing.value=true}}catch{}}
const current=computed(()=>props.plan.draft)
const stale=computed(()=>editing.value&&base.value!==props.plan.revision)
const drive=(v:string)=>({YES:'愿意自驾',NO:'不自驾',UNKNOWN:'驾驶意愿未定'}[v]||'未定')
const optional=computed(()=>[
 !current.value.days&&'天数未定：以后用于缩小玩法选择面，当前可先研究。',
 current.value.transport==='UNKNOWN'&&'交通未定：以后比较跨度与衔接，当前可先研究；核实具体路段时才需选择方式。',
 !current.value.inputs.depart_at&&'日期未定：以后检查时令、开放与班次适用性，不阻止初步建议。',
 !current.value.trip_budget.people&&'人数未定：以后计算人均预算，不阻止研究。',
 current.value.trip_budget.target_fen===null&&'预算未定：以后比较花费与取舍，不代表预算为零。',
 current.value.walking_allowed===null&&'步行意愿未定：不会把未回答当作拒绝，可之后补充。',
].filter(Boolean))
watch(editing,v=>emit('editing',v),{flush:'sync'})
watch(()=>props.plan,(v)=>{if(submitted.value&&JSON.stringify(values(v.draft))===JSON.stringify(values(draft.value)))cancel()},{deep:true})
watch(draft,remember,{deep:true})
watch(()=>props.plan.session_id,()=>{editing.value=false;submitted.value=false;restore()},{immediate:true})
onUnmounted(()=>emit('editing',false))
function edit(){draft.value=copy(props.plan.draft);base.value=props.plan.revision;submitted.value=false;editing.value=true;remember()}
function save(){if(stale.value||props.busy)return;submitted.value=true;emit('save',{draft:copy(draft.value)})}
function transport(){if(draft.value.transport==='SELF_DRIVE'){draft.value.driving='YES';draft.value.inputs.mode='DRIVING'}else{draft.value.inputs.mode=({PUBLIC_TRANSIT:'TRANSIT',WALKING:'WALKING'} as Record<string,string>)[draft.value.transport]||'UNKNOWN'}}
function driving(){if(draft.value.driving==='NO'&&draft.value.transport==='SELF_DRIVE'){draft.value.transport='UNKNOWN';draft.value.inputs.mode='UNKNOWN'}}
</script>
<template>
 <section class="card trip-conditions" aria-label="本次旅行条件">
  <h2>{{plan.automatic_task?.understanding?.provisional?'本次暂定条件（等待模型理解）':'本次已生效条件'}}</h2><p>仅用于这次旅行；下面的当前值为准，旧消息、来源条件和其他旅行不会成为长期偏好。</p>
  <p>到达方式：{{({AIR:'飞机',RAIL:'铁路',ROAD:'道路交通',UNKNOWN:'未定'} as Record<string,string>)[current.arrival_transport||'UNKNOWN']}}；本地移动：{{transportLabel(current.transport)}}；租车：{{current.rental==='YES'?'愿意租车':current.rental==='NO'?'不租车':'未定'}}。到达方式与当地交通分别保存，机场、日期与私人起点不推断。</p>
  <dl><dt>目的区域</dt><dd>{{plan.destination}}</dd><dt>可用天数</dt><dd>{{current.days?`${current.days}天`:'未定'}}</dd><dt>交通意向</dt><dd>{{transportLabel(current.transport)}} · {{drive(current.driving)}}</dd><dt>节奏</dt><dd>{{current.pace==='RELAXED'?'轻松一些':'未定'}}</dd><dt>人数与参考预算</dt><dd>{{current.trip_budget.people?`${current.trip_budget.people}人`:'人数未定'}} · {{current.trip_budget.target_fen===null?'预算未定':`总预算 ${(current.trip_budget.target_fen/100).toFixed(2)} 元`}}</dd><dt>日期与固定条件</dt><dd>{{current.inputs.depart_at||'日期未定'}}；{{current.start_constraint==='FIXED'?`首项固定 ${current.inputs.activity_start||'待核对'}`:'不要求精确开始时间'}}；{{current.return_deadline?`必须在 ${current.return_deadline} 返回`:'无已确认的返回硬截止'}}；{{current.activities.filter(a=>a.locked||a.locked_start).length}}个锁定项目</dd></dl>
  <details v-if="optional.length"><summary>可暂未定的条件及补充原因（不阻止首次研究）</summary><p v-for="value in optional" :key="String(value)">{{value}}</p></details>
  <p>资料是否足够、系统能否启动在研究进展中单独说明，不等于你漏填了条件。</p>
  <button v-if="!editing" class="quiet" :disabled="busy" @click="edit">修改本次条件</button>
  <form v-else @submit.prevent="save" aria-label="未提交的条件草稿">
   <h3>未提交的条件草稿</h3><p>保存前不会用于研究或模型输入；取消只撤回这里的编辑，不改已生效条件或采用版。</p>
   <p v-if="stale" role="alert">已保存条件已变化，请取消草稿后基于最新条件修改。</p>
   <fieldset :disabled="busy||stale"><label>可用天数（可留空）<input type="number" min="1" max="90" :value="draft.days??''" @input="draft.days=($event.target as HTMLInputElement).value===''?null:Number(($event.target as HTMLInputElement).value)" /></label>
    <label>交通意向<select v-model="draft.transport" @change="transport"><option value="UNKNOWN">未定</option><option value="SELF_DRIVE">自驾</option><option value="PUBLIC_TRANSIT">公共交通</option><option value="WALKING">步行</option><option value="LOCAL_SERVICE">比较当地服务</option></select></label>
    <label>驾驶意愿<select v-model="draft.driving" @change="driving"><option value="UNKNOWN">未定</option><option value="YES">愿意</option><option value="NO">不愿意</option></select></label>
    <label>节奏<select v-model="draft.pace"><option value="UNKNOWN">未定</option><option value="RELAXED">轻松一些</option></select></label>
    <label>人数（可留空）<input type="number" min="1" max="100" :value="draft.trip_budget.people??''" @input="draft.trip_budget.people=($event.target as HTMLInputElement).value===''?null:Number(($event.target as HTMLInputElement).value)" /></label>
    <label>总参考预算（元，可留空）<input type="number" min="0" max="1000000" step="0.01" :disabled="draft.trip_budget.target_locked" :value="draft.trip_budget.target_fen===null?'':draft.trip_budget.target_fen/100" @input="draft.trip_budget.target_fen=($event.target as HTMLInputElement).value===''?null:Math.round(Number(($event.target as HTMLInputElement).value)*100)" /></label>
   </fieldset><p>修改驾驶意愿为不愿意会撤回冲突的自驾选择，交通重新保持未定。已锁定预算保留。</p><button :disabled="busy||stale">保存本次条件（仅本地）</button><button type="button" class="quiet" :disabled="busy" @click="cancel">取消条件编辑</button>
  </form>
  <details><summary>历史记录与采用版</summary><p>对话区保留过去的输入和失败，不代表每句话仍生效。来源引用描述作者条件，采用版是另一个已保存版本，以上当前条件用于下一次操作。</p><p v-if="plan.adopted">已采用版：{{plan.adopted.days?`${plan.adopted.days}天`:'天数未定'}} · {{transportLabel(plan.adopted.transport)}} · {{plan.adopted.activities.length}}个项目；本地修改不会覆盖它。</p><p v-else>尚无采用版；旧旅行需从历史旅行列表主动打开。</p></details>
 </section>
</template>
<style scoped>dl{display:grid;grid-template-columns:8em 1fr;gap:.5em}dd{margin:0}dt{color:#566}fieldset{display:flex;gap:1em;flex-wrap:wrap}label{display:grid;gap:.3em}h3{margin-top:1em}</style>
