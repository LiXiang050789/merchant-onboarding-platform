import {AppShell} from "@/shared/shell/app-shell";
import {DocsView} from "@/features/docs/view/docs-view";

export default function DocsPage() {
  return (
    <AppShell title="知识文档">
      <DocsView />
    </AppShell>
  );
}
