/** 把一段文字切成「普通文字」和「场景编号」两种片段，给 SceneRefs 组件渲染成可点的链接。
 *  认的写法跟后端 refs_in 一致：S- 后面至少四位数字（S-0030、S-12345）。 */
export type RefPart = { text: string; id?: undefined } | { id: string; text?: undefined }

const RE = /S-\d{4,}/g

export function splitRefs(text: string): RefPart[] {
  const out: RefPart[] = []
  let last = 0
  for (const m of text.matchAll(RE)) {
    const i = m.index ?? 0
    if (i > last) out.push({ text: text.slice(last, i) })
    out.push({ id: m[0] })
    last = i + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}
