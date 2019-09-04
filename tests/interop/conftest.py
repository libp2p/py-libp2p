import asyncio
import sys
from typing import Union

import pexpect
import pytest

from tests.factories import FloodsubFactory, GossipsubFactory, PubsubFactory
from tests.pubsub.configs import GOSSIPSUB_PARAMS

from .daemon import Daemon, make_p2pd


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
def is_gossipsub():
    return True


@pytest.fixture
async def p2pds(num_p2pds, is_host_secure, is_gossipsub, unused_tcp_port_factory):
    p2pds: Union[Daemon, Exception] = await asyncio.gather(
        *[
            make_p2pd(
                unused_tcp_port_factory(),
                unused_tcp_port_factory(),
                is_host_secure,
                is_gossipsub=is_gossipsub,
            )
            for _ in range(num_p2pds)
        ],
        return_exceptions=True,
    )
    p2pds_succeeded = tuple(p2pd for p2pd in p2pds if isinstance(p2pd, Daemon))
    if len(p2pds_succeeded) != len(p2pds):
        # Not all succeeded. Close the succeeded ones and print the failed ones(exceptions).
        await asyncio.gather(*[p2pd.close() for p2pd in p2pds_succeeded])
        exceptions = tuple(p2pd for p2pd in p2pds if isinstance(p2pd, Exception))
        raise Exception(f"not all p2pds succeed: first exception={exceptions[0]}")
    try:
        yield p2pds
    finally:
        await asyncio.gather(*[p2pd.close() for p2pd in p2pds])


@pytest.fixture
def pubsubs(num_hosts, hosts, is_gossipsub):
    if is_gossipsub:
        routers = GossipsubFactory.create_batch(num_hosts, **GOSSIPSUB_PARAMS._asdict())
    else:
        routers = FloodsubFactory.create_batch(num_hosts)
    _pubsubs = tuple(
        PubsubFactory(host=host, router=router) for host, router in zip(hosts, routers)
    )
    yield _pubsubs
    # TODO: Clean up
