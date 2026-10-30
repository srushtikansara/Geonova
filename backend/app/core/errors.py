"""Domain errors and their HTTP mapping."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def _json(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def register_handlers(app: FastAPI) -> None:
    from app.db.session import DatabaseUnavailable

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound):
        return _json(404, str(e))

    @app.exception_handler(Conflict)
    async def _cf(_: Request, e: Conflict):
        return _json(409, str(e))

    @app.exception_handler(Invalid)
    async def _iv(_: Request, e: Invalid):
        return _json(422, str(e))

    @app.exception_handler(DatabaseUnavailable)
    async def _du(_: Request, e: DatabaseUnavailable):
        return _json(503, "Database is not configured or not reachable.")

    @app.exception_handler(OperationalError)
    async def _oe(_: Request, e: OperationalError):
        # Do not echo driver text: it may contain host names or user names.
        return _json(503, "Database is not reachable.")

    @app.exception_handler(IntegrityError)
    async def _ie(_: Request, e: IntegrityError):
        code = getattr(getattr(e, "orig", None), "sqlstate", None)
        if code == "23505":
            return _json(409, "A record with the same unique value already exists.")
        if code == "23503":
            return _json(422, "A referenced record does not exist (or is still referenced).")
        if code == "23514":
            return _json(422, "A value violates a database constraint.")
        return _json(422, "The data violates a database integrity rule.")

    @app.exception_handler(DBAPIError)
    async def _db(_: Request, e: DBAPIError):
        return _json(500, "Database error.")
