import asyncio
from prometheus_client import Counter


class BandwidthMetrics:
    """
    Prometheus bandwidth metrics for libp2p transport streams.
    """

    def __init__(self):

        self.bandwidth = Counter(
            "libp2p_bandwidth_bytes_total",
            "Bandwidth usage by direction and protocol stack",
            ["direction", "protocols"],
        )

    def outbound(self, protocols, n):
        self.bandwidth.labels(
            direction="outbound",
            protocols=protocols,
        ).inc(n)

    def inbound(self, protocols, n):
        self.bandwidth.labels(
            direction="inbound",
            protocols=protocols,
        ).inc(n)


class InstrumentedStream:
    """
    Wraps a stream to measure bandwidth.
    """

    def __init__(self, stream, metrics: BandwidthMetrics, protocols: str):
        self.stream = stream
        self.metrics = metrics
        self.protocols = protocols

    async def read(self, n=-1):
        data = await self.stream.read(n)

        if data:
            self.metrics.inbound(self.protocols, len(data))

        return data

    async def write(self, data: bytes):
        n = await self.stream.write(data)

        if n is None:
            n = len(data)

        self.metrics.outbound(self.protocols, n)

        return n

    async def close(self):
        await self.stream.close()


class TransportWrapper:
    """
    Wraps a transport and instruments bandwidth.
    """

    def __init__(self, transport, metrics: BandwidthMetrics):
        self.transport = transport
        self.metrics = metrics

    async def dial(self, addr, protocols):

        stream = await self.transport.dial(addr)

        return InstrumentedStream(
            stream,
            self.metrics,
            protocols,
        )

    async def accept(self, protocols):

        stream = await self.transport.accept()

        return InstrumentedStream(
            stream,
            self.metrics,
            protocols,
        )