"""Shared dependencies: settings, the connection, and who is asking.

The authentication here is a **seam, not a implementation**. Roles matching the
firm -- article clerk, senior accountant, partner -- exist now, ``require_role``
guards the routes that will need it, and every privileged action already writes
an audit line. What is missing is only the part that establishes *which* human
is on the other end, which arrives with sessions in step 7.

Building it this way round means step 7 replaces one function. Building it the
other way round means reshaping every route and back-filling an audit trail that
has no record of anything done before it existed.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Callable, Iterator

from fastapi import Depends, Header, HTTPException, Request, status

from ..config import Settings
from ..store import db
from ..store.models import Principal, Role

#: Until sessions exist, every caller is this. It is deliberately a partner so
#: nothing is blocked during development, and deliberately named so that an
#: audit line written before real login is obvious for what it is.
DEV_PRINCIPAL = Principal(name="dev", role=Role.PARTNER)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_connection(request: Request) -> Iterator[sqlite3.Connection]:
    yield request.app.state.connection


def open_database(settings: Settings) -> sqlite3.Connection:
    return db.connect(settings.db_path)


def current_principal(request: Request) -> Principal:
    """Who is asking.

    Step 7 resolves this from a session cookie. Until then the app-wide default
    stands in, and tests override this dependency to act as a specific role.
    """
    return getattr(request.app.state, "principal", DEV_PRINCIPAL)


def require_role(required: Role) -> Callable[[Principal], Principal]:
    """Guard a route on the firm's hierarchy.

    A partner outranks a senior accountant outranks an article clerk, so this
    compares rank rather than testing for one exact role -- otherwise every
    partner-only route would also have to list the roles above it, and one
    forgotten entry becomes a permission bug.
    """

    def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not principal.role.can_act_as(required):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"this action requires {required.value}",
            )
        return principal

    return dependency


def require_worker_token(
    request: Request,
    x_worker_token: Annotated[str | None, Header()] = None,
) -> None:
    """Gate the worker protocol on a shared secret.

    This is not user authentication and does not pretend to be. It stops
    anything else on the LAN draining the queue, which is the whole job.
    """
    expected = request.app.state.settings.worker_token
    if not x_worker_token or x_worker_token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing worker token")


ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]
