import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ErrorBox, Loading } from "../components/States";
import { api } from "../lib/api";
import { useAnnounceAnalysis } from "../lib/current";
import { useApi } from "../lib/hooks";
import { DashboardView } from "./Dashboard";
import { RunningView } from "./Running";

const TERMINAL = ["succeeded", "failed", "cancelled"];

/**
 * One URL per run. While it is queued or running this polls and shows the
 * pipeline; once it finishes the same URL is the dashboard. A reviewer can
 * share a link to a run without knowing which state it was in.
 */
export function AnalysisView() {
  const { analysisId = "" } = useParams();
  // Polling stops the moment a run reaches a terminal state, so a finished
  // dashboard is not re-fetched every few seconds forever.
  const [live, setLive] = useState(true);

  const { data, error, initial, reload } = useApi(
    () => api.analysis(analysisId),
    [analysisId],
    live ? 2500 : null,
  );

  useAnnounceAnalysis(analysisId);

  useEffect(() => {
    if (data && TERMINAL.includes(data.status)) setLive(false);
  }, [data]);

  useEffect(() => {
    setLive(true);
  }, [analysisId]);

  if (initial)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <Loading label="Loading the run" />
      </div>
    );

  if (error || !data)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <ErrorBox
          message={error ?? "That run could not be loaded"}
          onRetry={reload}
          hint="If the id came from an old link, the run may since have been deleted."
        />
      </div>
    );

  if (data.status === "succeeded") return <DashboardView analysis={data} />;
  return <RunningView analysis={data} />;
}
