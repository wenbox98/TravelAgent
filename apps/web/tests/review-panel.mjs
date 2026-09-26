// Render the actual Vue template with authored data; no browser or network needed.
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import { parse, compileTemplate } from 'vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

const source = readFileSync(new URL('../src/components/ReviewPanel.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileTemplate({ source: descriptor.template.content, filename: 'ReviewPanel.vue', id: 'review-panel', ssr: true })
assert.deepEqual(compiled.errors, [])
const code = compiled.code.replace(/from "([^"]+)"/g, (_, name) => `from "${import.meta.resolve(name)}"`)
const { ssrRender } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))
const item = { source_label: '来源 1', candidate_index: 0, topic: 'ROUTE', origin: '本地重校验', rule_version: 3,
  action: 'NEEDS_REVIEW', category: '上下文', explanation: '缺少同源对象锚点', next_action: '保留待审',
  quote: '<img src="https://invalid.example" onerror="alert(1)">', locator: 'P-authored', reason_code: 'DEPENDENCY_UNRESOLVED' }
const render = (changes = {}) => renderToString(createSSRApp({ ssrRender, data: () => ({
  data: { message: '待审不等于错误，也不等于已通过', items: [item], updates: [] },
  error: '', busy: false, proposed: null, view: { research_id: 'old', evidence_count: 29, preferences: { days: 5, driving: 'NO' } },
  actionLabel: () => '待审', ...changes
}) }))
const html = await render()
assert(html.includes('&lt;img') && !html.includes('<img'))
assert(html.includes('缺少同源对象锚点') && html.includes('P-authored') && html.includes('本地重校验'))
assert((await render({ data: { items: [], updates: [] } })).includes('暂无可展示的审核记录'))
assert((await render({ error: '<script>fixture</script>' })).includes('&lt;script&gt;fixture&lt;/script&gt;'))
const preview = await render({ proposed: { evidence_count: 34 } })
assert(preview.includes('当前 29 条更新至 34 条') && preview.includes('采用本地更新') && preview.includes('取消本地更新'))
console.log('PASS ReviewPanel: reasons, quoted text escaping, local provenance, empty/error states, adoption preview')
