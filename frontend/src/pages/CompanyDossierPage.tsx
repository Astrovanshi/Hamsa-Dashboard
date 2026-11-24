import React, { useEffect, useState } from 'react';
import {
  FileText,
  Bookmark,
  TrendingUp,
  ShieldCheck,
  Calendar,
  Layers,
  CheckCircle2,
  HelpCircle,
  Clock,
  Send,
  ExternalLink,
} from 'lucide-react';
import { hamsaService } from '@/services/hamsaService';
import { CompanyDossier } from '@/types';

interface CompanyDossierProps {
  initialSymbol?: string;
}

export const CompanyDossierPage: React.FC<CompanyDossierProps> = ({ initialSymbol = 'POLYCAB' }) => {
  const [symbol, setSymbol] = useState<string>(initialSymbol);
  const [dossier, setDossier] = useState<CompanyDossier | null>(null);
  const [activeTab, setActiveTab] = useState<'financials' | 'engines' | 'hamsa11' | 'prices' | 'notes'>('financials');
  const [allCompanies, setAllCompanies] = useState<CompanyDossier[]>([]);
  const [newNote, setNewNote] = useState<string>('');

  useEffect(() => {
    hamsaService.getCompanies().then((comps) => {
      setAllCompanies(comps);
      const found = comps.find((c) => c.identity.symbol.toUpperCase() === symbol.toUpperCase());
      setDossier(found || comps[0]);
    });
  }, [symbol]);

  if (!dossier) {
    return <div className="text-xs font-mono text-[#526079]">Loading company dossier...</div>;
  }

  const handleAddNote = async () => {
    if (!newNote.trim()) return;
    await hamsaService.addResearchNote(dossier.identity.entityId, newNote.trim());
    setNewNote('');
    // refresh
    const refreshed = await hamsaService.getCompanyBySymbol(dossier.identity.symbol);
    if (refreshed) setDossier({ ...refreshed });
  };

  const handleUpdateWatchlist = async (status: any) => {
    await hamsaService.updateWatchlist(dossier.identity.entityId, status);
    const refreshed = await hamsaService.getCompanyBySymbol(dossier.identity.symbol);
    if (refreshed) setDossier({ ...refreshed });
  };

  return (
    <div className="space-y-6">
      {/* Dossier Header & Selector */}
      <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <select
            value={dossier.identity.symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="bg-[#131822] border border-[#1b2230] text-[#f0f6fc] font-bold text-sm rounded px-3 py-1.5 font-mono focus:outline-none focus:border-blue-500/50"
          >
            {allCompanies.map((c) => (
              <option key={c.identity.entityId} value={c.identity.symbol}>
                {c.identity.symbol} - {c.identity.companyName}
              </option>
            ))}
          </select>

          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-base font-bold text-[#f0f6fc]">{dossier.identity.companyName}</h2>
              <span className="text-xs font-mono text-[#526079]">({dossier.identity.isin})</span>
            </div>
            <div className="flex items-center space-x-2 text-xs font-mono text-[#8b949e] mt-0.5">
              <span>{dossier.identity.exchange} : {dossier.identity.series}</span>
              <span>•</span>
              <span className="uppercase text-blue-400">{dossier.identity.businessClass}</span>
              <span>•</span>
              <span>STATUS: {dossier.identity.listingStatus}</span>
            </div>
          </div>
        </div>

        {/* Watchlist Action */}
        <div className="flex items-center space-x-2 font-mono text-xs">
          <span className="text-[#526079]">WATCHLIST:</span>
          <select
            value={dossier.watchlistStatus}
            onChange={(e) => handleUpdateWatchlist(e.target.value)}
            className="bg-[#131822] border border-[#1b2230] text-[#f0f6fc] rounded px-2.5 py-1 focus:outline-none text-xs"
          >
            <option value="unassigned">Unassigned</option>
            <option value="research_priority">Research Priority</option>
            <option value="watch">Watch</option>
            <option value="archive">Archive</option>
          </select>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="flex border-b border-[#1b2230] font-mono text-xs space-x-2">
        {[
          { id: 'financials', label: 'Financial Statements (Ind-AS)' },
          { id: 'engines', label: '5-Engine Evaluations' },
          { id: 'hamsa11', label: 'HAMSA 11 Gates' },
          { id: 'prices', label: 'EOD Price History' },
          { id: 'notes', label: `Research Notes (${dossier.researchNotes.length})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2 border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-blue-500 text-blue-400 font-semibold'
                : 'border-transparent text-[#8b949e] hover:text-[#f0f6fc]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Sub-Tab 1: Financials */}
      {activeTab === 'financials' && (
        <div className="space-y-3 font-mono">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#8b949e]">Sourced Ind-AS XBRL Metric Observations</span>
            <span className="text-[#526079]">Total Records: {dossier.financials.length}</span>
          </div>

          <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden max-h-[500px] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] sticky top-0 uppercase">
                <tr>
                  <th className="py-2.5 px-4">Period End</th>
                  <th className="py-2.5 px-4">Period Start</th>
                  <th className="py-2.5 px-4">Metric</th>
                  <th className="py-2.5 px-4 text-right">Value</th>
                  <th className="py-2.5 px-4">Unit</th>
                  <th className="py-2.5 px-4">Scope</th>
                  <th className="py-2.5 px-4">Document Ref</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1b2230]/60">
                {dossier.financials.map((f, i) => (
                  <tr key={i} className="hover:bg-[#131822] transition-colors">
                    <td className="py-2 px-4 text-[#f0f6fc]">{f.periodEnd}</td>
                    <td className="py-2 px-4 text-[#526079]">{f.periodStart}</td>
                    <td className="py-2 px-4 font-bold text-blue-400 uppercase">{f.metric}</td>
                    <td className="py-2 px-4 text-right font-bold text-[#f0f6fc]">
                      {f.value !== null ? f.value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : 'NULL'}
                    </td>
                    <td className="py-2 px-4 text-[#8b949e]">{f.unit}</td>
                    <td className="py-2 px-4 text-amber-400/90 text-[11px]">{f.reportingScope}</td>
                    <td className="py-2 px-4 text-[#526079] text-[10px] truncate max-w-xs">{f.sourceDocumentId}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sub-Tab 2: Engines */}
      {activeTab === 'engines' && (
        <div className="grid grid-cols-1 gap-4 font-mono">
          {dossier.engineFindings.map((ef) => (
            <div key={ef.engine} className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-[#f0f6fc] uppercase tracking-wide">
                  {ef.engine.replace(/_/g, ' ')}
                </span>
                <span
                  className={`px-2 py-0.5 rounded text-xs uppercase font-bold ${
                    ef.state === 'triggered'
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                      : ef.state === 'blocked'
                      ? 'bg-rose-950 text-rose-400 border border-rose-800'
                      : 'bg-[#161b22] text-[#8b949e] border border-[#21262d]'
                  }`}
                >
                  {ef.state}
                </span>
              </div>
              <p className="text-xs text-[#8b949e]">{ef.explanation}</p>
              <div className="grid grid-cols-4 gap-2 text-[11px]">
                {Object.entries(ef.inputs)
                  .filter(([k]) => k !== 'input_quality_states' && k !== 'source_observation_ids')
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <div key={k} className="bg-[#090d14] p-2 rounded border border-[#1b2230]/40">
                      <div className="text-[10px] text-[#526079] uppercase">{k.replace(/_/g, ' ')}</div>
                      <div className="text-[#f0f6fc] font-semibold mt-0.5 truncate">{String(v)}</div>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Sub-Tab 3: HAMSA 11 */}
      {activeTab === 'hamsa11' && (
        <div className="space-y-3 font-mono">
          {dossier.hamsa11.map((gate) => (
            <div key={gate.key} className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded flex items-start justify-between">
              <div>
                <div className="flex items-center space-x-2">
                  <span className="font-bold text-xs text-[#f0f6fc]">{gate.label}</span>
                  <span className="text-[10px] uppercase px-1.5 py-0.2 rounded bg-[#161b22] text-[#526079] border border-[#1b2230]">
                    {gate.category}
                  </span>
                </div>
                <p className="text-xs text-[#8b949e] mt-1">{gate.findings}</p>
                <div className="text-[10px] text-[#526079] mt-1.5">
                  Citations: {gate.evidenceCitations.join(', ')}
                </div>
              </div>
              <span
                className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                  gate.status === 'passed'
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : 'bg-[#161b22] text-[#8b949e] border border-[#21262d]'
                }`}
              >
                {gate.status}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Sub-Tab 4: EOD Price History */}
      {activeTab === 'prices' && (
        <div className="space-y-3 font-mono">
          <div className="border border-[#1b2230] rounded bg-[#0d1117] overflow-hidden max-h-[500px] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#131822] text-[#8b949e] border-b border-[#1b2230] text-[11px] sticky top-0 uppercase">
                <tr>
                  <th className="py-2.5 px-4">Date</th>
                  <th className="py-2.5 px-4 text-right">Open (₹)</th>
                  <th className="py-2.5 px-4 text-right">High (₹)</th>
                  <th className="py-2.5 px-4 text-right">Low (₹)</th>
                  <th className="py-2.5 px-4 text-right">Close (₹)</th>
                  <th className="py-2.5 px-4 text-right">Volume</th>
                  <th className="py-2.5 px-4 text-right">Turnover (Cr)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1b2230]/60">
                {dossier.priceData.map((p) => (
                  <tr key={p.tradeDate} className="hover:bg-[#131822] transition-colors">
                    <td className="py-2 px-4 text-[#f0f6fc]">{p.tradeDate}</td>
                    <td className="py-2 px-4 text-right">₹{p.open.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-emerald-400">₹{p.high.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-rose-400">₹{p.low.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right font-bold text-[#f0f6fc]">₹{p.close.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-cyan-300">{p.volume.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-amber-400">₹{p.turnoverCr} Cr</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sub-Tab 5: Research Notes */}
      {activeTab === 'notes' && (
        <div className="space-y-4 font-mono">
          <div className="bg-[#0d1117] border border-[#1b2230] p-4 rounded space-y-3">
            <h3 className="text-xs font-bold text-[#f0f6fc] uppercase tracking-wide">
              Append Analyst Research Note (SQLite Review Ledger)
            </h3>
            <textarea
              value={newNote}
              onChange={(e) => setNewNote(e.target.value)}
              placeholder="Record business thesis, thesis-killer conditions, or qualitative evidence findings..."
              className="w-full bg-[#131822] border border-[#1b2230] rounded p-3 text-xs text-[#f0f6fc] focus:outline-none focus:border-blue-500/50 h-24"
            />
            <button
              onClick={handleAddNote}
              className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-[#f0f6fc] text-xs font-semibold flex items-center space-x-1.5 transition-colors"
            >
              <Send className="w-3.5 h-3.5" />
              <span>Append Note to Dossier</span>
            </button>
          </div>

          <div className="space-y-3">
            {dossier.researchNotes.map((n) => (
              <div key={n.id} className="bg-[#0d1117] border border-[#1b2230] p-3.5 rounded space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-blue-400">{n.author}</span>
                  <span className="text-[#526079] text-[10px]">{n.date}</span>
                </div>
                <p className="text-xs text-[#c9d1d9]">{n.thesis}</p>
                <div className="text-[10px] text-[#526079]">Citation / Locator: {n.evidenceLocator}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};