import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { currentUser, login, userManager } from "./lib/auth";
import { Admin } from "./pages/Admin";
import { AgentCouncil } from "./pages/AgentCouncil";
import { AlertsCenter } from "./pages/AlertsCenter";
import { ApprovalInbox } from "./pages/ApprovalInbox";
import { AuditPage } from "./pages/AuditPage";
import { BoardReports } from "./pages/BoardReports";
import { CommandCenter } from "./pages/CommandCenter";
import { DataRoom } from "./pages/DataRoom";
import { ForecastStudio } from "./pages/ForecastStudio";
import { GrantCalendar } from "./pages/GrantCalendar";
import { GraphExplorer } from "./pages/GraphExplorer";
import { OpportunityDetail } from "./pages/OpportunityDetail";
import { ProposalFactory } from "./pages/ProposalFactory";
import { Radar } from "./pages/Radar";
import { Relationships } from "./pages/Relationships";
import { ScoringStudio } from "./pages/ScoringStudio";
import { Sources } from "./pages/Sources";
import { CallbackPage, NotFound } from "./pages/AuthPages";
import { ScreenPage } from "./pages/ScreenPage";
import { SCREENS } from "./routes";

/** Screens with a live implementation in the current phase. Everything else renders "Coming in Phase n". */
const IMPLEMENTED: Record<string, ReactNode> = {
  audit: <AuditPage />,
  "command-center": <CommandCenter />,
  radar: <Radar />,
  scoring: <ScoringStudio />,
  graph: <GraphExplorer />,
  sources: <Sources />,
  forecast: <ForecastStudio />,
  relationships: <Relationships />,
  council: <AgentCouncil />,
  calendar: <GrantCalendar />,
  approvals: <ApprovalInbox />,
  alerts: <AlertsCenter />,
  proposals: <ProposalFactory />,
  dataroom: <DataRoom />,
  "board-reports": <BoardReports />,
  admin: <Admin />,
};

function RequireAuth({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    currentUser().then((u) => (u ? setReady(true) : login()));
    const onExpired = () => login();
    userManager.events.addAccessTokenExpired(onExpired);
    return () => userManager.events.removeAccessTokenExpired(onExpired);
  }, []);
  return ready ? <>{children}</> : <div className="p-6 text-sm text-muted-foreground">Redirecting to sign-in…</div>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth/callback" element={<CallbackPage />} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          {SCREENS.map((s) => (
            <Route key={s.id} path={s.path} element={<ScreenPage screen={s}>{IMPLEMENTED[s.id]}</ScreenPage>} />
          ))}
          <Route path="/opportunities/:id" element={<OpportunityDetail />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
