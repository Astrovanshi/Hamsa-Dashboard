# Full-universe identity design

**Status:** proposed use of the existing model; no schema changes in this milestone.

## Locked eligibility rule

The investable universe contains only ordinary equity shares officially classified and confirmed as listed on the NSE or BSE mainboard. An ISIN identifies one security across venues; each exchange instrument remains a separate listing. NSE Emerge, BSE SME, all other SME listings, ETFs, mutual funds, REITs, InvITs, preference shares, warrants, rights instruments, debt, and other non-ordinary-equity instruments are excluded. Record excluded rows only in a reconciliation-only outcome; never expose them as eligible securities to HAMSA's investment universe or discovery engines. Use official exchange classification and status, not size or market capitalisation. Missing or conflicting classification is quarantined.

For an SME-to-mainboard migration, retain the earlier SME listing and its source/history separately. A mainboard listing is eligible only starting on the source-verified effective migration/listing date. Preserve both the source snapshot date and effective date; never use a later snapshot date to infer an earlier effective date or backdate mainboard eligibility.

## Identity layers already represented

HAMSA distinguishes:

- **Issuer entity (`issuer_entity`)**: legal issuer identity. This is the stable research/company identity.
- **Equity security (`equity_security`)**: share security/share class issued by an issuer. Histories attach to this security and are not blended across reorganizations.
- **Identifier revision (`security_identifier_revision`)**: sourced, reviewed, effective-dated ISIN or other security identifier mapping.
- **Exchange listing (`exchange_listing`)**: venue-specific instrument identity, including exchange and exchange instrument identifier.
- **Listing revision (`exchange_listing_revision`)**: sourced effective-dated symbol, series and status (`active`, `suspended`, `delisted`, `relisted`).
- **Entity/security relationship revision**: explicit reviewed lineage for issuer reorganizations and security succession. These relationships describe links; they do not collapse identities or histories.

These entities and their provenance fields are in `sql/duckdb_schema.sql`; lifecycle intent is documented in [data-model.md](data-model.md). No automatic entity merge is proposed.

## Resolution policy

1. Treat a valid, sourced ISIN as the primary cross-venue security key for its effective period, subject to review and source conflicts. One approved security can have separate NSE and BSE listing records for the same effective period.
2. Resolve a price row to its **venue listing first** using the source instrument ID/security code plus venue and session date. Where the source lacks an identifier (as in the inspected BSE per-scrip CSV), require an explicit reviewed input mapping with source evidence and effective dates. No name/symbol fuzzy resolution.
3. Resolve the listing to the security through the identifier/listing revisions applicable on that date. Resolve the security to its issuer separately. Preserve the original source symbol, series, venue code, ISIN and raw row in provenance.
4. For routine symbol, exchange-code or same-legal-issuer ISIN changes, retain issuer identity; retain the security if legal/instrument continuity is supported and use new effective-dated identifier/listing revisions. If it is unclear whether the security itself continues, quarantine pending review.
5. For merger, demerger, spin-off, new successor share, scheme allotment or other reorganization, keep predecessor and successor entities/securities distinct. Add explicit reviewed `predecessor_of`, `successor_of`, `merged_into`, `demerged_into` or `spun_out_to` relationships. Never transfer historical prices or financial observations to the successor by inference.
6. Suspension, delisting and relisting update listing status intervals; they do not delete the listing. Relisting requires evidence and a reviewed interval. A new exchange code/ISIN after relisting may require a new listing/security decision.
7. Identifier ambiguity, conflicting overlapping effective intervals, reused codes/symbols, missing ISIN, unsupported series, or incompatible issuer/security claims result in quarantine. The reviewer may append an approved or rejected mapping revision; prior revisions remain preserved.
8. Determine mainboard/SME platform, ordinary-share instrument class, and active status from official exchange classification fields or a sourced official listing notice. Do not infer eligibility from symbol, name, market capitalization, company size, or ISIN alone. Classify explicit excluded rows as `excluded_from_hamsa_universe` for reconciliation; quarantine if classification is ambiguous.
9. Treat migration as two listing periods/identities: the SME period remains excluded; a separately evidenced mainboard listing can become eligible only from its effective date. A shared issuer, security, symbol, or ISIN does not retroactively make the SME period eligible.

## Effective-date and point-in-time treatment

Identity effectiveness and information availability are different dimensions. `effective_from`/`effective_to` tell which mapping applied in market history. Source-document publication and actual ingestion timestamps tell when the mapping could be known. A mapping discovered later can correct the interpretation of a historical security in `public_as_of` if its source was public then, but `hamsa_known_as_of` cannot use the mapping before the actual ingestion time. An uncertain date stays unknown; do not impute a date from the filename alone.

For a source row on trade date *d*, the resolution decision must record the selected listing and listing/identifier revision IDs. Resolution requires exactly one approved applicable mapping. Zero candidates, more than one candidate, or a candidate sourced only after the as-of cutoff is quarantined for that snapshot. A later correction adds a mapping revision and relinks only through a reproducible new extraction; it does not rewrite the source row or silently mutate prior lineage.

## Collision and lifecycle cases

| Case | Required treatment |
|---|---|
| Same ISIN on NSE and BSE | One approved security, two exchange listings, separate venue-specific EOD observations. Never average price or merge delivery fields. |
| Same symbol, different ISINs | Distinct security candidates; only source ISIN/code plus effective date may resolve. |
| Symbol reused after delisting | Separate effective intervals; if same venue code/listing continuity is not proven, create a new listing identity or quarantine for review. |
| ISIN change, same legal issuer | Keep issuer entity. Append sourced identifier revisions; preserve security continuity only after explicit review. Never change past row ISIN in raw/provenance. |
| Merger or demerger | Separate predecessor/successor entities and securities; append reviewed relationship and event records. Histories remain separate. |
| Suspended and resumed | Keep same listing only when source evidence supports continuity; append status interval revisions. No synthetic price rows during suspension. |
| Delisting and relisting | Preserve the historical listing and its status. Treat a materially new instrument/code/ISIN as a separate listing/security pending review. |
| Missing BSE file identifier | Require a reviewed BSE code/symbol/ISIN listing map valid for the EOD date and tied to the source evidence. Otherwise quarantine. |
| SME-to-mainboard migration | Preserve excluded SME listing history; create/approve the mainboard listing from the confirmed effective date. No earlier SME observation enters the investment universe. |
| Mainboard/ordinary-equity classification missing or conflicting | Quarantine; do not infer from size, symbol, company name, or instrument activity. |
| Conflicting exchange masters | Keep each original venue record. If ISIN/security assignments conflict or intervals overlap incompatibly, quarantine both candidates rather than picking one venue. |

## Review record requirements

Every identity decision should retain source document/checksum, extraction locator, parser version, mapping effective interval, mapping review state, reviewer and review timestamp, and any superseded mapping relationship. A review action can approve or reject a candidate; it cannot erase the evidence or alter raw market records. When a source does not supply effective dates, mark the bounds as unverified and require review instead of fabricating precision.

## Unresolved assumptions

- It is not yet verified that either exchange provides a historical master archive complete for inactive securities. A current master is only a current snapshot.
- The current schema stores listing `series` and status, but has no explicit normalized mainboard/SME platform classification or ordinary-share instrument-class field on a listing revision. If official classification cannot be losslessly preserved and queried through existing fields/source metadata, a schema addition or repository-maintained sourced eligibility classification may be required. Do not implement either without approval.
- `exchange_listing_revision.effective_from` is required. For a current master row with no verified effective date, the repository must not claim the file's snapshot date is the true listing start. A safe current-only treatment must retain snapshot provenance and limit applicability to the known snapshot/current period; historical validity remains unresolved.
- BSE's observed Stock Prices file does not identify the instrument in its columns; this design assumes a separately sourced listing map will be available for broad ingestion. If not, BSE full-universe ingestion is blocked beyond manually reviewed per-scrip mappings.
- ISIN is useful but does not by itself encode issuer continuity, share-class continuity, listing venue or all corporate-reorganization semantics.
- Whether a new ISIN represents the same security or a new security requires reviewed legal/source evidence; the software must not decide by issuer name alone.
