<script setup lang="ts">
/**
 * 泳道图。组件不做任何计算，只把 lib/axis·segments·gaps 三个纯函数算出来的坐标画成 DOM。
 * spec 第 4 章。数据坑见 dispatch.md「已知的坑」F1 给 D3 那几条：
 * - offset 为 null 的线用 isAligned 判断，不当 0；不画段，线尾标「没对齐」。
 * - gap.thread 为 null 的缺口挂到世界级；场景没时间用 scenesWithoutTime（含缺键）。
 * - 缺口簇按 clusterRatio = 28 / width * 100 传参，在渲染层算，width 变了自动重算。
 */
import { computed } from 'vue'
import { buildAxis } from '@/lib/axis'
import type { Axis } from '@/lib/axis'
import { buildSegments, isAligned, scenesWithoutTime, threadPoints } from '@/lib/segments'
import type { Segment } from '@/lib/segments'
import { gapsWithoutThread, layoutGaps, sceneTimeLookup } from '@/lib/gaps'
import type { GapLayout } from '@/lib/gaps'
import type { Gap, Intersection, Thread, ThreadsFile, VersionGroup, World } from '@/api/types'

const props = withDefaults(
  defineProps<{
    data: ThreadsFile
    selectedThread?: string | null
    /** 容器宽度（px）。默认 1200。clusterRatio 按它算，resize 时重算，不缓存。 */
    width?: number
    /**
     * GET /versions 的 groups（Task 20 传进来）。task19 任务书 DOM 结构里的 `.ver` 角标要用它，
     * 但 Step 1 的 props 清单没列——按 spec 4.5「多版本角标」和 DOM 注释补上，是这个组件在计划外
     * 多加的一个可选 prop，不影响任何既有测试。
     */
    versions?: VersionGroup[]
  }>(),
  { selectedThread: null, width: 1200, versions: () => [] },
)

const emit = defineEmits<{
  'select-thread': [threadId: string]
  'select-cluster': [payload: { threadId: string; gaps: Gap[] }]
  'select-orphans': [payload: { threadId: string; gaps: Gap[] }]
}>()

const 颜色变量 = ['--w1', '--w2', '--w3']
function worldColor(idx: number): string {
  return `var(${颜色变量[idx % 颜色变量.length]})`
}

const axis = computed<Axis | null>(() => buildAxis(props.data.threads.flatMap((t) => threadPoints(t))))
const 查时间 = computed(() => sceneTimeLookup(props.data))
const clusterRatio = computed(() => (28 / (props.width || 1200)) * 100)

const worldIndexOf = computed(() => {
  const m = new Map<string, number>()
  props.data.worlds.forEach((w, i) => m.set(w.id, i))
  return m
})

/** 没归到任何线的缺口（`gap.thread` 为 null）。不能哪条线都不挂就悄悄丢掉（spec 4.5）。 */
const 未归线缺口 = computed<Gap[]>(() => gapsWithoutThread(props.data))
function worldOrphanGapCount(w: World): number {
  return 未归线缺口.value.filter((g) => g.world === w.id).length
}

function endMarkKind(t: Thread): '完' | '待定' | '断' {
  const s = t.end?.state ?? ''
  if (s === '完结') return '完'
  if (s === '待定') return '待定'
  return '断'
}

interface VersionBadge { id: string; x: number; count: number }

/** 把一个版本组映射到它在这条线上的位置：取 main（没有就取第一个成员），按那个场景的全局时间定位。 */
function versionBadgeFor(g: VersionGroup, t: Thread, ax: Axis): VersionBadge | null {
  if (!isAligned(t)) return null
  const membersRaw = g.members
  const members = Array.isArray(membersRaw) ? membersRaw.filter((m): m is string => typeof m === 'string') : []
  const main = typeof g.main === 'string' ? g.main : members[0]
  if (!main || !t.scenes.includes(main)) return null
  const time = t.times?.[main]?.t
  if (time === null || time === undefined) return null
  const off = t.offset as number
  return { id: String(g.id), x: ax.x(off + time), count: Math.max(members.length, 1) }
}

interface LaneVM {
  thread: Thread
  worldIdx: number
  segments: Segment[]
  gapLayout: GapLayout
  scenesWithoutTimeCount: number
  aligned: boolean
  intersections: Array<{ key: string; x: number; reason: string }>
  versionBadges: VersionBadge[]
  endMark: '完' | '待定' | '断'
  endMarkX: number | null
}

const laneVMs = computed<LaneVM[]>(() => {
  const ax = axis.value
  if (!ax) return []
  const lookup = 查时间.value
  return props.data.threads.map((t) => {
    const segments = buildSegments(threadPoints(t), ax)
    const gs = props.data.gaps.filter((g) => g.thread === t.id)
    const gapLayout = layoutGaps(gs, lookup, ax, { clusterRatio: clusterRatio.value })
    const intersections = props.data.intersections
      .filter((ix: Intersection) => ix.thread === t.id)
      .map((ix, i) => {
        const time = lookup(ix.scene)
        return time === null ? null : { key: `${ix.scene}-${i}`, x: ax.x(time), reason: ix.reason }
      })
      .filter((v): v is { key: string; x: number; reason: string } => v !== null)
    const versionBadges = props.versions
      .map((g) => versionBadgeFor(g, t, ax))
      .filter((v): v is VersionBadge => v !== null)
    const segLast = segments[segments.length - 1]
    return {
      thread: t,
      worldIdx: worldIndexOf.value.get(t.world) ?? 0,
      segments,
      gapLayout,
      scenesWithoutTimeCount: scenesWithoutTime(t).length,
      aligned: isAligned(t),
      intersections,
      versionBadges,
      endMark: endMarkKind(t),
      endMarkX: segLast ? segLast.x1 : null,
    }
  })
})

const worldGroups = computed(() =>
  props.data.worlds
    .map((w, idx) => ({ world: w, idx, lanes: laneVMs.value.filter((vm) => vm.thread.world === w.id) }))
    .filter((g) => g.lanes.length > 0),
)

// ---------- 刻度 ----------
interface AxisTick { key: string; x: number; label: string }

/** 挑一个「好看」的步长（1/2/5 × 10^n），别把几百年的区块画成密密麻麻的整数年刻度。 */
function niceStep(span: number, target = 4): number {
  if (span <= 0) return 1
  const raw = span / target
  const mag = 10 ** Math.floor(Math.log10(raw))
  const norm = raw / mag
  const mult = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10
  return mult * mag
}

const axisTicks = computed<AxisTick[]>(() => {
  const ax = axis.value
  if (!ax) return []
  const unit = props.data.time_unit || ''
  const out: AxisTick[] = []
  ax.blocks.forEach((blk, bi) => {
    const span = blk.t1 - blk.t0
    if (span === 0) {
      out.push({ key: `${bi}-0`, x: (blk.x0 + blk.x1) / 2, label: `${Math.round(blk.t0)}${unit}` })
      return
    }
    const step = niceStep(span)
    let t = Math.ceil(blk.t0 / step) * step
    let guard = 0
    while (t <= blk.t1 + 1e-9 && guard < 30) {
      out.push({ key: `${bi}-${guard}`, x: ax.x(t), label: `${Math.round(t)}${unit}` })
      t += step
      guard += 1
    }
  })
  return out
})

function 点缺口簇(threadId: string, gaps: Gap[]): void {
  emit('select-cluster', { threadId, gaps })
}
function 点orphan(threadId: string, gaps: Gap[]): void {
  emit('select-orphans', { threadId, gaps })
}
</script>

<template>
  <div class="lanes">
    <div v-if="!axis" class="empty" data-test="空态">
      这本书还没有估出故事时间，先跑完步骤 6 再看全景。
    </div>
    <template v-else>
      <p v-if="axis?.degraded" class="degraded">区块太碎，放不下断口，暂时按等比例轴显示。</p>

      <div class="row axis-row" data-test="轴">
        <div class="lab"></div>
        <div class="track">
          <span
            v-for="tick in axisTicks"
            :key="tick.key"
            class="tick"
            :style="{ left: tick.x + '%' }"
          >{{ tick.label }}</span>
          <span
            v-for="(brk, i) in axis?.breaks ?? []"
            :key="`brk-${i}`"
            class="brk"
            data-test="断口"
            :style="{ left: brk.x0 + '%', width: Math.max(brk.x1 - brk.x0, 0) + '%' }"
            :title="`这里跨了 ${brk.years.toFixed(1)} 年`"
          >跨了 {{ brk.years.toFixed(1) }} 年</span>
        </div>
      </div>

      <template v-for="wg in worldGroups" :key="wg.world.id">
        <div class="world" data-test="世界">
          <i class="dot" :style="{ background: worldColor(wg.idx) }"></i>{{ wg.world.name }}
          <span v-if="worldOrphanGapCount(wg.world) > 0" class="world-orphan">
            {{ worldOrphanGapCount(wg.world) }} 处没归到线
          </span>
        </div>

        <div v-for="vm in wg.lanes" :key="vm.thread.id" data-test="泳道">
        <div
          class="row lane"
          :class="{ 排序失败: vm.thread.order_failed, sel: vm.thread.id === selectedThread }"
          :data-test="`泳道-${vm.thread.id}`"
          tabindex="0"
          role="button"
          @click="emit('select-thread', vm.thread.id)"
        >
          <div class="lab">
            {{ vm.thread.name }}<small>{{ vm.thread.scenes.length }} 场景</small>
            <span v-if="vm.thread.order_failed" class="fail-note">排序失败，顺序不可信</span>
          </div>
          <div class="track">
            <span
              v-for="(seg, i) in vm.segments"
              :key="`seg-${i}`"
              class="seg"
              data-test="段"
              :style="{ left: seg.x0 + '%', width: Math.max(seg.x1 - seg.x0, 0) + '%', background: worldColor(vm.worldIdx) }"
            ></span>

            <span
              v-for="ix in vm.intersections"
              :key="ix.key"
              class="meet"
              data-test="交汇"
              :style="{ left: ix.x + '%' }"
              :title="ix.reason"
            ></span>

            <span
              v-for="vb in vm.versionBadges"
              :key="vb.id"
              class="ver"
              data-test="版本角标"
              :style="{ left: vb.x + '%' }"
            >{{ vb.count }}版</span>

            <span
              v-if="vm.aligned && vm.endMarkX !== null"
              class="mark"
              :class="`mark-${vm.endMark}`"
              :data-test="`标记-${vm.endMark}`"
              :style="{ left: vm.endMarkX + '%' }"
            >{{ vm.endMark }}</span>

            <span
              v-for="c in vm.gapLayout.clusters"
              :key="`gap-${c.x}`"
              class="gap"
              data-test="缺口簇"
              :data-count="c.gaps.length"
              :style="{ left: c.x + '%' }"
              :title="c.gaps.map((g) => g.event).join('；')"
              @click.stop="点缺口簇(vm.thread.id, c.gaps)"
            >{{ c.gaps.length > 1 ? c.gaps.length : '' }}</span>

            <span
              v-if="vm.gapLayout.orphans.length > 0"
              class="orph"
              data-test="缺口orphan"
              :data-count="vm.gapLayout.orphans.length"
              @click.stop="点orphan(vm.thread.id, vm.gapLayout.orphans)"
            >{{ vm.gapLayout.orphans.length }} 处定不了位</span>

            <span v-if="vm.scenesWithoutTimeCount > 0" class="nt" data-test="无时间场景">
              {{ vm.scenesWithoutTimeCount }} 个场景没有时间
            </span>

            <span v-if="!vm.aligned" class="nt" data-test="未对齐">
              这条线没对齐到主线，时间位置未知
            </span>
          </div>
        </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.lanes{min-width:640px}
.empty{color:var(--ink-3);padding:24px 0;font-size:13px}
.degraded{color:var(--amber);font-size:12px;margin-bottom:6px}
.row{display:grid;grid-template-columns:160px minmax(0,1fr);align-items:center}
.axis-row{height:28px;border-bottom:1px solid var(--line);margin-bottom:4px}
.axis-row .track{height:100%}
.tick{position:absolute;bottom:4px;transform:translateX(-50%);font-family:var(--mono);font-size:11px;color:var(--ink-3)}
.brk{
  position:absolute;top:0;bottom:4px;
  background:repeating-linear-gradient(45deg,var(--red) 0 2px,transparent 2px 6px);
  opacity:.45;font-size:10px;color:var(--red);display:flex;align-items:flex-end;justify-content:center;
}
.world{font-size:12px;color:var(--ink-3);letter-spacing:.06em;padding:10px 0 2px;display:flex;align-items:center;gap:6px}
.world .dot{width:8px;height:8px;border-radius:2px;display:inline-block}
.world-orphan{color:var(--red);margin-left:8px}
.lane{height:38px;border-radius:6px;cursor:pointer}
.lane:hover .lab{color:var(--accent)}
.lane.sel{background:var(--accent-soft)}
.lane.排序失败{background:var(--amber-soft)}
.lab{padding-left:10px;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lab small{color:var(--ink-3);font-family:var(--mono);font-size:11px;margin-left:4px}
.fail-note{color:var(--amber);font-size:11px;margin-left:8px}
.track{position:relative;height:38px}
.seg{position:absolute;top:12px;height:14px;border-radius:3px}
.mark{
  position:absolute;top:8px;width:22px;height:22px;transform:translateX(-50%);
  display:grid;place-items:center;font-family:var(--serif);font-size:12px;font-weight:700;border-radius:3px;
}
.mark-断{background:var(--red);color:var(--panel)}
.mark-完{background:var(--green-soft);color:var(--green);border:1px solid var(--green)}
.mark-待定{background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber)}
.meet{
  position:absolute;top:13px;width:12px;height:12px;border-radius:50%;
  border:2px solid var(--ink);background:var(--panel);transform:translateX(-50%);
}
.ver{
  position:absolute;top:-1px;transform:translateX(-50%);font-family:var(--mono);font-size:10px;color:var(--ink-2);
  background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:0 3px;line-height:14px;
}
.gap{
  position:absolute;top:9px;width:14px;height:14px;transform:translateX(-50%) rotate(45deg);
  background:var(--red);border-radius:2px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:var(--panel);font-size:9px;
}
.gap > * { transform: rotate(-45deg); }
.orph{
  margin-left:10px;font-size:11px;color:var(--red);background:var(--red-soft);border-radius:4px;
  padding:1px 6px;cursor:pointer;position:absolute;right:0;top:11px;
}
.nt{display:block;font-size:11px;color:var(--ink-3);margin-top:2px}
</style>
