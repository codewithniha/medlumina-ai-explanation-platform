"""
approve_doctor.py  --  approve or reject doctors from the command line.

    cd backend/module4
    python approve_doctor.py

You sign in as an admin (password typed at a hidden prompt), see the doctors
waiting for approval, and for each one:
  1. open https://pmdc.pk and search the registration number shown here,
  2. check that the name (and father's name) match and note "valid up to",
  3. choose A (approve, then type that date) or R (reject) or S (skip).
"""

import getpass
import sys
from datetime import date

import admin_ops
import auth_core
from accounts_schema import init_accounts_schema


def main() -> int:
    init_accounts_schema()
    conn = auth_core.open_db()
    try:
        email = input("Admin email: ").strip()
        admin = auth_core.authenticate(conn, email, getpass.getpass("Admin password: "))
        if admin is None or admin["role"] != "admin":
            print("Sign-in failed. Nothing was changed.")
            return 1

        pending = admin_ops.list_doctors(conn, "pending")
        if not pending:
            print("No doctors are waiting for approval.")
            return 0

        for d in pending:
            print("\n" + "-" * 60)
            print(f"{d['display_id']}   submitted {d['submitted_at']}")
            print(f"  Name on register : {d['register_full_name']}")
            print(f"  Father's name    : {d['register_father_name'] or '(not given)'}")
            print(f"  PMDC number      : {d['pmdc_number']}")
            if d["verification_status"] == "expired":
                print("  NOTE: previously verified, licence date has passed. Re-check the register.")
            choice = input("  [A]pprove / [R]eject / [S]kip ? ").strip().lower()
            if choice == "a":
                raw = input("  Licence 'valid up to' from the register (YYYY-MM-DD): ").strip()
                try:
                    admin_ops.approve_doctor(conn, admin, d["user_id"], date.fromisoformat(raw))
                    print("  Approved.")
                except (ValueError, admin_ops.BadLicenceDate) as e:
                    print(f"  Not approved: {e}")
            elif choice == "r":
                admin_ops.reject_doctor(conn, admin, d["user_id"], input("  Reason (optional): ").strip())
                print("  Rejected.")
            else:
                print("  Skipped.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
