<script setup lang="ts">
defineProps<{
  bookName: string
  bookTitle: string
  pendingEntities: number
  pendingThreads: number
  /** 计划④起：未裁决的严重矛盾数（不再是矛盾组总数），由 BookLayout 现算。 */
  contradictions: number
}>()
</script>

<template>
  <aside class="rail">
    <div class="brand">
      <b>理稿台</b>
      <small>长篇手稿整理与成书</small>
    </div>

    <div class="book">
      <div class="t">《{{ bookTitle }}》</div>
    </div>

    <nav>
      <RouterLink class="tab" :to="`/b/${bookName}/pipeline`">
        <span>理稿流水线</span><span class="step">1–7</span>
      </RouterLink>
      <RouterLink
        v-if="pendingEntities > 0"
        class="tab sub"
        :to="`/b/${bookName}/pipeline/entities`"
      >
        <span>↳ 实体确认</span><span class="n" data-test="实体角标">{{ pendingEntities }}</span>
      </RouterLink>
      <!-- 归线页常驻（9-22 作者定）：除了处理待办，线改名 / 设为主线平时也要用，收起就没入口了 -->
      <RouterLink
        class="tab sub"
        :to="`/b/${bookName}/pipeline/threads`"
      >
        <span>↳ 归线确认</span><span v-if="pendingThreads > 0" class="n" data-test="归线角标">{{ pendingThreads }}</span>
      </RouterLink>

      <RouterLink class="tab" :to="`/b/${bookName}/panorama`"><span>全景</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/scenes`"><span>场景浏览</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/archive`"><span>设定库</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/contradictions`">
        <span>矛盾</span>
        <span v-if="contradictions > 0" class="n" data-test="矛盾角标">{{ contradictions }}</span>
      </RouterLink>

      <div class="group" data-test="取舍组">
        <div class="glabel">取舍</div>
        <RouterLink class="tab" :to="`/b/${bookName}/board`"><span>取舍看板</span></RouterLink>
        <RouterLink class="tab" :to="`/b/${bookName}/skeleton`"><span>成书骨架</span></RouterLink>
      </div>
    </nav>

    <div class="foot">
      <RouterLink to="/">书架</RouterLink>
      ·
      <RouterLink to="/settings">设置</RouterLink>
    </div>
  </aside>
</template>

<style scoped>
.brand{padding:0 8px}
.brand b{font-family:var(--serif);font-size:22px;letter-spacing:.08em;display:block;line-height:1.2}
.brand small{color:var(--ink-3);font-size:12px}
.book{padding:10px 8px;border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2)}
.book .t{font-family:var(--serif);font-size:15px}
nav{display:flex;flex-direction:column;gap:2px}
.tab{
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:8px 10px;border-radius:6px;text-decoration:none;color:var(--ink-2);
}
.tab:hover{background:var(--sunk);color:var(--ink)}
.tab.router-link-active{background:var(--accent-soft);color:var(--accent);font-weight:500}
.tab.sub{padding:4px 10px 4px 22px;font-size:13px}
.step{color:var(--ink-3);font-size:12px}
.n{color:var(--red);font-size:12px;font-variant-numeric:tabular-nums}
.group{margin-top:10px;padding-top:8px;border-top:1px solid var(--line-2);display:flex;flex-direction:column;gap:2px}
.glabel{font-size:12px;color:var(--ink-3);padding:0 10px 4px}
.foot{margin-top:auto;padding:0 8px;color:var(--ink-3);font-size:12px}
.foot a{color:var(--ink-3);text-decoration:none}
.foot a:hover{color:var(--accent)}
</style>
