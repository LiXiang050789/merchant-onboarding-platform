"use client";

import {ReactNode, useEffect, useState} from "react";
import Link from "next/link";
import {usePathname, useRouter} from "next/navigation";
import {BarChart3, Boxes, FileText, Map, ScrollText} from "lucide-react";
import {useQueryClient} from "@tanstack/react-query";
import {getAccessToken} from "@/shared/api/client";
import {RealtimeState, startRealtime} from "@/shared/realtime/realtime";

const nav = [
  {href: "/map", label: "地图", icon: Map},
  {href: "/forms", label: "表单", icon: ScrollText},
  {href: "/batches", label: "批次", icon: Boxes},
  {href: "/stats", label: "统计", icon: BarChart3},
  {href: "/docs", label: "文档", icon: FileText}
];

export function AppShell({children, title}: {children: ReactNode; title: string}) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [realtimeState, setRealtimeState] = useState<RealtimeState>("connecting");

  useEffect(() => {
    if (!getAccessToken()) {
      router.replace("/login");
      return;
    }
    return startRealtime(queryClient, setRealtimeState);
  }, [queryClient, router]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Merchant Onboarding</div>
        <nav className="nav" aria-label="主导航">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} data-active={pathname === item.href}>
                <Icon size={18} aria-hidden="true" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="content">
        <div className="topbar">
          <div className="page-title">{title}</div>
          <span className="connection-badge" data-state={realtimeState} data-testid="realtime-state">{realtimeState}</span>
        </div>
        {children}
      </main>
    </div>
  );
}
