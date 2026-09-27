<script setup lang="ts">
import { ref, watch } from 'vue'
import { mapLabel, type MapPlace, type MapCandidate } from '../route-api'
const props = defineProps<{places: MapPlace[]; busy: boolean; canQuery: boolean; sameReturn: boolean; synthetic?: boolean}>()
const emit = defineEmits<{action: [action: string, patch: Record<string, unknown>]}>()
const expanded = ref<Record<string, boolean>>({})
const relation = (c: MapCandidate) => c.object_type === 'AREA' ? 'REGIONAL_REFERENCE' : c.object_type === 'ENTRANCE' || c.object_type === 'PARKING' ? 'ACCESS_POINT' : 'SAME_OBJECT'
const recommended = (p: MapPlace, c: MapCandidate) => p.candidates.filter(x => x.name === p.name && !!p.region && (x.cityname === p.region || x.adname === p.region) && p.object_type !== 'UNKNOWN' && x.object_type === p.object_type).length === 1 && c.name === p.name && (c.cityname === p.region || c.adname === p.region) && c.object_type === p.object_type
watch(() => props.places.map(p => p.confirmed?.candidate_id).join(','), () => { expanded.value = {} })
</script>
<template>
  <article v-for="p in places" :key="p.place_id" class="map-place">
    <template v-if="sameReturn && p.place_id === 'return'"><h4>返程 · {{ p.name }}</h4><p>复用出发点的同一地点身份与确认。返程路段保留，耗时须另核实。</p></template>
    <template v-else><h4>{{ p.name }}</h4><p v-if="p.confirmed">已选：{{ p.confirmed.name }} · {{ p.confirmed.cityname }} {{ p.confirmed.adname }} · {{ mapLabel(p.confirmed.relation || 'UNKNOWN') }}</p>
      <button v-if="p.confirmed" class="quiet" :disabled="busy" @click="expanded[p.place_id] = !expanded[p.place_id]">{{ expanded[p.place_id] ? '收起备选' : '重新选择' }}</button>
      <template v-if="!p.confirmed || expanded[p.place_id]">
        <button v-if="!p.candidates.length" class="quiet" :disabled="busy || !canQuery" @click="emit('action', 'resolve', {place_id:p.place_id})">{{ synthetic ? '查看合成候选（本地）' : '查询这个地点（1次）' }}</button>
        <p v-if="p.candidates.length > 1">有多个地区或对象候选，请核对具体位置。名称相同不代表同一地点。</p>
        <div v-for="c in p.candidates" :key="c.candidate_id" class="map-candidate"><strong>{{ c.name }}</strong><p>{{ c.cityname }} {{ c.adname }} · {{ mapLabel(c.object_type) }}</p><p v-if="recommended(p,c)">推荐匹配（尚未经你确认）</p><details><summary>位置和对象依据</summary><p>{{ c.pname }} · {{ c.address }} · {{ c.type }}</p><a v-if="!synthetic" :href="c.uri" target="_blank" rel="noopener noreferrer">在高德查看</a></details><button :disabled="busy" @click="emit('action', 'confirm_place', {place_id:p.place_id, candidate_id:c.candidate_id, relation:relation(c)})">{{ c.object_type === 'AREA' ? '选择这个区域参考' : c.object_type === 'ENTRANCE' || c.object_type === 'PARKING' ? '选择这个接入点' : '选择这个地点' }}</button></div>
      </template>
    </template>
  </article>
</template>
<style scoped>.map-place {border-top:1px solid #d7dfd5;padding:1rem 0}.map-candidate{border-left:3px solid #8ea68b;padding:.7rem 1rem;margin:.6rem 0}</style>
