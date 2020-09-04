import asyncio
import logging
from base64 import b64encode
from urllib.parse import quote

from .pool import ProxyPool


async def pipe(reader, writer, proxy_auth: str = None):
    try:
        iteration = 0
        while not reader.at_eof():
            data = await reader.read(1024)
            if data == b"":
                break

            if iteration == 0 and proxy_auth:
                data = data.replace(b"\r\n", f"\r\n{proxy_auth}\r\n".encode(), 1)
            iteration += 1
            writer.write(data)
    finally:
        writer.close()


def basic_auth(username: str, password: str) -> str:
    if ":" in username:
        raise ValueError

    credentials = "%s:%s" % (quote(username), quote(password))
    return "Basic " + b64encode(credentials.encode()).decode()


class Server:
    def __init__(self, pool: ProxyPool) -> None:
        self.pool = pool

    async def listen(self, host: str = "127.0.0.1", port: int = 9080):
        server = await asyncio.start_server(self._serve, host, port)
        await server.serve_forever()

    async def _serve(
        self, reader: asyncio.streams.StreamReader, writer: asyncio.streams.StreamWriter
    ):
        try:
            proxy = self.pool.pick()
            if not proxy:
                writer.write(b"HTTP/1.1 412 Empty proxy list")
                writer.write(b"\r\n\r\n")
                await writer.drain()
                writer.close()
                return

            logging.info("Selected proxy %s" % proxy)
            remote_reader, remote_writer = await asyncio.open_connection(
                proxy.hostname, proxy.port
            )
            proxy_auth = None
            if proxy.username:
                proxy_auth = "Proxy-Authorization: %s" % basic_auth(
                    proxy.username, proxy.password
                )
            await asyncio.gather(
                *[
                    pipe(reader, remote_writer, proxy_auth),
                    pipe(remote_reader, writer),
                ]
            )
            proxy.usages += 1
        finally:
            writer.close()
