import {AppShell} from "@/shared/shell/app-shell";
import {BatchesView} from "@/features/batches/view/batches-view";

export default function BatchesPage() {
  return (
    <AppShell title="批次处理">
      <BatchesView />
    </AppShell>
  );
}
