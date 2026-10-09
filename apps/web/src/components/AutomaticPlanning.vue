<script setup lang="ts">
import {computed,nextTick,ref,watch} from 'vue'
import type {PlanView} from '../planning-api'
import {readMessage,storeMessage,submitShortcut} from '../intake'
const props=defineProps<{plan:PlanView;busy:boolean;blockedReason?:string;submitting?:boolean;feedback?:string;failure?:string;unconfirmed?:boolean;resumable?:boolean;acknowledgment?:{session_id:string;text:string;sequence:number}|null}>()
const emit=defineEmits<{run:[action:string,text?:string];talk:[action:string,optionId?:string,text?:string,activityId?:string];preview:[index:number];adopt:[index:number];exportReference:[];recover:[];resume:[]}>()
const text=ref(readMessage(props.plan.session_id)),log=ref<HTMLElement|null>(null),attempted=ref(''),composing=ref(false)
watch(text,value=>storeMessage(props.plan.session_id,value),{flush:'sync'})
watch(()=>props.plan.session_id,(sid,previous)=>{storeMessage(previous,text.value);text.value=readMessage(sid);attempted.value=''},{flush:'sync'})
const conversation=computed(()=>props.plan.conversation)
watch(()=>conversation.value?.version,async()=>{await nextTick();if(log.value)log.value.scrollTop=log.value.scrollHeight})
watch(()=>props.acknowledgment,ack=>{if(ack?.session_id===props.plan.session_id&&ack.text===text.value)text.value=''},{immediate:true})
const task=computed(()=>props.plan.automatic_task)
const startupFailure=computed(()=>!task.value?.research_attempted&&!task.value?.search_count&&/JOB_STOPPED_BEFORE_COMPLETION|XHS_PROFILE_UNAVAILABLE|CONFIGURED_|BOUNDED_|WORKER_START_FAILED|WORKER_NOT_STARTED/.test(task.value?.reason||''))
const hasMaterial=computed(()=>Boolean(props.plan.draft.activities.length||props.plan.job?.proposals.length||props.plan.references?.length||overview.value?.available))
const ready=computed(()=>['COMPLETED','PARTIAL'].includes(task.value?.status||'')&&task.value?.generated)
const active=computed(()=>['QUEUED','RUNNING'].includes(task.value?.status||''))
const answering=computed(()=>['QUEUED','RUNNING'].includes(props.plan.answer_job?.status||''))
const blocked=computed(()=>props.submitting?'正在提交消息，请稍候；不会重复发送。':props.busy?'正在处理上一项操作，完成后再发送。':props.blockedReason|| (props.unconfirmed?'上次提交结果尚未确认，请先读取已保存状态。':active.value?'当前任务仍在进行，请先等待完成或停止任务。':answering.value?'上一条消息仍在回答，请先等待完成。':!text.value.trim()?'请先写下想问或想修改的内容。':''))
const sendLabel=computed(()=>props.submitting?'正在提交…':props.busy?'正在处理…':props.unconfirmed?'结果待确认':active.value?'任务进行中':answering.value?'正在回答…':'发送')
const notice=computed(()=>attempted.value||(props.submitting?props.feedback||blocked.value:props.busy||props.blockedReason||props.unconfirmed||active.value||answering.value?blocked.value:props.feedback||blocked.value)||'发送后会先显示是否接收，再显示任务进度；尚未发送的文字仅留在当前浏览器。')
function send(){if(blocked.value){attempted.value='未发送：'+blocked.value;return}attempted.value='';emit('talk','submit',undefined,text.value)}
function keyboard(e:KeyboardEvent){if(!composing.value&&submitShortcut(e)){e.preventDefault();send()}}
watch(()=>[props.busy,props.blockedReason,props.unconfirmed,text.value],()=>attempted.value='')
const overview=computed(()=>props.plan.reference_overview)
const showMore=ref(false)
const referenceCards=computed(()=>overview.value?.current?.cards||[])
const visibleReferenceCards=computed(()=>showMore.value?referenceCards.value:referenceCards.value.slice(0,3))
const points=computed(()=>overview.value?.projected?.points||[])
const morePoints=ref(false)
const visiblePoints=computed(()=>morePoints.value?points.value:points.value.slice(0,6))
const returnedSearches=computed(()=>task.value?.query_progress.filter(q=>q.observed_candidates!==undefined).length||0)
const canUpdate=computed(()=>Boolean(conversation.value?.selected||conversation.value?.excluded.length||conversation.value?.excluded_activities.length||overview.value?.selected_current||overview.value?.excluded_current?.length||overview.value?.selected_points?.length||overview.value?.excluded_points?.length))
watch(()=>props.plan.session_id,()=>{showMore.value=false;morePoints.value=false})
const stage=computed(()=>({CACHE:'正在检查可用本机资料',RESEARCH:'正在查小红书',LOGIN:'等待正常登录',LOGIN_CHECK:'正在检查小红书登录',LOGIN_REQUIRED:'请在官方窗口完成正常登录',LOGIN_AUTHENTICATED:'小红书登录已确认',SEARCH:'正在查小红书',READING:'正在阅读笔记正文',EXTRACT:'正在提取必要资料',REVIEW:'正在审核来源上下文',MATERIALS:'正在组织暂定材料',PLANNING:'正在整理旅行建议',RESULT:'新的旅行建议已就绪'}[task.value?.stage||'']||'任务状态已保存'))
const names=(id:string)=>props.plan.draft.activities.find(a=>a.activity_id===id)?.name||props.plan.combination_candidates.find(a=>a.activity_id===id)?.name||'来源活动'
const problem=computed(()=>{
 const r=task.value?.reason||''
 if(r.includes('XHS_PROFILE_UNAVAILABLE'))return '研究启动失败：本机服务无法安全访问专用浏览器目录，尚未检查登录或搜索。这是启动环境问题，不是你漏填条件。需要用普通本机权限正常重启工作台；失败与额度记录保留，不会自动重放。'
 if(startupFailure.value)return '研究在开始查找前异常停止，尚未得到材料。这是系统故障，不是资料已足够或需要你补填条件。原失败已保留；修复后由你显式发起新任务，不会自动重试。'
 if(r==='ROUTE_REFERENCE_ONLY')return '资料支持下面的路线参考，暂不支持具体玩法安排；交通与当前可行性仍有缺口。'
 if(r.includes('VERIFICATION')||r.includes('DENIED')||r.includes('RATE_LIMIT'))return '网站需要验证或限制了访问，已停止。请查看官方页面；不会尝试规避，也不会自动重试。'
 if(r.includes('LOGIN'))return '尚未完成正常登录，未继续查找。已有资料和结果保留。'
 if(r==='USER_CANCELED')return '已停止本次任务，已有采用版保留。'
 if(r.includes('SERVER_STOPPED'))return '服务已重启，本次任务没有自动重放；已保存的结果可继续查看。'
 if(r.includes('CONDITIONS_CHANGED')||r.includes('STALE'))return '条件已变化，旧任务停止，不能覆盖当前结果。'
 if(r.startsWith('PLANNING_'))return '资料已保存，但建议未通过生成或约束检查；原采用版保留。可查看依据并补充条件。'
 if(r.includes('CONTEXT_REVIEW'))return '本次内容审核未完成，未审核的条目不能当作可用事实。已合格的参考仍保留在下方；旧失败不会自动重试。'
 if(props.plan.references?.length)return `已保留${props.plan.references.length}条合格参考，本次因后续读取或审核问题停止，未继续生成攻略。可以先查看和选择已有内容；旧失败不会自动重试。`
 return '本次没有取得足够合格材料，未编造攻略。可查看失败阶段和已保存来源，再补充具体的区域或玩法。'
})
</script>
<template>
 <section class="card automatic-planning" aria-label="自动查资料与建议">
  <h2>{{ready?(task?.status==='PARTIAL'?'资料有限，先看局部建议':'先看看这几种玩法'):overview?.valid?'先看已有路线参考':active?stage:task?.status==='WAITING_CONFIGURATION'?'先完成一次模型配置':'查资料并给你初步建议'}}</h2>
  <p class="muted">本次对话记录 · 历史消息保留；当前生效条件见上方，尚未发送的消息不生效。</p><div class="conversation-log" ref="log" aria-label="旅行对话" role="log"><article v-for="m in conversation?.messages||[]" :key="m.message_id" :class="['bubble',m.role==='USER'?'user':'assistant']"><small>{{m.role==='USER'?'你':m.origin==='AI_CACHED_ADVICE'?'AI缓存问答 · 建议与解释，非事实核实':m.origin==='LOCAL_REFERENCE_OVERVIEW'?'路线资料整理 · 本地':m.origin==='LOCAL_REFERENCE_EXPLANATION'?'依据现有资料回答 · 本地':'旅行助手'}}</small><p>{{m.text}}</p><p v-for="g in m.gaps||[]" :key="g">仍需确认：{{g}}</p><details v-if="m.citations?.length"><summary>回答依据</summary><blockquote v-for="r in m.citations" :key="r.citation_id">{{r.text}}<small>{{r.source_title}} · {{r.role}} · {{r.review}}</small><p>{{r.conditions.join('；')}}</p></blockquote></details><small v-if="m.options?.length">历史方案版本保留；当前可选方案见下方，不自动重新采用。</small></article></div>
  <p>已识别：{{plan.destination}} · {{plan.draft.days?`${plan.draft.days} 天`:'天数未定'}}。人数、预算和日期可以以后再补。</p>
  <form class="composer" v-if="conversation&&task?.status!=='WAITING_CONFIGURATION'" @submit.prevent="send" :aria-busy="submitting||false">
   <label for="modify-idea">继续聊聊这次旅行</label><textarea id="modify-idea" v-model="text" maxlength="500" rows="2" placeholder="例如：只有5天、不想自驾，更新方案；或问问推荐依据" aria-describedby="message-hint message-feedback" @keydown="keyboard" @compositionstart="composing=true" @compositionend="composing=false" />
   <p id="message-hint" class="muted">{{!blocked?'Ctrl / ⌘ + Enter 发送，Enter 换行。':'当前暂不能发送；输入会保留。'}}</p>
   <p v-if="failure" role="alert" class="warning">{{failure}}</p>
   <div v-if="failure||unconfirmed"><button type="button" class="quiet" :disabled="busy" @click="emit('recover')">读取已保存状态</button><button v-if="resumable" type="button" :disabled="busy||Boolean(blockedReason)" @click="emit('resume')">继续确认原提交</button></div>
   <p id="message-feedback" role="status" aria-live="polite">{{notice}}</p>
   <p>发送会结合本次选择和必要公开资料交给现有DeepSeek处理；更新优先用缓存，需要补资料才有限查小红书。仅提问或假设不改条件、不查新资料，当前采用版保留。</p>
   <button :disabled="Boolean(blocked)">{{sendLabel}}</button><button type="button" class="quiet" :disabled="busy||active||answering||Boolean(blockedReason)||unconfirmed||!canUpdate" @click="emit('talk','submit',undefined,'按当前取舍更新建议')">按当前取舍更新建议</button>
   <p v-if="answering" role="status">消息已接收，正在结合现有资料回答，刷新不会重复请求。</p><p v-else-if="plan.answer_job?.status==='COMPLETED'" role="status">本次缓存回答已完成；建议与事实核实仍有区别。</p><p v-if="plan.answer_job?.status==='FAILED'" class="warning">本次回答未完成：{{plan.answer_job.reason}}。失败已保留，不会自动重试。</p>
   <aside v-if="conversation.proposed_conditions&&Object.keys(conversation.proposed_conditions).length"><p>AI需要你确认的解释：{{conversation.proposed_conditions.days?`可用${conversation.proposed_conditions.days}天；`:''}}{{conversation.proposed_conditions.driving==='NO'?'不自驾；':conversation.proposed_conditions.driving==='YES'?'愿意自驾；':''}}{{conversation.proposed_conditions.pace==='RELAXED'?'轻松节奏；':''}}{{conversation.proposed_conditions.transport?`交通：${({UNKNOWN:'暂未决定',PUBLIC_TRANSIT:'公共交通',SELF_DRIVE:'自驾',LOCAL_SERVICE:'当地服务',WALKING:'步行'} as Record<string,string>)[conversation.proposed_conditions.transport]}；`:''}}</p><button type="button" :disabled="busy||active||answering" @click="emit('talk','confirm_update')">确认并更新建议</button><p>这次点击会按上方用途启动一次有界更新；旧采用版保留。</p></aside>
   <details><summary>本次必要处理与调用范围</summary><p>接收方：api.deepseek.com；只发送本次条件、选择与过滤后的必要公开引用，每来源每次最多6000字，不发凭据、私址或地图返回。缓存问答或路线讨论最多模型1次，不查新资料；具体建议更新或明确补资料最多连接1、搜索1、正文2篇、模型5次，缓存足够时只需模型1次。地图、报价、embedding为0，不自动重试，不使用旧余额。</p></details>
  </form>
  <template v-if="!task"><p>这次会先复用适用的本机资料；不足时查询小红书并阅读少量公开笔记，将过滤后的必要文字交给已配置的 DeepSeek 整理。</p><p>点击即启动本次有限任务；每来源最多6000字，不发送凭据、私址或地图返回。新建议不会覆盖采用版。</p><button :disabled="busy" @click="emit('run','continue')">查资料并生成旅行建议</button></template>
  <template v-else-if="task.status==='WAITING_CONFIGURATION'"><p>在本机用户环境变量配置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY，再正常重启工作台。密钥只在服务端读取，不填入本页面或聊天；无需额外测连接。</p><p>配置完成后仅需继续这一次任务，未产生任何外部调用。</p><button :disabled="busy" @click="emit('run','continue')">配置完成，继续本次任务</button></template>
  <template v-else-if="active"><p role="status">{{stage}}。页面可以刷新，任务不会重复派发。</p><p v-if="['LOGIN','LOGIN_REQUIRED'].includes(task.stage)">如果官方登录页面需要扫码，请在打开的小红书官方页面完成正常登录；完成后会继续同一个任务。</p><button class="quiet" :disabled="busy" @click="emit('run','cancel')">停止本次任务</button></template>
  <p v-else-if="!ready" class="warning" role="status">{{problem}} <small>停止阶段：{{task.stage}}；原因：{{task.reason||task.status}}。</small></p>
  <section v-if="overview?.available||overview?.current" aria-label="本地路线参考">
   <h3>已有资料能支持的路线参考</h3><p>先看来源怎么安排，再选想讨论的方向。路线参考与具体活动分开，资料不足仍可先比较。</p>
   <button v-if="overview.available&&!overview.valid" class="quiet" :disabled="busy||active||answering" @click="emit('talk','derive_overview')">整理已有路线参考（本地）</button>
   <p v-if="overview.current&&!overview.valid" class="warning">旧整理版本已保存，当前条件或引用变化后需重新整理；当前有效取舍仍按各自引用版本校验。</p>
   <template v-if="overview.valid&&overview.current"><p>{{overview.current.meaning}} · 本地版本{{overview.current.version}}</p>
    <p>{{overview.current.direction_count}}个路线备选来自{{overview.current.source_count}}个来源；备选数量不代表来源独立，作者独立性仍未知。</p>
    <div class="options"><article v-for="card in visibleReferenceCards" :key="card.option_id" class="option" :aria-label="card.title"><h4>{{card.title}}</h4><small>{{card.role_label}}<span v-if="overview.selected_current&&overview.selected?.option_id===card.option_id"> · 当前暂定方向</span><span v-if="overview.excluded_current?.includes(card.option_id)"> · 本轮不选</span></small><p>{{card.summary}}</p><p v-for="(c,i) in card.condition_excerpts" :key="i">条件摘录：{{c.text}}{{c.truncated?'…（完整见依据）':''}}</p><button :disabled="busy||active||answering" @click="emit('talk','select_reference',card.option_id)">选择这个方向</button><button v-if="overview.selected_current&&overview.selected?.option_id===card.option_id" class="quiet" :disabled="busy||answering" @click="emit('talk','clear_reference')">撤回方向</button><button class="quiet" :disabled="busy||active||answering" @click="emit('talk',overview.excluded_current?.includes(card.option_id)?'restore_reference':'exclude_reference',card.option_id)">{{overview.excluded_current?.includes(card.option_id)?'恢复方向':'本轮不选'}}</button><details><summary>查看依据</summary><blockquote v-for="r in card.entries" :key="r.citation_id"><p>{{r.text}}</p><small>{{r.role_label}} · {{r.review}} · {{r.source_title}}</small><p v-if="r.topic==='DURATION'">时长范围：{{r.duration_scope==='WHOLE_TRIP'?'整趟参考':r.duration_scope==='DAY_SEGMENT'?'日段参考':'未知'}}。</p><p>{{r.route_association?`关联对象：${r.route_association.object_quote}（${r.route_association.scope}）`:'未证明与其他条目的具体关联；不能因同源自动套用。'}}</p><p>条件：{{r.conditions.join('；')||'原引用未提供额外条件，不能据此确认当前适用。'}}</p><small v-if="r.citation_ids?.length">同一内容的引用：{{r.citation_ids.join('、')}}</small></blockquote></details></article></div>
    <button v-if="referenceCards.length>3" class="quiet" @click="showMore=!showMore">{{showMore?'收起更多方向':`更多已有方向（${referenceCards.length-3}）`}}</button>
    <details><summary>资料缺口与独立性</summary><p v-for="g in overview.current.gaps" :key="g">{{g}}</p><p v-if="overview.current.unassigned_reference_count">{{overview.current.unassigned_reference_count}}条参考未证明对应路线，未套用到这些方向。</p></details><button class="quiet" :disabled="busy" @click="emit('exportReference')">导出本地路线参考</button>
   </template>
  </section>
  <section v-if="points.length" aria-label="正文拆分点">
   <h3>正文里有哪些玩法和取舍</h3><p>这些是已采信的来源参考，保留作者角色与条件；一个来源的多个点不代表多个独立作者。选中只记录本次兴趣，更新建议需另行点击。</p>
   <p>共{{points.length}}条内容参考；引用详细条件可展开查看。</p><div class="options"><article v-for="point in visiblePoints" :key="point.option_id" class="option"><h4>{{point.topic_label}}</h4><p>{{point.title}}</p><small>{{overview?.selected_points?.includes(point.option_id)?'已选为本次兴趣':overview?.excluded_points?.includes(point.option_id)?'本轮不采用':'可选参考'}}</small>
    <button :disabled="busy||active||answering" @click="emit('talk',overview?.selected_points?.includes(point.option_id)?'clear_point':'select_point',point.option_id)">{{overview?.selected_points?.includes(point.option_id)?'撤回兴趣':'想了解这个'}}</button><button class="quiet" :disabled="busy||active||answering" @click="emit('talk',overview?.excluded_points?.includes(point.option_id)?'restore_point':'exclude_point',point.option_id)">{{overview?.excluded_points?.includes(point.option_id)?'恢复这条参考':'本轮不采用'}}</button>
    <details><summary>完整引用与作用范围</summary><blockquote v-for="entry in point.entries" :key="entry.citation_id"><p>{{entry.text}}</p><small>{{entry.role_label}} · {{entry.review}} · {{entry.source_title}}</small><p>条件：{{entry.conditions.join('；')||'未提供额外条件，当前适用性仍未知。'}}</p><p>{{entry.route_association?`已证明关联：${entry.route_association.object_quote}（${entry.route_association.scope}）`:'未证明与具体路线或地点的关联，不能当作每站特色。'}}</p><small>引用：{{(entry.citation_ids||[entry.citation_id]).join('、')}}</small></blockquote></details>
   </article></div><button v-if="points.length>6" class="quiet" @click="morePoints=!morePoints">{{morePoints?'收起更多内容':`更多正文参考（${points.length-6}）`}}</button>
  </section>
  <details v-if="task" class="research-message" :open="startupFailure"><summary>研究进展与资料依据 · 新正文 {{task.new_body_count}} 篇 · 复用 {{task.cache_source_count}} 个来源</summary><p v-if="startupFailure" class="warning">{{problem}}</p><p v-if="task">本次{{task.research_attempted?'已派发小红书搜索':startupFailure?'因系统启动故障尚未派发小红书搜索':'尚未派发小红书搜索'}}；本轮搜索已预留 {{task.search_count}} 次，成功返回列表 {{returnedSearches}} 次；列表条目 {{task.candidate_count}} 条（含跨轮重复，未读正文），去重后 {{task.unique_candidate_count}} 个笔记；成功取得新正文 {{task.new_body_count}} 篇，尝试读取 {{task.body_attempts}} 次；本轮采信来源 {{task.accepted_source_count}} 个，复用历史来源 {{task.cache_source_count}} 个。正文成功不代表所有结论已经接纳。</p>
  <p v-if="plan.operation">本次旅行历史累计：搜索 {{plan.operation.cumulative_used.search||0}} 次（包含历史任务和失败，与本轮计数分开）。</p>
  <p v-for="skip in task.source_skips||[]" :key="skip.detail_number">第{{skip.detail_number}}次详情未取得正文，已计入用量；不重试同一来源，仅在原上限内继续其他候选。</p>
  <p v-if="task">登录：{{startupFailure&&task.login_state==='NOT_CHECKED'?'启动失败，尚未进入登录检查':({NOT_CHECKED:'本次尚未检查；仅浏览缓存不需要登录',LOGIN_CHECK:'正在检查',LOGIN_REQUIRED:'等待官方正常登录',LOGIN_AUTHENTICATED:'本次研究已确认登录',EXPIRED_OR_REQUIRED:'会话失效或需要登录，已停止'} as Record<string,string>)[task.login_state]||task.login_state}}。不同来源内容重复 {{task.duplicate_body_count}} 篇，不重复提取，也不算新覆盖。</p>
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
  <aside v-if="!active&&conversation?.pending_question" class="bubble assistant"><p>{{conversation.pending_question.text}}</p><template v-if="hasMaterial"><p>可选补充，不是开始研究的必填项；当前采用版不会覆盖。</p><button v-for="choice in conversation.pending_question.choices.filter(c=>c!=='继续补充研究'&&c!=='为什么推荐这些')" :key="choice" class="quiet" :disabled="busy||answering" @click="emit('talk','submit',undefined,choice)">{{choice}}</button><button class="quiet" :disabled="busy||answering" @click="emit('talk','message',undefined,'为什么推荐这些')">为什么推荐这些</button></template></aside>
  <details v-if="task?.query_progress.length"><summary>每轮研究进展</summary><p v-for="q in task.query_progress" :key="q.search_number">第{{q.search_number}}次搜索：返回{{q.observed_candidates??'尚未确认'}}条列表条目，尝试读取详情{{q.body_reads||0}}次，新增{{q.new_facts||0}}条去重后的合格引用。无新增信息不会计作覆盖改善。</p></details>
  <details v-if="task"><summary>高级：本次执行上限与用量</summary><p>上限：搜索{{task.limits.search}}次、正文{{task.limits.detail}}篇、模型{{task.limits.model}}次，连接{{task.limits.connect}}次；不调用地图、报价或embedding。覆盖满足本次研究目标后可提前停止，不自动重试。</p><p>已预留（失败也计数）：搜索{{task.budget?.used.search||0}}、正文{{task.budget?.used.detail||0}}、模型{{task.budget?.used.model||0}}。费用无法实时核算，次数上限不是价格承诺；本任务一小时内有效，结束即关闭。</p></details>
 </section>
</template>
<style scoped>.conversation-log{max-height:50vh;overflow:auto;display:flex;flex-direction:column;gap:.8rem}.bubble{padding:1rem;border-radius:16px;max-width:92%;background:#edf1ea}.bubble.user{align-self:flex-end;background:#e1ebf5}.composer{background:#fff;padding:.7rem;border-top:1px solid #d7dfd5}.composer p{font-size:.85rem}.compact{font-size:.75rem;padding:.2rem .4rem}.choices{border-top:1px solid #dde3db;margin-top:.6rem}.options{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:1rem}.option{border:1px solid #cbd4ca;border-radius:12px;padding:1rem}button{margin:.4rem .4rem .4rem 0}form{margin-top:1rem}small{display:block}li{margin:.5rem 0}details{margin-top:1rem}</style>
