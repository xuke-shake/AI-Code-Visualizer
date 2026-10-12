import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MermaidCanvas from './MermaidCanvas.vue'

const mermaid = vi.hoisted(() => ({ render: vi.fn() }))
vi.mock('@/utils/mermaid', () => ({
  ensureMermaid: () => mermaid,
  sanitizeMermaidCode: (code: string) => code,
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function waitForRenderCall(): Promise<void> {
  for (let i = 0; i < 20 && mermaid.render.mock.calls.length === 0; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
}

const svg = '<svg viewBox="0 0 100 100"><g class="node"><text>A</text></g></svg>'

async function waitForSvg(wrapper: { vm: { getSvgElement: () => SVGElement | null } }, present: boolean): Promise<void> {
  for (let i = 0; i < 40; i += 1) {
    if (Boolean(wrapper.vm.getSvgElement()) === present) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
}

describe('MermaidCanvas export eligibility', () => {
  beforeEach(() => vi.resetAllMocks())
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

  it('does not expose the old SVG while a new render is pending', async () => {
    const first = deferred<{ svg: string }>()
    const second = deferred<{ svg: string }>()
    mermaid.render.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mount(MermaidCanvas, { props: { code: 'flowchart TD\nA-->B', loading: false } })
    await waitForRenderCall()
    first.resolve({ svg })
    await waitForSvg(wrapper, true)
    expect(wrapper.vm.getSvgElement()).not.toBeNull()

    await wrapper.setProps({ code: 'flowchart TD\nA-->C' })
    await waitForRenderCall()
    await waitForSvg(wrapper, false)
    expect(wrapper.vm.getSvgElement()).toBeNull()
    second.resolve({ svg })
    await waitForSvg(wrapper, true)
    expect(wrapper.vm.getSvgElement()).not.toBeNull()
    wrapper.unmount()
  })

  it('keeps export disabled after a failed render', async () => {
    mermaid.render.mockRejectedValueOnce(new Error('invalid mermaid'))
    const wrapper = mount(MermaidCanvas, { props: { code: 'bad', loading: false } })
    await waitForRenderCall()
    await waitForSvg(wrapper, false)
    expect(wrapper.vm.getSvgElement()).toBeNull()
    wrapper.unmount()
  })

  it('uses original viewBox dimensions and fits very wide diagrams below 0.1', async () => {
    vi.useFakeTimers()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(900)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(500)
    mermaid.render.mockResolvedValue({ svg: '<svg viewBox="0 0 20000 1000"><text>wide</text></svg>' })
    const wrapper = mount(MermaidCanvas, { props: { code: 'flowchart TD\nA-->B', loading: false } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(35)
    const element = wrapper.vm.getSvgElement()!
    expect(element.getAttribute('width')).toBe('20000')
    expect(element.getAttribute('height')).toBe('1000')
    expect(element.style.maxWidth).toBe('none')
    const transform = wrapper.get('.mermaid-host').attributes('style')
    const scale = Number(transform.match(/scale\(([^)]+)\)/)?.[1])
    expect(scale).toBeCloseTo(0.0405)
    await wrapper.setProps({ loading: true })
    expect(wrapper.vm.getSvgElement()).toBeNull()
    wrapper.unmount()
  })

  it('does not let an older layout wait recover a newer failed render', async () => {
    vi.useFakeTimers()
    mermaid.render.mockResolvedValueOnce({ svg }).mockRejectedValueOnce(new Error('new render failed'))
    const wrapper = mount(MermaidCanvas, { props: { code: 'old', loading: false } })
    await flushPromises() // 旧图已经插入，但仍处于 30ms 布局等待。
    await wrapper.setProps({ code: 'new' })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(50)
    expect(wrapper.emitted('rendered')).toBeUndefined()
    expect(wrapper.emitted('error')?.[0]).toEqual(['new render failed'])
    expect(wrapper.vm.getSvgElement()).toBeNull()
    wrapper.unmount()
  })

  it('rejects Mermaid maximum-size error SVG instead of exporting it', async () => {
    mermaid.render.mockResolvedValue({ svg: '<svg viewBox="0 0 100 100"><text>Maximum text size in diagram exceeded</text></svg>' })
    const wrapper = mount(MermaidCanvas, { props: { code: 'too large', loading: false } })
    await flushPromises()
    expect(wrapper.vm.getSvgElement()).toBeNull()
    expect(wrapper.emitted('error')?.length).toBe(1)
    expect(wrapper.emitted('rendered')).toBeUndefined()
    wrapper.unmount()
  })

  it('ignores a render that resolves after unmount', async () => {
    const pending = deferred<{ svg: string }>()
    mermaid.render.mockReturnValue(pending.promise)
    const wrapper = mount(MermaidCanvas, { props: { code: 'old', loading: false } })
    await waitForRenderCall()
    wrapper.unmount()
    pending.resolve({ svg })
    await flushPromises()
    expect(wrapper.emitted('rendered')).toBeUndefined()
    expect(wrapper.vm.getSvgElement()).toBeNull()
  })

  it('rerenders identical code when the request key changes', async () => {
    mermaid.render.mockResolvedValue({ svg })
    const wrapper = mount(MermaidCanvas, { props: { code: 'flowchart TD\nA-->B', loading: false, renderRequestKey: 1 } })
    await flushPromises()
    const firstCalls = mermaid.render.mock.calls.length
    await wrapper.setProps({ renderRequestKey: 2 })
    await flushPromises()
    expect(mermaid.render.mock.calls.length).toBeGreaterThan(firstCalls)
    await waitForSvg(wrapper, true)
    expect(wrapper.emitted('rendered')?.at(-1)?.[0]).toMatchObject({ requestKey: 2, status: 'success' })
    wrapper.unmount()
  })
})
