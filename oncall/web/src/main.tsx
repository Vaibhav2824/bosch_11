import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// SmoothUI themes with a .dark class; follow the OS setting.
const dark = window.matchMedia('(prefers-color-scheme: dark)')
const sync = () => document.documentElement.classList.toggle('dark', dark.matches)
sync()
dark.addEventListener('change', sync)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
