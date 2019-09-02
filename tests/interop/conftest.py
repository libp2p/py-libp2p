import asyncio
import sys

import pexpect
import pytest

from .daemon import make_p2pd


@pytest.fixture
def proc_factory():
    procs = []

    def call_proc(cmd, args, logfile=None, encoding=None):
        if logfile is None:
            logfile = sys.stdout
        if encoding is None:
            encoding = "utf-8"
        proc = pexpect.spawn(cmd, args, logfile=logfile, encoding=encoding)
        procs.append(proc)
        return proc

    try:
        yield call_proc
    finally:
        for proc in procs:
            proc.close()


@pytest.fixture
def num_p2pds():
    return 1


@pytest.fixture
async def p2pds(num_p2pds, is_host_secure, unused_tcp_port_factory):
    p2pds = await asyncio.gather(
        *[make_p2pd(unused_tcp_port_factory, is_host_secure) for _ in range(num_p2pds)]
    )
    try:
        yield p2pds
    finally:
        await asyncio.gather(*[p2pd.close() for p2pd in p2pds])
