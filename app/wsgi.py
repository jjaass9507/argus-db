"""Waitress (WSGI) 進入點。

FastAPI 是 ASGI，Waitress 是 WSGI，故以 a2wsgi 橋接，讓 skill 的
`waitress-serve ... wsgi:application` web.config 範本可直接沿用。
注意：WSGI 橋接不支援 WebSocket / streaming；本平台 API 為 REST，無此需求。
若未來需要原生 ASGI，可改用 uvicorn/hypercorn 並調整 web.config 的 arguments。
"""
from a2wsgi import ASGIMiddleware

from argus_api.main import app

application = ASGIMiddleware(app)
