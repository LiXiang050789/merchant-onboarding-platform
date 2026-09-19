import {AppShell} from "@/shared/shell/app-shell";
import {MapView} from "@/features/map/view/map-view";

export default function MapPage() {
  return (
    <AppShell title="地图聚合">
      <MapView />
    </AppShell>
  );
}
