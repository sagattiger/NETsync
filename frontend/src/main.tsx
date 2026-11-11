import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { auth } from "./api";
import { ThemeProvider } from "./theme";
import Layout from "./components/Layout";
import Login from "./pages/Login";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1 } } });

function Protected({ children }: { children: React.ReactNode }) {
  return auth.token ? <>{children}</> : <Navigate to="/login" replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={<Protected><Layout /></Protected>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
