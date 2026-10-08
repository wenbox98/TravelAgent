<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {request} from '../api'
import {mapLabel} from '../route-api'
import type {PlanView} from '../planning-api'
import PlaceChoices from './PlaceChoices.vue'
const props=defineProps<{plan:PlanView;busy:boolean}>()
const emit=defineEmits<{updated:[value:PlanView];mode:[value:string]}>()
const busy=ref(false),error=ref(''),pair=ref(''),confirmed=ref(false),date=ref('')
const value=computed(()=>props.plan.critical_map!)
watch(()=>value.value.intent_key,key=>{try{const pending=JSON.parse(localStorage.getItem('ta-key-leg-intent')||'null');if(pending?.key===key)localStorage.removeItem('ta-key-leg-intent')}catch{}},{immediate:true})
watch(()=>[props.plan.session_id,props.plan.revision],()=>{if(!value.value.pairs.some(p=>p.leg_id===pair.value))pair.value=value.value.pairs[0]?.leg_id||'';confirmed.value=false},{immediate:true})
async function act(action:string,patch:Record<string,unknown>={}){
 if(busy.value||props.busy)return
 busy.value=true;error.value=''
 const body={action,expected_revision:props.plan.revision,...patch}
 const url='/api/v1/preview/key-leg/'+props.plan.session_id
 const signature=JSON.stringify([url,body]);let key:string=crypto.randomUUID()
 try{
  const pending=JSON.parse(localStorage.getItem('ta-key-leg-intent')||'null') as {signature:string;key:string}|null
  if(pending&&pending.signature===signature)key=pending.key
  else if(pending){error.value='上次结果尚未确认，请先刷新本地状态；不会重复查询。';return}
  localStorage.setItem('ta-key-leg-intent',JSON.stringify({signature,key}))
  emit('updated',await request<PlanView>(url,body,key));localStorage.removeItem('ta-key-leg-intent')
 }catch(e){error.value=e instanceof Error?e.message:'结果尚未确认，请读取已保存状态。';if(e instanceof Error&&'status' in e&&Number(e.status)>0)localStorage.removeItem('ta-key-leg-intent')}
 finally{busy.value=false}
}
</script>
<template><section class="card" aria-label="关键路段核实"><h2>先核实一段关键移动</h2><p>{{value.meaning}}</p>
 <p v-if="error" class="warning" role="alert">{{error}}</p><p v-for="g in value.gaps" :key="g">待补充：{{g}}</p>
 <label v-if="plan.draft.activities.length>=2">本次核实哪种交通<select :value="plan.draft.inputs.mode" :disabled="busy||props.busy" @change="emit('mode',($event.target as HTMLSelectElement).value)"><option value="UNKNOWN">先保持未知</option><option value="TRANSIT">公共交通</option><option value="WALKING">步行</option><option value="DRIVING">自己驾车</option></select></label>
 <p v-if="!value.configured">高德服务尚未配置。可以先选择玩法；本页不会为此探测Key。</p>
 <template v-if="value.ready&&!value.active"><label>先查看哪一段<select v-model="pair" :disabled="busy||props.busy"><option v-for="p in value.pairs" :key="p.leg_id" :value="p.leg_id">第{{p.day}}天 · {{p.names.join(' → ')}}</option></select></label><label><input v-model="confirmed" type="checkbox" />确认这个公共地点顺序；本次允许向高德发送必要公共名称与适用时间，最多地点2次、路径1次，旧账本保留，无自动重试。</label><button :disabled="busy||props.busy||!confirmed||!value.configured" @click="act('start',{leg_id:pair,consent:'PRIVATE_KEY_LEG_V1'})">核实这段地点（最多2次）</button></template>
 <template v-if="value.current&&value.task"><h3>{{value.task.names.join(' → ')}}</h3><p>地点余额{{value.remaining.map_place}}次；路径余额{{value.remaining.map_route}}次。地点身份需你核对；名称相同不会自动确认。</p>
  <button v-if="value.active" class="quiet" :disabled="busy||props.busy||value.remaining.map_place===0" @click="act('resolve')">查询这两个公共地点（至多2次）</button>
  <PlaceChoices :places="value.places||[]" :busy="busy||props.busy||!value.active" :can-query="false" :same-return="false" @action="(action,patch)=>action==='confirm_place'&&act('confirm',patch)" />
  <label v-if="value.active">这段出发日期时间（未定可留空，返回一般参考）<input v-model="date" type="datetime-local" /></label>
  <button v-if="value.active" :disabled="busy||props.busy||value.remaining.map_route===0||(value.places||[]).filter(p=>p.confirmed).length!==2" @click="act('route',{leg_depart_at:date||null})">核实这段移动参考（1次）</button>
  <p v-if="value.leg">{{mapLabel(value.leg.mode)}} · {{mapLabel(value.leg.status)}}<span v-if="value.leg.duration_seconds!==null&&!value.leg.stale"> · 高德估算约{{Math.ceil(value.leg.duration_seconds/60)}}分钟</span>。未知停留、接驳、班次与假期变化未计作零，不代表整趟已验证。</p>
  <p v-if="value.map_result_state==='EXPIRED_OR_NOT_QUERIED'">未查询或临时结果已过期。重启与刷新不会重新查询。</p><button v-if="value.active" class="quiet" :disabled="busy||props.busy" @click="act('close')">结束本次路段核实</button>
 </template>
</section></template>
