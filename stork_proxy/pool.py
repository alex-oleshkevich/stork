from __future__ import annotations
import asyncio
import logging
import ssl
import httpx
import datetime

import os
import random
import urllib.parse


class BaseProvider:
    async def provide(self):
        return []


class FileProvider(BaseProvider):
    def __init__(self, proxies_file: str) -> None:
        self.proxies_file = proxies_file

    async def provide(self, pool: ProxyPool):
        if os.path.exists(self.proxies_file):
            with open(self.proxies_file, "r") as f:
                for row in f.readlines():
                    row = row.strip()
                    if len(row) and row[0] != "#":
                        pool.add(row)


class Proxy:
    def __init__(self, url) -> None:
        if not url.startswith("http"):
            url = "http://" + url
        self.url = url
        self._components = urllib.parse.urlsplit(url)

        self.usages = 0
        self.last_checked = None
        self.latency: datetime.timedelta = None
        self.healthy = False

    async def health_check(self):
        try:
            http = httpx.AsyncClient(proxies={"all": self.url})
            response = await http.get(
                "https://google.com",
                timeout=10,
            )
            self.latency = response.elapsed
            self.healthy = True
        except (
            httpx.HTTPError,
            ssl.SSLCertVerificationError,
            asyncio.TimeoutError,
            ConnectionRefusedError,
            ConnectionResetError,
        ):
            self.healthy = False
        finally:
            self.last_checked = datetime.datetime.now()
            logging.info(
                'Proxy %s is "%s", latency: %.3fs'
                % (
                    self,
                    "healthy" if self.healthy else "unhealthy",
                    self.latency.microseconds / 1000 ** 2 if self.latency else -1,
                )
            )

    @property
    def hostname(self):
        return self._components.hostname

    @property
    def port(self):
        return self._components.port

    @property
    def username(self):
        return self._components.username

    @property
    def password(self):
        return self._components.password

    def __str__(self) -> str:
        return f"{self.hostname}:{self.port}"


class BaseStrategy:
    def get_proxy(self, pool: ProxyPool) -> Proxy:
        raise NotImplementedError()


class RandomStrategy(BaseStrategy):
    def get_proxy(self, pool: ProxyPool) -> Proxy:
        if not len(pool):
            return None
        random.seed()
        choice = random.randint(0, len(pool) - 1)
        return pool[choice]


class ProxyPool:
    def __init__(self, providers=None, strategy=None) -> None:
        self.strategy = strategy or RandomStrategy()
        self.proxies = []
        self.providers = providers or []

    @property
    def healthy(self):
        return [proxy for proxy in self.proxies if proxy.healthy]

    async def bootstrap(self):
        for provider in self.providers:
            await provider.provide(self)

    def pick(self) -> Proxy:
        return self.strategy.get_proxy(self)

    def add_provider(self, provider: BaseProvider):
        self.providers.append(provider)

    def add(self, url):
        self.proxies.append(Proxy(url))

    async def start_healthcheck(self, interval: int = 600):
        while True:
            try:
                logging.info("Starting health check task.")
                await asyncio.gather(*[proxy.health_check() for proxy in self.proxies])
                logging.info('%s of %s proxies are healthy.' % (
                    len(self.healthy), len(self.proxies)
                ))
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as ex:
                logging.exception(ex)

    def clear(self):
        self.proxies = []

    def __getitem__(self, index):
        return self.healthy[index]

    def __iter__(self):
        return iter(self.healthy)

    def __len__(self):
        return len(self.healthy)
