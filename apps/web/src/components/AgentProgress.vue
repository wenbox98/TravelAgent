<script setup lang="ts">
import type {AutomaticTask} from '../planning-api'
defineProps<{task:AutomaticTask}>()
const label=(s:string)=>({CACHE:'复核本机资料',DECOMPOSE:'整理来源玩法与取舍',RESEARCH_GAP:'按缺口择读并审核来源正文',GENERATE:'生成可选择建议',KEY_LEG:'核实关键公共衔接',ANSWER:'结合缓存回答',FINISH:'结束本次循环'}[s]||s)
const fieldLabel=(s:string)=>({destination:'目的区域',days:'天数',arrival_transport:'到达方式',transport:'当地交通',driving:'驾驶意愿',rental:'租车意向',pace:'节奏',walking_allowed:'步行意愿',spatial:'活动范围',people:'人数',target_fen:'参考预算',activity_start:'首项开始',return_deadline:'返回截止',depart_at:'出发时间',return_by:'返回时间'}[s]||s)
const position=(task:AutomaticTask,field:string)=>task.understanding?.input_evidence?.find(e=>e.field===field)
const valueLabel=(field:string,value:unknown)=>value===null?'未定':field==='target_fen'&&typeof value==='number'?`${value/100}元参考目标`:field==='days'&&typeof value==='number'?`${value}天`:({UNKNOWN:'未定',YES:'是',NO:'否',AIR:'飞机',RAIL:'铁路',ROAD:'公路',SELF_DRIVE:'自己驾驶',PUBLIC_TRANSIT:'公共交通',WALKING:'步行',LOCAL_SERVICE:'当地服务待核实',RELAXED:'轻松',NORMAL:'常规',CITY_CORE:'市区',REGION:'区域旅行',UNDECIDED:'未定',true:'愿意步行',false:'不愿意步行'}[String(value)]||String(value))
</script>
<template>
 <section v-if="['PRIVATE_GOAL_AGENT_V3','PRIVATE_GOAL_AGENT_V4'].includes(task.protocol||'')" aria-label="需求理解与工具循环">
  <h3>需求理解与本次进展</h3>
  <p v-if="task.understanding?.status==='QUEUED'" role="status">正在等待模型理解。{{task.understanding.provisional?'当前规则结果仅为暂定，尚未确认理解完成。':'本条消息尚未理解完成；此前确认的条件继续有效。'}}</p>
  <p v-else-if="task.understanding?.status==='FAILED'" class="warning">模型理解未完成：{{task.understanding.reason}}。{{task.understanding.model_executed?'已尝试模型请求，结果未被采用。':'尚无已执行模型的记录。'}}没有自动重试。</p>
  <template v-else-if="task.understanding?.result">
   <p>{{task.understanding.result.summary}} · 来自本次模型理解，原话定位经程序校验。</p>
   <p v-if="['QUESTION','HYPOTHETICAL'].includes(task.understanding.result.intent)">这次是问题或假设，不修改当前条件，也不查新资料。</p>
   <details><summary>查看本条原话依据</summary><p v-for="u in task.understanding.result.updates" :key="u.field">{{fieldLabel(u.field)}}：{{valueLabel(u.field,u.value)}} · “{{u.quote}}”<template v-if="position(task,u.field)">（原话位置{{position(task,u.field)!.start}}–{{position(task,u.field)!.end}}）</template></p><p v-if="task.understanding.destination_field">目的区域字段：{{task.understanding.destination_field}}（来自你单独填写的字段，不伪造原话位置）</p></details>
   <p v-if="task.understanding.result.user_needs.length">可选补充：{{task.understanding.result.user_needs.join('；')}}。未提供的条件仍未知。</p>
  </template>
  <ol v-if="task.agent_rounds?.length"><li v-for="round in task.agent_rounds" :key="round.round"><strong>第{{round.round}}轮 · {{label(round.tool)}}</strong><p>{{round.reason}}</p><p>{{round.status==='DISPATCHED'?'正在执行；刷新不会重复派发':round.result?.status||round.result?.reason||round.status}}</p><p v-if="round.result?.accepted!==undefined">本轮合格结果：{{round.result.accepted}}；保留来源条件，不代表现实已核实。</p></li></ol>
  <p v-if="task.coverage?.gaps.length">系统待研究：{{task.coverage.gaps.map(g=>g.label).join('；')}}。这些是资料缺口，不是要求你先填完整问卷。</p>
  <p>首次理解、每轮决策、提取审核和建议生成共用本次模型额度；任何失败都不会自动重试。已有可用初稿可先比较和采用。</p>
 </section>
</template>
