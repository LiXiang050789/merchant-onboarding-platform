"use client";

import {ReactNode, useEffect, useState} from "react";
import Link from "next/link";
import {usePathname, useRouter} from "next/navigation";
import {BarChart3, Boxes, FileText, Map, ScrollText} from "lucide-react";
import {useQueryClient} from "@tanstack/react-query";
import {getAccessToken, getCurrentRole} from "@/shared/api/client";
import {useAuthStore} from "@/shared/auth/auth-store";
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
  const logout = useAuthStore((state) => state.logout);
  const [role, setRole] = useState<string | null>(null);
  const [realtimeState, setRealtimeState] = useState<RealtimeState>("connecting");

  useEffect(() => {
    setRole(getCurrentRole());
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
          <div style={{display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", justifyContent: "flex-end"}}>
            <span className="connection-badge" data-state={realtimeState} data-testid="realtime-state">{realtimeState}</span>
            <span className="muted" data-testid="current-role">角色：{role ? ({merchant: "商户", operator: "运营", admin: "管理员"} as Record<string, string>)[role] ?? role : ""}</span>
            <button className="secondary-button" data-testid="logout-button" onClick={() => {
              logout();
              queryClient.clear();
              router.replace("/login");
            }}>退出登录</button>
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
