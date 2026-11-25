import React, { useState } from 'react';
import {
  Activity,
  Compass,
  TrendingUp,
  Zap,
  Hammer,
  ShieldCheck,
  AlertTriangle,
  FileText,
  Bookmark,
  Radio,
  Server,
  Layers,
  Search,
  Database,
  Calendar,
  Clock,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';

interface LayoutProps {
  currentTab: string;
  onSelectTab: (tab: string, param?: string) => void;
  children: React.ReactNode;
}

interface NavItem {
  id: string;
  label: string;
  icon: any;
  badge?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

export const Layout: React.FC<LayoutProps> = ({ currentTab, onSelectTab, children }) => {
  const [globalSearch, setGlobalSearch] = useState('');
  const conn = hamsaService.getConnectionStatus();

  const navigationSections: NavSection[] = [
    {
      title: 'MARKET CONTEXT',
      items: [
        { id: 'market-radar', label: 'Market Radar', icon: Activity, badge: 'LIVE REGIME' },
        { id: 'opportunity-radar', label: 'Opportunity Radar', icon: Compass, badge: '5 ENGINES' },
      ],
    },
    {
      title: 'OPPORTUNITY ENGINES',
      items: [
        { id: 'compounders', label: '1. Compounders', icon: TrendingUp },
        { id: 'earnings-inflection', label: '2. Earnings Inflection', icon: Zap },
        { id: 'capex-conversion', label: '3. Capex Conversion', icon: Hammer },
        { id: 'cash-quality', label: '4. Cash Quality', icon: ShieldCheck },
        { id: 'extreme-liquidity', label: '5. Extreme Sell-Side', icon: AlertTriangle },
      ],
    },
    {
      title: 'INVESTIGATION & DOSSIERS',
      items: [
        { id: 'company-dossier', label: 'Company Dossier', icon: FileText },
        { id: 'hamsa-11', label: 'HAMSA 11 Framework', icon: Layers },
        { id: 'watchlists', label: 'Watchlists & Theses', icon: Bookmark },
        { id: 'daily-brief', label: 'Daily Market Brief', icon: FileText, badge: 'DAILY EOD' },
        { id: 'discovery-feed', label: 'Discovery Feed', icon: Radio },
      ],
    },
    {
      title: 'SYSTEM & INTEGRITY',
      items: [
        { id: 'universe-lifecycle', label: 'Universe Lifecycle', icon: Layers, badge: '3 TIERS' },
        { id: 'data-coverage', label: 'Data Coverage', icon: Database },
        { id: 'system-health', label: 'System Health', icon: Server },
      ],
    },
  ];

  return (
    <div className="flex h-screen bg-[#07090e] text-[#c9d1d9] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 border-r border-[#1b2230] bg-[#090d14] flex flex-col justify-between shrink-0 select-none">
        <div>
          {/* Logo & Terminal Header */}
          <div className="px-5 py-4 border-b border-[#1b2230] flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="w-7 h-7 rounded bg-blue-600/20 border border-blue-500/40 flex items-center justify-center font-bold text-blue-400 text-sm tracking-wider">
                H
              </div>
              <div>
                <h1 className="text-sm font-bold tracking-wider text-[#f0f6fc] font-mono">HAMSA RADAR</h1>
                <p className="text-[10px] text-[#526079] tracking-tight uppercase">Capital Intelligence Terminal</p>
              </div>
            </div>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
              PIT v6
            </span>
          </div>

          {/* Quick Search */}
          <div className="px-3 py-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[#526079]" />
              <input
                type="text"
                placeholder="Search symbol (e.g. POLYCAB)..."
                value={globalSearch}
                onChange={(e) => setGlobalSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && globalSearch.trim()) {
                    onSelectTab('company-dossier', globalSearch.trim());
                    setGlobalSearch('');
                  }
                }}
                className="w-full bg-[#0d1117] border border-[#1b2230] focus:border-blue-500/50 rounded text-xs pl-8 pr-2.5 py-1.5 text-[#f0f6fc] placeholder-[#526079] focus:outline-none transition-colors font-mono"
              />
            </div>
          </div>

          {/* Navigation Items */}
          <nav className="px-2 py-1 space-y-4 overflow-y-auto max-h-[calc(100vh-220px)]">
            {navigationSections.map((sec) => (
              <div key={sec.title}>
                <div className="px-3 pb-1 text-[10px] font-mono font-semibold tracking-wider text-[#526079]">
                  {sec.title}
                </div>
                <div className="space-y-0.5">
                  {sec.items.map((item) => {
                    const Icon = item.icon;
                    const isActive = currentTab === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => onSelectTab(item.id)}
                        className={`w-full flex items-center justify-between px-3 py-2 rounded text-xs font-medium transition-colors ${
                          isActive
                            ? 'bg-blue-600/15 text-blue-400 border border-blue-500/30'
                            : 'text-[#8b949e] hover:bg-[#131822] hover:text-[#f0f6fc]'
                        }`}
                      >
                        <div className="flex items-center space-x-2.5">
                          <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-blue-400' : 'text-[#526079]'}`} />
                          <span>{item.label}</span>
                        </div>
                        {item.badge && (
                          <span className="text-[9px] font-mono uppercase px-1.5 py-0.2 rounded bg-[#131822] text-[#526079] border border-[#1b2230]">
                            {item.badge}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </div>

        {/* Footer State & Cutoff */}
        <div className="p-3 border-t border-[#1b2230] bg-[#07090e] space-y-2 text-[10px] font-mono">
          <div className="flex items-center justify-between text-[#526079]">
            <div className="flex items-center space-x-1.5">
              <Calendar className="w-3 h-3 text-[#526079]" />
              <span>SESSION</span>
            </div>
            <span className="text-[#c9d1d9]">2026-11-09 EOD</span>
          </div>
          <div className="flex items-center justify-between text-[#526079]">
            <div className="flex items-center space-x-1.5">
              <Clock className="w-3 h-3 text-[#526079]" />
              <span>PIT CUTOFF</span>
            </div>
            <span className="text-amber-400/90">15:30 IST FAIL-CLOSED</span>
          </div>
          <div className="pt-1 border-t border-[#1b2230]/60 flex items-center justify-between">
            <span className="text-[9px] text-[#526079] truncate">{conn.dataSource}</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden">
        {/* Top Navbar */}
        <header className="h-12 border-b border-[#1b2230] bg-[#090d14] flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center space-x-4">
            <span className="text-xs font-mono font-semibold text-[#f0f6fc] tracking-wider uppercase">
              {currentTab.replace('-', ' ')}
            </span>
            <span className="text-[11px] text-[#526079]">|</span>
            <span className="text-[11px] text-[#526079] font-mono">
              COVERAGE UNIVERSE: <strong className="text-[#f0f6fc]">40 ADMITTED MAINBOARD EQUITIES</strong> <span className="text-[#526079] text-[10px]">(INDIAN MAINBOARD EXPANSION IN PROGRESS)</span>
            </span>
          </div>

          <div className="flex items-center space-x-3 text-xs font-mono">
            <span className="px-2.5 py-1 rounded bg-amber-950/80 text-amber-300 border border-amber-700/60 text-[11px] font-bold flex items-center space-x-1">
              <span>HISTORICAL SNAPSHOT: 9 NOV 2026</span>
              <span className="text-[9px] font-normal text-amber-400/80">(NOT LIVE FEED)</span>
            </span>
            <span className="px-2 py-0.5 rounded bg-blue-950/60 text-blue-400 border border-blue-800/40 text-[10px]">
              VENUE: NSE PRIMARY
            </span>
            <span className="px-2 py-0.5 rounded bg-[#131822] text-[#8b949e] border border-[#1b2230] text-[10px]">
              MODE: public_as_of (15:30 IST)
            </span>
          </div>
        </header>

        {/* Viewport Container */}
        <div className="flex-1 overflow-y-auto p-6 bg-[#07090e]">
          {children}
        </div>
      </main>
    </div>
  );
};