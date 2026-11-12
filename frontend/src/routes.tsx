import { lazy, Suspense } from "react";
import { Route } from "react-router-dom";
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
import Tokens from "./pages/Tokens";
import Housekeeping from "./pages/Housekeeping";
import AiTools from "./pages/AiTools";
import Store from "./pages/Store";
import TerminalPage from "./pages/TerminalPage";
import TerminalSetup from "./pages/TerminalSetup";
import Probes from "./pages/Probes";
import ProbePage from "./pages/ProbePage";
import Dashboards from "./pages/dashboards/Dashboards";
import DashboardView from "./pages/dashboards/DashboardView";
import { Empty } from "./components/ui";

// Dev-only widget gallery (kept out of production bundles unless built with VITE_UI_KIT=1).
const SHOW_UI_KIT = import.meta.env.DEV || import.meta.env.VITE_UI_KIT === "1";
const UiKit = SHOW_UI_KIT ? lazy(() => import("./pages/UiKit")) : null;

/** Pages inside the app shell. Each tab renders these against its own location (components/Tabs.tsx). */
export const pageRoutes = (
  <>
    <Route path="/" element={<Overview />} />
    <Route path="/problems" element={<Problems />} />
    <Route path="/devices" element={<Devices />} />
    <Route path="/devices/:id/*" element={<DevicePage />} />
    <Route path="/probes" element={<Probes />} />
    <Route path="/probes/:id" element={<ProbePage />} />
    <Route path="/syslog" element={<Syslog />} />
    <Route path="/setup/rules" element={<Rules />} />
    <Route path="/setup/notifications" element={<Notifications />} />
    <Route path="/setup/users" element={<Users />} />
    <Route path="/setup/plugins" element={<Plugins />} />
    <Route path="/setup/tokens" element={<Tokens />} />
    <Route path="/setup/housekeeping" element={<Housekeeping />} />
    <Route path="/setup/ai-tools" element={<AiTools />} />
    <Route path="/setup/store" element={<Store />} />
    <Route path="/setup/terminal" element={<TerminalSetup />} />
    <Route path="/terminal" element={<TerminalPage />} />
    <Route path="/profile" element={<Profile />} />
    <Route path="/dashboards" element={<Dashboards />} />
    <Route path="/dashboards/:id" element={<DashboardView />} />
    <Route path="/about" element={<About />} />
    {UiKit && <Route path="/ui-kit" element={<Suspense fallback={null}><UiKit /></Suspense>} />}
    <Route path="*" element={<div className="p-8"><Empty>Page not found</Empty></div>} />
  </>
);
