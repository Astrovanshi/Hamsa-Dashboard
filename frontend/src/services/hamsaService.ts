import {
  CompanyDossier,
  MarketRadarSummary,
  IntelligenceFeedItem,
  SystemHealthMetric,
  EngineType,
  EvaluationState,
} from '@/types';

class HamsaDataService {
  private companies: CompanyDossier[] = [];
  private radar: MarketRadarSummary | null = null;
  private feed: IntelligenceFeedItem[] = [];
  private health: SystemHealthMetric | null = null;

  private isLoaded: boolean = false;
  private loadPromise: Promise<void> | null = null;

  // Real backend endpoint configuration (default to local server on port 8080 if available)
  private apiBaseUrl: string = import.meta.env.VITE_HAMSA_API_BASE || 'http://127.0.0.1:8080';
  private isLiveConnected: boolean = false;
  private checkedLive: boolean = false;

  constructor() {
    this.checkLiveConnection();
  }

  private async checkLiveConnection(): Promise<boolean> {
    if (this.checkedLive) return this.isLiveConnected;
    try {
      const res = await fetch(`${this.apiBaseUrl}/health`, { method: 'GET' });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'healthy') {
          this.isLiveConnected = true;
          this.checkedLive = true;
          return true;
        }
      }
    } catch {
      this.isLiveConnected = false;
    }
    this.checkedLive = true;
    return false;
  }

  private async ensureDataLoaded(): Promise<void> {
    if (this.isLoaded) return;
    if (!this.loadPromise) {
      this.loadPromise = (async () => {
        const live = await this.checkLiveConnection();
        if (live) {
          try {
            const [radarRes, compsRes, feedRes, healthRes] = await Promise.all([
              fetch(`${this.apiBaseUrl}/api/radar`),
              fetch(`${this.apiBaseUrl}/api/companies`),
              fetch(`${this.apiBaseUrl}/api/feed`),
              fetch(`${this.apiBaseUrl}/health`),
            ]);
            if (radarRes.ok && compsRes.ok) {
              this.radar = await radarRes.json();
              this.companies = await compsRes.json();
              this.feed = feedRes.ok ? await feedRes.json() : [];
              this.health = healthRes.ok ? await healthRes.json() : null;
              this.isLoaded = true;
              return;
            }
          } catch (e) {
            console.warn('Live API fetch failed, falling back to local snapshot:', e);
          }
        }

        // Fallback to local snapshot
        const module = await import('@/data/hamsaDatabaseSnapshot.json');
        const data = module.default;
        this.companies = data.companies as any;
        this.radar = data.radar as any;
        this.feed = data.feed as any;
        this.health = data.health as any;
        this.isLoaded = true;
      })();
    }
    return this.loadPromise;
  }

  public getConnectionStatus(): { isLive: boolean; dataSource: string; isRealSnapshot: boolean } {
    return {
      isLive: this.isLiveConnected,
      dataSource: this.isLiveConnected
        ? 'Live Analytical REST Server (DuckDB 2.0.0 & SQLite)'
        : 'Sourced DuckDB Analytical Snapshot (v6 PIT Validated)',
      isRealSnapshot: true,
    };
  }

  public async getMarketRadar(): Promise<MarketRadarSummary> {
    await this.ensureDataLoaded();
    return this.radar!;
  }

  public async getCompanies(): Promise<CompanyDossier[]> {
    await this.ensureDataLoaded();
    return this.companies;
  }

  public async getCompanyBySymbol(symbol: string): Promise<CompanyDossier | undefined> {
    await this.ensureDataLoaded();
    const clean = symbol.toUpperCase().trim();
    return this.companies.find(
      (c) => c.identity.symbol.toUpperCase() === clean || c.identity.entityId === clean
    );
  }

  public async getEngineOpportunities(engine: EngineType): Promise<{
    company: CompanyDossier;
    state: EvaluationState;
    explanation: string;
    inputs: Record<string, any>;
    citations: string[];
  }[]> {
    await this.ensureDataLoaded();
    const results: {
      company: CompanyDossier;
      state: EvaluationState;
      explanation: string;
      inputs: Record<string, any>;
      citations: string[];
    }[] = [];

    for (const comp of this.companies) {
      const finding = comp.engineFindings.find((ef) => ef.engine === engine);
      if (finding) {
        results.push({
          company: comp,
          state: finding.state,
          explanation: finding.explanation,
          inputs: finding.inputs,
          citations: finding.sourceDocumentIds,
        });
      }
    }

    return results;
  }

  public async getIntelligenceFeed(): Promise<IntelligenceFeedItem[]> {
    await this.ensureDataLoaded();
    return this.feed;
  }

  public async getSystemHealth(): Promise<SystemHealthMetric> {
    await this.ensureDataLoaded();
    return this.health!;
  }

  public async updateWatchlist(entityId: string, status: 'research_priority' | 'watch' | 'unassigned' | 'archive'): Promise<void> {
    await this.ensureDataLoaded();
    const comp = this.companies.find((c) => c.identity.entityId === entityId);
    if (comp) {
      comp.watchlistStatus = status;
    }

    if (this.isLiveConnected) {
      try {
        await fetch(`${this.apiBaseUrl}/api/watchlist`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entityId, status, author: 'terminal-ui' }),
        });
      } catch (err) {
        console.warn('Failed to sync watchlist to live backend:', err);
      }
    }
  }

  public async addResearchNote(entityId: string, thesis: string, author: string = 'hamsa-operator'): Promise<void> {
    await this.ensureDataLoaded();
    const comp = this.companies.find((c) => c.identity.entityId === entityId);
    if (comp) {
      comp.researchNotes.unshift({
        id: `note-${Date.now()}`,
        date: new Date().toISOString().slice(0, 10),
        author,
        thesis,
        evidenceLocator: 'Operator manual dossier entry',
      });
    }

    if (this.isLiveConnected) {
      try {
        await fetch(`${this.apiBaseUrl}/api/notes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entityId, thesis, author }),
        });
      } catch (err) {
        console.warn('Failed to sync research note to live backend:', err);
      }
    }
  }
}

export const hamsaService = new HamsaDataService();
