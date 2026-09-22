// ---------- 步骤与书 ----------
export type StepName = 'import' | 'split' | 'dedup' | 'cards' | 'entities' | 'threads' | 'archive'
export const STEPS: StepName[] = ['import', 'split', 'dedup', 'cards', 'entities', 'threads', 'archive']
export const STEP_LABELS: Record<StepName, string> = {
  import: '导入', split: '切场景', dedup: '查重', cards: '场景卡',
  entities: '实体合并', threads: '归线排序', archive: '档案+矛盾+地图',
}
/** 能通过 /steps/{step}/run 跑的。import 走单独的 /import 接口。 */
export const RUNNABLE: StepName[] = ['split', 'dedup', 'cards', 'entities', 'threads', 'archive']

export type StepStatus = 'todo' | 'running' | 'done' | 'failed' | 'outdated'

export interface StepState {
  status: StepStatus
  updated: string | null
  /** 每步自己的统计，形状按步骤不同。里头有 cost_usd，界面一律不渲染（spec 7.3）。 */
  summary: Record<string, unknown>
}

export interface BookSummary { name: string; title: string; created: string }

export interface BookMeta {
  name: string
  schema: number
  title: string
  created: string
  settings: Record<string, unknown>
  steps: Record<StepName, StepState>
  /** 原稿根目录名 → 上次导入时的来源文件夹完整路径 */
  roots: Record<string, string>
}

// ---------- 任务 ----------
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  id: string
  name: string
  book: string
  status: JobStatus
  done: number
  total: number
  message: string
  error: string
  result: Record<string, unknown> | null
  started: string
  finished: string
  cancel_requested: boolean
}

// ---------- 配置 ----------
/**
 * 核对过 src/ligaotai/config.py 的 TierConfig：不只是 model/max_tokens，
 * 还有 thinking（"on"/"off"/"default"）、effort（思考强度，空字符串=不传）、
 * json_mode。计划原稿只写了 model/max_tokens，这里按真实字段补全。
 */
export interface TierConfig {
  model: string
  thinking: 'on' | 'off' | 'default'
  effort: string
  json_mode: boolean
  max_tokens: number
  [k: string]: unknown
}

export interface PublicConfig {
  library_dir: string
  api_base: string
  /** 打码后的 key，形如 sk-…abcd */
  api_key: string
  concurrency: number
  timeout: number
  /** 后端保留、界面不渲染（spec 7.3） */
  price_input: number
  price_output: number
  batch: TierConfig
  synth: TierConfig
  has_key: boolean
  key_from_env: boolean
  library_path: string
}

// ---------- 场景与卡 ----------
export interface SceneMeta { id: string; [k: string]: unknown }

export interface CardRow {
  id: string
  fresh: boolean
  kind: string | null
  summary: string
  problems: number
  dropped: number
}

// ---------- 实体 ----------
export type EntityType = 'person' | 'location' | 'organization'
export type EntityStatus = 'draft' | 'confirmed' | 'single'

export interface Entity {
  id: string            // E-0001
  type: EntityType
  canonical: string
  names: string[]
  status: EntityStatus
  reason: string
  scenes: string[]
}

export interface EntitiesFile { next_id: number; entities: Entity[] }

/**
 * 跨批冲突。注意：**conflicts 不在 实体.json 里**，它只出现在步骤跑完的
 * summary 中，也就是 BookMeta.steps.entities.summary.conflicts。
 * 界面要从那儿读（spec 第 5 章「conflicts 必须单独列出给作者手动处理」）。
 */
export interface EntityConflict { type: EntityType; chunk: number; names: string[] }

// ---------- 归线 ----------
export interface World {
  id: string            // W-01
  name: string
  reason: string
  status: string
  notes: string[]
  outlines: unknown[]
}

export interface SceneTime {
  /** 线内故事时间。**可能是 null**——有场景估不出时间（spec 4.5）。 */
  t: number | null
  conf: string          // 高 / 中 / 低
}

export interface ThreadEnd {
  /** 真值是「完结」/「待定」。注意不是 thread.status。 */
  state: string
  note: string
  last: string
}

export interface Thread {
  id: string            // L-001
  world: string         // W-01
  name: string
  about: string
  /**
   * 核对过 src/ligaotai/threads.py:574（_thread_dict）：**不是恒为 "draft"**。
   * 实际是 `CONFIRMED if t.locked else DRAFT`——沿用自上一轮已确认结果的线会是
   * "confirmed"，新生成/未锁定的线才是 "draft"。别拿它判"完没完"，那个看 end.state；
   * 但也别当它恒定不变，它会随重跑切换。
   */
  status: string
  scenes: string[]
  times: Record<string, SceneTime>
  outlines: unknown[]   // 两本真书里都是空数组（spec 4.3）
  /**
   * 该线相对全局时间轴的偏移。全局时间 = offset + times[sid].t。
   * **可能是 null**：对齐失败 / 输入超预算跳过 / 模型没给这条线的偏移（`threads_check.py` 默认全 None，
   * 只有主线强制 0；`threads_ops.py` 改主线后非数字的也置 None）。null 的线**不能当 0**，
   * 不进全局轴、不画段、不定位缺口，见 `lib/segments.ts` 的 `isAligned`（审查 M2）。
   */
  offset: number | null
  end: ThreadEnd | null
  order_failed: boolean
}

export interface Intersection { thread: string; scene: string; main_scene: string; reason: string }

export interface Gap {
  id: string            // Q-001，每次重跑会重排，别拿它当稳定标识
  world: string
  event: string
  mentioned_in: string[]
  thread: string | null
  /** 场景编号，不是时间。两个都可能是 null（spec 4.4）。 */
  after: string | null
  before: string | null
}

export interface PendingScene { scene: string; thread: string; reason: string }
export interface UnassignedScene { scene: string; reason: string }

export interface ThreadsFile {
  next_world: number
  next_thread: number
  time_unit: string     // 实测是「年」
  main_thread: string
  main_by: string       // 核对过 threads.py：真实取值是 "auto" / "author"，不是 "manual"
  worlds: World[]
  threads: Thread[]
  intersections: Intersection[]
  gaps: Gap[]
  unassigned: UnassignedScene[]
  pending: PendingScene[]
}

// ---------- 版本组 ----------
export interface VersionGroup { id: string; [k: string]: unknown }
export interface VersionsFile { params: Record<string, unknown>; groups: VersionGroup[] }

// ---------- 档案与矛盾 ----------
export interface ArchiveEntry {
  /** 生成这份档案用的模型名。跟 current_model 不一致时提示作者（spec 第 5 章）。 */
  model?: string
  outdated?: boolean
  [k: string]: unknown
}

export interface ArchiveIndex {
  current_model: string
  [k: string]: unknown
}

export interface ContradictionsFile {
  groups: unknown[]
  stats: Record<string, unknown>
}
