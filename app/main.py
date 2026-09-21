from fastapi import FastAPI
from app.api.routes_health import router as health_router
from app.api.routes_chat import router as chat_router
from app.api.routes_sessions import router as sessions_router


app = FastAPI(title="mini-agent")
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(sessions_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
