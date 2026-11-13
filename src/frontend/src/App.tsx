import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { CurrentAnalysisProvider, useCurrentAnalysis } from "./lib/current";
import { useDisplayPreferences } from "./lib/hooks";
import { AnalysisView } from "./pages/AnalysisView";
import { ChatbotPage } from "./pages/Chatbot";
import { FindingDetailPage } from "./pages/FindingDetail";
import { FindingsPage } from "./pages/Findings";
import { NewAnalysisPage } from "./pages/NewAnalysis";
import { PatchPage } from "./pages/PatchDetail";
import { QuickExplainPage } from "./pages/QuickExplain";
import { RepositoriesPage } from "./pages/Repositories";
import { SearchPage } from "./pages/Search";
import { SettingsPage } from "./pages/Settings";

function Shell() {
  const { analysisId } = useCurrentAnalysis();
  const { theme, density, toggleTheme, toggleDensity } = useDisplayPreferences();

  return (
    <div
      className="rv-shell"
      style={{
        display: "grid",
        gridTemplateColumns: "214px minmax(0,1fr)",
        minHeight: "100vh",
        background: "var(--paper)",
        color: "var(--ink)",
        fontSize: 14,
        lineHeight: 1.5,
      }}
    >
      <Sidebar
        analysisId={analysisId}
        theme={theme}
        density={density}
        onToggleTheme={toggleTheme}
        onToggleDensity={toggleDensity}
      />
      <main style={{ minWidth: 0 }}>
        <Routes>
          <Route path="/" element={<RepositoriesPage />} />
          <Route path="/new" element={<NewAnalysisPage />} />
          <Route path="/analyses/:analysisId" element={<AnalysisView />} />
          <Route path="/analyses/:analysisId/findings" element={<FindingsPage />} />
          <Route path="/analyses/:analysisId/search" element={<SearchPage />} />
          <Route path="/analyses/:analysisId/quick-explain" element={<QuickExplainPage />} />
          <Route path="/quick-explain" element={<QuickExplainPage />} />
          <Route path="/analyses/:analysisId/chat" element={<ChatbotPage />} />
          <Route path="/chat" element={<ChatbotPage />} />
          <Route path="/findings/:findingId" element={<FindingDetailPage />} />
          <Route path="/patches/:patchId" element={<PatchPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <CurrentAnalysisProvider>
      <Shell />
    </CurrentAnalysisProvider>
  );
}
