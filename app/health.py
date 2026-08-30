import os
from aiohttp import web
from sqlalchemy import text
from app.config import get_settings
from app.database.session import create_engine

async def health(_):
    settings=get_settings(); engine=create_engine(settings)
    try:
        async with engine.connect() as c: await c.execute(text("SELECT 1"))
        return web.json_response({"status":"ok","service":os.getenv("SERVICE_ROLE","health")})
    except Exception as exc: return web.json_response({"status":"error","detail":type(exc).__name__},status=503)
    finally: await engine.dispose()

app=web.Application(); app.router.add_get("/health",health)
if __name__=="__main__": web.run_app(app,port=int(os.getenv("PORT",str(get_settings().web_port))))
