import React, { useState } from 'react';
import { Layout } from '@/components/layout/Layout';
import { MarketRadarPage } from '@/pages/MarketRadarPage';
import { OpportunityRadarPage } from '@/pages/OpportunityRadarPage';
import { EngineWorkbenchPage } from '@/pages/EngineWorkbenchPage';
import { CompanyDossierPage } from '@/pages/CompanyDossierPage';
import { Hamsa11Page, WatchlistsPage, DiscoveryFeedPage, DataCoveragePage, SystemHealthPage } from '@/pages/OtherPages';
import { UniverseLifecyclePage } from '@/pages/UniverseLifecyclePage';
import { DailyBriefPage } from '@/pages/DailyBriefPage';
import { EngineType } from '@/types';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<string>('market-radar');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('POLYCAB');

  const handleSelectTab = (tab: string, param?: string) => {
    setCurrentTab(tab);
    if (param) {
      setSelectedSymbol(param.toUpperCase());
    }
  };

  const handleSelectCompany = (symbol: string) => {
    setSelectedSymbol(symbol.toUpperCase());
    setCurrentTab('company-dossier');
  };

  const renderContent = () => {
    switch (currentTab) {
      case 'market-radar':
        return <MarketRadarPage onSelectCompany={handleSelectCompany} />;
      case 'opportunity-radar':
        return <OpportunityRadarPage onSelectCompany={handleSelectCompany} />;
      case 'compounders':
        return <EngineWorkbenchPage engineType="compounders" onSelectCompany={handleSelectCompany} />;
      case 'earnings-inflection':
        return <EngineWorkbenchPage engineType="earnings_inflection" onSelectCompany={handleSelectCompany} />;
      case 'capex-conversion':
        return <EngineWorkbenchPage engineType="capex_conversion" onSelectCompany={handleSelectCompany} />;
      case 'cash-quality':
        return <EngineWorkbenchPage engineType="cash_quality" onSelectCompany={handleSelectCompany} />;
      case 'extreme-liquidity':
        return <EngineWorkbenchPage engineType="extreme_sell_side_liquidity" onSelectCompany={handleSelectCompany} />;
      case 'company-dossier':
        return <CompanyDossierPage initialSymbol={selectedSymbol} />;
      case 'hamsa-11':
        return <Hamsa11Page />;
      case 'watchlists':
        return <WatchlistsPage onSelectCompany={handleSelectCompany} />;
      case 'discovery-feed':
        return <DiscoveryFeedPage onSelectCompany={handleSelectCompany} />;
      case 'data-coverage':
        return <DataCoveragePage />;
      case 'system-health':
        return <SystemHealthPage />;
      default:
        return <MarketRadarPage onSelectCompany={handleSelectCompany} />;
    }
  };

  return (
    <Layout currentTab={currentTab} onSelectTab={handleSelectTab}>
      {renderContent()}
    </Layout>
  );
};