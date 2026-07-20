import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// The single entry point. React renders <App/> into the #root div from
// index.html. StrictMode double-invokes some lifecycles in dev to surface bugs
// — harmless, and it doesn't happen in a production build.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
