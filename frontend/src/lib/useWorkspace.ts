import { useEffect, useState, useSyncExternalStore } from 'react'
import axios from 'axios'
import { api, apiErrorMessage } from './api'
import { WorkspaceStore } from './workspaceStore'

export function useWorkspace(userId: string) {
  // AccountWorkspace 以 user.id 为 key，账户切换会销毁整个存储实例。
  const [store] = useState(() => new WorkspaceStore(userId, {
    load: api.loadWorkspace, save: api.saveWorkspace, message: apiErrorMessage,
    conflict: (reason) => axios.isAxiosError(reason) && reason.response?.status === 409,
  }))
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot)
  useEffect(() => {
    void store.start()
    const leaving = (event: BeforeUnloadEvent) => {
      if (store.hasUnsaved()) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', leaving)
    return () => { store.dispose(); window.removeEventListener('beforeunload', leaving) }
  }, [store])
  return { ...snapshot, update: store.update, load: store.load, flush: store.flush, retrySave: store.retrySave, hasUnsaved: store.hasUnsaved }
}
