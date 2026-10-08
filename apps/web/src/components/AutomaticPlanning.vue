<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {PlanView} from '../planning-api'
const props=defineProps<{plan:PlanView;busy:boolean}>()
const emit=defineEmits<{run:[action:string,text?:string];preview:[index:number];adopt:[index:number]}>()
const text=ref('')
watch(()=>props.plan.session_id,()=>text.value='')
const task=computed(()=>props.plan.automatic_task)
const active=computed(()=>['QUEUED','RUNNING'].includes(task.value?.status||''))
const stage=computed(()=>({CACHE:'正在检查可用本机资料',RESEARCH:'正在查小红书',LOGIN:'等待正常登录',SEARCH:'正在查小红书',READING:'正在阅读笔记正文',EXTRACT:'正在提取必要资料',REVIEW:'正在审核来源上下文',MATERIALS:'正在组织暂定材料',PLANNING:'正在整理旅行建议',RESULT:'新的旅行建议已就绪'}[task.value?.stage||'']||'任务状态已保存'))
const names=(id:string)=>props.plan.draft.activities.find(a=>a.activity_id===id)?.name||props.plan.combination_candidates.find(a=>a.activity_id===id)?.name||'来源活动'
const problem=computed(()=>{
 const r=task.value?.reason||''
 if(r.includes('VERIFICATION')||r.includes('DENIED')||r.includes('RATE_LIMIT'))return '网站需要验证或限制了访问，已停止。请查看官方页面；不会尝试规避，也不会自动重试。'
 if(r.includes('LOGIN'))return '尚未完成正常登录，未继续查找。已有资料和结果保留。'
 if(r==='USER_CANCELED')return '已停止本次任务，已有采用版保留。'
 if(r.includes('SERVER_STOPPED'))return '服务已重启，本次任务没有自动重放；已保存的结果可继续查看。'
 if(r.includes('CONDITIONS_CHANGED')||r.includes('STALE'))return '条件已变化，旧任务停止，不能覆盖当前结果。'
 if(r.startsWith('PLANNING_'))return '资料已保存，但建议未通过生成或约束检查；原采用版保留。可查看依据并补充条件。'
 return '本次没有取得足够合格材料，未编造攻略。可查看失败阶段和已保存来源，再补充具体的区域或玩法。'
})
</script>
<template>
 <section class="card automatic-planning" aria-label="自动查资料与建议">
  <h2>{{task?.status==='COMPLETED'?'先看看这几种玩法':active?stage:task?.status==='WAITING_CONFIGURATION'?'先完成一次模型配置':'查资料并给你初步建议'}}</h2>
  <p>已识别：{{plan.destination}} · {{plan.draft.days?`${plan.draft.days} 天`:'天数未定'}}。人数、预算和日期可以以后再补。</p>
  <template v-if="!task"><p>这次会先复用适用的本机资料；不足时查询小红书并阅读少量公开笔记，将过滤后的必要文字交给已配置的 DeepSeek 整理。</p><p>点击即启动本次有限任务；每来源最多6000字，不发送凭据、私址或地图返回。新建议不会覆盖采用版。</p><button :disabled="busy" @click="emit('run','continue')">查资料并生成旅行建议</button></template>
  <template v-else-if="task.status==='WAITING_CONFIGURATION'"><p>在本机用户环境变量配置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY，再正常重启工作台。密钥只在服务端读取，不填入本页面或聊天；无需额外测连接。</p><p>配置完成后仅需继续这一次任务，未产生任何外部调用。</p><button :disabled="busy" @click="emit('run','continue')">配置完成，继续本次任务</button></template>
  <template v-else-if="active"><p role="status">{{stage}}。页面可以刷新，任务不会重复派发。</p><p v-if="task.stage==='LOGIN'">如果官方登录页面需要扫码，请在打开的小红书官方页面完成正常登录；完成后会继续同一个任务。</p><button class="quiet" :disabled="busy" @click="emit('run','cancel')">停止本次任务</button></template>
  <p v-else-if="task.status!=='COMPLETED'" class="warning" role="status">{{problem}} <small>停止阶段：{{task.stage}}；原因：{{task.reason||task.status}}。</small></p>
  <p v-if="task">本次{{task.research_attempted?'已派发小红书搜索':'没有派发小红书搜索'}}；成功取得新正文 {{task.new_body_count}} 篇，复用历史来源 {{task.cache_source_count}} 个。正文成功不代表所有结论已经接纳。</p>
  <p v-if="task?.changes.length">本次补充已落实到：{{task.changes.join('、')}}。原采用版保留，新结果尚未覆盖。</p>
  <div v-if="task?.status==='COMPLETED'" class="options">
   <article v-for="(p,i) in plan.job?.proposals||[]" :key="i" class="option"><small>本次新生成的AI建议 · 当前可行性未核实</small><h3>{{p.title}}</h3><p>{{p.reason}}</p><ol><li v-for="a in p.activities" :key="a.activity_id">第{{a.day}}天 · {{names(a.activity_id)}} · 建议停留{{a.stay_min}}–{{a.stay_max}}分钟</li></ol><p v-for="u in p.unknowns" :key="u">待核实：{{u}}</p><p v-if="p.assessment">{{p.assessment.label}}；{{p.assessment.coverage.meaning}}</p><button class="quiet" :disabled="busy||!plan.job?.can_preview" @click="emit('preview',i)">预览这版</button><button :disabled="busy||!plan.job?.can_preview" @click="emit('adopt',i)">采用这版建议</button></article>
  </div>
  <details v-if="task?.sources.length"><summary>查看本次资料依据</summary><article v-for="(s,i) in task.sources" :key="i"><h3><a v-if="s.url" :href="s.url" target="_blank" rel="noreferrer">{{s.title}}</a><span v-else>{{s.title}}</span></h3><p>{{s.origin==='CACHE'?'本次复用历史资料':'本次取得正文'}} · {{s.completeness||'完整度见原记录'}} · 取得时间 {{s.retrieved_at||'历史记录未提供'}}</p><p>原旅行时间与适用条件以引用为准，取得时间不是旅行发生时间。</p></article></details>
  <form v-if="!active&&task&&task.status!=='WAITING_CONFIGURATION'" @submit.prevent="emit('run','revise',text)"><label for="modify-idea">补充或修改想法</label><textarea id="modify-idea" v-model="text" maxlength="500" rows="2" placeholder="例如：只有5天，不想自驾，想轻松一点" /><p>优先复用当前资料，局部调整；缺少可用活动才有限补查。点击会建立一次新的有界任务，旧用量保留。</p><button :disabled="busy||!text.trim()">按补充调整建议</button></form>
  <details v-if="task"><summary>高级：本次执行上限与用量</summary><p>上限：搜索{{task.limits.search}}次、正文{{task.limits.detail}}篇、模型{{task.limits.model}}次，连接{{task.limits.connect}}次；不调用地图、报价或embedding。取得合格活动后可提前停止，不自动重试。</p><p>已预留（失败也计数）：搜索{{task.budget?.used.search||0}}、正文{{task.budget?.used.detail||0}}、模型{{task.budget?.used.model||0}}。费用无法实时核算，次数上限不是价格承诺；本任务一小时内有效，结束即关闭。</p></details>
 </section>
</template>
<style scoped>.options{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:1rem}.option{border:1px solid #cbd4ca;border-radius:12px;padding:1rem}button{margin:.4rem .4rem .4rem 0}form{margin-top:1rem}small{display:block}li{margin:.5rem 0}details{margin-top:1rem}</style>
