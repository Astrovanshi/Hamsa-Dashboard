import React, { useEffect, useState } from 'react';
import {
  Compass,
  TrendingUp,
  Zap,
  Hammer,
  ShieldCheck,
  AlertTriangle,
  Filter,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Ban,
  Search,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { CompanyDossier, EngineType } from '@/types';

interface OpportunityRadarProps {
  onSelectCompany: (symbol: string) => void;
}

export const OpportunityRadarPage: React.FC<OpportunityRadarProps> = ({ onSelectCompany }) => {
  const [companies, setCompanies] = useState<CompanyDossier[]>([]);
  const [filterEngine, setFilterEngine] = useState<string>('all');
  const [filterState, setFilterState] = useState<string>('triggered');
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    hamsaService.getCompanies().then(setCompanies);
  }, []);

  const engineMeta: Record<EngineType, { label: string; icon: any; color: string }> = {
    compounders: { label: 'Compounders', icon: TrendingUp, color: 'text-blue-400' },
    earnings_inflection: { label: 'Earnings Inflection', icon: Zap, color: 'text-amber-400' },
    capex_conversion: { label: 'Capex Conversion', icon: Hammer, color: 'text-purple-400' },
    cash_quality: { label: 'Cash Quality', icon: ShieldCheck, color: 'text-emerald-400' },
    extreme_sell_side_liquidity: { label: 'Extreme Liquidity', icon: AlertTriangle, color: 'text-rose-400' },
  };

  const filteredCompanies = companies.filter((c) => {
    const matchesSearch =
      c.identity.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.identity.companyName.toLowerCase().includes(searchQuery.toLowerCase());

    if (!matchesSearch) return false;

    if (filterEngine === 'all') {
      if (filterState === 'all') return true;
      return c.engineFindings.some((ef) => ef.state === filterState);
    } else {
      const finding = c.engineFindings.find((ef) => ef.engine === filterEngine);
      if (!finding) return false;
      if (filterState === 'all') return true;
      return finding.state === filterState;
    }
  });

  const renderBadge = (state: string) => {
    switch (state) {
      case 'triggered':
        return (
          <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
            <CheckCircle2 className="w-2.5 h-2.5" />
            <span>TRIGGERED</span>
          </span>
        );
      case 'not_triggered':
        return (
          <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#161b22] text-[#8b949e] border border-[#21262d]">
            <XCircle className="w-2.5 h-2.5" />
            <span>NOT TRIG</span>
          </span>
        );
      case 'unproven':
        return (
          <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-950/80 text-amber-400 border border-amber-800/40">
            <HelpCircle className="w-2.5 h-2.5" />
            <span>UNPROVEN</span>
          </span>
        );
      case 'blocked':
        return (
          <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-rose-950/80 text-rose-400 border border-rose-800/40">
            <Ban className="w-2.5 h-2.5" />
            <span>BLOCKED</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex items-center justify-between border-b border-[#1b2230] pb-4">
        <div>
          <h2 className="text-lg font-bold text-[#f0f6fc] tracking-tight">Opportunity Radar (5-Engine Cross-Matrix)</h2>
          <p className="text-xs text-[#526079]">
            Unified cross-sectional opportunity discovery across Compounders, Inflections, Capex Conversions, Cash Quality, and Extreme Liquidity.
          </p>
        </div>
      </div>

      {/* Control & Filter Strip */}
      <div className="flex items-center justify-between bg-[#0d1117] border border-[#1b2230] p-3 rounded font-mono text-xs">
        <div className="flex items-center space-x-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[#526079]" />
            <input
              type="text"
              placeholder="Filter company..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-[#131822] border border-[#1b2230] rounded pl-8 pr-2.5 py-1 text-[#f0f6fc] text-xs focus:outline-none focus:border-blue-500/50"
            />
          </div>

          <div className="flex items-center space-x-1.5">
            <span className="text-[#526079]">ENGINE:</span>
            <select
              value={filterEngine}
              onChange={(e) => setFilterEngine(e.target.value)}
              className="bg-[#131822] border border-[#1b2230] text-[#f0f6fc] rounded px-2.5 py-1 focus:outline-none"
            >
              <option value="all">All 5 Engines</option>
              <option value="compounders">1. Compounders</option>
              <option value="earnings_inflection">2. Earnings Inflection</option>
              <option value="capex_conversion">3. Capex Conversion</option>
              <option value="cash_quality">4. Cash Quality</option>
              <option value="extreme_sell_side_liquidity">5. Extreme Sell-Side</option>
            </select>
          </div>

          <div className="flex items-center space-x-1.5">
            <span className="text-[#526079]">STATE:</span>
            <select
              value={filterState}
              onChange={(e) => setFilterState(e.target.value)}
              className="bg-[#131822] border border-[#1b2230] text-[#f0f6fc] rounded px-2.5 py-1 focus:outline-none"
            >
              <option value="all">All States</option>
              <option value="triggered">Triggered Only</option>
              <option value="unproven">Unproven Only</option>
              <option value="blocked">Blocked Only</option>
              <option value="not_triggered">Not Triggered</option>
            </select>
          </div>
        </div>

        <div className="text-[#526079]">
          Showing <span className="text-[#f0f6fc] font-bold">{filteredCompanies.length}</span> of {companies.length} Admitted Equities
        </div>
      </div>

      {/* Cross-Engine Matrix Table */}
      <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] uppercase tracking-wider">
            <tr>
              <th className="py-2.5 px-4">Symbol / Name</th>
              <th className="py-2.5 px-4">Business Class</th>
              <th className="py-2.5 px-3 text-center">1. Compounder</th>
              <th className="py-2.5 px-3 text-center">2. Inflection</th>
              <th className="py-2.5 px-3 text-center">3. Capex</th>
              <th className="py-2.5 px-3 text-center">4. Cash Qual</th>
              <th className="py-2.5 px-3 text-center">5. Extreme Liq</th>
              <th className="py-2.5 px-4 text-center">Trigger Count</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1b2230]/60">
            {filteredCompanies.map((c) => {
              const triggeredCount = c.engineFindings.filter((ef) => ef.state === 'triggered').length;
              return (
                <tr
                  key={c.identity.entityId}
                  onClick={() => onSelectCompany(c.identity.symbol)}
                  className="hover:bg-[#131822] transition-colors cursor-pointer group"
                >
                  <td className="py-3 px-4">
                    <div className="font-bold text-blue-400 group-hover:underline">
                      {c.identity.symbol}
                    </div>
                    <div className="text-[11px] text-[#8b949e]">{c.identity.companyName}</div>
                  </td>
                  <td className="py-3 px-4">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] uppercase font-mono ${
                        c.identity.businessClass === 'industrial'
                          ? 'bg-blue-950/60 text-blue-300 border border-blue-800/40'
                          : 'bg-amber-950/60 text-amber-300 border border-amber-800/40'
                      }`}
                    >
                      {c.identity.businessClass}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-center">
                    {renderBadge(c.engineFindings.find((ef) => ef.engine === 'compounders')?.state || 'unproven')}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {renderBadge(c.engineFindings.find((ef) => ef.engine === 'earnings_inflection')?.state || 'unproven')}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {renderBadge(c.engineFindings.find((ef) => ef.engine === 'capex_conversion')?.state || 'unproven')}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {renderBadge(c.engineFindings.find((ef) => ef.engine === 'cash_quality')?.state || 'unproven')}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {renderBadge(c.engineFindings.find((ef) => ef.engine === 'extreme_sell_side_liquidity')?.state || 'unproven')}
                  </td>
                  <td className="py-3 px-4 text-center">
                    <span
                      className={`font-bold px-2 py-0.5 rounded text-xs ${
                        triggeredCount >= 2
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-700/60'
                          : triggeredCount === 1
                          ? 'bg-blue-950 text-blue-300 border border-blue-700/60'
                          : 'text-[#526079]'
                      }`}
                    >
                      {triggeredCount} / 5
                    </span>
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