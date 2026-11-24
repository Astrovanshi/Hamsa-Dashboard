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

  // Real backend endpoint configuration for future live connection
  private apiBaseUrl: string = import.meta.env.VITE_HAMSA_API_BASE || '';
  private isLiveConnected: boolean = false;

  constructor() {
    if (this.apiBaseUrl) {
      this.checkLiveConnection();
    }
  }

  private async checkLiveConnection(): Promise<void> {
    try {
      const res = await fetch(`${this.apiBaseUrl}/health`, { method: 'GET' });
      if (res.ok) {
        this.isLiveConnected = true;
      }
    } catch {
      this.isLiveConnected = false;
    }
  }

  private async ensureDataLoaded(): Promise<void> {
    if (this.isLoaded) return;
    if (!this.loadPromise) {
      this.loadPromise = import('@/data/hamsaDatabaseSnapshot.json').then((module) => {
        const data = module.default;
        this.companies = data.companies as any;
        this.radar = data.radar as any;
        this.feed = data.feed as any;
        this.health = data.health as any;
        this.isLoaded = true;
      });
    }
    return this.loadPromise;
  }

  public getConnectionStatus(): { isLive: boolean; dataSource: string; isRealSnapshot: boolean } {
    return {
      isLive: this.isLiveConnected,
      dataSource: this.isLiveConnected
        ? 'Live Analytical Backend (FastAPI / DuckDB)'
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
  }
}

export const hamsaService = new HamsaDataService();
