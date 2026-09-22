<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { listBooks, getBook, createBook, importFolder } from '@/api/endpoints'
import type { BookSummary, BookMeta } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const jobStore = useJobStore()

const books = ref<BookSummary[]>([])
const loading = ref(true)
const error = ref('')

const newTitle = ref('')
const creating = ref(false)

const 当前书 = ref<BookMeta | null>(null)
const 来源文件夹 = ref('')
const importing = ref(false)

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : String(e)
}

async function 加载列表(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    books.value = await listBooks()
  } catch (e) {
    报错(e)
  } finally {
    loading.value = false
  }
}

onMounted(加载列表)

async function 新建(): Promise<void> {
  const title = newTitle.value.trim()
  if (!title) return
  creating.value = true
  error.value = ''
  try {
    await createBook(title)
    newTitle.value = ''
    await 加载列表()
  } catch (e) {
    报错(e)
  } finally {
    creating.value = false
  }
}

async function 选书(b: BookSummary): Promise<void> {
  error.value = ''
  来源文件夹.value = ''
  try {
    当前书.value = await getBook(b.name)
  } catch (e) {
    报错(e)
  }
}

/** 取路径的文件夹名。这是 Windows 工具，分隔符是 `\`，不能只按 `/` 切。 */
function 取名(p: string): string {
  const s = p.replace(/[\\/]+$/, '')
  const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'))
  return i >= 0 ? s.slice(i + 1) : s
}

const 同名提醒 = computed(() => {
  const b = 当前书.value
  const folder = 来源文件夹.value.trim()
  if (!b || !folder) return null
  const name = 取名(folder)
  const existing = b.roots[name]
  if (existing && existing !== folder) return { name, existing }
  return null
})

async function 导入(): Promise<void> {
  const b = 当前书.value
  const folder = 来源文件夹.value.trim()
  if (!b || !folder) return
  importing.value = true
  error.value = ''
  try {
    await importFolder(b.name, folder)
    当前书.value = await getBook(b.name)
  } catch (e) {
    报错(e)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="page">
    <h1>书架</h1>
    <ErrorBox :message="error" />

    <section class="new">
      <input v-model="newTitle" placeholder="书名" data-test="新书名" @keyup.enter="新建" />
      <button data-test="新建" :disabled="jobStore.busy || creating || !newTitle.trim()" @click="新建">
        新建
      </button>
    </section>

    <div v-if="loading">加载中…</div>
    <div v-else-if="books.length === 0" class="empty">
      还没有书。填个书名建一本，然后选文件夹导入。
    </div>
    <ul v-else class="books">
      <li v-for="b in books" :key="b.name">
        <RouterLink :to="`/b/${b.name}/pipeline`">{{ b.title }}</RouterLink>
        <span class="created">{{ b.created }}</span>
        <button data-test="选书" @click="选书(b)">导入原稿</button>
      </li>
    </ul>

    <section v-if="当前书" class="import">
      <h2>导入原稿——《{{ 当前书.title }}》</h2>
      <label>
        来源文件夹（浏览器拿不到本地路径，填完整路径，比如 D:\我的稿子）
        <input v-model="来源文件夹" placeholder="D:\我的稿子" data-test="来源文件夹" />
      </label>
      <p v-if="同名提醒" class="warn">
        ⚠ 这本书里已经有一个叫「{{ 同名提醒.name }}」的原稿目录，上次是从 {{ 同名提醒.existing }} 导入的。
        从不同位置的同名文件夹导入会覆盖它，并算作「改动」。
      </p>
      <button
        data-test="导入"
        :disabled="jobStore.busy || importing || !来源文件夹.trim()"
        @click="导入"
      >
        导入
      </button>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:720px}
h1{font-family:var(--serif);font-size:22px;margin:0 0 16px}
.new{display:flex;gap:8px;margin-bottom:20px}
.empty{color:var(--ink-3);padding:24px 0}
.books{list-style:none;padding:0;margin:0}
.books li{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line-2)}
.books .created{color:var(--ink-3);font-size:12px;margin-left:auto}
.import{margin-top:24px;padding:16px;border:1px solid var(--line-2);border-radius:8px}
.import label{display:block;font-size:13px;color:var(--ink-2);margin-bottom:8px}
.import input{width:100%;margin-top:4px}
.warn{color:var(--amber);background:var(--amber-soft);border-radius:6px;padding:8px 10px;font-size:13px}
</style>
