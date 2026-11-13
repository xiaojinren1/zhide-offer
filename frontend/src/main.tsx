import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import SharedResumePage from './pages/SharedResumePage'
import AdminConsole from './pages/AdminConsole'
import './index.css'
import './poster-theme.css'

const sharedResume = window.location.pathname.match(/^\/resume\/share\/([A-Za-z0-9_-]{32})\/?$/)
// 管理端是独立入口：/admin 走单独的登录与校验，不加载用户端的求职界面
const adminConsole = /^\/admin\/?$/.test(window.location.pathname)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {sharedResume ? <SharedResumePage token={sharedResume[1]} />
      : adminConsole ? <AdminConsole />
      : <App />}
  </React.StrictMode>
)
