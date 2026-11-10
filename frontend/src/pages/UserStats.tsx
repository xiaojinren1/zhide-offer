import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function UserStats() {
  const [stats, setStats] = useState<Awaited<ReturnType<typeof api.userStats>>>(null)
  const [stale, setStale] = useState(false)

  useEffect(() => {
    let live = true
    const refresh = async () => {
      try {
        const value = await api.userStats()
        if (live) {
          setStats(value)
          setStale(false)
        }
      } catch {
        if (live) setStale(true)
      }
    }
    void refresh()
    const timer = window.setInterval(refresh, 30_000)
    return () => { live = false; window.clearInterval(timer) }
  }, [])

  if (!stats) return null
  return <section className="panel" aria-label="用户统计">
    <h2>用户统计</h2>
    {stale && <p role="status">刷新失败，当前显示上次结果。</p>}
    <dl>
      <dt>当前在线（近 5 分钟）</dt><dd>{stats.online}</dd>
      <dt>本周新增（北京时间）</dt><dd>{stats.new_this_week}</dd>
      <dt>累计注册</dt><dd>{stats.registered}</dd>
    </dl>
  </section>
}
