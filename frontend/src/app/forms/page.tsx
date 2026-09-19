import {AppShell} from "@/shared/shell/app-shell";
import {FormsView} from "@/features/forms/view/forms-view";

export default function FormsPage() {
  return (
    <AppShell title="表单列表">
      <FormsView />
    </AppShell>
  );
}
