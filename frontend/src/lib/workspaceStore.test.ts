import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceStore } from './workspaceStore'
import { emptyWorkspace } from './workspace'
import type { WorkspaceResponse, WorkspaceState } from './workspace'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const empty = (): WorkspaceResponse => ({ ok: true, revision: 0, state: null, saved_at: null })
function fixture() {
  const load = vi.fn<() => Promise<WorkspaceResponse>>().mockResolvedValue(empty())
  const save = vi.fn<(userId: string, revision: number, state: WorkspaceState) => Promise<{ revision: number; saved_at: string }>>()
    .mockImplementation(async (_id, revision) => ({ revision: revision + 1, saved_at: '2026-10-31T01:30:00+00:00' }))
  const store = new WorkspaceStore('user-a', { load, save, message: (reason) => String(reason), conflict: (reason) => reason === 'conflict' })
  return { store, load, save }
}
describe('工作台保存队列', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('恢复完整内容与版本，恢复本身不产生写入', async () => {
    const { store, load, save } = fixture()
    const state = { ...emptyWorkspace(), source_text: '材料', jd_text: '产品岗位', page: 'memory' as const }
    load.mockResolvedValue({ ok: true, revision: 7, state, saved_at: 'saved' })
    await store.start(); await vi.advanceTimersByTimeAsync(1000)
    expect(store.getSnapshot().state).toEqual(state)
    expect(store.hasUnsaved()).toBe(false); expect(save).not.toHaveBeenCalled()
    store.update((value) => ({ ...value, jd_text: '新岗位' })); await store.flush()
    expect(save).toHaveBeenCalledWith('user-a', 7, expect.objectContaining({ jd_text: '新岗位' }))
    store.dispose()
  })

  it('恢复失败锁定更新且禁止空内容覆盖，重试成功才允许保存', async () => {
    const { store, load, save } = fixture()
    load.mockRejectedValueOnce(new Error('offline'))
    await store.start(); store.update((value) => ({ ...value, jd_text: '不能写入' }))
    await expect(store.flush()).rejects.toThrow('尚未恢复')
    await vi.advanceTimersByTimeAsync(1000)
    expect(store.getSnapshot().phase).toBe('load-error'); expect(save).not.toHaveBeenCalled()
    expect(store.getSnapshot().state.jd_text).toBe('')
    await store.load(); expect(store.getSnapshot().loaded).toBe(true)
    store.dispose()
  })

  it('不完整的成功响应被视为恢复失败', async () => {
    const { store, load, save } = fixture()
    load.mockResolvedValue({ ok: true, revision: 0 } as WorkspaceResponse)
    await store.start()
    expect(store.getSnapshot().phase).toBe('load-error'); expect(save).not.toHaveBeenCalled()
    store.dispose()
  })

  it('600毫秒合并连续输入，立即flush也会取消等待', async () => {
    const { store, save } = fixture(); await store.start()
    store.update((value) => ({ ...value, source_text: '1' }))
    await vi.advanceTimersByTimeAsync(500)
    store.update((value) => ({ ...value, source_text: '12' }))
    await vi.advanceTimersByTimeAsync(599); expect(save).not.toHaveBeenCalled()
    await store.flush(); expect(save).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000); expect(save).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot().phase).toBe('saved'); store.dispose()
  })

  it('保存中编辑排队，新写入等待上一版成功且使用新版本号', async () => {
    const { store, save } = fixture(); await store.start()
    const first = deferred<{ revision: number; saved_at: string }>()
    save.mockReturnValueOnce(first.promise)
    store.update((value) => ({ ...value, jd_text: '第一版' }))
    const flushing = store.flush()
    store.update((value) => ({ ...value, jd_text: '第二版' }))
    await vi.advanceTimersByTimeAsync(1000); expect(save).toHaveBeenCalledTimes(1)
    first.resolve({ revision: 1, saved_at: 'first' }); await flushing
    expect(save).toHaveBeenCalledTimes(2)
    expect(save.mock.calls[1]).toEqual(['user-a', 1, expect.objectContaining({ jd_text: '第二版' })])
    expect(store.hasUnsaved()).toBe(false); store.dispose()
  })

  it('保存失败向调用方抛错且停止自动重试，手动重试保存最新输入', async () => {
    const { store, save } = fixture(); await store.start()
    save.mockRejectedValueOnce(new Error('offline'))
    store.update((value) => ({ ...value, jd_text: '第一版' }))
    await expect(store.flush()).rejects.toThrow('offline')
    expect(store.getSnapshot().phase).toBe('save-error')
    store.update((value) => ({ ...value, jd_text: '第二版' }))
    await vi.advanceTimersByTimeAsync(5000); expect(save).toHaveBeenCalledTimes(1)
    await store.retrySave(); expect(save).toHaveBeenCalledTimes(2)
    expect(save.mock.calls[1][2].jd_text).toBe('第二版'); store.dispose()
  })

  it('409冲突保持本地内容并停止写入，显式加载才替换', async () => {
    const { store, load, save } = fixture(); await store.start()
    save.mockRejectedValueOnce('conflict')
    store.update((value) => ({ ...value, jd_text: '本地' }))
    await expect(store.flush()).rejects.toBe('conflict')
    store.update((value) => ({ ...value, jd_text: '继续编辑' }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(store.getSnapshot().phase).toBe('conflict'); expect(save).toHaveBeenCalledTimes(1)
    load.mockResolvedValue({ ok: true, revision: 9, state: { ...emptyWorkspace(), jd_text: '服务器' }, saved_at: 'saved' })
    await store.load(); expect(store.getSnapshot().state.jd_text).toBe('服务器')
    expect(store.hasUnsaved()).toBe(false); store.dispose()
  })

  it('销毁会取消待保存计时，不再产生请求', async () => {
    const { store, save } = fixture(); await store.start()
    store.update((value) => ({ ...value, jd_text: '未发送' })); store.dispose()
    await vi.advanceTimersByTimeAsync(5000); expect(save).not.toHaveBeenCalled()
  })

  it('保存请求未返回时销毁，不再为后续编辑发送下一次请求', async () => {
    const { store, save } = fixture(); await store.start()
    const request = deferred<{ revision: number; saved_at: string }>(); save.mockReturnValueOnce(request.promise)
    store.update((value) => ({ ...value, jd_text: '第一版' }))
    const result = store.flush().catch((reason: unknown) => reason)
    store.update((value) => ({ ...value, jd_text: '第二版' })); store.dispose()
    request.resolve({ revision: 1, saved_at: 'first' }); await result
    await vi.advanceTimersByTimeAsync(5000); expect(save).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot().phase).toBe('saving')
  })

  it('旧恢复请求晚到不能覆盖更新的恢复结果', async () => {
    const { store, load } = fixture(); const old = deferred<WorkspaceResponse>()
    load.mockReturnValueOnce(old.promise)
    const first = store.start(); await store.load()
    store.update((value) => ({ ...value, jd_text: '当前编辑' }))
    old.resolve({ ok: true, revision: 7, state: { ...emptyWorkspace(), jd_text: '旧请求' }, saved_at: 'old' })
    await first; expect(store.getSnapshot().state.jd_text).toBe('当前编辑'); store.dispose()
  })

  it('编辑后改回已保存内容会恢复已保存提示，不留下待保存状态', async () => {
    const { store, load, save } = fixture()
    load.mockResolvedValue({ ok: true, revision: 3, state: emptyWorkspace(), saved_at: 'saved' })
    await store.start()
    store.update((value) => ({ ...value, jd_text: '临时编辑' }))
    expect(store.getSnapshot().phase).toBe('pending')
    store.update((value) => ({ ...value, jd_text: '' }))
    expect(store.getSnapshot().phase).toBe('saved')
    expect(store.hasUnsaved()).toBe(false)
    await vi.advanceTimersByTimeAsync(1000); expect(save).not.toHaveBeenCalled(); store.dispose()
  })

  it('冲突后显式重新加载失败，仍然标记本页未保存以防直接退出丢稿', async () => {
    const { store, load, save } = fixture(); await store.start()
    save.mockRejectedValueOnce('conflict')
    store.update((value) => ({ ...value, jd_text: '保留本地' }))
    await expect(store.flush()).rejects.toBe('conflict')
    load.mockRejectedValueOnce(new Error('offline')); await store.load()
    expect(store.getSnapshot().loaded).toBe(false)
    expect(store.hasUnsaved()).toBe(true)
    await expect(store.flush()).rejects.toThrow('尚未恢复'); store.dispose()
  })
})
