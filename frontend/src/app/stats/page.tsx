import {AppShell} from "@/shared/shell/app-shell";
import {StatsView} from "@/features/stats/view/stats-view";

export default function StatsPage() {
  return (
    <AppShell title="成功率统计">
      <StatsView />
    </AppShell>
  );
}
