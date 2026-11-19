import getpass
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No user named {username!r}")
        password = getpass.getpass(f"New password for {username}: ")
        if len(password) < 8:
            sys.exit("Password not changed: use at least 8 characters")
        if getpass.getpass("Type it again: ") != password:
            sys.exit("Password not changed: the two entries differ")
        user.password_hash = hash_password(password)
        user.token_version += 1
        db.commit()
    print(f"Password changed for {username} ({user.full_name}). Sign in with the new password.")


if __name__ == "__main__":
    main()
