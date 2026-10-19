import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { auth } from "./api";
import { ThemeProvider } from "./theme";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Problems from "./pages/Problems";
import Devices from "./pages/Devices";
import DevicePage from "./pages/DevicePage";
import Syslog from "./pages/Syslog";
import Rules from "./pages/Rules";
import Notifications from "./pages/Notifications";
import Users from "./pages/Users";
import Plugins from "./pages/Plugins";
import Profile from "./pages/Profile";
import About from "./pages/About";
import Dashboards from "./pages/dashboards/Dashboards";
import DashboardView from "./pages/dashboards/DashboardView";

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
          <Route element={<Protected><Layout /></Protected>}>
            <Route path="/" element={<Overview />} />
            <Route path="/problems" element={<Problems />} />
            <Route path="/devices" element={<Devices />} />
            <Route path="/devices/:id/*" element={<DevicePage />} />
            <Route path="/syslog" element={<Syslog />} />
            <Route path="/setup/rules" element={<Rules />} />
            <Route path="/setup/notifications" element={<Notifications />} />
            <Route path="/setup/users" element={<Users />} />
            <Route path="/setup/plugins" element={<Plugins />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/dashboards" element={<Dashboards />} />
            <Route path="/dashboards/:id" element={<DashboardView />} />
            <Route path="/about" element={<About />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
