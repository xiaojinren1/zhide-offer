import { useEffect, useState } from 'react'
import axios from 'axios'
import { api } from '../lib/api'
import ResumePreview from './workbench/ResumePreview'
import './workbench/workbench.css'

export default function SharedResumePage({ token }: { token: string }) {
  const [resume, setResume] = useState<Awaited<ReturnType<typeof api.sharedResume>>>()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.sharedResume(token).then(result => { if (active) setResume(result) }).catch(reason => {
      if (active) setError(axios.isAxiosError(reason) && reason.response?.status === 404
        ? '分享链接不存在或已撤回。' : '暂时无法加载简历，请稍后刷新。')
    })
    return () => { active = false }
  }, [token])

  return <main className="role-b-workbench shared-resume">
    {error ? <p role="alert">{error}</p> : resume
      ? <div className="resume-preview-canvas" style={{ backgroundColor: resume.appearance.background }}>
          <ResumePreview markdown={resume.markdown} appearance={resume.appearance} />
        </div>
      : <p role="status">正在加载简历…</p>}
  </main>
}
