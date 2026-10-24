"""
create_admin.py  --  creates the first (or another) ADMIN account.

There is deliberately no web form for this: an admin approves doctors, so
nobody must be able to sign themselves up as one. Run it on the server:

    cd backend/module4
    python create_admin.py

The password is typed at a hidden prompt, so it never appears in your command
history or on screen.
"""

import getpass
import sys

import auth_core
from accounts_schema import init_accounts_schema


def main() -> int:
    init_accounts_schema()  # no-op if the tables already exist

    email = input("Admin email: ").strip()
    full_name = input("Full name: ").strip()
    password = getpass.getpass(f"Password (at least {auth_core.PASSWORD_MIN_LENGTH} characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("The two passwords do not match. Nothing was created.")
        return 1

    conn = auth_core.open_db()
    try:
        user = auth_core.create_admin_user(conn, email, password, full_name)
    except auth_core.EmailTaken:
        print("An account with this email already exists. Nothing was created.")
        return 1
    except ValueError as e:
        print(f"{e} Nothing was created.")
        return 1
    finally:
        conn.close()

    print(f"Admin created. Display ID: {user['display_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
