import React, { useEffect, useState } from 'react';
import {
  TrendingUp,
  Zap,
  Hammer,
  ShieldCheck,
  AlertTriangle,
  FileCheck,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Ban,
  Sliders,
  ExternalLink,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { CompanyDossier, EngineType, EvaluationState } from '@/types';

interface EngineWorkbenchProps {
  engineType: EngineType;
  onSelectCompany: (symbol: string) => void;
}

export const EngineWorkbenchPage: React.FC<EngineWorkbenchProps> = ({ engineType, onSelectCompany }) => {
  const [items, setItems] = useState<{
    company: CompanyDossier;
    state: EvaluationState;
    explanation: string;
    inputs: Record<string, any>;
    citations: string[];
  }[]>([]);
  const [filterState, setFilterState] = useState<string>('all');

  useEffect(() => {
    hamsaService.getEngineOpportunities(engineType).then(setItems);
  }, [engineType]);

  const engineHeaders: Record<
    EngineType,
    { title: string; subtitle: string; icon: any; color: string; ruleSummary: string }
  > = {
    compounders: {
      title: 'Engine 1: Compounders',
      subtitle: 'Sustained capital efficiency & multi-year operational compounding without leverage distortion.',
      icon: TrendingUp,
      color: 'text-blue-400',
      ruleSummary: 'Sales CAGR ≥ 12%, PAT CAGR ≥ 12%, ROCE ≥ 12% across 4 comparable annual cycles.',
    },
    earnings_inflection: {
      title: 'Engine 2: Earnings Inflection',
      subtitle: 'Quarterly acceleration in top-line growth and operating leverage expansion.',
      icon: Zap,
      color: 'text-amber-400',
      ruleSummary: 'YoY Sales Growth ≥ 20%, PAT Growth ≥ 25%, Margin expansion over consecutive quarters.',
    },
    capex_conversion: {
      title: 'Engine 3: Capex Conversion',
      subtitle: 'Transition of major fixed-capital investments (Gross Block / CWIP) into productive operating cash flow.',
      icon: Hammer,
      color: 'text-purple-400',
      ruleSummary: 'Rising multi-year capex + 3 Human Verified Qualitative Gates (Commissioning, Demand, Customer Evidence).',
    },
    cash_quality: {
      title: 'Engine 4: Cash Quality & Conversion',
      subtitle: 'True cash-backed accounting audit; identifies divergence between reported earnings and operating cash.',
      icon: ShieldCheck,
      color: 'text-emerald-400',
      ruleSummary: 'Cumulative CFO / PAT ≥ 0.8 across 3 years + Working capital divergence check.',
    },
    extreme_sell_side_liquidity: {
      title: 'Engine 5: Extreme Sell-Side Liquidity',
      subtitle: 'Dislocation discovery: institutional forced-selling absorption and volume exhaustion.',
      icon: AlertTriangle,
      color: 'text-rose-400',
      ruleSummary: 'Volume multiple ≥ 1.5x 20D, elevated delivery, price drawdown + Verified Forced Selling & Absorption evidence.',
    },
  };

  const currentMeta = engineHeaders[engineType];
  const Icon = currentMeta.icon;

  const filteredItems = items.filter((item) => {
    if (filterState === 'all') return true;
    return item.state === filterState;
  });

  const renderBadge = (state: string) => {
    switch (state) {
      case 'triggered':
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
            <CheckCircle2 className="w-3 h-3" />
            <span>TRIGGERED</span>
          </span>
        );
      case 'not_triggered':
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-mono bg-[#161b22] text-[#8b949e] border border-[#21262d]">
            <XCircle className="w-3 h-3" />
            <span>NOT TRIGGERED</span>
          </span>
        );
      case 'unproven':
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-mono bg-amber-950/80 text-amber-400 border border-amber-800/40">
            <HelpCircle className="w-3 h-3" />
            <span>UNPROVEN (GATES PENDING)</span>
          </span>
        );
      case 'blocked':
        return (
          <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-mono bg-rose-950/80 text-rose-400 border border-rose-800/40">
            <Ban className="w-3 h-3" />
            <span>BLOCKED (GUARDRAIL)</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Workbench Header Banner */}
      <div className="border-b border-[#1b2230] pb-4 flex items-start justify-between">
        <div className="flex items-start space-x-3">
          <div className="p-2.5 rounded bg-[#0d1117] border border-[#1b2230] mt-0.5">
            <Icon className={`w-5 h-5 ${currentMeta.color}`} />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#f0f6fc] tracking-tight">{currentMeta.title}</h2>
            <p className="text-xs text-[#526079] max-w-2xl mt-0.5">{currentMeta.subtitle}</p>
            <div className="mt-2 text-[11px] font-mono text-[#8b949e] bg-[#0d1117] px-2.5 py-1 rounded border border-[#1b2230] inline-block">
              RULE: <span className="text-[#f0f6fc]">{currentMeta.ruleSummary}</span>
            </div>
          </div>
        </div>

        {/* State Filter Controls */}
        <div className="flex items-center space-x-2 font-mono text-xs">
          <span className="text-[#526079]">STATUS:</span>
          <select
            value={filterState}
            onChange={(e) => setFilterState(e.target.value)}
            className="bg-[#0d1117] border border-[#1b2230] text-[#f0f6fc] rounded px-3 py-1.5 focus:outline-none"
          >
            <option value="all">All ({items.length})</option>
            <option value="triggered">
              Triggered ({items.filter((i) => i.state === 'triggered').length})
            </option>
            <option value="unproven">
              Unproven ({items.filter((i) => i.state === 'unproven').length})
            </option>
            <option value="not_triggered">
              Not Triggered ({items.filter((i) => i.state === 'not_triggered').length})
            </option>
            <option value="blocked">
              Blocked ({items.filter((i) => i.state === 'blocked').length})
            </option>
          </select>
        </div>
      </div>

      {/* Results Cards List */}
      <div className="space-y-3 font-mono">
        {filteredItems.map((item) => {
          const comp = item.company;
          const isTriggered = item.state === 'triggered';

          return (
            <div
              key={comp.identity.entityId}
              className={`p-4 rounded border transition-all ${
                isTriggered
                  ? 'bg-[#0d1420] border-emerald-800/40 hover:border-emerald-600/60'
                  : 'bg-[#0d1117] border-[#1b2230] hover:border-[#242e42]'
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center space-x-3">
                    <button
                      onClick={() => onSelectCompany(comp.identity.symbol)}
                      className="text-sm font-bold text-blue-400 hover:underline flex items-center space-x-1"
                    >
                      <span>{comp.identity.symbol}</span>
                      <ExternalLink className="w-3 h-3 text-blue-400/60" />
                    </button>
                    <span className="text-xs text-[#f0f6fc]">{comp.identity.companyName}</span>
                    <span className="text-[10px] uppercase px-1.5 py-0.2 rounded bg-[#161b22] text-[#8b949e] border border-[#21262d]">
                      {comp.identity.businessClass}
                    </span>
                  </div>

                  <p className="text-xs text-[#8b949e] mt-2 max-w-3xl">
                    {item.explanation}
                  </p>
                </div>

                <div>{renderBadge(item.state)}</div>
              </div>

              {/* Dynamic Inputs Strip */}
              <div className="mt-3 pt-3 border-t border-[#1b2230]/60 grid grid-cols-4 gap-2 text-[11px]">
                {Object.entries(item.inputs)
                  .filter(([k]) => k !== 'input_quality_states' && k !== 'source_observation_ids')
                  .slice(0, 4)
                  .map(([key, val]) => (
                    <div key={key} className="bg-[#090d14] p-2 rounded border border-[#1b2230]/40">
                      <div className="text-[10px] text-[#526079] uppercase truncate">
                        {key.replace(/_/g, ' ')}
                      </div>
                      <div className="text-[#f0f6fc] font-semibold truncate mt-0.5">
                        {typeof val === 'boolean'
                          ? val
                            ? 'TRUE'
                            : 'FALSE'
                          : typeof val === 'number'
                          ? Number(val).toFixed(2)
                          : String(val)}
                      </div>
                    </div>
                  ))}
              </div>

              {/* Citation Footer */}
              {item.citations.length > 0 && (
                <div className="mt-2.5 flex items-center space-x-1.5 text-[10px] text-[#526079]">
                  <FileCheck className="w-3 h-3 text-[#526079]" />
                  <span>Verified Filings:</span>
                  <span className="text-blue-400/80 truncate">{item.citations.join(', ')}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};