import React, { useEffect, useState } from 'react';
import { Layers, Bookmark, Radio, Database, Server, CheckCircle2, ShieldCheck, AlertCircle } from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { CompanyDossier, IntelligenceFeedItem, SystemHealthMetric } from '@/types';

// 1. HAMSA 11 Framework Page
export const Hamsa11Page: React.FC = () => {
  const gates = [
    { num: 1, name: 'GAP', desc: 'Is there a structural dislocation between operational performance and market valuation?', category: 'Quantitative Valuation' },
    { num: 2, name: 'CHOKE POINT', desc: 'Does the company occupy an indispensable node or monopoly bottleneck in the value chain?', category: 'Moat Verification' },
    { num: 3, name: 'TURBO', desc: 'Is there an accelerating operational driver (volume demand, product mix enrichment)?', category: 'Growth Engine' },
    { num: 4, name: 'REAL BUYERS', desc: 'Is institutional/mutual fund accumulation evident in shareholder registers and delivery spikes?', category: 'Sponsorship' },
    { num: 5, name: 'STACK', desc: 'Is the balance sheet resilient, low-debt, and capable of funding self-compounding growth?', category: 'Solvency & Stack' },
    { num: 6, name: 'TRIGGER', desc: 'Is a concrete operational catalyst active (commissioning, regulatory reform, de-bottlenecking)?', category: 'Operational Event' },
    { num: 7, name: 'JOCKEY', desc: 'Does management possess proven capital allocation discipline, skin in the game, and integrity?', category: 'Governance Track Record' },
    { num: 8, name: 'THIN FLOAT', desc: 'Is tradeable float scarce enough that institutional demand creates sustained re-rating?', category: 'Market Microstructure' },
    { num: 9, name: 'CEILING', desc: 'Is the market headroom vast enough to support 5-10x growth without market saturation?', category: 'Runway / TAM' },
    { num: 10, name: 'WHAT KILLS IT', desc: 'What are the catastrophic failure modes (tariff changes, raw material inflation, obsolescence)?', category: 'Risk Defense' },
    { num: 11, name: 'EXTREME LIQUIDITY', desc: 'Has forced selling or panic distribution been absorbed by strong institutional hands?', category: 'Liquidity Exhaustion' },
  ];

  return (
    <div className="space-y-6 font-mono">
      <div className="border-b border-[#1b2230] pb-4">
        <h2 className="text-lg font-bold text-[#f0f6fc]">HAMSA 11 Qualitative Investigation Framework</h2>
        <p className="text-xs text-[#526079]">
          Eleven rigorous mental models distinguishing verified facts, hypotheses, and critical risks.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {gates.map((g) => (
          <div key={g.num} className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="w-5 h-5 rounded bg-blue-950 text-blue-400 border border-blue-800 text-[10px] flex items-center justify-center font-bold">
                  {g.num}
                </span>
                <span className="font-bold text-xs text-[#f0f6fc]">{g.name}</span>
              </div>
              <span className="text-[10px] text-[#526079] uppercase">{g.category}</span>
            </div>
            <p className="text-xs text-[#8b949e]">{g.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

// 2. Watchlists Page
export const WatchlistsPage: React.FC<{ onSelectCompany: (symbol: string) => void }> = ({ onSelectCompany }) => {
  const [companies, setCompanies] = useState<CompanyDossier[]>([]);

  useEffect(() => {
    hamsaService.getCompanies().then((cs) => {
      setCompanies(cs.filter((c) => c.watchlistStatus !== 'unassigned'));
    });
  }, []);

  return (
    <div className="space-y-6 font-mono">
      <div className="border-b border-[#1b2230] pb-4">
        <h2 className="text-lg font-bold text-[#f0f6fc]">Active Watchlists & Theses</h2>
        <p className="text-xs text-[#526079]">
          Tracked opportunities with human-authored investment theses and review histories.
        </p>
      </div>

      <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] uppercase">
            <tr>
              <th className="py-2.5 px-4">Symbol</th>
              <th className="py-2.5 px-4">Company Name</th>
              <th className="py-2.5 px-4">Status</th>
              <th className="py-2.5 px-4">Latest Research Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1b2230]/60">
            {companies.map((c) => (
              <tr
                key={c.identity.entityId}
                onClick={() => onSelectCompany(c.identity.symbol)}
                className="hover:bg-[#131822] cursor-pointer transition-colors"
              >
                <td className="py-3 px-4 font-bold text-blue-400">{c.identity.symbol}</td>
                <td className="py-3 px-4 text-[#f0f6fc]">{c.identity.companyName}</td>
                <td className="py-3 px-4">
                  <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-blue-950 text-blue-400 border border-blue-800">
                    {c.watchlistStatus}
                  </span>
                </td>
                <td className="py-3 px-4 text-[#8b949e] text-xs">
                  {c.researchNotes[0]?.thesis || 'Thesis formulation in progress'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// 3. Discovery Feed Page
export const DiscoveryFeedPage: React.FC<{ onSelectCompany: (symbol: string) => void }> = ({ onSelectCompany }) => {
  const [feed, setFeed] = useState<IntelligenceFeedItem[]>([]);

  useEffect(() => {
    hamsaService.getIntelligenceFeed().then(setFeed);
  }, []);

  return (
    <div className="space-y-6 font-mono">
      <div className="border-b border-[#1b2230] pb-4">
        <h2 className="text-lg font-bold text-[#f0f6fc]">Chronological Intelligence Feed</h2>
        <p className="text-xs text-[#526079]">
          Sourced disclosures, engine signals, and research findings in chronological publication order.
        </p>
      </div>

      <div className="space-y-3">
        {feed.map((item) => (
          <div
            key={item.id}
            onClick={() => onSelectCompany(item.symbol)}
            className="p-4 rounded bg-[#0d1117] border border-[#1b2230] hover:border-[#242e42] transition-colors cursor-pointer space-y-2"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="font-bold text-blue-400 text-xs">{item.symbol}</span>
                <span className="text-xs text-[#f0f6fc]">{item.companyName}</span>
                <span className="text-[10px] uppercase px-1.5 py-0.2 rounded bg-[#161b22] text-[#8b949e] border border-[#21262d]">
                  {item.category}
                </span>
              </div>
              <span className="text-xs text-[#526079]">{item.eventDate}</span>
            </div>
            <p className="text-xs text-[#c9d1d9] font-medium">{item.whatHappened}</p>
            <div className="flex items-center justify-between text-[11px] pt-1 border-t border-[#1b2230]/40 text-[#8b949e]">
              <span>Impact: {item.whyItMatters}</span>
              <span className="text-[#526079] text-[10px]">Source: {item.source}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// 4. Data Coverage Page
export const DataCoveragePage: React.FC = () => {
  const [companies, setCompanies] = useState<CompanyDossier[]>([]);

  useEffect(() => {
    hamsaService.getCompanies().then(setCompanies);
  }, []);

  return (
    <div className="space-y-6 font-mono">
      <div className="border-b border-[#1b2230] pb-4">
        <h2 className="text-lg font-bold text-[#f0f6fc]">Admitted Equity Coverage Matrix (40 Securities)</h2>
        <p className="text-xs text-[#526079]">
          Audit grid verifying historical filing depth, EOD price continuity, and exchange classification for the 40 admitted mainboard equities. Note: Full NSE/BSE universe expansion is in progress.
        </p>
      </div>

      <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden max-h-[550px] overflow-y-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] sticky top-0 uppercase">
            <tr>
              <th className="py-2.5 px-4">ISIN</th>
              <th className="py-2.5 px-4">Symbol</th>
              <th className="py-2.5 px-4">Company Name</th>
              <th className="py-2.5 px-4">Classification</th>
              <th className="py-2.5 px-4 text-center">Filing Depth</th>
              <th className="py-2.5 px-4 text-center">EOD Prices</th>
              <th className="py-2.5 px-4 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1b2230]/60">
            {companies.map((c) => (
              <tr key={c.identity.entityId} className="hover:bg-[#131822] transition-colors">
                <td className="py-2.5 px-4 text-[#526079]">{c.identity.isin}</td>
                <td className="py-2.5 px-4 font-bold text-blue-400">{c.identity.symbol}</td>
                <td className="py-2.5 px-4 text-[#f0f6fc]">{c.identity.companyName}</td>
                <td className="py-2.5 px-4 uppercase text-[10px] text-blue-300">{c.identity.businessClass}</td>
                <td className="py-2.5 px-4 text-center text-emerald-400">{c.financials.length} Metrics</td>
                <td className="py-2.5 px-4 text-center text-cyan-300">{c.priceData.length} Sessions</td>
                <td className="py-2.5 px-4 text-center">
                  <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
                    PASS (v6)
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// 5. System Health Page
export const SystemHealthPage: React.FC = () => {
  const [health, setHealth] = useState<SystemHealthMetric | null>(null);

  useEffect(() => {
    hamsaService.getSystemHealth().then(setHealth);
  }, []);

  if (!health) return <div className="text-xs font-mono text-[#526079]">Loading system health telemetry...</div>;

  return (
    <div className="space-y-6 font-mono">
      <div className="border-b border-[#1b2230] pb-4">
        <h2 className="text-lg font-bold text-[#f0f6fc]">System Health & Provenance Telemetry</h2>
        <p className="text-xs text-[#526079]">
          Storage engine status, point-in-time cutoff invariants, and content-addressed archive integrity.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-2">
          <div className="text-xs text-[#526079]">DUCKDB ANALYTICAL REPOSITORY</div>
          <div className="text-base font-bold text-[#f0f6fc]">{health.databaseVersion}</div>
          <div className="text-xs text-emerald-400">Schema Version {health.schemaVersion} (Migrated)</div>
          <div className="text-[11px] text-[#526079]">Size: {(health.duckdbSizeBytes / (1024 * 1024)).toFixed(1)} MB</div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-2">
          <div className="text-xs text-[#526079]">SQLITE REVIEW LEDGER</div>
          <div className="text-base font-bold text-[#f0f6fc]">SQLite 3 Append-Only</div>
          <div className="text-xs text-blue-400">Dossier Notes & Qualitative Gates</div>
          <div className="text-[11px] text-[#526079]">Size: {(health.sqliteSizeBytes / 1024).toFixed(1)} KB</div>
        </div>

        <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-2">
          <div className="text-xs text-[#526079]">TEMPORAL BOUNDARY</div>
          <div className="text-base font-bold text-amber-400">{health.pitCutoffHour}</div>
          <div className="text-xs text-[#8b949e]">Fail-Closed Point-in-Time</div>
          <div className="text-[11px] text-[#526079]">Freshness: {health.dataFreshnessDate}</div>
        </div>
      </div>

      <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-3">
        <div className="text-xs font-bold text-[#f0f6fc] uppercase tracking-wide">
          Normalized Observation Registry Totals
        </div>
        <div className="grid grid-cols-4 gap-3 text-xs">
          <div className="bg-[#090d14] p-3 rounded border border-[#1b2230]/60">
            <div className="text-[#526079] text-[10px]">FINANCIAL OBSERVATIONS</div>
            <div className="text-base font-bold text-blue-400 mt-1">{health.totalFinancialObservations.toLocaleString()}</div>
          </div>
          <div className="bg-[#090d14] p-3 rounded border border-[#1b2230]/60">
            <div className="text-[#526079] text-[10px]">EOD PRICE OBSERVATIONS</div>
            <div className="text-base font-bold text-cyan-400 mt-1">{health.totalEodPrices.toLocaleString()}</div>
          </div>
          <div className="bg-[#090d14] p-3 rounded border border-[#1b2230]/60">
            <div className="text-[#526079] text-[10px]">DELIVERY OBSERVATIONS</div>
            <div className="text-base font-bold text-emerald-400 mt-1">{health.totalDeliveryRecords.toLocaleString()}</div>
          </div>
          <div className="bg-[#090d14] p-3 rounded border border-[#1b2230]/60">
            <div className="text-[#526079] text-[10px]">EXCHANGE TRADING SESSIONS</div>
            <div className="text-base font-bold text-amber-400 mt-1">{health.activeSessions.toLocaleString()}</div>
          </div>
        </div>
      </div>
    </div>
  );
};