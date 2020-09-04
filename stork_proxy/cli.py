import argparse
import asyncio
import inspect
import logging
from logging import log
import signal

import os

from .pool import FileProvider, ProxyPool, RandomStrategy
from .server import Server

STRATEGIES = {
    "random": RandomStrategy,
}


async def serve(host, port, strategy, data_dir, **kwargs):
    pool = ProxyPool(
        providers=[
            FileProvider(f"{data_dir}/proxies.txt"),
        ],
        strategy=strategy(),
    )

    async def init_pool():
        pool.clear()
        logging.info("Bootstrapping proxy pool providers...")
        await pool.bootstrap()

        logging.info("Starting initial healthcheck...")
        asyncio.create_task(pool.start_healthcheck())

    await init_pool()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, lambda: asyncio.create_task(init_pool()))

    logging.info(f"Starting server at {host}:{port}. PID: {os.getpid()}")
    logging.info(f"Send HUP signal to reload configs: kill -HUP {os.getpid()}")
    logging.info("Press Ctrl+C to exit.\n")
    server = Server(pool)
    await server.listen(host, port)


LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _abs_path(path):
    return os.path.abspath(os.path.expanduser(path))


def main(argv):
    parser = argparse.ArgumentParser("stork")
    parser.add_argument("--log-level", default="warning", choices=LOG_LEVELS.keys())

    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", default=9080, type=int)
    serve_parser.add_argument("--data-dir", default="./.config/stock", type=_abs_path)
    serve_parser.add_argument(
        "--strategy",
        default="random",
        type=lambda x: STRATEGIES[x],
        choices=STRATEGIES.keys(),
    )
    serve_parser.set_defaults(func=serve)

    arguments = parser.parse_args(argv)
    variables = vars(arguments).copy()
    del variables["func"]
    del variables["command"]

    logging.basicConfig(level=LOG_LEVELS[arguments.log_level])

    try:
        if inspect.iscoroutinefunction(arguments.func):
            asyncio.run(arguments.func(**variables))
        else:
            arguments.func(**variables)
    except KeyboardInterrupt:
        pass
