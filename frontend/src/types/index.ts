export type EngineType =
  | 'compounders'
  | 'earnings_inflection'
  | 'capex_conversion'
  | 'cash_quality'
  | 'extreme_sell_side_liquidity';

export type EvaluationState = 'triggered' | 'not_triggered' | 'unproven' | 'blocked';

export type ExchangeVenue = 'NSE' | 'BSE';

export type AvailabilityMode = 'public_as_of' | 'hamsa_known_as_of';

export interface SecurityIdentity {
  entityId: string;
  isin: string;
  symbol: string;
  companyName: string;
  industry: string;
  sector: string;
  businessClass: 'industrial' | 'financial' | 'unclassified';
  exchange: ExchangeVenue;
  series: string;
  listingStatus: 'active' | 'suspended' | 'delisted';
  effectiveListingDate: string;
}

export interface EodPricePoint {
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnoverCr: number;
  deliveryQty?: number;
  deliveryPct?: number;
}

export interface FinancialMetricRecord {
  periodEnd: string;
  periodStart: string;
  metric: string;
  value: number;
  unit: string;
  reportingScope: 'consolidated' | 'standalone';
  sourceDocumentId: string;
}

export interface EngineResultModel {
  engine: EngineType;
  state: EvaluationState;
  calculationExpression: string;
  inputs: Record<string, any>;
  explanation: string;
  sourceObservationIds: string[];
  sourceDocumentIds: string[];
}

export interface MarketDislocation {
  symbol: string;
  companyName: string;
  close: number;
  returnPct: number;
  volumeMultiple: number;
  deliveryPct: number;
  deliveryChgPp: number;
  dislocationType: 'volume_surge' | 'delivery_spike' | 'drawdown_absorption' | 'cross_venue_spread';
  rationale: string;
}

export interface MarketRadarSummary {
  exchange: ExchangeVenue;
  sessionDate: string;
  eligibleCount: number;
  totalListings: number;
  advancers: number;
  decliners: number;
  unchanged: number;
  totalTurnoverCr: number;
  regime: string;
  breadthRatio: number;
  dislocations: MarketDislocation[];
  volumeAnomaliesCount: number;
  deliveryAnomaliesCount: number;
}

export interface Hamsa11Gate {
  key: string;
  label: string;
  status: 'passed' | 'neutral' | 'failed' | 'unproven';
  category: 'quantitative' | 'qualitative_verified' | 'hypothesis' | 'unknown';
  evidenceCitations: string[];
  findings: string;
}

export interface CompanyDossier {
  identity: SecurityIdentity;
  priceData: EodPricePoint[];
  financials: FinancialMetricRecord[];
  engineFindings: EngineResultModel[];
  hamsa11: Hamsa11Gate[];
  researchNotes: {
    id: string;
    date: string;
    author: string;
    thesis: string;
    evidenceLocator: string;
  }[];
  watchlistStatus: 'research_priority' | 'watch' | 'unassigned' | 'archive';
}

export interface IntelligenceFeedItem {
  id: string;
  eventDate: string;
  category: string;
  severity: 'positive' | 'neutral' | 'warning' | 'alert';
  symbol: string;
  companyName: string;
  whatHappened: string;
  whyItMatters: string;
  source: string;
}

export interface SystemHealthMetric {
  databaseVersion: string;
  schemaVersion: number;
  duckdbSizeBytes: number;
  sqliteSizeBytes: number;
  totalFinancialObservations: number;
  totalEodPrices: number;
  totalDeliveryRecords: number;
  activeSessions: number;
  admittedIssuers: number;
  pitCutoffHour: string;
  lastIngestionTimestamp: string;
  dataFreshnessDate: string;
}
