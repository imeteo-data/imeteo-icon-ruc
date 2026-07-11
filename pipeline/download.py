"""Async cache-aware downloader for DWD GRIB files."""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path

import aiohttp
import certifi

from . import config, discover


def expected_path(variable: str, run_id: str, ensemble: str, step: str) -> Path:
    return config.RAW_DIR / discover.local_filename(variable, run_id, ensemble, step)


async def _fetch_one(
    session: aiohttp.ClientSession, sem: asyncio.Semaphore, url: str, dest: Path
) -> Path | None:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    async with sem:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"  HTTP {resp.status}: {url}")
                    return None
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        f.write(chunk)
                tmp.rename(dest)
                return dest
        except Exception as e:
            print(f"  error {url}: {e}")
            if dest.with_suffix(dest.suffix + ".part").exists():
                dest.with_suffix(dest.suffix + ".part").unlink()
            return None


async def fetch_variable(
    variable: str, run_id: str, ensembles: list[str], steps: list[str]
) -> list[Path]:
    """Download all (ensemble × step) files for one variable. Skips cached files."""
    config.ensure_dirs()
    targets: list[tuple[str, Path]] = []
    for ens in ensembles:
        for step in steps:
            dest = expected_path(variable, run_id, ens, step)
            url = discover.build_url(variable, run_id, ens, step)
            targets.append((url, dest))

    missing = [(u, d) for u, d in targets if not (d.exists() and d.stat().st_size > 0)]
    print(f"  {variable} {run_id}: {len(targets)} total, {len(missing)} to fetch")

    if not missing:
        return [d for _, d in targets]

    sem = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(
        limit=config.MAX_CONCURRENT_DOWNLOADS + 10,
        limit_per_host=config.MAX_CONCURRENT_DOWNLOADS,
        ssl=ssl_ctx,
    )
    timeout = aiohttp.ClientTimeout(total=config.DOWNLOAD_TIMEOUT_SECONDS)
    headers = {"User-Agent": config.HTTP_USER_AGENT}
    async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as s:
        await asyncio.gather(*(_fetch_one(s, sem, u, d) for u, d in missing))

    return [d for _, d in targets if d.exists() and d.stat().st_size > 0]
