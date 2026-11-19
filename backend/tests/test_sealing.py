import pytest
from sqlalchemy import select

from app import hiu
from app.config import settings
from app.database import SessionLocal
from app.models import User
from scripts.reseal_records import reseal

KEY_A = "sealing-key-A-long-enough-for-tests-0123456789"
KEY_B = "sealing-key-B-long-enough-for-tests-9876543210"


@pytest.fixture()
def sealing(monkeypatch):
    def configure(active=None, old=""):
        monkeypatch.setattr(settings, "record_sealing_key", active)
        monkeypatch.setattr(settings, "record_sealing_old_keys", old)
    configure()
    return configure


def test_legacy_mode_unchanged(sealing):
    sealed = hiu.seal("bundle")
    assert not sealed.startswith("v2.")
    assert hiu.unseal(sealed) == "bundle"
    assert not hiu.needs_reseal(sealed)


def test_sealing_key_is_independent_of_jwt_secret(sealing, monkeypatch):
    legacy = hiu.seal("old record")
    sealing(KEY_A)
    sealed = hiu.seal("new record")
    assert sealed.startswith(f"v2.{hiu.active_key_id()}.")
    assert hiu.unseal(legacy) == "old record"
    assert hiu.needs_reseal(legacy) and not hiu.needs_reseal(sealed)
    monkeypatch.setattr(settings, "jwt_secret", "a-rotated-jwt-secret-that-is-long-enough-xyz")
    assert hiu.unseal(sealed) == "new record"


def test_rotation_needs_the_old_key(sealing):
    sealing(KEY_A)
    sealed = hiu.seal("record")
    sealing(KEY_B)
    with pytest.raises(hiu.SealingKeyMissing):
        hiu.unseal(sealed)
    sealing(KEY_B, old=KEY_A)
    assert hiu.unseal(sealed) == "record"
    assert hiu.needs_reseal(sealed)


def test_reseal_moves_rows_to_active_key(client, sealing):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "dr.mehta"))
        user.mfa_secret = hiu.seal("JBSWY3DPEHPK3PXP")
        db.commit()
        sealing(KEY_A)
        assert reseal(db, dry_run=True)["users"] == 1
        assert not db.get(User, user.id).mfa_secret.startswith("v2.")
        assert reseal(db)["users"] == 1
        sealing(KEY_B, old=KEY_A)
        assert reseal(db)["users"] == 1
        assert reseal(db)["users"] == 0
        sealing(KEY_B)
        secret = db.get(User, user.id).mfa_secret
        assert secret.startswith(f"v2.{hiu.active_key_id()}.")
        assert hiu.unseal(secret) == "JBSWY3DPEHPK3PXP"


def test_short_sealing_key_refused():
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(jwt_secret="x" * 40, record_sealing_key="too-short")
