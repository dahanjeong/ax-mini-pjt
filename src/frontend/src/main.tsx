import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css"; // tokens and reset first; component styles load after it with their components
import App from "./App.tsx";

const root = document.getElementById("root");
if (!root) throw new Error("#root element is missing");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
