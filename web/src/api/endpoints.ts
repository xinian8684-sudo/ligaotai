import { del, get, post, put } from './client'
import type {
  ArchiveIndex, BoardCard, BoardView, BookMeta, BookSummary, CanonFile, CardRecord, CardReq, CardRow,
  ContradictionGroup, ContradictionsFile, EntitiesFile, ExportResult, Followups, ImpactView,
  Job, PublicConfig, SceneDetail, SceneMeta, Skeleton, StepName, ThreadsFile, VerdictReq,
  VersionsFile,
} from './types'

const b = (name: string) => `/books/${encodeURIComponent(name)}`

// 健康与配置
export const health = () => get<{ ok: boolean; version: string }>('/health')
export const getConfig = () => get<PublicConfig>('/config')
export const putConfig = (cfg: unknown) => put<PublicConfig>('/config', cfg)
export const testConfig = () => post<unknown[]>('/config/test')

// 书
export const listBooks = () => get<BookSummary[]>('/books')
export const createBook = (title: string) => post<BookMeta>('/books', { title })
export const getBook = (name: string) => get<BookMeta>(b(name))
export const importFolder = (name: string, folder: string) => post<Job>(`${b(name)}/import`, { folder })

// 步骤与任务
export const runStep = (name: string, step: StepName) => post<Job>(`${b(name)}/steps/${step}/run`)
export const currentJob = () => get<Job | null>('/jobs/current')
export const getJob = (id: string) => get<Job>(`/jobs/${id}`)
export const cancelJob = (id: string) => post<Job>(`/jobs/${id}/cancel`)

// 场景与卡
export const listScenes = (name: string, includeRemoved = false) =>
  get<SceneMeta[]>(`${b(name)}/scenes?include_removed=${includeRemoved}`)
export const getScene = (name: string, sid: string) => get<SceneDetail>(`${b(name)}/scenes/${sid}`)
export const listCards = (name: string) => get<CardRow[]>(`${b(name)}/cards`)
export const getCard = (name: string, sid: string) => get<CardRecord>(`${b(name)}/cards/${sid}`)
export const regenerateCard = (name: string, sid: string) => post<Job>(`${b(name)}/cards/${sid}/regenerate`)

// 实体
export const getEntities = (name: string) => get<EntitiesFile>(`${b(name)}/entities`)
export const confirmEntities = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/entities/confirm`, { ids })
export const mergeEntities = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/entities/merge`, { ids })
export const updateEntity = (name: string, eid: string, body: unknown) => put<unknown>(`${b(name)}/entities/${eid}`, body)
export const splitEntity = (name: string, eid: string, body: unknown) => post<unknown>(`${b(name)}/entities/${eid}/split`, body)

// 归线
export const getThreads = (name: string) => get<ThreadsFile>(`${b(name)}/threads`)
export const confirmThreads = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/threads/confirm`, { ids })
/** 拒绝模型的归入建议：这些块从 pending 挪进 unassigned，落盘。 */
export const rejectPending = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/threads/reject`, { ids })
export const setMainThread = (name: string, body: unknown) => put<unknown>(`${b(name)}/threads/main`, body)
export const mergeThreads = (name: string, body: unknown) => post<unknown>(`${b(name)}/threads/merge`, body)
export const renameThread = (name: string, oid: string, body: unknown) => put<unknown>(`${b(name)}/threads/${oid}/name`, body)
export const moveScenes = (name: string, tid: string, body: unknown) => post<unknown>(`${b(name)}/threads/${tid}/scenes`, body)
export const splitThread = (name: string, tid: string, body: unknown) => post<unknown>(`${b(name)}/threads/${tid}/split`, body)
export const setThreadWorld = (name: string, tid: string, body: unknown) => put<unknown>(`${b(name)}/threads/${tid}/world`, body)

// 版本组与原稿
export const getVersions = (name: string) => get<VersionsFile>(`${b(name)}/versions`)
export const setMainVersion = (name: string, gid: string, sceneId: string) =>
  put<unknown>(`${b(name)}/versions/${gid}/main`, { scene_id: sceneId })
export const getSource = (name: string, path: string) =>
  get<{ path: string; encoding: string; text: string }>(`${b(name)}/source?path=${encodeURIComponent(path)}`)

// 档案与矛盾
export const getArchiveIndex = (name: string) => get<ArchiveIndex>(`${b(name)}/archive`)
export const getArchiveBody = (name: string, kind: 'thread' | 'world', oid: string) =>
  get<{ id: string; body: string }>(`${b(name)}/archive/${kind}/${encodeURIComponent(oid)}`)
/**
 * 全书地图正文。计划原稿的 getArchiveBody 只支持 kind=thread/world，没有给地图开路。
 * D4（Task 22）核对真实返回时发现 GET /archive/map 直接 404（没有匹配的后端路由），
 * 已在 src/ligaotai/api.py 补了这条独立路由（地图只有一份，不需要 oid）。
 */
export const getArchiveMap = (name: string) => get<{ id: string; body: string }>(`${b(name)}/archive/map`)
export const getContradictions = (name: string) => get<ContradictionsFile>(`${b(name)}/contradictions`)
export const rerunArchive = (name: string, body: unknown) => post<unknown>(`${b(name)}/archive/rerun`, body)

// 二期：裁决
export const putVerdict = (name: string, cid: string, body: VerdictReq) =>
  put<ContradictionGroup>(`${b(name)}/contradictions/${cid}/verdict`, body)
export const getCanon = (name: string) => get<CanonFile>(`${b(name)}/canon`)
export const getFollowups = (name: string, cid: string) => get<Followups>(`${b(name)}/contradictions/${cid}/followups`)

// 二期：看板
export const getBoard = (name: string) => get<BoardView>(`${b(name)}/triage/board`)
export const putCard = (name: string, tid: string, body: CardReq) =>
  put<{ cards: Record<string, BoardCard> }>(`${b(name)}/triage/board/${tid}`, body)
export const deleteCard = (name: string, tid: string) =>
  del<{ cards: Record<string, BoardCard> }>(`${b(name)}/triage/board/${tid}`)
export const runAdvice = (name: string) => post<Job>(`${b(name)}/triage/advice`)
export const getImpact = (name: string, tid: string) => get<ImpactView>(`${b(name)}/triage/impact/${tid}`)
export const runImpact = (name: string, tid: string) => post<Job>(`${b(name)}/triage/impact/${tid}`)

// 二期：骨架与导出
export const getSkeleton = (name: string) => get<Skeleton>(`${b(name)}/skeleton`)
export const putSkeleton = (name: string, sk: Skeleton) => put<Skeleton>(`${b(name)}/skeleton`, sk)
export const generateSkeleton = (name: string) => post<Job>(`${b(name)}/skeleton/generate`)
export const exportBook = (name: string) => post<ExportResult>(`${b(name)}/export`)
export const exportUrl = (name: string, fmt: 'md' | 'txt') => `/api${b(name)}/export/${fmt}`
