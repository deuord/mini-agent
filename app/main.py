# 应用入口：
# 作用：启动 FastAPI 应用，挂载所有路由

from contextlib import asynccontextmanager
from fastapi import FastAPI

from api.router_chat import chat_router


# 生命周期：yield 之前是启动时执行，之后是关闭时执行
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)

# 挂载路由：以后新增 router 文件，在这里加一行 include_router
app.include_router(chat_router)
