"""Administrative commands.

python -m app.cli create-key "Acme survey team"
"""

from __future__ import annotations

import argparse

from app.config import get_settings
from app.database import create_db_engine, create_session_factory, init_db
from app.services.auth import create_client


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_key = commands.add_parser("create-key", help="Create an API client and print its key.")
    create_key.add_argument("name", help="Who the key is for.")
    args = parser.parse_args(argv)

    engine = create_db_engine(get_settings().database_url)
    init_db(engine)
    with create_session_factory(engine)() as session:
        client, key = create_client(session, args.name)
    print(f"Created API client {client.id} ({client.name}).")
    print(f"API key (shown once, store it safely): {key}")


if __name__ == "__main__":
    main()
