from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    AsyncExitStack,
    asynccontextmanager,
)

from libp2p.abc import (
    IHost,
    ISubscriptionAPI,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)
from libp2p.tools.async_service import (
    Service,
    background_trio_service,
)
from tests.utils.factories import (
    PubsubFactory,
)

CRYPTO_TOPIC = "ethereum"

# Message format:
# Sending crypto: <source>,<dest>,<amount as integer>
#                 Ex. send,aspyn,alex,5
# Set crypto: <dest>,<amount as integer>
#                 Ex. set,rob,5
# Determine message type by looking at first item before first comma


class DummyAccountNode(Service):
    """
    Node which has an internal balance mapping, meant to serve as a dummy
    crypto blockchain.

    There is no actual blockchain, just a simple map indicating how much
    crypto each user in the mappings holds
    """

    pubsub: Pubsub
    subscription: ISubscriptionAPI | None

    def __init__(self, pubsub: Pubsub) -> None:
        self.pubsub = pubsub
        self.subscription = None
        self.balances: dict[str, int] = {}

    @property
    def host(self) -> IHost:
        return self.pubsub.host

    async def run(self) -> None:
        self.subscription = await self.pubsub.subscribe(CRYPTO_TOPIC)
        self.manager.run_daemon_task(self.handle_incoming_msgs)
        await self.manager.wait_finished()

    @classmethod
    @asynccontextmanager
    async def create(cls, number: int) -> AsyncIterator[tuple["DummyAccountNode", ...]]:
        """
        Create a new DummyAccountNode and attach a libp2p node, a floodsub, and
        a pubsub instance to this new node.

        We use create as this serves as a factory function and allows us
        to use async await, unlike the init function
        """
        async with PubsubFactory.create_batch_with_floodsub(number) as pubsubs:
            async with AsyncExitStack() as stack:
                dummy_acount_nodes = tuple(cls(pubsub) for pubsub in pubsubs)
                for node in dummy_acount_nodes:
                    await stack.enter_async_context(background_trio_service(node))
                yield dummy_acount_nodes

    async def handle_incoming_msgs(self) -> None:
        """Handle all incoming messages on the CRYPTO_TOPIC from peers."""
        while True:
            if self.subscription is None:
                raise RuntimeError(
                    "Subscription must be set before handling incoming messages"
                )
            incoming = await self.subscription.get()
            msg_comps = incoming.data.decode("utf-8").split(",")

            if msg_comps[0] == "send":
                self.handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
            elif msg_comps[0] == "set":
                self.handle_set_crypto(msg_comps[1], int(msg_comps[2]))

    async def publish_send_crypto(
        self, source_user: str, dest_user: str, amount: int
    ) -> None:
        """
        Create a send crypto message and publish that message to all other
        nodes.

        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send
        """
        msg_contents = f"send,{source_user},{dest_user},{amount!s}"
        await self.pubsub.publish(CRYPTO_TOPIC, msg_contents.encode())

    async def publish_set_crypto(self, user: str, amount: int) -> None:
        """
        Create a set crypto message and publish that message to all other
        nodes.

        :param user: user to set crypto for
        :param amount: amount of crypto
        """
        msg_contents = f"set,{user},{amount!s}"
        await self.pubsub.publish(CRYPTO_TOPIC, msg_contents.encode())

    def handle_send_crypto(self, source_user: str, dest_user: str, amount: int) -> None:
        """
        Handle incoming send_crypto message.

        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send
        """
        if source_user in self.balances:
            self.balances[source_user] -= amount
        else:
            self.balances[source_user] = -amount

        if dest_user in self.balances:
            self.balances[dest_user] += amount
        else:
            self.balances[dest_user] = amount

    def handle_set_crypto(self, dest_user: str, amount: int) -> None:
        """
        Handle incoming set_crypto message.

        :param dest_user: user to set crypto for
        :param amount: amount of crypto
        """
        self.balances[dest_user] = amount

    def get_balance(self, user: str) -> int:
        """
        Get balance in crypto for a particular user.

        :param user: user to get balance for
        :return: balance of user
        """
        if user in self.balances:
            return self.balances[user]
        else:
            return -1
