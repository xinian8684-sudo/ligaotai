<script setup lang="ts">
import { computed } from 'vue'
import { splitRefs } from '@/lib/sceneRefs'

/** 文字里的场景编号（S-0030）渲染成链接，点了跳到场景浏览并选中那一块。其余文字原样输出。 */
const props = defineProps<{ text: string; book: string }>()
const parts = computed(() => splitRefs(props.text ?? ''))
</script>

<template>
  <template v-for="(p, i) in parts" :key="i">
    <RouterLink v-if="p.id" class="sref" :to="{ name: 'scenes', params: { name: book }, query: { s: p.id } }"
                :data-test="`场景链接-${p.id}`">{{ p.id }}</RouterLink>
    <template v-else>{{ p.text }}</template>
  </template>
</template>

<style scoped>
.sref{color:var(--accent);text-decoration:underline dotted;text-underline-offset:2px;font-family:var(--mono);cursor:pointer}
.sref:hover{text-decoration-style:solid}
</style>
