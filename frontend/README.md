# HAMSA Dashboard — Institutional Equity Intelligence Terminal

A dark-first institutional research and opportunity discovery terminal for Indian listed equities, built with React 18, TypeScript, Vite, and Tailwind CSS.

## Architecture

- **Sourced Analytical Snapshot**: Points to verified Point-in-Time (PIT) data as of **9 November 2026** (15:30 IST market cutoff).
- **Five Discovery Engines**:
  1. Compounders (CAGR, ROCE, Capital Allocation)
  2. Earnings Inflection (YoY Growth Acceleration & Operating Leverage)
  3. Capex Conversion (Fixed Asset Deployment & Qualitative Gates)
  4. Cash Quality & Conversion (CFO / PAT Audit)
  5. Extreme Sell-Side Liquidity (Institutional Forced-Selling Absorption)
- **Deep Company Dossiers**: Multi-year Ind-AS statements, 30-session EOD history, HAMSA 11 mental model gates, and analyst review notes.
- **Decoupled API Boundary**: Configured with `hamsaService.ts` for instant backend API attachment via `VITE_HAMSA_API_BASE`.

## Running Locally

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Production build
npm run build

# Preview build
npm run preview
```