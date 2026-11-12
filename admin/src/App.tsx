import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { Conversations, ConversationView } from "./pages/Conversations";
import { Costs } from "./pages/Costs";
import { DocumentView, Documents } from "./pages/Documents";
import { EvalRunView, Evals } from "./pages/Evals";
import { OverviewPage } from "./pages/Overview";
import { ReleaseView, Releases } from "./pages/Releases";
import { SignIn } from "./pages/SignIn";

export function AppRoutes() {
  const { me } = useAuth();
  if (!me) return <SignIn />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/:docId" element={<DocumentView />} />
        <Route path="releases" element={<Releases />} />
        <Route path="releases/:releaseId" element={<ReleaseView />} />
        <Route path="evals" element={<Evals />} />
        <Route path="evals/runs/:runId" element={<EvalRunView />} />
        <Route path="costs" element={<Costs />} />
        <Route path="conversations" element={<Conversations />} />
        <Route path="conversations/:conversationId" element={<ConversationView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
