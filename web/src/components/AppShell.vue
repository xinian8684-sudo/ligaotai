<script setup lang="ts">
import NavRail from './NavRail.vue'

defineProps<{
  bookName: string
  bookTitle: string
  pendingEntities: number
  pendingThreads: number
  contradictions: number
}>()
</script>

<template>
  <div class="app">
    <NavRail
      :book-name="bookName"
      :book-title="bookTitle"
      :pending-entities="pendingEntities"
      :pending-threads="pendingThreads"
      :contradictions="contradictions"
    />
    <main class="main"><slot /></main>
  </div>
</template>
