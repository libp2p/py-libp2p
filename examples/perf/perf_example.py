"""
Perf protocol example - Measure transfer performance between two libp2p nodes.

Usage:
    # Terminal 1 - Run the server (listener)
    python perf_example.py -p 8000

    # Terminal 2 - Run the client (measures performance to server)
    python perf_example.py -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID>
"""

import argparse

import multiaddr
import trio

from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.perf import PROTOCOL_NAME, PerfService

ONE_UNIT = 16 * 16  # 256 bytes
UPLOAD_BYTES = ONE_UNIT * 10  # 2560 bytes upload
DOWNLOAD_BYTES = ONE_UNIT * 10  # 2560 bytes download


async def run_server(host, perf_service) -> None:
    """Run as a perf server - listens for incoming perf requests."""
    await perf_service.start()

    print("\nPerf server ready, listening on:")
    for addr in host.get_addrs():
        print(f"  {addr}")

    print(f"\nProtocol: {PROTOCOL_NAME}")
    print("\nRun client with:")
    print(f"  python perf_example.py -d {host.get_addrs()[0]}")
    print("\nWaiting for incoming perf requests...")

    await trio.sleep_forever()


async def run_client(
    host, perf_service, destination: str, upload_bytes: int, download_bytes: int
) -> None:
    """Run as a perf client - measures performance to a remote peer."""
    await perf_service.start()

    maddr = multiaddr.Multiaddr(destination)
    info = info_from_p2p_addr(maddr)

    print(f"\nConnecting to {info.peer_id}...")
    await host.connect(info)
    print("Connected!")

    print("\nMeasuring performance:")
    print(f"  Upload:   {upload_bytes} bytes")
    print(f"  Download: {download_bytes} bytes")
    print()

    async for output in perf_service.measure_performance(
        maddr, upload_bytes, download_bytes
    ):
        if output["type"] == "intermediary":
            # Progress report
            upload_bytes_out = output["upload_bytes"]
            download_bytes_out = output["download_bytes"]
            time_s = output["time_seconds"]

            if upload_bytes_out > 0:
                throughput = upload_bytes_out / time_s if time_s > 0 else 0
                print(
                    f"  Upload: {upload_bytes_out}B in {time_s:.2f}s "
                    f"({throughput:.0f} B/s)"
                )
            elif download_bytes_out > 0:
                throughput = download_bytes_out / time_s if time_s > 0 else 0
                print(
                    f"  Download: {download_bytes_out}B in {time_s:.2f}s "
                    f"({throughput:.0f} B/s)"
                )

        elif output["type"] == "final":
            # Final summary
            total_time = output["time_seconds"]
            total_upload = output["upload_bytes"]
            total_download = output["download_bytes"]
            total_data = total_upload + total_download

            print(f"\n{'=' * 50}")
            print("Performance Results:")
            print(f"  Total time:     {total_time:.3f} seconds")
            print(f"  Uploaded:       {total_upload} bytes")
            print(f"  Downloaded:     {total_download} bytes")
            print(f"  Total data:     {total_data} bytes")
            print(f"  Throughput:     {total_data / total_time:.0f} bytes/s")
            print(f"{'=' * 50}")

    await perf_service.stop()


async def run(port: int, destination: str, upload_mb: int, download_mb: int) -> None:
    """Main run function."""
    from libp2p.utils.address_validation import find_free_port

    if port <= 0:
        port = find_free_port()

    listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]
    host = new_host(listen_addrs=listen_addrs)

    # Create perf service
    perf_service = PerfService(host)

    async with host.run(listen_addrs=listen_addrs):
        if destination:
            # Client mode
            await run_client(
                host,
                perf_service,
                destination,
                upload_mb * ONE_UNIT,
                download_mb * ONE_UNIT,
            )
        else:
            # Server mode
            await run_server(host, perf_service)


def main() -> None:
    description = """
    Perf protocol example - Measure transfer performance between libp2p nodes.

    To use:
    1. Start server:  python perf_example.py -p 8000
    2. Start client:  python perf_example.py -d <MULTIADDR_FROM_SERVER>
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="listening port")
    parser.add_argument("-d", "--destination", type=str, help="destination multiaddr")
    parser.add_argument(
        "-u",
        "--upload",
        default=10,
        type=int,
        help="upload size in units of 256 bytes (default: 10)",
    )
    parser.add_argument(
        "-D",
        "--download",
        default=10,
        type=int,
        help="download size in units of 256 bytes (default: 10)",
    )

    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.destination, args.upload, args.download)
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
