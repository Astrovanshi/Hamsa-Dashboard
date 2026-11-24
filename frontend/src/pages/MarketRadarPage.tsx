import React, { useEffect, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Info,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { MarketRadarSummary } from '@/types';

interface MarketRadarProps {
  onSelectCompany: (symbol: string) => void;
}

export const MarketRadarPage: React.FC<MarketRadarProps> = ({ onSelectCompany }) => {
  const [radar, setRadar] = useState<MarketRadarSummary | null>(null);

  useEffect(() => {
    hamsaService.getMarketRadar().then(setRadar);
  }, []);

  if (!radar) {
    return <div className="text-xs font-mono text-[#526079]">Loading market radar snapshot...</div>;
  }

  const advShare = Math.round((radar.advancers / (radar.advancers + radar.decliners + radar.unchanged)) * 100);
  const decShare = Math.round((radar.decliners / (radar.advancers + radar.decliners + radar.unchanged)) * 100);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex items-center justify-between border-b border-[#1b2230] pb-4">
        <div>
          <h2 className="text-lg font-bold text-[#f0f6fc] tracking-tight">Market Radar & Participation Context</h2>
          <p className="text-xs text-[#526079]">
            Comprehensive EOD market breadth, volume dislocation, and participation regime across admitted mainboard equities.
          </p>
        </div>
        <div className="flex items-center space-x-2 font-mono text-xs">
          <span className="text-[#526079]">REGIME:</span>
          <span className="px-2.5 py-1 rounded bg-blue-950/80 border border-blue-700/50 text-blue-300 font-semibold uppercase tracking-wider">
            {radar.regime}
          </span>
        </div>
      </div>

      {/* KPI Cards Strip */}
      <div className="grid grid-cols-5 gap-3 font-mono">
        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">TOTAL TURNOVER</div>
          <div className="text-lg font-bold text-[#f0f6fc] mt-1">₹{radar.totalTurnoverCr.toLocaleString()} Cr</div>
          <div className="text-[10px] text-emerald-400 mt-1 flex items-center">
            <span>NSE Mainboard Session</span>
          </div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">BREADTH RATIO (A/D)</div>
          <div className="text-lg font-bold text-amber-400 mt-1">{radar.breadthRatio}x</div>
          <div className="text-[10px] text-[#526079] mt-1">
            {radar.advancers} Adv / {radar.decliners} Dec
          </div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">ADVANCERS SHARE</div>
          <div className="text-lg font-bold text-emerald-400 mt-1">{advShare}%</div>
          <div className="w-full bg-[#1b2230] h-1.5 rounded-full mt-2 overflow-hidden">
            <div className="bg-emerald-500 h-full" style={{ width: `${advShare}%` }}></div>
          </div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">DECLINERS SHARE</div>
          <div className="text-lg font-bold text-rose-400 mt-1">{decShare}%</div>
          <div className="w-full bg-[#1b2230] h-1.5 rounded-full mt-2 overflow-hidden">
            <div className="bg-rose-500 h-full" style={{ width: `${decShare}%` }}></div>
          </div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded">
          <div className="text-[11px] text-[#526079]">ACTIVE DISLOCATIONS</div>
          <div className="text-lg font-bold text-cyan-400 mt-1">{radar.dislocations.length}</div>
          <div className="text-[10px] text-cyan-500/80 mt-1">Volume/Delivery Spikes</div>
        </div>
      </div>

      {/* Market Breadth & Anomaly Bar */}
      <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-2">
        <div className="flex items-center justify-between text-xs font-mono">
          <span className="text-[#8b949e]">SESSION PARTICIPATION DISTRIBUTION</span>
          <span className="text-[#526079]">Total Tracked: {radar.eligibleCount} Securities</span>
        </div>
        <div className="h-3 w-full bg-[#161b22] rounded flex overflow-hidden">
          <div className="bg-emerald-600/80 h-full" style={{ width: `${advShare}%` }} title={`Advancers: ${radar.advancers}`} />
          <div className="bg-neutral-600 h-full" style={{ width: `${Math.round((radar.unchanged / radar.eligibleCount) * 100)}%` }} title={`Unchanged: ${radar.unchanged}`} />
          <div className="bg-rose-600/80 h-full" style={{ width: `${decShare}%` }} title={`Decliners: ${radar.decliners}`} />
        </div>
        <div className="flex items-center justify-between text-[10px] font-mono text-[#526079] pt-1">
          <span className="text-emerald-400">● {radar.advancers} Advancers ({advShare}%)</span>
          <span className="text-neutral-400">● {radar.unchanged} Unchanged</span>
          <span className="text-rose-400">● {radar.decliners} Decliners ({decShare}%)</span>
        </div>
      </div>

      {/* Market Dislocations Table */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-[#f0f6fc] tracking-tight">
              Session Volume & Delivery Dislocations
            </h3>
          </div>
          <span className="text-xs text-[#526079] font-mono">
            Filtered by volume &gt; 1.5x 20D or Delivery shift &gt; 5pp
          </span>
        </div>

        <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] uppercase tracking-wider">
              <tr>
                <th className="py-2.5 px-4">Symbol</th>
                <th className="py-2.5 px-4">Company Name</th>
                <th className="py-2.5 px-4 text-right">Close (₹)</th>
                <th className="py-2.5 px-4 text-right">Return (1D)</th>
                <th className="py-2.5 px-4 text-right">Vol Multiple</th>
                <th className="py-2.5 px-4 text-right">Delivery %</th>
                <th className="py-2.5 px-4 text-right">Deliv Chg (pp)</th>
                <th className="py-2.5 px-4">Type</th>
                <th className="py-2.5 px-4">Investigation Rationale</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1b2230]/60">
              {radar.dislocations.map((d) => {
                const isPos = d.returnPct >= 0;
                return (
                  <tr
                    key={d.symbol}
                    onClick={() => onSelectCompany(d.symbol)}
                    className="hover:bg-[#131822] transition-colors cursor-pointer group"
                  >
                    <td className="py-2.5 px-4 font-bold text-blue-400 group-hover:underline">
                      {d.symbol}
                    </td>
                    <td className="py-2.5 px-4 text-[#c9d1d9]">{d.companyName}</td>
                    <td className="py-2.5 px-4 text-right text-[#f0f6fc] font-semibold">
                      ₹{d.close.toLocaleString()}
                    </td>
                    <td className={`py-2.5 px-4 text-right font-semibold ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      <span className="flex items-center justify-end">
                        {isPos ? <ArrowUpRight className="w-3 h-3 mr-0.5" /> : <ArrowDownRight className="w-3 h-3 mr-0.5" />}
                        {d.returnPct.toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right text-cyan-300 font-bold">
                      {d.volumeMultiple.toFixed(2)}x
                    </td>
                    <td className="py-2.5 px-4 text-right text-[#f0f6fc]">
                      {d.deliveryPct.toFixed(1)}%
                    </td>
                    <td className={`py-2.5 px-4 text-right ${d.deliveryChgPp >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {d.deliveryChgPp >= 0 ? `+${d.deliveryChgPp.toFixed(1)}` : d.deliveryChgPp.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-4">
                      <span className="px-2 py-0.5 rounded text-[10px] bg-cyan-950/80 text-cyan-300 border border-cyan-800/40">
                        {d.dislocationType.replace('_', ' ').toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-[#8b949e] text-[11px] truncate max-w-xs">
                      {d.rationale}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};