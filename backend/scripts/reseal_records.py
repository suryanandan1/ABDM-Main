import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app import hiu
from app.config import settings
from app.database import SessionLocal
from app.models import HiuDataRequest, RetrievedRecord, User

SEALED_COLUMNS = [(RetrievedRecord, "content"), (HiuDataRequest, "key_material"),
                  (User, "mfa_secret")]


def reseal(db, dry_run: bool = False) -> dict[str, int]:
    if not settings.record_sealing_key:
        raise SystemExit("Set RECORD_SEALING_KEY in backend/.env first")
    changed: dict[str, int] = {}
    for model, column in SEALED_COLUMNS:
        count = 0
        for row in db.scalars(select(model).where(getattr(model, column).is_not(None))):
            sealed = getattr(row, column)
            if not hiu.needs_reseal(sealed):
                continue
            text = hiu.unseal(sealed)
            resealed = hiu.seal(text)
            assert hiu.unseal(resealed) == text
            if not dry_run:
                setattr(row, column, resealed)
            count += 1
        changed[model.__tablename__] = count
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return changed


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    with SessionLocal() as db:
        try:
            changed = reseal(db, dry_run)
        except hiu.SealingKeyMissing as error:
            raise SystemExit(f"{error}. Add that key to RECORD_SEALING_OLD_KEYS and run again; nothing was changed.")
    verb = "Would re-seal" if dry_run else "Re-sealed"
    for table, count in changed.items():
        print(f"{verb} {count} value(s) in {table}")
    print(f"Active key id: {hiu.active_key_id()}")


if __name__ == "__main__":
    main()
