from fastapi import Request, HTTPException


def get_db(request: Request):
    from mindmargin.analytics.memory import _get_db
    return _get_db()
