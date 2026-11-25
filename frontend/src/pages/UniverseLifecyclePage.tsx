import React, { useEffect, useState } from 'react';
import { Layers, ShieldCheck, ArrowRight, Clock, User, Sparkles, Filter, RefreshCw } from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { CompanyDossier, IntelligenceTier } from '@/types';

interface UniverseLifecycleProps {
  onSelectCompany: (symbol: string) => void;
}

export const UniverseLifecyclePage: React.FC<UniverseLifecycleProps> = ({ onSelectCompany }) => {
  const [companies, setCompanies] = useState<CompanyDossier[]>([]);
  const [selectedTier, setSelectedTier] = useState<string>('ALL');
  const [filterSearch, setFilterSearch] = useState<string>('');
  const [breakdown, setBreakdown] = useState<Record<string, number>>({
    RADAR: 0,
    CANDIDATE: 0,
    INVESTIGATION: 0,
    WATCH: 0,
    ARCHIVED: 0,
  });

  useEffect(() => {
    hamsaService.getCompanies().then((comps) => {
      setCompanies(comps);
      const counts: Record<string, number> = {
        RADAR: 0,
        CANDIDATE: 0,
        INVESTIGATION: 0,
        WATCH: 0,
        ARCHIVED: 0,
      };
      comps.forEach((c) => {
        const t = c.tier || 'CANDIDATE';
        counts[t] = (counts[t] || 0) + 1;
      });
      setBreakdown(counts);
    });
  }, []);

  const handleTierChange = async (entityId: string, newTier: IntelligenceTier) => {
    await hamsaService.transitionTier(entityId, newTier, 'Manual operator tier update via Universe Lifecycle');
    const updated = await hamsaService.getCompanies();
    setCompanies([...updated]);
  };

  const filtered = companies.filter((c) => {
    const matchesTier = selectedTier === 'ALL' || (c.tier || 'CANDIDATE') === selectedTier;
    const matchesSearch =
      c.identity.symbol.toLowerCase().includes(filterSearch.toLowerCase()) ||
      c.identity.companyName.toLowerCase().includes(filterSearch.toLowerCase());
    return matchesTier && matchesSearch;
  });

  const getTierBadge = (tier: string) => {
    switch (tier) {
      case 'INVESTIGATION':
        return 'bg-purple-950/80 text-purple-300 border-purple-800/60';
      case 'CANDIDATE':
        return 'bg-amber-950/80 text-amber-300 border-amber-800/60';
      case 'WATCH':
        return 'bg-blue-950/80 text-blue-300 border-blue-800/60';
      case 'ARCHIVED':
        return 'bg-neutral-900 text-neutral-400 border-neutral-700';
      case 'RADAR':
      default:
        return 'bg-emerald-950/80 text-emerald-300 border-emerald-800/60';
    }
  };

  return (
    <div className="space-y-6 font-mono">
      {/* Header */}
      <div className="border-b border-[#1b2230] pb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-[#f0f6fc]">Tiered Universe & Company Intelligence Lifecycle</h2>
          <p className="text-xs text-[#526079] mt-0.5">
            Dynamic company progression: Market-Wide Radar (T1) → Candidate Intelligence (T2) → Deep Human Investigation (T3).
          </p>
        </div>
        <div className="text-[11px] text-[#526079] bg-[#0d1117] px-3 py-1.5 rounded border border-[#1b2230]">
          Total Monitored Equities: <strong className="text-[#f0f6fc]">{companies.length}</strong>
        </div>
      </div>

      {/* Tier Summary KPI Cards */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { id: 'RADAR', label: '1. RADAR (T1)', desc: 'Continuous EOD/Deliv', count: breakdown.RADAR, color: 'text-emerald-400', border: 'border-emerald-800/40' },
          { id: 'CANDIDATE', label: '2. CANDIDATE (T2)', desc: 'Fundamental Ingestion', count: breakdown.CANDIDATE, color: 'text-amber-400', border: 'border-amber-800/40' },
          { id: 'INVESTIGATION', label: '3. INVESTIGATION (T3)', desc: 'HAMSA 11 Research', count: breakdown.INVESTIGATION, color: 'text-purple-400', border: 'border-purple-800/40' },
          { id: 'WATCH', label: 'WATCH', desc: 'Paused Thesis', count: breakdown.WATCH, color: 'text-blue-400', border: 'border-blue-800/40' },
          { id: 'ARCHIVED', label: 'ARCHIVED', desc: 'Re-entry Eligible', count: breakdown.ARCHIVED, color: 'text-neutral-400', border: 'border-neutral-800' },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setSelectedTier(selectedTier === t.id ? 'ALL' : t.id)}
            className={`p-3.5 rounded text-left transition-all border ${t.border} ${
              selectedTier === t.id ? 'bg-[#161f30] ring-1 ring-blue-500' : 'bg-[#0d1117] hover:bg-[#131822]'
            }`}
          >
            <div className="text-[10px] text-[#526079] font-bold">{t.label}</div>
            <div className={`text-xl font-bold mt-1 ${t.color}`}>{t.count}</div>
            <div className="text-[10px] text-[#526079] mt-0.5">{t.desc}</div>
          </button>
        ))}
      </div>

      {/* Filter and Search Bar */}
      <div className="flex items-center justify-between bg-[#0d1117] border border-[#1b2230] p-3 rounded text-xs">
        <div className="flex items-center space-x-3">
          <input
            type="text"
            placeholder="Search symbol or name..."
            value={filterSearch}
            onChange={(e) => setFilterSearch(e.target.value)}
            className="bg-[#131822] border border-[#1b2230] rounded px-3 py-1 text-[#f0f6fc] text-xs focus:outline-none focus:border-blue-500/50"
          />
          <div className="flex items-center space-x-1.5 text-[#526079]">
            <span>FILTER TIER:</span>
            <select
              value={selectedTier}
              onChange={(e) => setSelectedTier(e.target.value)}
              className="bg-[#131822] border border-[#1b2230] text-[#f0f6fc] rounded px-2.5 py-1 focus:outline-none"
            >
              <option value="ALL">All Tiers ({companies.length})</option>
              <option value="RADAR">Tier 1: Radar</option>
              <option value="CANDIDATE">Tier 2: Candidate</option>
              <option value="INVESTIGATION">Tier 3: Investigation</option>
              <option value="WATCH">Watch</option>
              <option value="ARCHIVED">Archived</option>
            </select>
          </div>
        </div>
        <div className="text-[#526079] text-xs">
          Showing <span className="text-[#f0f6fc] font-bold">{filtered.length}</span> companies
        </div>
      </div>

      {/* Universe Lifecycle Management Grid */}
      <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] uppercase tracking-wider">
            <tr>
              <th className="py-2.5 px-4">Symbol / Name</th>
              <th className="py-2.5 px-4">ISIN</th>
              <th className="py-2.5 px-4">Current Intelligence Tier</th>
              <th className="py-2.5 px-4 text-center">Filing Depth</th>
              <th className="py-2.5 px-4 text-center">EOD History</th>
              <th className="py-2.5 px-4 text-center">Engine Findings</th>
              <th className="py-2.5 px-4 text-right">Transition Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1b2230]/60">
            {filtered.map((c) => {
              const tier = c.tier || 'CANDIDATE';
              const trigCount = c.engineFindings.filter((ef) => ef.state === 'triggered').length;

              return (
                <tr key={c.identity.entityId} className="hover:bg-[#131822] transition-colors">
                  <td
                    onClick={() => onSelectCompany(c.identity.symbol)}
                    className="py-3 px-4 cursor-pointer group"
                  >
                    <div className="font-bold text-blue-400 group-hover:underline">
                      {c.identity.symbol}
                    </div>
                    <div className="text-[11px] text-[#8b949e]">{c.identity.companyName}</div>
                  </td>
                  <td className="py-3 px-4 text-[#526079]">{c.identity.isin}</td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${getTierBadge(tier)}`}>
                      {tier}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-center text-emerald-400">
                    {c.financials.length > 0 ? `${c.financials.length} Metrics` : 'On-Demand'}
                  </td>
                  <td className="py-3 px-4 text-center text-cyan-300">
                    {c.priceData.length} Sessions
                  </td>
                  <td className="py-3 px-4 text-center">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-bold ${
                        trigCount >= 2
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-700/60'
                          : trigCount === 1
                          ? 'bg-blue-950 text-blue-300 border border-blue-700/60'
                          : 'text-[#526079]'
                      }`}
                    >
                      {trigCount} / 5 Triggered
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <select
                      value={tier}
                      onChange={(e) => handleTierChange(c.identity.entityId, e.target.value as any)}
                      className="bg-[#090d14] border border-[#1b2230] text-[#f0f6fc] text-[11px] rounded px-2 py-1 focus:outline-none focus:border-blue-500/50"
                    >
                      <option value="RADAR">Promote to Radar (T1)</option>
                      <option value="CANDIDATE">Candidate Intelligence (T2)</option>
                      <option value="INVESTIGATION">Deep Investigation (T3)</option>
                      <option value="WATCH">Move to Watch</option>
                      <option value="ARCHIVED">Archive Company</option>
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};