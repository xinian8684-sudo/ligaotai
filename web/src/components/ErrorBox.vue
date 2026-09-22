<script setup lang="ts">
defineProps<{ message: string }>()
</script>

<template>
  <div v-if="message" class="err" role="alert">
    <b>出错了</b>
    <pre>{{ message }}</pre>
  </div>
</template>

<style scoped>
.err{
  border:1px solid var(--red); background:var(--red-soft); color:var(--ink);
  border-radius:6px; padding:10px 12px; margin:12px 0;
}
.err b{color:var(--red);display:block;margin-bottom:4px}
.err pre{margin:0;white-space:pre-wrap;font-family:var(--mono);font-size:12px}
</style>
