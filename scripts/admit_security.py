"""Operator-facing security admission and prerequisite audit tool.

Supports idempotent staging, evidence-backed reviews (Approved/Rejected/Pending),
and point-in-time prerequisite auditing without modifying production rules.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


def format_audit_table(audit: dict[str, object]) -> str:
    lines = [
        f"Issuer Entity: {audit.get('issuer_entity_id')}",
        f"Security ID:   {audit.get('security_id')}",
        f"Listing ID:    {audit.get('listing_id')}",
        f"Exchange:      {audit.get('exchange')}",
        f"Instrument ID: {audit.get('exchange_instrument_id')}",
        f"Disposition:   {audit.get('disposition')}",
        "",
        f"{'Prerequisite':<32} | {'Status':<10} | {'Detail / Notes':<35} | {'Source Documents':<30} | {'Locators'}",
        "-" * 130,
    ]
    for check in audit.get("checks", []):
        prereq = str(check.get("prerequisite", ""))
        status = str(check.get("status", ""))
        detail = str(check.get("detail", ""))[:35]
        sources = ", ".join(str(s) for s in check.get("source_documents", []))[:30]
        locators = ", ".join(str(l) for l in check.get("locators", []))[:30]
        lines.append(f"{prereq:<32} | {status:<10} | {detail:<35} | {sources:<30} | {locators}")
    return "\n".join(lines)


def audit_command(args: argparse.Namespace) -> int:
    cutoff = datetime.combine(args.observation_date, time(15, 30), tzinfo=MARKET_TIMEZONE)
    with DuckDBRepository(args.database) as repo:
        listing_id = args.listing_id
        if not listing_id:
            if not args.exchange or not args.symbol:
                sys.stderr.write("Error: Provide either --listing-id or both --exchange and --symbol.\n")
                return 1
            row = repo._connection.execute(
                """SELECT l.listing_id FROM exchange_listing l
                   JOIN exchange_listing_revision r USING(listing_id)
                   WHERE l.exchange=? AND r.symbol=?
                   ORDER BY r.effective_from DESC LIMIT 1""",
                [args.exchange, args.symbol],
            ).fetchone()
            if not row:
                sys.stderr.write(f"Error: No listing found for {args.exchange} {args.symbol}.\n")
                return 1
            listing_id = row[0]

        audit = repo.security_admission_checklist(
            listing_id=listing_id,
            observation_date=args.observation_date,
            cutoff=cutoff,
            availability_mode=args.availability_mode,
            calendar_version=args.calendar_version,
        )
        print(format_audit_table(audit))
    return 0


def register_source_command(args: argparse.Namespace) -> int:
    published_at = datetime.fromisoformat(args.published_at) if args.published_at else None
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would register source: {args.source_path} ({args.source_identifier})")
            return 0
        registered = repo.register_local_source_document(
            args.source_path,
            archive_root=args.archive_root,
            exchange=args.exchange,
            dataset=args.dataset,
            source_identifier=args.source_identifier,
            source_document_date=args.source_document_date,
            publication_date=args.publication_date,
            published_at=published_at,
            parser_version=args.parser_version,
            retention_authorized=args.authorize_local_retention,
        )
        print(json.dumps({
            "source_document_id": registered.source_document_id,
            "source_file_id": registered.source_file_id,
            "checksum_sha256": registered.checksum_sha256,
            "duplicate": registered.duplicate,
        }, indent=2))
    return 0


def stage_candidate_command(args: argparse.Namespace) -> int:
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would stage candidate for {args.legal_name} ({args.isin}, {args.symbol}) on {args.exchange}")
            return 0
        # 1. Identity candidate
        res = repo.append_security_identity_candidate(
            issuer_entity_id=args.issuer_entity_id,
            security_id=args.security_id,
            listing_id=args.listing_id,
            exchange=args.exchange,
            exchange_instrument_id=args.exchange_instrument_id,
            isin=args.isin,
            legal_name=args.legal_name,
            identity_observed_from=args.identity_observed_from,
            source_document_id=args.source_document_id,
            source_locator=args.source_locator,
            share_class="ordinary",
        )
        # 2. Listing revision
        listing_rev_id = args.listing_revision_id or f"listrev-{args.exchange.lower()}-{args.symbol.lower()}-v1"
        rev_id = repo.append_exchange_listing_revision({
            "listing_revision_id": listing_rev_id,
            "listing_id": args.listing_id,
            "symbol": args.symbol,
            "series": args.series or "EQ",
            "status": args.listing_status or "active",
            "effective_from": args.listing_effective_from or args.identity_observed_from,
            "effective_to": args.listing_effective_to,
            "source_document_id": args.source_document_id,
            "extraction_locator": args.source_locator,
            "parser_version": "admission-workflow-v1",
        })
        print(json.dumps({
            "issuer_entity_id": args.issuer_entity_id,
            "security_id": args.security_id,
            "listing_id": args.listing_id,
            "identifier_revision_id": res["identifier_revision_id"],
            "listing_revision_id": rev_id,
        }, indent=2))
    return 0


def stage_snapshot_command(args: argparse.Namespace) -> int:
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would stage snapshot {args.snapshot_id} for listing {args.listing_id}")
            return 0
        snap_id = args.snapshot_id or f"snap-{args.exchange.lower()}-{args.symbol.lower()}-v1"
        existing_snap = repo._connection.execute(
            "SELECT listing_classification_snapshot_id FROM listing_classification_snapshot WHERE listing_classification_snapshot_id=?",
            [snap_id],
        ).fetchone()
        if existing_snap:
            print(json.dumps({"listing_classification_snapshot_id": existing_snap[0], "status": "exists"}, indent=2))
            return 0
        snap_id = repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": snap_id,
            "listing_id": args.listing_id,
            "exchange": args.exchange,
            "source_document_id": args.source_document_id,
            "source_snapshot_date": args.source_snapshot_date,
            "raw_exchange_instrument_id": args.exchange_instrument_id,
            "raw_isin": args.isin,
            "raw_symbol": args.symbol,
            "raw_series": args.series or "EQ",
            "raw_listing_status": args.listing_status or "active",
            "source_fields_json": {"symbol": args.symbol, "series": args.series, "isin": args.isin},
            "parser_version": "admission-workflow-v1",
            "extraction_locator": args.source_locator,
        })
        print(json.dumps({"listing_classification_snapshot_id": snap_id, "status": "created"}, indent=2))
    return 0


def review_identity_command(args: argparse.Namespace) -> int:
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would record identity mapping review {args.status} for {args.identifier_revision_id}")
            return 0
        new_rev_id = repo.append_security_identifier_review(
            identifier_revision_id=args.identifier_revision_id,
            review_status=args.status,
            reviewer=args.reviewer,
            reviewer_actor_type=args.actor_type,
            evidence_source_document_id=args.evidence_source_id,
            evidence_locator=args.evidence_locator,
            rationale=args.rationale or "",
            supersedes_review_id=getattr(args, "supersedes_review_id", None),
        )
        print(json.dumps({
            "review_id": new_rev_id,
            "identifier_revision_id": args.identifier_revision_id,
            "status": args.status,
            "reviewer": args.reviewer,
        }, indent=2))
    return 0


def review_listing_command(args: argparse.Namespace) -> int:
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would record listing review {args.status} for revision {args.listing_revision_id}")
            return 0
        review_id = args.review_id or f"revchk-{args.listing_revision_id}-{args.status}"
        rev_id = repo.append_exchange_listing_revision_review({
            "listing_revision_review_id": review_id,
            "listing_revision_id": args.listing_revision_id,
            "review_status": args.status,
            "reviewed_by": args.reviewer,
            "evidence_source_document_id": args.evidence_source_id,
            "evidence_locator": args.evidence_locator,
            "rationale": args.rationale,
            "supersedes_review_id": getattr(args, "supersedes_review_id", None),
        })
        print(json.dumps({
            "listing_revision_review_id": rev_id,
            "listing_revision_id": args.listing_revision_id,
            "status": args.status,
            "reviewer": args.reviewer,
        }, indent=2))
    return 0


def review_classification_command(args: argparse.Namespace) -> int:
    with DuckDBRepository(args.database) as repo:
        if args.dry_run:
            print(f"[DRY-RUN] Would record classification review for snapshot {args.snapshot_id}")
            return 0
        review_id = args.review_id or f"classrev-{args.snapshot_id}-{args.instrument_status}-{args.platform_status}"
        rev_dict = {
            "classification_review_revision_id": review_id,
            "listing_classification_snapshot_id": args.snapshot_id,
            "listing_id": args.listing_id,
            "rationale": args.rationale,
            "instrument_review_status": args.instrument_status,
            "platform_review_status": args.platform_status,
            "supersedes_review_revision_id": getattr(args, "supersedes_review_id", None),
        }
        if args.instrument_status == "approved":
            rev_dict.update({
                "instrument_class": args.instrument_class,
                "instrument_valid_from": args.instrument_valid_from,
                "instrument_valid_to": args.instrument_valid_to,
                "instrument_evidence_source_document_id": args.instrument_evidence_source_id,
                "instrument_evidence_locator": args.instrument_evidence_locator,
                "instrument_reviewed_by": args.instrument_reviewer,
            })
        elif args.instrument_status == "rejected":
            rev_dict.update({"instrument_reviewed_by": args.instrument_reviewer})

        if args.platform_status == "approved":
            rev_dict.update({
                "platform_class": args.platform_class,
                "platform_valid_from": args.platform_valid_from,
                "platform_valid_to": args.platform_valid_to,
                "platform_evidence_source_document_id": args.platform_evidence_source_id,
                "platform_evidence_locator": args.platform_evidence_locator,
                "platform_reviewed_by": args.platform_reviewer,
            })
        elif args.platform_status == "rejected":
            rev_dict.update({"platform_reviewed_by": args.platform_reviewer})

        review_rev_id = repo.append_listing_classification_review_revision(rev_dict)
        print(json.dumps({
            "classification_review_revision_id": review_rev_id,
            "snapshot_id": args.snapshot_id,
            "instrument_status": args.instrument_status,
            "platform_status": args.platform_status,
        }, indent=2))
    return 0


def review_business_class_command(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(f"[DRY-RUN] Would record business class {args.business_class} for {args.issuer_entity_id}")
        return 0
    schema_path = ROOT / "sql" / "sqlite_schema.sql"
    with DuckDBRepository(args.database) as a_repo:
        d_repo = DossierReviewRepository(args.sqlite_database, schema_path=schema_path, analytics_repository=a_repo)
        try:
            rev_id = d_repo.append_business_classification_review(
                entity_id=args.issuer_entity_id,
                business_class=args.business_class,
                valid_from=args.valid_from.isoformat() if args.valid_from else "1995-01-01",
                valid_to=args.valid_to.isoformat() if args.valid_to else None,
                reviewer=args.reviewer,
                rationale=args.rationale,
                source_document_id=args.evidence_source_id,
                locator=args.evidence_locator,
                review_status=args.status,
            )
            print(json.dumps({
                "business_classification_review_revision_id": rev_id,
                "issuer_entity_id": args.issuer_entity_id,
                "business_class": args.business_class,
                "status": args.status,
                "reviewer": args.reviewer,
            }, indent=2))
        finally:
            d_repo.close()
    return 0


def review_engine_evidence_command(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(f"[DRY-RUN] Would record engine evidence {args.evidence_key}={args.status} for {args.issuer_entity_id}")
        return 0
    schema_path = ROOT / "sql" / "sqlite_schema.sql"
    with DuckDBRepository(args.database) as a_repo:
        d_repo = DossierReviewRepository(args.sqlite_database, schema_path=schema_path, analytics_repository=a_repo)
        try:
            rev_id = d_repo.append_engine_evidence_review(
                entity_id=args.issuer_entity_id,
                evidence_key=args.evidence_key,
                review_status=args.status,
                valid_from=args.valid_from.isoformat(),
                valid_to=args.valid_to.isoformat() if args.valid_to else None,
                reviewer=args.reviewer,
                rationale=args.rationale,
                source_document_id=args.evidence_source_id,
                locator=args.evidence_locator,
            )
            print(json.dumps({
                "engine_evidence_review_revision_id": rev_id,
                "issuer_entity_id": args.issuer_entity_id,
                "evidence_key": args.evidence_key,
                "status": args.status,
                "reviewer": args.reviewer,
            }, indent=2))
        finally:
            d_repo.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. audit
    p_audit = subparsers.add_parser("audit", help="Audit security admission prerequisites and disposition")
    p_audit.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_audit.add_argument("--listing-id", help="Explicit listing ID")
    p_audit.add_argument("--exchange", choices=("NSE", "BSE"))
    p_audit.add_argument("--symbol")
    p_audit.add_argument("--observation-date", type=date.fromisoformat, required=True)
    p_audit.add_argument("--availability-mode", choices=("public_as_of", "hamsa_known_as_of"), default="public_as_of")
    p_audit.add_argument("--calendar-version", default="nse-cm-2026-pilot-v1")

    # 2. register-source
    p_reg = subparsers.add_parser("register-source", help="Register an official evidence source document")
    p_reg.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_reg.add_argument("--archive-root", type=Path, default=Path("data/raw/archive/official-evidence"))
    p_reg.add_argument("--source-path", type=Path, required=True)
    p_reg.add_argument("--exchange", choices=("NSE", "BSE"), required=True)
    p_reg.add_argument("--dataset", required=True)
    p_reg.add_argument("--source-identifier", required=True)
    p_reg.add_argument("--source-document-date", type=date.fromisoformat, required=True)
    p_reg.add_argument("--publication-date", type=date.fromisoformat, required=True)
    p_reg.add_argument("--published-at")
    p_reg.add_argument("--parser-version", default="source-v1")
    p_reg.add_argument("--authorize-local-retention", action="store_true", required=True)
    p_reg.add_argument("--dry-run", action="store_true")

    # 3. stage-candidate
    p_stage = subparsers.add_parser("stage-candidate", help="Stage candidate entity, listing, and initial snapshot")
    p_stage.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_stage.add_argument("--issuer-entity-id", required=True)
    p_stage.add_argument("--security-id", required=True)
    p_stage.add_argument("--listing-id", required=True)
    p_stage.add_argument("--exchange", choices=("NSE", "BSE"), required=True)
    p_stage.add_argument("--exchange-instrument-id", required=True)
    p_stage.add_argument("--isin", required=True)
    p_stage.add_argument("--legal-name", required=True)
    p_stage.add_argument("--identity-observed-from", type=date.fromisoformat, required=True)
    p_stage.add_argument("--source-document-id", required=True)
    p_stage.add_argument("--source-locator", required=True)
    p_stage.add_argument("--symbol", required=True)
    p_stage.add_argument("--series", default="EQ")
    p_stage.add_argument("--listing-status", choices=("active", "suspended", "delisted", "relisted"), default="active")
    p_stage.add_argument("--listing-effective-from", type=date.fromisoformat)
    p_stage.add_argument("--listing-effective-to", type=date.fromisoformat)
    p_stage.add_argument("--listing-revision-id")
    p_stage.add_argument("--snapshot-id")
    p_stage.add_argument("--dry-run", action="store_true")

    # 4. stage-snapshot
    p_stagesnap = subparsers.add_parser("stage-snapshot", help="Stage listing classification snapshot (requires approved ISIN mapping)")
    p_stagesnap.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_stagesnap.add_argument("--listing-id", required=True)
    p_stagesnap.add_argument("--exchange", choices=("NSE", "BSE"), required=True)
    p_stagesnap.add_argument("--source-document-id", required=True)
    p_stagesnap.add_argument("--source-snapshot-date", type=date.fromisoformat, required=True)
    p_stagesnap.add_argument("--isin", required=True)
    p_stagesnap.add_argument("--symbol", required=True)
    p_stagesnap.add_argument("--series", default="EQ")
    p_stagesnap.add_argument("--exchange-instrument-id", required=True)
    p_stagesnap.add_argument("--listing-status", default="active")
    p_stagesnap.add_argument("--source-locator", required=True)
    p_stagesnap.add_argument("--snapshot-id")
    p_stagesnap.add_argument("--dry-run", action="store_true")

    # 5. review-identity
    p_revid = subparsers.add_parser("review-identity", help="Record reviewed ISIN mapping decision")
    p_revid.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_revid.add_argument("--identifier-revision-id", required=True)
    p_revid.add_argument("--status", choices=("pending", "approved", "rejected"), required=True)
    p_revid.add_argument("--reviewer")
    p_revid.add_argument("--actor-type", choices=("human", "system", "provider"))
    p_revid.add_argument("--evidence-source-id", required=True)
    p_revid.add_argument("--evidence-locator", required=True)
    p_revid.add_argument("--rationale", default="")
    p_revid.add_argument("--supersedes-review-id", help="review_id of the existing active review being superseded")
    p_revid.add_argument("--dry-run", action="store_true")

    # 5. review-listing
    p_revlist = subparsers.add_parser("review-listing", help="Record reviewed listing revision decision")
    p_revlist.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_revlist.add_argument("--listing-revision-id", required=True)
    p_revlist.add_argument("--status", choices=("pending", "approved", "rejected"), required=True)
    p_revlist.add_argument("--reviewer")
    p_revlist.add_argument("--evidence-source-id")
    p_revlist.add_argument("--evidence-locator")
    p_revlist.add_argument("--rationale", required=True)
    p_revlist.add_argument("--review-id")
    p_revlist.add_argument("--supersedes-review-id", help="listing_revision_review_id being superseded")
    p_revlist.add_argument("--dry-run", action="store_true")

    # 6. review-classification
    p_revclass = subparsers.add_parser("review-classification", help="Record independent instrument and platform reviews")
    p_revclass.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_revclass.add_argument("--snapshot-id", required=True)
    p_revclass.add_argument("--listing-id", required=True)
    p_revclass.add_argument("--instrument-status", choices=("pending", "approved", "rejected"), required=True)
    p_revclass.add_argument("--instrument-class", choices=("ordinary_equity", "etf", "mutual_fund", "reit", "invit", "preference", "warrant", "rights", "debt", "other", "unknown"))
    p_revclass.add_argument("--instrument-valid-from", type=date.fromisoformat)
    p_revclass.add_argument("--instrument-valid-to", type=date.fromisoformat)
    p_revclass.add_argument("--instrument-evidence-source-id")
    p_revclass.add_argument("--instrument-evidence-locator")
    p_revclass.add_argument("--instrument-reviewer")
    p_revclass.add_argument("--platform-status", choices=("pending", "approved", "rejected"), required=True)
    p_revclass.add_argument("--platform-class", choices=("mainboard", "sme", "other_platform", "unknown"))
    p_revclass.add_argument("--platform-valid-from", type=date.fromisoformat)
    p_revclass.add_argument("--platform-valid-to", type=date.fromisoformat)
    p_revclass.add_argument("--platform-evidence-source-id")
    p_revclass.add_argument("--platform-evidence-locator")
    p_revclass.add_argument("--platform-reviewer")
    p_revclass.add_argument("--rationale", required=True)
    p_revclass.add_argument("--review-id")
    p_revclass.add_argument("--supersedes-review-id", help="classification_review_revision_id being superseded")
    p_revclass.add_argument("--dry-run", action="store_true")

    # 7. review-business-class
    p_biz = subparsers.add_parser("review-business-class", help="Record SQLite business class review (financial/industrial)")
    p_biz.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_biz.add_argument("--sqlite-database", type=Path, default=Path("data/processed/hamsa_reviews.sqlite3"))
    p_biz.add_argument("--issuer-entity-id", required=True)
    p_biz.add_argument("--business-class", choices=("financial", "industrial"), required=True)
    p_biz.add_argument("--status", choices=("approved", "rejected"), default="approved")
    p_biz.add_argument("--valid-from", type=date.fromisoformat)
    p_biz.add_argument("--valid-to", type=date.fromisoformat)
    p_biz.add_argument("--reviewer", required=True)
    p_biz.add_argument("--evidence-source-id", required=True)
    p_biz.add_argument("--evidence-locator", required=True)
    p_biz.add_argument("--rationale", required=True)
    p_biz.add_argument("--dry-run", action="store_true")

    # 8. review-engine-evidence
    p_engev = subparsers.add_parser("review-engine-evidence", help="Record human-reviewed qualitative engine evidence gate")
    p_engev.add_argument("--database", type=Path, default=Path("data/processed/hamsa.duckdb"))
    p_engev.add_argument("--sqlite-database", type=Path, default=Path("data/processed/hamsa_reviews.sqlite3"))
    p_engev.add_argument("--issuer-entity-id", required=True)
    p_engev.add_argument("--evidence-key", choices=DossierReviewRepository.ENGINE_EVIDENCE_KEYS, required=True)
    p_engev.add_argument("--status", choices=("approved", "rejected", "unproven"), required=True)
    p_engev.add_argument("--valid-from", type=date.fromisoformat, required=True)
    p_engev.add_argument("--valid-to", type=date.fromisoformat)
    p_engev.add_argument("--reviewer", required=True)
    p_engev.add_argument("--evidence-source-id")
    p_engev.add_argument("--evidence-locator")
    p_engev.add_argument("--rationale", required=True)
    p_engev.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    commands = {
        "audit": audit_command,
        "register-source": register_source_command,
        "stage-candidate": stage_candidate_command,
        "stage-snapshot": stage_snapshot_command,
        "review-identity": review_identity_command,
        "review-listing": review_listing_command,
        "review-classification": review_classification_command,
        "review-business-class": review_business_class_command,
        "review-engine-evidence": review_engine_evidence_command,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
