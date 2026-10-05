import React from "react";
import { createRoot } from "react-dom/client";
import { WorkbenchApp } from "./m1/WorkbenchApp.tsx";
const Prototype = React.lazy(async () => {
  await import("./styles.css");
  const { App } = await import("./App.tsx");
  return { default: App };
});

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {location.pathname === "/prototype" ? (
      <React.Suspense fallback="正在载入…">
        <Prototype />
      </React.Suspense>
    ) : (
      <WorkbenchApp />
    )}
  </React.StrictMode>,
);
