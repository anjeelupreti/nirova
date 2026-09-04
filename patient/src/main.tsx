import React from "react"
import ReactDOM from "react-dom/client"

import App from "@/App"
import "@/index.css"

// No router. The patient app is four screens deep at most and every one of
// them is reachable from the home screen, so a router would be a dependency
// carrying no weight — and this bundle is downloaded over a phone connection.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
