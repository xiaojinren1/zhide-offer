import { emptyWorkspace, isWorkspaceState } from './workspace'
import type { WorkspaceResponse, WorkspaceState } from './workspace'

export type WorkspacePhase = 'loading' | 'ready' | 'pending' | 'saving' | 'saved' | 'load-error' | 'save-error' | 'conflict'
interface Snapshot {
  state: WorkspaceState; phase: WorkspacePhase; error: string; savedAt: string | null; loaded: boolean
}
interface Storage {
  load: () => Promise<WorkspaceResponse>
  save: (userId: string, revision: number, state: WorkspaceState) => Promise<{ revision: number; saved_at: string }>
  message: (reason: unknown) => string
  conflict: (reason: unknown) => boolean
}

/** 与 React、网络和浏览器解耦，保存队列可用固定响应回放。 */
export class WorkspaceStore {
  private snapshot: Snapshot = { state: emptyWorkspace(), phase: 'loading', error: '', savedAt: null, loaded: false }
  private listeners = new Set<() => void>()
  private baseline = JSON.stringify(this.snapshot.state)
  private revision = 0
  private active = false
  private generation = 0
  private blocked = false
  private timer: ReturnType<typeof setTimeout> | undefined
  private saving: Promise<void> | null = null

  constructor(private userId: string, private storage: Storage) {}
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private notify(patch: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...patch }
    this.listeners.forEach((listener) => listener())
  }
  private cancelTimer() { clearTimeout(this.timer); this.timer = undefined }
  hasUnsaved = () => this.baseline !== JSON.stringify(this.snapshot.state)
  start = () => { this.active = true; return this.load() }
  dispose = () => { this.active = false; ++this.generation; this.cancelTimer() }

  load = async () => {
    const ticket = ++this.generation
    this.cancelTimer(); this.blocked = true
    this.notify({ phase: 'loading', error: '', loaded: false })
    try {
      const result = await this.storage.load()
      if (!this.active || ticket !== this.generation) return
      if (result?.ok !== true || !Number.isInteger(result.revision) || result.revision < 0
        || (result.saved_at !== null && typeof result.saved_at !== 'string')
        || (result.state !== null && !isWorkspaceState(result.state))) throw new Error('工作台恢复响应不完整，请重试恢复。')
      const restored = result.state ?? emptyWorkspace()
      this.baseline = JSON.stringify(restored); this.revision = result.revision
      this.blocked = false
      this.notify({ state: restored, phase: result.saved_at ? 'saved' : 'ready', savedAt: result.saved_at, loaded: true })
    } catch (reason) {
      if (this.active && ticket === this.generation) this.notify({ phase: 'load-error', error: this.storage.message(reason) })
    }
  }

  update = (change: (previous: WorkspaceState) => WorkspaceState) => {
    if (!this.active || !this.snapshot.loaded) return
    const state = change(this.snapshot.state)
    const dirty = this.baseline !== JSON.stringify(state)
    this.notify({ state, ...(!this.blocked && !this.saving ? { phase: dirty ? 'pending' as const : this.snapshot.savedAt ? 'saved' as const : 'ready' as const } : {}) })
    this.cancelTimer()
    if (!this.blocked && this.hasUnsaved()) this.timer = setTimeout(() => { void this.flush().catch(() => undefined) }, 600)
  }

  flush = async (): Promise<void> => {
    this.cancelTimer()
    if (!this.active || !this.snapshot.loaded) throw new Error('工作台尚未恢复，请先重试恢复。')
    if (this.blocked) throw new Error('工作台尚未保存，请先处理保存提示。')
    if (this.saving) return this.saving
    const ticket = this.generation
    const work = async () => {
      try {
        while (this.active && ticket === this.generation && this.hasUnsaved()) {
          const state = this.snapshot.state
          const encoded = JSON.stringify(state)
          this.notify({ phase: 'saving' })
          const result = await this.storage.save(this.userId, this.revision, state)
          if (!this.active || ticket !== this.generation) throw new Error('账户状态已改变，请重新登录后恢复。')
          if (result.revision !== this.revision + 1 || typeof result.saved_at !== 'string' || !result.saved_at) throw new Error('工作台保存响应不完整，请重试保存。')
          this.revision = result.revision; this.baseline = encoded
          this.notify({ savedAt: result.saved_at })
        }
        if (this.active && ticket === this.generation) this.notify({ phase: 'saved', error: '' })
      } catch (reason) {
        if (this.active && ticket === this.generation) {
          this.blocked = true
          this.notify({ phase: this.storage.conflict(reason) ? 'conflict' : 'save-error', error: this.storage.message(reason) })
        }
        throw reason
      }
    }
    const promise = work()
    this.saving = promise
    try { await promise }
    finally { if (this.saving === promise) this.saving = null }
  }

  retrySave = async () => {
    if (!this.snapshot.loaded) return
    this.blocked = false; this.notify({ error: '' })
    await this.flush()
  }
}
