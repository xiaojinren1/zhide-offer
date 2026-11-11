import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import SharedResumePage from './pages/SharedResumePage'
import './index.css'
import './poster-theme.css'

const sharedResume = window.location.pathname.match(/^\/resume\/share\/([A-Za-z0-9_-]{32})\/?$/)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {sharedResume ? <SharedResumePage token={sharedResume[1]} /> : <App />}
  </React.StrictMode>
)
