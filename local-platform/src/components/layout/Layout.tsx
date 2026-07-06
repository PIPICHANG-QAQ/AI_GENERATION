import React, { useState } from "react";
import { Link, useLocation } from "wouter";
import { Database, FileText, GraduationCap, ScanLine, LogOut, Menu, X, GalleryVerticalEnd, PanelLeftClose, PanelLeftOpen } from "lucide-react";

const NAV_ITEMS = [
  { href: "/import", label: "题目导入", icon: ScanLine },
  { href: "/", label: "题库中心", icon: Database },
  { href: "/papers", label: "组卷中心", icon: FileText },
  { href: "/knowledge", label: "知识点库", icon: GraduationCap },
];

function NavLinks({ location, onNavigate, collapsed }: { location: string, onNavigate?: () => void, collapsed?: boolean }) {
  return (
    <>
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = location === href;
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            title={collapsed ? label : undefined}
            className={`relative flex items-center rounded-md text-sm font-medium transition-colors ${
              collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2.5"
            } ${
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            }`}
          >
            {active && (
              <span className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-primary" />
            )}
            <Icon className={`w-4 h-4 ${collapsed ? "" : "mr-3"}`} />
            {!collapsed && label}
          </Link>
        );
      })}
    </>
  );
}

function BrandMark() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-9 h-9 rounded-md gradient-primary ring-gloss flex items-center justify-center text-primary-foreground shadow-glow-primary">
        <GalleryVerticalEnd className="w-5 h-5" />
      </div>
      <h1 className="font-bold text-lg gradient-text tracking-tight">AI 题库后台</h1>
    </div>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("qb-sidebar-collapsed") === "1";
  });

  const toggleCollapsed = () =>
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem("qb-sidebar-collapsed", next ? "1" : "0");
      } catch {
        /* ignore storage errors */
      }
      return next;
    });

  return (
    <div className="min-h-[100dvh] flex gradient-hero overflow-hidden">
      {/* Desktop sidebar */}
      <aside
        className={`${
          collapsed ? "w-16" : "w-64"
        } glass-sidebar border-r border-sidebar-border flex flex-col flex-shrink-0 z-10 hidden md:flex transition-[width] duration-200 ease-in-out`}
      >
        <div className={`h-16 flex items-center border-b border-sidebar-border ${collapsed ? "justify-center px-0" : "justify-between px-5"}`}>
          {!collapsed && <BrandMark />}
          <button
            onClick={toggleCollapsed}
            className="w-9 h-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground transition-colors"
            title={collapsed ? "展开导航" : "收起导航"}
            aria-label={collapsed ? "展开导航" : "收起导航"}
          >
            {collapsed ? <PanelLeftOpen className="w-5 h-5" /> : <PanelLeftClose className="w-5 h-5" />}
          </button>
        </div>
        <nav className="flex-1 py-4 px-3 space-y-1">
          {!collapsed && <p className="px-3 pb-2 text-eyebrow uppercase text-muted-foreground/70">导航</p>}
          <NavLinks location={location} collapsed={collapsed} />
        </nav>
        <div className={`border-t border-sidebar-border ${collapsed ? "p-3" : "p-4"}`}>
          {collapsed ? (
            <div className="flex flex-col items-center gap-3">
              <div className="w-9 h-9 rounded-full gradient-primary ring-gloss flex items-center justify-center text-primary-foreground font-bold text-sm" title="admin">A</div>
              <button className="text-muted-foreground hover:text-destructive transition-colors" title="退出登录" aria-label="退出登录">
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="w-9 h-9 rounded-full gradient-primary ring-gloss flex items-center justify-center text-primary-foreground font-bold text-sm">A</div>
                <div>
                  <p className="text-sm font-medium text-sidebar-foreground">admin</p>
                  <p className="text-xs text-muted-foreground">管理员</p>
                </div>
              </div>
              <button className="text-muted-foreground hover:text-destructive transition-colors" title="退出登录">
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0 h-[100dvh] overflow-hidden relative">
        {/* Mobile top bar */}
        <div className="md:hidden h-14 shrink-0 glass-nav border-b border-border flex items-center justify-between px-4 z-20">
          <BrandMark />
          <button
            onClick={() => setMobileOpen((o) => !o)}
            className="w-9 h-9 flex items-center justify-center rounded-md text-foreground/70 hover:bg-accent"
            aria-label="切换导航"
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

        {/* Mobile collapsible nav */}
        {mobileOpen && (
          <>
            <div className="md:hidden fixed inset-0 top-14 bg-foreground/30 z-20" onClick={() => setMobileOpen(false)} />
            <div className="md:hidden absolute top-14 left-0 right-0 glass-strong border-b border-border elevation-3 z-30 p-3 space-y-1">
              <NavLinks location={location} onNavigate={() => setMobileOpen(false)} />
            </div>
          </>
        )}

        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {children}
        </div>
      </main>
    </div>
  );
}
