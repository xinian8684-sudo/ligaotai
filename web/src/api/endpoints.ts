import { get, post, put } from './client'
import type {
  ArchiveIndex, BookMeta, BookSummary, CardRow, ContradictionsFile,
  EntitiesFile, Job, PublicConfig, SceneMeta, StepName, ThreadsFile, VersionsFile,
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
export const getScene = (name: string, sid: string) => get<unknown>(`${b(name)}/scenes/${sid}`)
export const listCards = (name: string) => get<CardRow[]>(`${b(name)}/cards`)
export const getCard = (name: string, sid: string) => get<unknown>(`${b(name)}/cards/${sid}`)
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
export const getContradictions = (name: string) => get<ContradictionsFile>(`${b(name)}/contradictions`)
export const rerunArchive = (name: string, body: unknown) => post<unknown>(`${b(name)}/archive/rerun`, body)
