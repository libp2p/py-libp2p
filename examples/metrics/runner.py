from prompt_toolkit import PromptSession
import trio

from examples.metrics.coordinator import COMMANDS, Node
from libp2p.metrics.metrics import Metrics
from libp2p.utils.address_validation import get_available_interfaces


async def main() -> None:
    # Create a libp2p-node instance
    listen_addrs = get_available_interfaces(0)
    node = Node(listen_addrs=listen_addrs)

    async with (
        node.host.run(listen_addrs=listen_addrs),
        trio.open_nursery() as nursery,
    ):
        # Start metrics service
        metrics = Metrics()

        nursery.start_soon(
            metrics.start_prometheus_server, node.host.metric_recv_channel
        )
        nursery.start_soon(node.host.get_peerstore().start_cleanup_task, 60)
        nursery.start_soon(node.command_executor, nursery)

        print(f"Host multiaddr: {node.host.get_addrs()[0]}")
        await trio.sleep(1)

        print("Entering intractive mode, type commands below.")
        promt_session = PromptSession()
        print(COMMANDS)

        while not node.termination_event.is_set():
            try:
                _ = await trio.to_thread.run_sync(input)
                user_input = await trio.to_thread.run_sync(
                    lambda: promt_session.prompt("Command> ")
                )
                cmds = user_input.strip().split(" ", 2)
                await node.input_send_channel.send(cmds)

            except Exception as e:
                print(f"Error in the interactive shell: {e}")
                await trio.sleep(1)

    print("Shutdown complete, Goodbye!")


def cli() -> None:
    try:
        trio.run(main)
    except* KeyboardInterrupt:
        print("Session terminated by user")


if __name__ == "__main__":
    cli()
