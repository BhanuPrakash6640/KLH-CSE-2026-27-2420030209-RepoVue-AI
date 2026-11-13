import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

/**
 * A finding and a patch both belong to an analysis, but their URLs don't carry
 * one. Rather than thread ids through every link, pages announce the analysis
 * they are showing and the sidebar follows. It persists so a reload lands the
 * reviewer back where they were.
 */
interface CurrentAnalysis {
  analysisId: string | null;
  setAnalysisId: (id: string | null) => void;
}

const Context = createContext<CurrentAnalysis>({ analysisId: null, setAnalysisId: () => {} });
const STORAGE = "repovue.analysis";

export function CurrentAnalysisProvider({ children }: { children: ReactNode }) {
  const [analysisId, setValue] = useState<string | null>(
    () => window.localStorage.getItem(STORAGE),
  );

  const setAnalysisId = useCallback((id: string | null) => {
    setValue((previous) => (previous === id ? previous : id));
    if (id) window.localStorage.setItem(STORAGE, id);
    else window.localStorage.removeItem(STORAGE);
  }, []);

  const value = useMemo(() => ({ analysisId, setAnalysisId }), [analysisId, setAnalysisId]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useCurrentAnalysis(): CurrentAnalysis {
  return useContext(Context);
}

/** Call from any page that knows which analysis it is rendering. */
export function useAnnounceAnalysis(id: string | null | undefined): void {
  const { setAnalysisId } = useCurrentAnalysis();
  useEffect(() => {
    if (id) setAnalysisId(id);
  }, [id, setAnalysisId]);
}
