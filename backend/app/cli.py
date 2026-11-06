import argparse
import getpass
import os
import re
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.security import get_password_hash
from app.db.database import SessionLocal, engine, Base
from app.db.models import User, UserRole


def create_admin_interactive(email: str = None, name: str = None, password: str = None):
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("\n=== NeuroForge AI: Secure Administrator Setup ===")
        if not name:
            name = input("Administrator Full Name: ").strip()
            if not name:
                print("Error: Name cannot be blank.", file=sys.stderr)
                sys.exit(1)

        if not email:
            email = input("Administrator Email: ").strip().lower()

        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, email):
            print("Error: Invalid email format.", file=sys.stderr)
            sys.exit(1)

        if not password:
            pw1 = getpass.getpass("Password (min 8 chars, letters & numbers): ")
            pw2 = getpass.getpass("Confirm Password: ")
            if pw1 != pw2:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)
            password = pw1

        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            print("Error: Password must be at least 8 characters and include both letters and numbers.", file=sys.stderr)
            sys.exit(1)

        # Check existing user
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            existing_user.role = UserRole.ADMIN.value
            existing_user.hashed_password = get_password_hash(password)
            existing_user.full_name = name
            existing_user.is_active = True
            db.commit()
            print(f"Success: Existing account '{email}' updated to Administrator.")
        else:
            admin_user = User(
                email=email,
                full_name=name,
                hashed_password=get_password_hash(password),
                role=UserRole.ADMIN.value,
                is_active=True,
            )
            db.add(admin_user)
            db.commit()
            print(f"Success: Administrator account '{email}' successfully provisioned.")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="NeuroForge AI Management CLI")
    subparsers = parser.add_subparsers(dest="command")

    admin_parser = subparsers.add_parser("create-admin", help="Create or promote an administrator account")
    admin_parser.add_argument("--email", required=False, help="Administrator email")
    admin_parser.add_argument("--name", required=False, help="Administrator full name")
    admin_parser.add_argument("--password", required=False, help="Administrator password")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin_interactive(email=args.email, name=args.name, password=args.password)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
