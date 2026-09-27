<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { request } from '../api'
import type { PlanView, Draft, BudgetLine, GuideView } from '../planning-api'
const props = defineProps<{plan:PlanView;busy:boolean}>()
const emit = defineEmits<{action:[action:string,extra:Record<string,unknown>]}>()
const copy=<T,>(v:T):T=>JSON.parse(JSON.stringify(v)) as T
const editing=ref(false),composing=ref(false),selected=ref<string[]>([]),error=ref(''),exported=ref('')
const form=ref<Draft>(copy(props.plan.draft))
const guide=computed(()=>props.plan.guide_view as GuideView)
watch(()=>props.plan,(v)=>{form.value=copy(v.draft);selected.value=v.draft.activities.map(a=>a.activity_id)},{deep:true,immediate:true})
watch(()=>props.plan.session_id,()=>{editing.value=false;composing.value=false;exported.value='';error.value=''})
const money=(v:{min_fen:number|null;max_fen:number|null})=>v.min_fen===null?'未知':`${(v.min_fen/100).toFixed(2)}–${((v.max_fen??v.min_fen)/100).toFixed(2)} 元`
const sign=(v:number)=>`${v>0?'+':''}${(v/100).toFixed(2)}`
const number=(e:Event)=>{const s=(e.target as HTMLInputElement).value;return s===''?null:Number(s)}
function walking(e:Event){const value=(e.target as HTMLSelectElement).value;form.value.walking_allowed=value==='UNKNOWN'?null:value==='ALLOWED';form.value.walking_origin='USER_EXPLICIT';save()}
function save(){emit('action','save',{draft:copy(form.value)})}
function reorder(index:number,offset:number){const to=index+offset;if(to<0||to>=selected.value.length)return;[selected.value[index],selected.value[to]]=[selected.value[to],selected.value[index]]}
function price(line:BudgetLine,key:'min_fen'|'max_fen',e:Event){const n=number(e);line.unit_amount[key]=n===null?null:Math.round(n*100);if(line.unit_amount.min_fen===null||line.unit_amount.max_fen===null)return;if(line.unit_amount.min_fen>line.unit_amount.max_fen)return;line.basis='USER_BUDGET_TARGET';line.status='ESTIMATED';save()}
function basis(line:BudgetLine,e:Event){line.basis=(e.target as HTMLSelectElement).value;line.status=line.basis==='USER_BUDGET_TARGET'?'ESTIMATED':'UNKNOWN';if(line.status==='UNKNOWN'){line.unit_amount.min_fen=null;line.unit_amount.max_fen=null;save()}}
function time(e:Event){form.value.inputs.activity_start=(e.target as HTMLInputElement).value||null;save()}
function stay(i:number,key:'stay_min'|'stay_max',e:Event){form.value.activities[i][key]=number(e);const a=form.value.activities[i];if((a.stay_min===null)===(a.stay_max===null)&&!(a.stay_min!==null&&a.stay_max!==null&&a.stay_min>a.stay_max))save()}
async function download(){error.value='';try{const v=await request<{filename:string;markdown:string}>(`/api/v1/preview/planning/${props.plan.session_id}/guide-export`);const u=URL.createObjectURL(new Blob([v.markdown],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=v.filename;a.click();URL.revokeObjectURL(u);exported.value='已从当前采用版导出 Markdown；没有联网查询。'}catch(e){error.value=e instanceof Error?e.message:'导出失败，采用版保留'}}
</script>
<template>
  <section class="card advisory-guide">
    <div class="guide-title"><div><p class="eyebrow">先选玩法，时间留有弹性</p><h2>建议攻略</h2></div><button class="quiet" :disabled="busy" @click="editing=!editing">{{editing?'收起条件':'修改本次条件'}}</button></div>
    <p>{{guide.summary}}。{{form.inputs.activity_start ? (form.start_constraint==='LOCKED'?'首项锁定 ':'首项大约 ')+form.inputs.activity_start : '首项钟点未定也可以先看建议。'}}</p>
    <p>{{guide.walking.label}}。{{guide.walking_suggestion}}</p>
    <p v-for="note in form.hard_notes||[]" :key="note" class="notice">{{note}}。可展开项目确认预约；未确认前不能判断是否衔接。</p><fieldset v-if="editing" :disabled="busy"><legend>本次条件（可以没想好）</legend><div class="grid">
      <label>玩几天<input :value="form.days??''" type="number" min="1" max="90" placeholder="未定" @change="form.days=number($event);save()" /></label>
      <label>交通意向<select v-model="form.transport" @change="save"><option value="UNKNOWN">还没想好</option><option value="PUBLIC_TRANSIT">公共交通</option><option value="WALKING">步行</option><option value="SELF_DRIVE">自己驾驶</option><option value="LOCAL_SERVICE">比较当地服务</option></select></label>
<label>步行意愿<select :value="guide.walking.state" @change="walking"><option value="UNKNOWN">没想好，允许先给待选择的建议</option><option value="ALLOWED">明确允许步行</option><option value="DECLINED">明确不接受步行</option></select></label>
      <label>首项大概钟点（可留空）<input type="time" :value="form.inputs.activity_start||''" @change="time" /></label>
      <label>首项时间性质<select v-model="form.start_constraint" @change="save"><option value="FLEXIBLE">弹性偏好</option><option value="LOCKED">明确必须遵守</option></select></label>
      <label>必须返回时间（仅有硬要求时填）<input type="time" :value="form.return_deadline||''" @change="form.return_deadline=($event.target as HTMLInputElement).value||null;save()" /></label>
      <label>往返范围<select v-model="form.inputs.planning_scope" @change="save"><option value="ACTIVITY_WINDOW">到达与返程自行安排</option><option value="DOOR_TO_DOOR">主动扩展为门到门</option></select></label>
      <label>游玩范围<select v-model="form.spatial.intent" @change="save"><option value="UNDECIDED">先比较，范围未定</option><option value="CITY_CORE">只在市区</option><option value="CITY_AND_SURROUNDINGS">市区和周边</option><option value="REGIONAL">区域旅行</option></select></label>
    </div><p>锁定预约在项目里单独填写；未知路程、休息和接驳不会按零计算。</p></fieldset>
    <div class="guide-title"><h3>{{guide.title}}</h3><button class="quiet" :disabled="busy" @click="composing=!composing">{{composing?'收起组合':'修改活动组合'}}</button></div><p>{{guide.reason}}</p>
    <div v-if="composing" class="combination"><p>从已经提供的候选中增删或替换；预览不覆盖采用版。范围未知可暂定，明确不匹配的保留为备选。</p>
      <label v-for="a in plan.combination_candidates" :key="a.activity_id" class="check"><input v-model="selected" type="checkbox" :value="a.activity_id" :disabled="busy || !!a.locked || !!a.locked_start || (form.spatial.intent==='CITY_CORE' && a.spatial_status==='MISMATCH')" />{{a.name}} <small>{{a.spatial_status==='MATCH'?'来源支持范围':a.spatial_status==='MISMATCH'?'范围备选':'范围待核实'}}</small></label>
      <ol><li v-for="(id,i) in selected" :key="id">{{plan.combination_candidates.find(a=>a.activity_id===id)?.name}} <button class="quiet" :disabled="busy||i===0" @click="reorder(i,-1)">上移</button> <button class="quiet" :disabled="busy||i===selected.length-1" @click="reorder(i,1)">下移</button></li></ol>
      <button :disabled="busy||!selected.length" @click="emit('action','preview_combination',{activity_ids:selected});composing=false">预览这个组合</button>
    </div>
    <p v-if="!guide.available">先从本机资料选一个感兴趣的项目；一个项目也可以开始，不要求先确定全部时刻。</p>
    <article v-for="(a,i) in guide.activities" :key="a.activity_id" class="activity"><h4>第 {{a.day}} 天 · {{a.period}} · {{a.name}}</h4><p>{{a.highlight}}</p><p>{{a.stay}}；{{a.rest}}。{{a.locked_start?'预约锁定 '+a.locked_start+'。':''}}</p>
      <details><summary>修改停留、日段或预约</summary><fieldset :disabled="busy"><div class="grid">
        <label>第几天<input v-model.number="form.activities[i].day" type="number" min="1" max="90" @change="save" /></label>
        <label>建议日段<select v-model="form.activities[i].period" @change="save"><option value="UNDECIDED">自定</option><option value="MORNING">上午</option><option value="AFTERNOON">午后</option><option value="EVENING">傍晚</option></select></label>
        <label>停留最少（分钟）<input :value="form.activities[i].stay_min??''" type="number" min="0" @change="stay(i,'stay_min',$event)" /></label>
        <label>停留最多（分钟）<input :value="form.activities[i].stay_max??''" type="number" min="0" @change="stay(i,'stay_max',$event)" /></label>
        <label>明确预约（可留空）<input :value="form.activities[i].locked_start||''" type="time" @change="form.activities[i].locked_start=($event.target as HTMLInputElement).value||null;save()" /></label>
        <label class="check"><input v-model="form.activities[i].locked" type="checkbox" @change="save" />锁定保留这个项目</label>
      </div></fieldset></details>
      <details v-if="a.conditions.length"><summary>来源条件</summary><p v-for="c in a.conditions" :key="c">{{c}}</p></details>
    </article>
    <div class="actions"><button :disabled="busy||!plan.model_available" @click="emit('action','suggest',{})">让AI给出建议攻略</button><button v-if="plan.job && ['QUEUED','RUNNING'].includes(plan.job.status)" class="quiet" :disabled="busy" @click="emit('action','cancel_job',{})">停止本次生成</button></div>
    <p v-if="!plan.model_available">{{plan.model_reason}} 本地修改和导出仍可使用。</p>
    <p v-if="plan.job" role="status">{{['QUEUED','RUNNING'].includes(plan.job.status)?'正在生成建议，原采用版保留。':`原返回 ${plan.job.generated_count??0} 个提议；当时校验接纳 ${plan.job.accepted_count}，拒绝 ${plan.job.rejected_count}。`}}</p>
    <p v-if="plan.job?.reason" class="warning">本次未完成可用提议，已有资料保留；没有自动重试。</p>
    <p v-if="plan.job?.proposals.length && plan.job.can_preview===false" class="notice">历史提议仅供查看：输入或版本已变，当前不能直接采用。既有资料和本地修改保留。</p><details v-if="plan.job?.proposals.length" :open="plan.job.request_revision===plan.revision"><summary>比较AI建议与取舍</summary><article v-for="(p,i) in plan.job.proposals" :key="i"><h4>{{p.title}}</h4><p>{{p.reason}}</p><ul><li v-for="a in p.activities" :key="a.activity_id">第 {{a.day}} 天 · {{plan.combination_candidates.find(c=>c.activity_id===a.activity_id)?.name||'已有候选'}} · {{a.stay_min===null?'停留待选':`建议 ${a.stay_min}–${a.stay_max} 分钟`}}</li></ul><p v-for="t in p.impacts" :key="t">{{t}}</p><button :disabled="busy||plan.job.can_preview===false" @click="emit('action','use_proposal',{proposal_index:i})">预览此建议</button></article></details>
    <h3>用餐与住宿怎么选</h3><p v-for="m in guide.dining" :key="m.day+m.window">第 {{m.day}} 天{{m.window}}：{{m.text}}</p><p>{{guide.lodging.text}}</p><p v-if="guide.lodging.areas.length">片区备选：{{guide.lodging.areas.join('、')}}（没有核实酒店或交通便利性）</p>
    <details><summary>修改住宿策略与人数口径</summary><fieldset :disabled="busy"><div class="grid">
      <label>人数<input :value="form.trip_budget.people??''" type="number" min="1" @change="form.trip_budget.people=number($event);save()" /></label>
      <label>房间数<input :value="form.trip_budget.rooms??''" type="number" min="1" @change="form.trip_budget.rooms=number($event);save()" /></label>
      <label>住宿晚数<input :value="form.trip_budget.nights??''" type="number" min="0" @change="form.trip_budget.nights=number($event);save()" /></label>
      <label>住宿取舍<select v-model="form.guide.lodging.strategy" @change="save"><option value="UNDECIDED">尚未决定</option><option value="NEAR_ACTIVITIES">靠近活动集中区域</option><option value="NEXT_DAY_AREA">衔接次日活动</option><option value="FEWER_MOVES">减少换酒店</option><option value="NOT_APPLICABLE">不住宿</option></select></label>
    </div></fieldset></details>
    <h3>旅行花费参考</h3><p>已知条件：{{guide.budget_context.known_conditions.join("、")||"尚未填写"}}。</p><p>待补充条件：{{guide.budget_context.pending_conditions.join("、")||"人数、天数与房晚条件已明确；实际价格仍待核实"}}。</p><p>已计入部分：<strong>{{money(guide.budget.known_total)}}</strong>。这是预算草案，不是全程报价。</p><p v-if="guide.budget.per_person">每人项目小计 {{money(guide.budget.per_person)}}；房间总价单列，不自动平摊。</p><p v-if="guide.budget_difference">与采用版相比：已计入部分 {{sign(guide.budget_difference.min_fen)}}—{{sign(guide.budget_difference.max_fen)}} 元；未知项目未折算。</p><p v-if="guide.budget.target_note" class="notice">{{guide.budget.target_note}}</p>
    <ul class="budget-list"><li v-for="line in guide.budget.lines" :key="line.line_id"><strong>{{line.label}}</strong>：{{line.basis_label}} · {{line.unit_label}} × {{line.quantity}} · 本次 {{money(line.total)}}<small>{{line.note}}</small><details v-if="line.conditions.length"><summary>计价条件</summary><p v-for="c in line.conditions" :key="c">{{c}}</p></details></li></ul>
    <p v-if="guide.budget.missing_categories.length">尚未计入类别：{{guide.budget.missing_categories.join('、')}}</p>
    <p v-if="guide.budget.paid_fen">用户记录已付 {{(guide.budget.paid_fen/100).toFixed(2)}} 元，包含在明细中，不重复加价。</p>
    <details><summary>修改预算目标与明细（本地）</summary><fieldset :disabled="busy"><label>本次预算目标（元）<input :value="form.trip_budget.target_fen===null?'':form.trip_budget.target_fen/100" type="number" min="0" step="0.01" @change="form.trip_budget.target_fen=number($event)===null?null:Math.round(number($event)!*100);save()" /></label><label class="check"><input v-model="form.trip_budget.target_locked" type="checkbox" @change="save" />这个目标是不可超过的硬上限</label>
      <article v-for="line in form.trip_budget.lines" :key="line.line_id"><h4>{{line.label}}</h4><div class="grid"><label>金额性质<select :value="line.basis" :disabled="line.locked||line.paid_fen>0" @change="basis(line,$event)"><option value="USER_BUDGET_TARGET">我计划预留</option><option v-if="line.basis==='AI_BUDGET_PROPOSAL'" value="AI_BUDGET_PROPOSAL">AI预算假设</option><option value="UNKNOWN">还不知道</option><option value="NOT_APPLICABLE">不适用</option><option value="EXCLUDED_SELF_ARRANGED">自行安排不计入</option></select></label>
      <template v-if="['USER_BUDGET_TARGET','AI_BUDGET_PROPOSAL'].includes(line.basis)"><label>单价目标下限（元）<input :value="line.unit_amount.min_fen===null?'':line.unit_amount.min_fen/100" :disabled="line.locked||line.paid_fen>0" type="number" min="0" step="0.01" @change="price(line,'min_fen',$event)" /></label><label>单价目标上限（元）<input :value="line.unit_amount.max_fen===null?'':line.unit_amount.max_fen/100" :disabled="line.locked||line.paid_fen>0" type="number" min="0" step="0.01" @change="price(line,'max_fen',$event)" /></label></template>
      <label>计价口径<select v-model="line.unit" :disabled="line.locked||line.paid_fen>0" @change="save"><option value="ONCE">一次性</option><option value="PER_PERSON">每人</option><option value="PER_PERSON_DAY">每人每天</option><option value="PER_ROOM_NIGHT">每间每晚</option><option value="PER_DAY">每天</option></select></label><label v-if="line.optional" class="check"><input v-model="line.include_optional" type="checkbox" @change="save" />纳入本次预留</label></div></article>
    </fieldset></details>
    <details><summary>可选详细时间视图</summary><p>只有已知的假设参与计算；后续移动未知时，具体到达时间保持未知。</p><p v-for="r in plan.timeline" :key="r.activity_id">第 {{r.day}} 天 {{r.name}}：{{r.display_start}} → {{r.display_end}}</p></details>
    <details><summary>还需留意的事项与来源</summary><p v-for="v in [...guide.assumptions,...guide.tradeoffs,...guide.unknowns,...plan.gaps]" :key="v">{{v}}</p><p>来源知识、地点提及、用户选择与AI停留建议保持各自含义；具体卡片可在资料库展开。</p><p v-for="d in plan.job?.decisions.filter(d=>d.status==='REJECTED')||[]" :key="d.proposal_id">提议未采用：{{d.reason}}</p></details>
    <p v-if="plan.differences.length">草稿有修改，原采用版保留。</p><div class="actions"><button :disabled="busy||!guide.available" @click="emit('action','adopt',{})">采用这版建议攻略</button><button class="quiet" :disabled="busy||(!plan.adopted&&!plan.proposal_preview_active)" @click="emit('action','cancel',{})">取消修改，恢复原版</button><button class="quiet" :disabled="busy||!plan.adopted" @click="download">导出采用版 Markdown</button></div>
    <p v-if="exported" role="status">{{exported}}</p><p v-if="error" class="warning" role="alert">{{error}}</p>
  </section>
</template>
<style scoped>
.guide-title{display:flex;align-items:center;justify-content:space-between;gap:1rem}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}fieldset{border:0;padding:0}h3{margin-top:1.7rem}.activity,.combination{border:1px solid #ccd8c9;border-radius:12px;padding:1rem;margin:1rem 0}.check{display:flex;align-items:center;gap:.5rem}.check input{width:auto}details{margin:.8rem 0}small{display:block;color:#586354}.budget-list li{padding:.4rem 0}@media(max-width:650px){.grid{grid-template-columns:1fr}.guide-title{align-items:start}}
</style>
