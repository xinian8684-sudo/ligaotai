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
/**
 * 核对过 src/ligaotai/scenes.py 的 Scene.meta()（asdict 去掉 text）+ 实测
 * GET /scenes、GET /scenes/{sid} 的真实返回。列表接口只给 meta，详情接口
 * 在 meta 基础上加一个 text 字段（见 SceneDetail）。
 */
export interface SceneMeta {
  id: string          // S-0001
  source: string       // 来自哪个原稿文件
  index: number        // 在该文件里第几块
  start: number
  end: number
  chars: number
  hash: string
  heading: string
  part: number
  kind_hint: string
  stale: boolean        // 场景卡该重做了（原文变了、卡还没跟上）
  removed: boolean       // 这次没切出来，编号不回收，界面一般应该过滤掉
}

export interface SceneDetail extends SceneMeta { text: string }

export interface CardRow {
  id: string
  fresh: boolean
  kind: string | null
  summary: string
  problems: number
  dropped: number
}

/** 场景卡里一条人物 / 一条事实。核对过 src/ligaotai/cards.py 的 Character / Fact。 */
export interface CardCharacter { name: string; role: '主要' | '次要' | '提及' }
export interface CardFact { subject: string; attribute: string; value: string; quote: string }

/**
 * 场景卡正文（src/ligaotai/cards.py 的 Card，model_dump() 之后的形状）。
 * `GET /cards/{sid}` 整份返回的 `card` 字段就是这个。
 */
export interface Card {
  summary: string
  pov: string
  characters: CardCharacter[]
  locations: string[]
  organizations: string[]
  world_hint: string
  time_hints: string[]
  events: string[]
  facts: CardFact[]
  hooks_planted: string[]
  hooks_resolved: string[]
  refs_elsewhere: string[]
  incomplete: boolean
  incomplete_note: string
  kind: '正文' | '提纲' | '设定笔记' | '碎片'
}

/**
 * `GET /cards/{sid}` 的整份返回（load_card 直接读盘）。跟列表接口 CardRow 不是一回事：
 * 这里是完整卡片，CardRow 是给列表用的摘要投影。手改坏的文件字段可能缺，界面要能扛。
 */
export interface CardRecord {
  id: string
  scene_hash: string
  model?: string
  created?: string
  problems?: string[]
  dropped?: { facts?: unknown[]; names?: unknown[]; attrs?: number; long_values?: number }
  card: Card
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
  /** 这条线最后一个场景。线里一个场景都没有时后端给 null（`_thread_dict`：`t.scenes[-1] if t.scenes else None`）。 */
  last: string | null
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

export interface Intersection { thread: string; scene: string; main_scene: string; reason: string; same_time?: boolean }

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
  /** 时间单位。两本验收书是「年」，但还没跑步骤 6 / normalize 兜底时是空串 `""`，界面拼单位要兜底。 */
  time_unit: string
  /** 主线 id。还没跑步骤 6 时 GET /threads 返回的就是 null（`threads.py` EMPTY / normalize）。 */
  main_thread: string | null
  main_by: string       // 核对过 threads.py：真实取值是 "auto" / "author"，不是 "manual"
  worlds: World[]
  threads: Thread[]
  intersections: Intersection[]
  gaps: Gap[]
  unassigned: UnassignedScene[]
  pending: PendingScene[]
}

// ---------- 版本组 ----------
/** 核对过 src/ligaotai/dedup.py 的 run()：groups.append({...}) 那段。 */
export interface VersionPair { a: string; b: string; jaccard: number; containment: number }
export interface VersionGroup {
  id: string            // G-001
  members: string[]      // 场景 id，含主版本自己
  main: string           // 当前主版本的场景 id
  main_by: 'auto' | 'author'
  pairs: VersionPair[]
}
export interface VersionsFile { params: Record<string, unknown>; groups: VersionGroup[] }

// ---------- 档案与矛盾 ----------
/**
 * 核对过 src/ligaotai/archive.py 的 load_index()：threads/worlds 下每条、
 * 以及 map 本身，形状一致。`scenes`/`world` 只有支线档案条目有；世界条目和 map 没有。
 * 老档案可能没有 `model`（这个字段是后补的），界面要能扛（Task 22 测试钉着这条）。
 */
export interface ArchiveEntry {
  file: string
  sig: string
  outdated: boolean
  generated: string
  /** 生成这份档案用的模型名。跟 current_model 不一致时提示作者（spec 第 5 章）。 */
  model?: string
  /** 只有支线档案条目有：这条线包含哪些场景。 */
  scenes?: string[]
  /** 只有支线档案条目有：这条线所属的世界。 */
  world?: string
}

export interface ArchiveIndex {
  threads: Record<string, ArchiveEntry>
  worlds: Record<string, ArchiveEntry>
  /** 全书地图只有一份，不是按 id 存的字典。 */
  map: ArchiveEntry
  /** 当前配置里的模型名，跟每份档案的 model 比对用（GET /archive 拼进去的，I2）。 */
  current_model: string
  [k: string]: unknown
}

export type ContradictionStatus = '真矛盾' | '合理变化' | '无法判断'
export type ContradictionLevel = '严重' | '中等' | '轻微' | ''
export type ContradictionCategory = '人物' | '设定' | '时间' | '称谓'

export interface ContradictionSceneRef {
  id: string
  quote: string
  thread: string
  /** 全局故事时间，线没对齐 / 没估出来时是 null（跟 lib/segments.ts 同一个 null 语义）。 */
  t: number | null
  conf: string
}

export interface ContradictionValue {
  value: string
  scenes: ContradictionSceneRef[]
}

/**
 * 核对过 src/ligaotai/contradictions.py 的 build_result()。`verdict_sig` /
 * `verdict_stale` 是 ②c 之后新加的字段，7.2 节文档还没写进去——以代码为准（任务书原话）。
 * 一期界面只展示，`verdict` 永远是 null，不做裁决。
 */
export interface ContradictionGroup {
  id: string             // C-001
  subject: string
  attribute: string
  status: ContradictionStatus
  level: ContradictionLevel
  category: ContradictionCategory
  reason: string
  values: ContradictionValue[]
  values_sig: string
  /** 二期起作者裁决写这里（计划④ spec 第 5 节）。 */
  verdict: Verdict | null
  verdict_sig: string | null
  /** 上一次判定依据的值集合跟现在不一样了（多了新值 / 原来的值消失了），要标出来重看。 */
  verdict_stale: boolean
}

export interface ContradictionsFile {
  generated?: string
  next_id?: number
  groups: ContradictionGroup[]
  skipped?: { subject: string; attribute: string; reason: string }[]
  orphan_verdicts?: unknown[]
  id_registry?: unknown[]
  /** 里头有计数统计，没有任何费用字段——contradictions.py 的 stats 只统计条数。 */
  stats: Record<string, unknown>
}

// ---- 二期：取舍（计划④）----

/** 不是流水线步骤的任务名（submit 时的 name），JobBar 显示用。 */
export const EXTRA_JOB_LABELS: Record<string, string> = {
  triage_advice: 'AI 取舍建议',
  triage_impact: '影响检查',
  skeleton: '生成骨架',
}

export type VerdictKind = 'pick' | 'own' | 'later'
export interface Verdict { kind: VerdictKind; value?: string; note?: string; by: string; at: string }
export interface VerdictReq { kind: VerdictKind | null; value?: string; note?: string }
export interface CanonItem { id: string; subject: string; attribute: string; value: string; sources: string[]; note: string }
export interface CanonFile { generated: string; items: CanonItem[] }
export interface Followups { id: string; verdict: Verdict | null; scenes: { id: string; quote: string; value: string }[] }

export type BoardCol = 'keep' | 'merge' | 'cut' | 'undecided'
export interface BoardCard { col: BoardCol; merge_into: string | null; note: string; orphan: boolean; merge_invalid: boolean }
export interface ThreadStat {
  name: string; world: string; words: number; scenes: number; state: string
  gaps: number; is_main: boolean; order_failed: boolean
}
export type AdviceKind = 'keep' | 'merge' | 'cut' | 'flashback'
export interface AdviceItem { thread: string; advice: AdviceKind; merge_into?: string | null; reason: string }
export interface AdviceStatus { generated: string; sig: string; items: AdviceItem[]; stale: boolean }
export interface BoardView { cards: Record<string, BoardCard>; stats: Record<string, ThreadStat>; advice: AdviceStatus | null }
export interface CardReq { col: BoardCol; merge_into?: string | null; note?: string | null }

export interface ProgramImpact {
  thread: string
  crossings: { other: string; scene: string; main_scene: string; reason: string }[]
  only_characters: { name: string; scenes: string[] }[]
  maybe_refs: { scene: string; thread: string; text: string; names: string[] }[]
}
export interface ModelImpact {
  sig: string; generated: string; stale: boolean; remedy: string
  pairs: { planted: string; resolved: string; hook: string }[]
}
export interface ImpactView { program: ProgramImpact; model: ModelImpact | null }

/**
 * 后端 skeleton.annotate() 实际会打的 flag（核对过 src/ligaotai/skeleton.py 的 mark()）：
 * 计划原稿只写了 missing/cut，漏了换过主版本这种（not_main）——真实后端已经在打这个值。
 */
export type SkFlag = 'missing' | 'not_main' | 'cut'
/**
 * S2：GET /skeleton（annotate() 的返回）才有 summary/thread_name——只读的界面标注
 * （场景卡摘要前 30 字、线的名字），PUT 会被 _strip_flags 剥掉，别指望它们能存住。
 */
export interface SkScene { type: 'scene'; id: string; thread?: string | null; flag?: SkFlag; summary?: string; thread_name?: string }
export interface SkHole {
  type: 'hole'; id: string; task: string; gap?: string | null; after?: string | null; before?: string | null
  event?: string; thread?: string | null; mentioned_in?: string[]
}
export type SkItem = SkScene | SkHole
export interface SkNote { kind: 'undecided' | 'merge' | 'cut_crossing'; thread: string; into?: string; scene?: string }
export interface SkChapter { title: string; items: SkItem[]; notes: SkNote[] }
export interface SkVolume { title: string; chapters: SkChapter[] }
export interface SkUnplacedScene { id: string; thread: string | null; why: string; flag?: SkFlag; summary?: string; thread_name?: string }
export interface Skeleton {
  generated: string; by: 'program' | 'author'; edited?: string; fallback_chapters?: boolean
  volumes: SkVolume[]
  unplaced: { scenes: SkUnplacedScene[]; holes: (SkHole & { why?: string })[] }
  /**
   * 只有 GET /skeleton（annotate() 的返回）才有：按现在的线应该在书里、骨架里却找不到的
   * 场景编号（src/ligaotai/skeleton.py 的 annotate()，见 p4/context.md）。计划原稿没写这个字段。
   */
  absent?: string[]
}
export interface ExportResult {
  md: string; txt: string; scenes: number; holes: number; missing: number
  /**
   * 计划原稿漏了这两个字段——核对过 src/ligaotai/export.py 的 export_book()，
   * counts 实际是 {scenes, holes, missing, chars, cut} 五项都会返回。
   */
  chars: number; cut: number
}
