"""Operator-only CLI. No public registration or password-bearing command-line arguments."""

import argparse
import getpass
from uuid import UUID

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.models.identity import AuthSession, Membership, Organization, User, now
from app.security.passwords import hash_password
from app.services.audit import audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision PEClaw identities using local DB access"
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name")
    parser.add_argument("--organization")
    parser.add_argument("--organization-id", type=UUID)
    parser.add_argument("--role", choices=["owner", "admin", "member", "viewer"], default="member")
    states = parser.add_mutually_exclusive_group()
    states.add_argument("--disable", action="store_true")
    states.add_argument("--enable", action="store_true")
    parser.add_argument("--data-curator", choices=["grant", "revoke"])
    args = parser.parse_args()
    if args.data_curator and (
        args.organization or args.organization_id or args.disable or args.enable
    ):
        parser.error("Change curator permission separately after provisioning an active account")
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        if args.disable or args.enable:
            if not user:
                parser.error("User does not exist")
            user.is_active = not args.disable
            db.execute(
                update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=now())
            )
            audit(
                db,
                None,
                None,
                "operator.user.disable" if args.disable else "operator.user.enable",
                user.id,
            )
            db.commit()
            print("User status updated; prior sessions remain revoked")
            return
        if args.data_curator and not args.organization and not args.organization_id:
            if not user or not user.is_active:
                parser.error("Active account required")
            user.is_data_curator = args.data_curator == "grant"
            audit(
                db,
                None,
                None,
                "operator.catalog.curator",
                user.id,
                details={"granted": user.is_data_curator},
            )
            db.commit()
            print("Public catalog curator permission updated")
            return
        if bool(args.organization) == bool(args.organization_id):
            parser.error("Supply exactly one of --organization or --organization-id")
        if not user:
            if not args.name or len(args.name.strip()) > 100:
                parser.error("A new user needs --name (1-100 characters)")
            password = getpass.getpass("New password (12-256 characters): ")
            if not 12 <= len(password) <= 256 or password != getpass.getpass("Confirm password: "):
                parser.error("Password length or confirmation is invalid")
            user = User(
                email=email, full_name=args.name.strip(), password_hash=hash_password(password)
            )
            db.add(user)
            db.flush()
        if not user.is_active:
            parser.error("User is disabled")
        if args.organization:
            if not 1 <= len(args.organization.strip()) <= 150:
                parser.error("Organization name must be 1-150 characters")
            org = Organization(name=args.organization.strip())
            db.add(org)
            db.flush()
            role = "owner"
        else:
            org = db.get(Organization, args.organization_id)
            if not org:
                parser.error("Organization does not exist")
            role = args.role
        if db.get(Membership, (org.id, user.id)):
            parser.error("Membership already exists; use the audited management API to update it")
        db.add(Membership(organization_id=org.id, user_id=user.id, role=role))
        audit(db, None, org.id, "operator.membership.provision", user.id, details={"role": role})
        db.commit()
        print(f"Provisioned user {user.id} in organization {org.id}")


if __name__ == "__main__":
    main()
