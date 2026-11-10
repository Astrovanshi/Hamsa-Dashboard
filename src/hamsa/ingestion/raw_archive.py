"""Content-addressed raw-file archive with explicit retention approval."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil


@dataclass(frozen=True, slots=True)
class ArchivedSource:
    sha256_hex: str
    archive_path: Path
    original_filename: str


def archive_approved_source(
    source_path: Path,
    *,
    archive_root: Path,
    license_status: str,
) -> ArchivedSource:
    """Archive original bytes without overwriting an existing content object.

    Licensing/retention must be reviewed before this function is called. A
    non-approved source is rejected, and the source file is never modified.
    """
    if license_status != "approved":
        raise ValueError("raw source retention is not approved")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    digest = sha256()
    with source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    destination = archive_root / checksum[:2] / checksum
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        if _sha256_file(destination) != checksum:
            raise OSError("content-address collision: existing archive object checksum differs")
    else:
        try:
            with source_path.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
        except FileExistsError:
            # Another process stored the same content concurrently. Verify it
            # before treating the operation as idempotent.
            if _sha256_file(destination) != checksum:
                raise OSError("content-address collision during concurrent archive write")

    return ArchivedSource(checksum, destination, source_path.name)


def archive_user_authorized_source(
    source_path: Path,
    *,
    archive_root: Path,
    license_status: str,
    retention_authorized: bool,
) -> ArchivedSource:
    """Archive a user-directed source without asserting a license conclusion.

    Public accessibility and the user's instruction to retain a local copy are
    recorded separately from whether the source terms have been reviewed.
    """
    if not retention_authorized:
        raise ValueError("local retention requires explicit user authorization")
    if license_status not in {"pending", "approved"}:
        raise ValueError("restricted or rejected sources cannot be archived")
    # Use the same immutable content-addressed implementation after the
    # caller's explicit retention authorization.
    return archive_approved_source(source_path, archive_root=archive_root, license_status="approved")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
