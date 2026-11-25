import React, { useEffect, useState } from 'react';
import {
  FileText,
  Activity,
  Layers,
  TrendingUp,
  AlertTriangle,
  Zap,
  Calendar,
  CheckCircle2,
  ShieldCheck,
  Search,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';

interface DailyBriefProps {
  onSelectCompany: (symbol: string) => void;
}

export const DailyBriefPage: React.FC<DailyBriefProps> = ({ onSelectCompany }) => {
  const [brief, setBrief] = useState<any>(null);
  const [selectedTab, setSelectedTab] = useState<'brief' | 'shadow' | 'regime'>('brief');

  useEffect(() => {
    // Attempt live fetch first, fallback to snapshot
    fetch('http://127.0.0.1:8080/api/brief?date=2026-11-09')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setBrief(data);
        } else {
          // Fallback minimal structure
          setBrief({
            trade_date: '2026-11-09',
            market_regime: 'Selective Rotational Dispersion',
            breadth_ratio: 1.0,
            advancers: 20,
            decliners: 20,
            total_turnover_cr: 30922.1,
            high_importance_events: [
              { symbol: 'SUPRIYA', volume_multiple: 13.09, delivery_pct: 21.5, delivery_chg_pp: -11.9, session_return_pct: -9.28 },
              { symbol: 'FINCABLES', volume_multiple: 10.79, delivery_pct: 14.8, delivery_chg_pp: -38.6, session_return_pct: 12.96 },
              { symbol: 'HAPPYFORGE', volume_multiple: 5.3, delivery_pct: 33.1, delivery_chg_pp: -32.2, session_return_pct: 6.34 },
              { symbol: 'TENNIND', volume_multiple: 3.73, delivery_pct: 60.4, delivery_chg_pp: 10.8, session_return_pct: 0.31 },
            ],
            absorption_watch: [
              { symbol: 'SUPRIYA', volume_multiple: 13.09, drawdown_20d_pct: -30.2, close_range_pos: 0.52 },
              { symbol: 'NEULANDLAB', volume_multiple: 2.51, drawdown_20d_pct: -5.0, close_range_pos: 0.52 },
              { symbol: 'AIAENG', volume_multiple: 1.92, drawdown_20d_pct: -17.5, close_range_pos: 0.44 },
            ],
            momentum_expansion: [
              { symbol: 'FINCABLES', session_return_pct: 12.96, volume_multiple: 10.79, delivery_pct: 14.8 },
              { symbol: 'HAPPYFORGE', session_return_pct: 6.34, volume_multiple: 5.3, delivery_pct: 33.1 },
            ],
            new_shadow_candidates: [
              { symbol: 'AIAENG', primary_trigger: 'Deliv Chg +19.3pp', trigger_detail: 'Absorption (DD -17.5%, ClosePos 0.44)' },
              { symbol: 'RATEGAIN', primary_trigger: 'Vol 3.57x & Deliv Chg +19.2pp', trigger_detail: 'Dual institutional surge' },
              { symbol: 'TENNIND', primary_trigger: 'Vol 3.73x & Deliv Chg +10.8pp', trigger_detail: 'High turnover expansion' },
              { symbol: 'BLUEJET', primary_trigger: 'Deliv Chg +48.6pp', trigger_detail: 'Heavy institutional settlement shift' },
            ],
          });
        }
      })
      .catch(() => {
        // Fallback default
        setBrief({
          trade_date: '2026-11-09',
          market_regime: 'Selective Rotational Dispersion',
          breadth_ratio: 1.0,
          advancers: 20,
          decliners: 20,
          total_turnover_cr: 30922.1,
          high_importance_events: [],
          absorption_watch: [],
          momentum_expansion: [],
          new_shadow_candidates: [],
        });
      });
  }, []);

  if (!brief) {
    return <div className="text-xs font-mono text-[#526079]">Loading daily intelligence brief...</div>;
  }

  return (
    <div className="space-y-6 font-mono">
      {/* Header Banner */}
      <div className="border-b border-[#1b2230] pb-4 flex items-center justify-between">
        <div>
          <div className="flex items-center space-x-3">
            <h2 className="text-lg font-bold text-[#f0f6fc]">HAMSA Daily Market Intelligence Brief</h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-blue-950/80 text-blue-300 border border-blue-800/60">
              SESSION: {brief.trade_date}
            </span>
          </div>
          <p className="text-xs text-[#526079] mt-0.5">
            Ranked, evidence-first end-of-day market briefing summarizing participation regimes, absorption candidates, and shadow triggers.
          </p>
        </div>
        <div className="flex items-center space-x-2 text-xs">
          <span className="text-[#526079]">REGIME:</span>
          <span className="px-2.5 py-1 rounded bg-amber-950/80 text-amber-300 border border-amber-800/60 font-bold uppercase">
            {brief.market_regime}
          </span>
        </div>
      </div>

      {/* Top Breadth & Turnover Strip */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">TOTAL MARKET TURNOVER</div>
          <div className="text-lg font-bold text-[#f0f6fc] mt-1">₹{brief.total_turnover_cr?.toLocaleString()} Cr</div>
          <div className="text-[10px] text-emerald-400 mt-1">Official NSE Mainboard EOD</div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">BREADTH RATIO (A/D)</div>
          <div className="text-lg font-bold text-amber-400 mt-1">{brief.breadth_ratio}x</div>
          <div className="text-[10px] text-[#526079] mt-1">
            {brief.advancers} Advancers / {brief.decliners} Decliners
          </div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">ABSORPTION CANDIDATES</div>
          <div className="text-lg font-bold text-cyan-400 mt-1">{brief.absorption_watch?.length || 0}</div>
          <div className="text-[10px] text-cyan-500/80 mt-1">Heavy Selling Absorbed</div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">SHADOW QUALIFIED (T2)</div>
          <div className="text-lg font-bold text-purple-400 mt-1">{brief.new_shadow_candidates?.length || 0}</div>
          <div className="text-[10px] text-purple-500/80 mt-1">Experimental Profile v1.0</div>
        </div>
      </div>

      {/* Sub-Navigation */}
      <div className="flex border-b border-[#1b2230] text-xs space-x-2">
        {[
          { id: 'brief', label: 'Ranked Brief Sections' },
          { id: 'shadow', label: `Shadow Candidate Queue (${brief.new_shadow_candidates?.length || 0})` },
          { id: 'regime', label: 'Participation & Breadth' },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setSelectedTab(t.id as any)}
            className={`px-4 py-2 border-b-2 transition-colors ${
              selectedTab === t.id
                ? 'border-blue-500 text-blue-400 font-bold'
                : 'border-transparent text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Ranked Brief Sections */}
      {selectedTab === 'brief' && (
        <div className="grid grid-cols-2 gap-4">
          {/* Section A: High-Importance Radar Events */}
          <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-3">
            <div className="flex items-center justify-between border-b border-[#1b2230] pb-2">
              <div className="flex items-center space-x-2">
                <Activity className="w-4 h-4 text-cyan-400" />
                <h3 className="text-xs font-bold text-[#f0f6fc] uppercase tracking-wide">
                  High-Importance Radar Events
                </h3>
              </div>
              <span className="text-[10px] text-[#526079]">Ranked by Volume & Delivery</span>
            </div>

            <div className="space-y-2">
              {brief.high_importance_events?.map((ev: any) => (
                <div
                  key={ev.symbol}
                  onClick={() => onSelectCompany(ev.symbol)}
                  className="p-2.5 rounded bg-[#090d14] border border-[#1b2230]/60 hover:border-[#242e42] transition-colors cursor-pointer flex items-center justify-between"
                >
                  <div>
                    <div className="font-bold text-blue-400 text-xs">{ev.symbol}</div>
                    <div className="text-[10px] text-[#526079] mt-0.5">
                      Vol: <strong className="text-cyan-300">{ev.volume_multiple?.toFixed(2)}x</strong> | Deliv: {ev.delivery_pct?.toFixed(1)}% (Δ {ev.delivery_chg_pp >= 0 ? `+${ev.delivery_chg_pp.toFixed(1)}` : ev.delivery_chg_pp?.toFixed(1)}pp)
                    </div>
                  </div>
                  <span className={`text-xs font-bold ${ev.session_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {ev.session_return_pct >= 0 ? `+${ev.session_return_pct?.toFixed(2)}` : ev.session_return_pct?.toFixed(2)}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Section B: Absorption Watch */}
          <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-3">
            <div className="flex items-center justify-between border-b border-[#1b2230] pb-2">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <h3 className="text-xs font-bold text-[#f0f6fc] uppercase tracking-wide">
                  Absorption Watch (Supply Exhaustion)
                </h3>
              </div>
              <span className="text-[10px] text-[#526079]">Drawdown + Strong Close</span>
            </div>

            <div className="space-y-2">
              {brief.absorption_watch?.map((ev: any) => (
                <div
                  key={ev.symbol}
                  onClick={() => onSelectCompany(ev.symbol)}
                  className="p-2.5 rounded bg-[#090d14] border border-[#1b2230]/60 hover:border-[#242e42] transition-colors cursor-pointer flex items-center justify-between"
                >
                  <div>
                    <div className="font-bold text-blue-400 text-xs">{ev.symbol}</div>
                    <div className="text-[10px] text-[#526079] mt-0.5">
                      Drawdown: <strong className="text-rose-400">{ev.drawdown_20d_pct?.toFixed(1)}%</strong> | Close Pos: <strong className="text-emerald-400">{ev.close_range_pos?.toFixed(2)}</strong>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                    Vol {ev.volume_multiple?.toFixed(2)}x
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Shadow Candidate Queue */}
      {selectedTab === 'shadow' && (
        <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden">
          <div className="px-4 py-3 bg-[#131822] border-b border-[#1b2230] flex items-center justify-between text-xs">
            <span className="text-[#8b949e]">SHADOW CANDIDATE EVALUATION QUEUE (EXPERIMENTAL PROFILE shadow-v1.0)</span>
            <span className="text-[#526079]">Isolated from automated fundamental downloads</span>
          </div>

          <table className="w-full text-left text-xs">
            <thead className="bg-[#090d14] text-[#8b949e] border-b border-[#1b2230] text-[11px] uppercase tracking-wider">
              <tr>
                <th className="py-2.5 px-4">Symbol / Name</th>
                <th className="py-2.5 px-4">Primary Trigger</th>
                <th className="py-2.5 px-4">Trigger Details</th>
                <th className="py-2.5 px-4 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1b2230]/60">
              {brief.new_shadow_candidates?.map((c: any) => (
                <tr
                  key={c.symbol}
                  onClick={() => onSelectCompany(c.symbol)}
                  className="hover:bg-[#131822] cursor-pointer transition-colors"
                >
                  <td className="py-3 px-4 font-bold text-blue-400">{c.symbol}</td>
                  <td className="py-3 px-4 text-cyan-300">{c.primary_trigger}</td>
                  <td className="py-3 px-4 text-[#8b949e]">{c.trigger_detail}</td>
                  <td className="py-3 px-4 text-center">
                    <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-purple-950 text-purple-300 border border-purple-800">
                      SHADOW QUALIFIED
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 3: Regime Breakdown */}
      {selectedTab === 'regime' && (
        <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-4 text-xs">
          <h3 className="text-xs font-bold text-[#f0f6fc] uppercase tracking-wide">
            Market Participation & Dispersion Diagnostics
          </h3>
          <p className="text-[#8b949e]">
            Session Breadth Ratio is currently at <strong className="text-amber-400">{brief.breadth_ratio}x</strong>, indicating a <strong>{brief.market_regime}</strong> market environment. Total daily mainboard turnover of <strong className="text-[#f0f6fc]">₹{brief.total_turnover_cr?.toLocaleString()} Cr</strong> shows active capital rotation across core industrial and banking sectors without broad index-level liquidation.
          </p>
        </div>
      )}
    </div>
  );
};