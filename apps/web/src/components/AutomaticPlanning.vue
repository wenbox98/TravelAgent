<script setup lang="ts">
import {computed,nextTick,ref,watch} from 'vue'
import type {PlanView} from '../planning-api'
const props=defineProps<{plan:PlanView;busy:boolean}>()
const emit=defineEmits<{run:[action:string,text?:string];talk:[action:string,optionId?:string,text?:string,activityId?:string];preview:[index:number];adopt:[index:number]}>()
const text=ref(''),log=ref<HTMLElement|null>(null)
watch(()=>props.plan.session_id,()=>text.value='')
const conversation=computed(()=>props.plan.conversation)
watch(()=>conversation.value?.version,async()=>{await nextTick();if(log.value)log.value.scrollTop=log.value.scrollHeight;if(conversation.value?.messages.slice(-3).some(m=>m.role==='USER'&&m.text===text.value))text.value=''})
const task=computed(()=>props.plan.automatic_task)
const ready=computed(()=>['COMPLETED','PARTIAL'].includes(task.value?.status||'')&&task.value?.generated)
const active=computed(()=>['QUEUED','RUNNING'].includes(task.value?.status||''))
const stage=computed(()=>({CACHE:'正在检查可用本机资料',RESEARCH:'正在查小红书',LOGIN:'等待正常登录',LOGIN_CHECK:'正在检查小红书登录',LOGIN_REQUIRED:'请在官方窗口完成正常登录',LOGIN_AUTHENTICATED:'小红书登录已确认',SEARCH:'正在查小红书',READING:'正在阅读笔记正文',EXTRACT:'正在提取必要资料',REVIEW:'正在审核来源上下文',MATERIALS:'正在组织暂定材料',PLANNING:'正在整理旅行建议',RESULT:'新的旅行建议已就绪'}[task.value?.stage||'']||'任务状态已保存'))
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
  <h2>{{ready?(task?.status==='PARTIAL'?'资料有限，先看局部建议':'先看看这几种玩法'):active?stage:task?.status==='WAITING_CONFIGURATION'?'先完成一次模型配置':'查资料并给你初步建议'}}</h2>
  <div class="conversation-log" ref="log" aria-label="旅行对话" role="log"><article v-for="m in conversation?.messages||[]" :key="m.message_id" :class="['bubble',m.role==='USER'?'user':'assistant']"><small>{{m.role==='USER'?'你':m.origin==='LOCAL_REFERENCE_EXPLANATION'?'依据现有资料回答 · 本地':'旅行助手'}}</small><p>{{m.text}}</p><details v-if="m.citations?.length"><summary>回答依据</summary><blockquote v-for="r in m.citations" :key="r.citation_id">{{r.text}}<small>{{r.source_title}} · {{r.role}} · {{r.review}}</small><p>{{r.conditions.join('；')}}</p></blockquote></details><small v-if="m.options?.length">历史方案版本保留；当前可选方案见下方，不自动重新采用。</small></article></div>
  <p>已识别：{{plan.destination}} · {{plan.draft.days?`${plan.draft.days} 天`:'天数未定'}}。人数、预算和日期可以以后再补。</p>
  <template v-if="!task"><p>这次会先复用适用的本机资料；不足时查询小红书并阅读少量公开笔记，将过滤后的必要文字交给已配置的 DeepSeek 整理。</p><p>点击即启动本次有限任务；每来源最多6000字，不发送凭据、私址或地图返回。新建议不会覆盖采用版。</p><button :disabled="busy" @click="emit('run','continue')">查资料并生成旅行建议</button></template>
  <template v-else-if="task.status==='WAITING_CONFIGURATION'"><p>在本机用户环境变量配置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY，再正常重启工作台。密钥只在服务端读取，不填入本页面或聊天；无需额外测连接。</p><p>配置完成后仅需继续这一次任务，未产生任何外部调用。</p><button :disabled="busy" @click="emit('run','continue')">配置完成，继续本次任务</button></template>
  <template v-else-if="active"><p role="status">{{stage}}。页面可以刷新，任务不会重复派发。</p><p v-if="['LOGIN','LOGIN_REQUIRED'].includes(task.stage)">如果官方登录页面需要扫码，请在打开的小红书官方页面完成正常登录；完成后会继续同一个任务。</p><button class="quiet" :disabled="busy" @click="emit('run','cancel')">停止本次任务</button></template>
  <p v-else-if="!ready" class="warning" role="status">{{problem}} <small>停止阶段：{{task.stage}}；原因：{{task.reason||task.status}}。</small></p>
  <details v-if="task" class="research-message"><summary>研究进展与资料依据 · 新正文 {{task.new_body_count}} 篇 · 复用 {{task.cache_source_count}} 个来源</summary>  <p v-if="task">本次{{task.research_attempted?'已派发小红书搜索':'没有派发小红书搜索'}}；搜索 {{task.search_count}} 次，观察候选 {{task.candidate_count}} 条，去重后 {{task.unique_candidate_count}} 个；成功取得新正文 {{task.new_body_count}} 篇，尝试读取 {{task.body_attempts}} 次；本轮采信来源 {{task.accepted_source_count}} 个，复用历史来源 {{task.cache_source_count}} 个。正文成功不代表所有结论已经接纳。</p>
  <p v-if="task">登录：{{({NOT_CHECKED:'本次尚未检查；缓存浏览不需要登录',LOGIN_CHECK:'正在检查',LOGIN_REQUIRED:'等待官方正常登录',LOGIN_AUTHENTICATED:'本次研究已确认登录',EXPIRED_OR_REQUIRED:'会话失效或需要登录，已停止'} as Record<string,string>)[task.login_state]||task.login_state}}。不同来源内容重复 {{task.duplicate_body_count}} 篇，不重复提取，也不算新覆盖。</p>
  <div v-if="task?.coverage"><p>{{task.coverage.meaning}} 已有玩法 {{task.coverage.activity_count}} 个，独立作者仍未核实。</p><p v-if="task.coverage.gaps.length" class="warning">当前仍缺：{{task.coverage.gaps.map(g=>g.label).join('；')}}。局部建议不能视为完整攻略。</p><p v-if="!active&&task.coverage.gaps.length">点击将按缺口建立新的有限任务：必要时检查登录、查找和读取公开笔记，过滤后的必要文字交给已配置的 DeepSeek；每来源最多6000字。本次仍按下方默认上限，旧用量和失败保留，不自动重试。</p></div>
  </details>
  <p v-if="ready&&task?.coverage?.gaps.length" class="warning">资料有限，仍缺{{task.coverage.gaps.slice(0,2).map(g=>g.label).join('、')}}等；可先比较局部玩法。</p>
  <button v-if="!active&&task?.coverage?.gaps.length" class="quiet" :disabled="busy" @click="emit('run','research_more')">继续补充研究</button>
  <p v-if="task?.changes.length">本次补充已落实到：{{task.changes.join('、')}}。原采用版保留，新结果尚未覆盖。</p>
  <p v-if="conversation?.selected" class="notice">已记住暂定方向：{{conversation.selected.title}}。{{conversation.selected_current?'仍可改选或撤回；尚未采用。':'来自上一轮，下一轮会作为偏好参考；旧方案不能直接覆盖新版本。'}}<button class="quiet" :disabled="busy" @click="emit('talk','clear',conversation.selected.option_id)">清除暂定方向</button></p>
  <p v-if="conversation?.excluded.length">本轮不选：<span v-for="o in conversation.excluded" :key="o.option_id">{{o.title}}<button class="quiet" :disabled="busy" @click="emit('talk','clear',o.option_id)">恢复这个备选</button></span>；不等于所有地点都排除。</p>
  <div v-if="ready" class="options">
   <article v-for="(p,i) in plan.job?.proposals||[]" :key="i" class="option"><small>本次新生成的AI建议 · 当前可行性未核实</small><h3>{{p.title}}</h3><p>{{p.reason}}</p><ol><li v-for="a in p.activities" :key="a.activity_id">第{{a.day}}天 · {{names(a.activity_id)}} · 建议停留{{a.stay_min}}–{{a.stay_max}}分钟 <button class="quiet compact" :disabled="busy" @click="emit('talk',conversation?.excluded_activities.includes(a.activity_id)?'restore_activity':'exclude_activity',undefined,undefined,a.activity_id)">{{conversation?.excluded_activities.includes(a.activity_id)?'恢复备选':'不想去这里'}}</button></li></ol><p v-for="u in p.unknowns" :key="u">待核实：{{u}}</p><p v-if="p.assessment">{{p.assessment.label}}；{{p.assessment.coverage.meaning}}</p><div class="choices" v-if="conversation?.options[i]"><button :disabled="busy||!plan.job?.can_preview" @click="emit('talk','select',conversation.options[i].option_id)">偏向这个方案</button><button class="quiet" :disabled="busy||!plan.job?.can_preview" @click="emit('talk','exclude',conversation.options[i].option_id)">本轮不选</button><button class="quiet" :disabled="busy||!plan.job?.can_preview" @click="emit('talk','clear',conversation.options[i].option_id)">撤回选择</button><small>选择方向只用于下一轮比较，与采用并保存分开。</small></div><button class="quiet" :disabled="busy||!plan.job?.can_preview" @click="emit('preview',i)">预览这版</button><button :disabled="busy||!plan.job?.can_preview" @click="emit('adopt',i)">采用这版建议</button></article>
  </div>
  <details v-if="task?.sources.length"><summary>查看本次资料依据</summary><article v-for="(s,i) in task.sources" :key="i"><h3><a v-if="s.url" :href="s.url" target="_blank" rel="noreferrer">{{s.title}}</a><span v-else>{{s.title}}</span></h3><p>{{s.origin==='CACHE'?'本次复用历史资料':'本次取得正文'}} · {{s.completeness||'完整度见原记录'}} · 取得时间 {{s.retrieved_at||'历史记录未提供'}}</p><p>原旅行时间与适用条件以引用为准，取得时间不是旅行发生时间。</p></article></details>
  <aside v-if="!active&&conversation?.pending_question" class="bubble assistant"><p>{{conversation.pending_question.text}}</p><button v-for="choice in conversation.pending_question.choices.filter(c=>c!=='继续补充研究'&&c!=='为什么推荐这些')" :key="choice" class="quiet" :disabled="busy" @click="emit('talk','message',undefined,choice)">{{choice}}</button><button class="quiet" :disabled="busy" @click="emit('talk','message',undefined,'为什么推荐这些')">为什么推荐这些</button></aside>
  <form class="composer" v-if="conversation&&task?.status!=='WAITING_CONFIGURATION'" @submit.prevent="emit('talk','message',undefined,text)">
   <label for="modify-idea">继续聊聊这次旅行</label><textarea id="modify-idea" v-model="text" maxlength="500" rows="2" placeholder="问问推荐依据，或补充：只有5天、不想自驾" />
   <p>提问和点选先用本机资料，不改已采用攻略。提交明确条件修改或点击更新时才启动下一轮：优先复用，缺口才有限查小红书，必要文字交给已配置 DeepSeek，每来源最多6000字。沿用下方范围，无自动重试。</p>
   <button :disabled="busy||active||!text.trim()">发送</button><button type="button" class="quiet" :disabled="busy||active||!conversation.selected&&!conversation.excluded.length&&!conversation.excluded_activities.length" @click="emit('talk','continue')">按当前取舍更新建议</button>
  </form>
  <details v-if="task?.query_progress.length"><summary>每轮研究进展</summary><p v-for="q in task.query_progress" :key="q.search_number">第{{q.search_number}}次搜索：观察{{q.observed_candidates||0}}条候选，读取{{q.body_reads||0}}篇正文，新增{{q.new_facts||0}}条去重后的合格引用。无新增信息不会计作覆盖改善。</p></details>
  <details v-if="task"><summary>高级：本次执行上限与用量</summary><p>上限：搜索{{task.limits.search}}次、正文{{task.limits.detail}}篇、模型{{task.limits.model}}次，连接{{task.limits.connect}}次；不调用地图、报价或embedding。覆盖满足本次研究目标后可提前停止，不自动重试。</p><p>已预留（失败也计数）：搜索{{task.budget?.used.search||0}}、正文{{task.budget?.used.detail||0}}、模型{{task.budget?.used.model||0}}。费用无法实时核算，次数上限不是价格承诺；本任务一小时内有效，结束即关闭。</p></details>
 </section>
</template>
<style scoped>.conversation-log{max-height:50vh;overflow:auto;display:flex;flex-direction:column;gap:.8rem}.bubble{padding:1rem;border-radius:16px;max-width:92%;background:#edf1ea}.bubble.user{align-self:flex-end;background:#e1ebf5}.composer{background:#fff;padding:.7rem;border-top:1px solid #d7dfd5}.composer p{font-size:.85rem}.compact{font-size:.75rem;padding:.2rem .4rem}.choices{border-top:1px solid #dde3db;margin-top:.6rem}.options{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:1rem}.option{border:1px solid #cbd4ca;border-radius:12px;padding:1rem}button{margin:.4rem .4rem .4rem 0}form{margin-top:1rem}small{display:block}li{margin:.5rem 0}details{margin-top:1rem}</style>
