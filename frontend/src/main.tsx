import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import App from "@/App"
import { PreferencesProvider } from "@/hooks/usePreferences"
import "@/index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/*
      Preferences wrap the router rather than sitting inside App, and the
      placement is the point: the theme has to be on <html> before anything
      renders, including the login screen. A signed-out visitor gets a 401
      from /auth/me/ and still sees the theme they last chose, because the
      provider reads its cache synchronously and only then asks the server.
    */}
    <PreferencesProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PreferencesProvider>
  </React.StrictMode>,
)
