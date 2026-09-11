import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import App from "@/App"
import { PreferencesProvider } from "@/hooks/usePreferences"

/*
  The typefaces, self-hosted rather than fetched from a font CDN.

  Not a preference: a hospital network that blocks fonts.googleapis.com — and
  plenty do, along with anything else not on an allow-list — would otherwise
  fall back to the system stack silently, so the product would look one way in
  development and another way on the ward. Bundling them means the console
  looks the same on an air-gapped deployment as it does here.

  Variable rather than static weights: one file covers 100–900, which is
  smaller than the four static cuts it replaces and lets a heading interpolate
  to 560 instead of choosing between 500 and 600.
*/
import "@fontsource-variable/geist"
import "@fontsource-variable/geist-mono"

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
