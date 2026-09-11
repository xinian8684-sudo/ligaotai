"""python -m ligaotai：在 127.0.0.1:8765 启动理稿台后端。"""

import uvicorn

from .api import create_app

HOST, PORT = "127.0.0.1", 8765


def main() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
