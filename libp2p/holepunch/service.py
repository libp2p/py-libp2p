from enum import (
    Enum,
)
import logging
import time
from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
)

import trio

from libp2p.abc import (
    IHost,
    INetConn,
    INetStream,
    INetwork,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamEOF,
    StreamError,
)
from libp2p.peer.id import (
    ID,
)

if TYPE_CHECKING:
    from multiaddr import (
        Multiaddr,
    )

    from libp2p.peer.peerinfo import (
        PeerInfo,
    )


PROTOCOL_ID: TProtocol = TProtocol("/libp2p/dcutr")
SERVICE_NAME = "libp2p.holepunch"
MAX_MSG_SIZE = 4096
PROTOCOL_MSG_TIMEOUT = 10.0
DIRECT_DIAL_TIMEOUT = 10.0
HOLE_PUNCH_TIMEOUT = 10.0
MAX_RETRIES = 3

logger = logging.getLogger(f"libp2p.{SERVICE_NAME}")


def is_relay_addr(addr: "Multiaddr") -> bool:
    try:
        for proto_code, _ in addr.protocols_with_values():
            if proto_code == 421:  # P_CIRCUIT
                return True
        return False
    except Exception:
        return False


def is_local_addr(addr: "Multiaddr") -> bool:
    from multiaddr.protocols import (
        P_IP4,
        P_IP6,
    )

    if addr.has_protocol(P_IP4):
        ip_str = addr.value_for_protocol(P_IP4)
        if ip_str is not None:
            if ip_str == "127.0.0.1":
                return True
            if ip_str.startswith("10."):
                return True
            if ip_str.startswith("192.168."):
                return True
            if ip_str.startswith("172."):
                try:
                    parts = ip_str.split(".")
                    if len(parts) > 1:
                        second_octet = int(parts[1])
                        if 16 <= second_octet <= 31:
                            return True
                except ValueError:
                    pass
    if addr.has_protocol(P_IP6):
        ip6_str = addr.value_for_protocol(P_IP6)
        if ip6_str is not None:
            if ip6_str == "::1":
                return True
            if ip6_str.upper().startswith("FC") or ip6_str.upper().startswith("FD"):
                return True
    return False


def is_public_addr(addr: "Multiaddr") -> bool:
    if is_local_addr(addr) or is_relay_addr(addr):
        return False
    from multiaddr.protocols import (
        P_IP4,
        P_IP6,
    )

    if not (addr.has_protocol(P_IP4) or addr.has_protocol(P_IP6)):
        return False
    return True


def addrs_to_bytes(multiaddrs: list["Multiaddr"]) -> list[bytes]:
    return [addr.to_bytes() for addr in multiaddrs]


def addrs_from_bytes(multiaddrs_bytes: list[bytes]) -> list["Multiaddr"]:
    from multiaddr import (
        Multiaddr,
    )

    return [Multiaddr(bs) for bs in multiaddrs_bytes]


def remove_relay_addrs(addrs: list["Multiaddr"]) -> list["Multiaddr"]:
    return [addr for addr in addrs if not is_relay_addr(addr)]


def get_direct_connection(host: "IHost", peer_id: ID) -> Optional[INetConn]:
    network = host.get_network()
    if not hasattr(network, "connections") or peer_id not in network.connections:
        return None
    conn = network.connections[peer_id]

    return conn


class HolePunchActiveError(Exception):
    pass


class HolePunchServiceClosedError(Exception):
    pass


class NoPublicAddrError(Exception):
    pass


class ProtocolError(Exception):
    pass


class HolePunchMsgType(Enum):
    CONNECT = 0
    SYNC = 1


class HolePunchPb:
    def __init__(
        self, type_val: HolePunchMsgType, obs_addrs: Optional[list[bytes]] = None
    ):
        self.type = type_val
        self.obs_addrs = obs_addrs if obs_addrs else []

    @classmethod
    def from_bytes(cls, data: bytes) -> "HolePunchPb":
        if not data:
            raise ValueError("Cannot parse empty data for HolePunchPb")
        msg_type_val = data[0]
        try:
            msg_type = HolePunchMsgType(msg_type_val)
        except ValueError:
            raise ProtocolError(f"Invalid message type: {msg_type_val}") from None

        obs_addrs = []
        if msg_type == HolePunchMsgType.CONNECT:
            i = 1
            while i < len(data):
                if i + 2 > len(data):
                    raise ProtocolError("Malformed address length prefix")
                addr_len = int.from_bytes(data[i : i + 2], "big")
                i += 2
                if i + addr_len > len(data):
                    raise ProtocolError("Malformed address data")
                obs_addrs.append(data[i : i + addr_len])
                i += addr_len
        return cls(msg_type, obs_addrs)

    def to_bytes(self) -> bytes:
        data = bytearray()
        data.append(self.type.value)
        if self.type == HolePunchMsgType.CONNECT:
            for addr_bytes_val in self.obs_addrs:
                data.extend(len(addr_bytes_val).to_bytes(2, "big"))
                data.extend(addr_bytes_val)
        return bytes(data)


async def read_pb_msg(
    stream: INetStream, timeout: float = PROTOCOL_MSG_TIMEOUT
) -> HolePunchPb:
    try:
        with trio.fail_after(timeout):
            len_bytes = await stream.read(4)
    except trio.TooSlowError:
        raise StreamError(f"Timeout reading message length after {timeout}s") from None

    if not len_bytes or len(len_bytes) < 4:
        raise StreamEOF("EOF reading msg len")
    msg_len = int.from_bytes(len_bytes, "big")

    if msg_len == 0:
        raise ProtocolError("Received message with zero length")
    if msg_len > MAX_MSG_SIZE:
        raise ProtocolError(f"Message too large: {msg_len} > {MAX_MSG_SIZE}")

    try:
        with trio.fail_after(timeout):
            msg_bytes = await stream.read(msg_len)
    except trio.TooSlowError:
        raise StreamError(f"Timeout reading message data after {timeout}s") from None

    if not msg_bytes or len(msg_bytes) != msg_len:
        raise StreamEOF(
            f"EOF reading msg data, expected {msg_len} got {len(msg_bytes)}"
        )
    return HolePunchPb.from_bytes(msg_bytes)


async def write_pb_msg(stream: INetStream, msg: HolePunchPb) -> None:
    data = msg.to_bytes()
    if not data:
        raise ProtocolError("Attempting to send empty message (serialization failed)")
    if len(data) > MAX_MSG_SIZE:
        raise ProtocolError(
            f"Trying to send message too large: {len(data)} > {MAX_MSG_SIZE}"
        )

    len_bytes = len(data).to_bytes(4, "big")
    await stream.write(len_bytes + data)


class AddrFilter:
    def FilterLocal(self, peer_id: ID, addrs: list["Multiaddr"]) -> list["Multiaddr"]:
        return addrs

    def FilterRemote(self, peer_id: ID, addrs: list["Multiaddr"]) -> list["Multiaddr"]:
        return addrs


class HolePunchService:
    host: "IHost"
    _listen_addrs_func: Callable[[], list["Multiaddr"]]
    direct_dial_timeout: float
    hole_punch_timeout: float
    _direct_connect_tasks: dict[ID, trio.CancelScope]
    _active_mx: trio.Lock
    _closed: bool
    _tasks: set[trio.CancelScope]
    addr_filter: AddrFilter
    legacy_behavior: bool

    def __init__(
        self,
        host: "IHost",
        addr_filter: Optional[AddrFilter] = None,
        direct_dial_timeout: float = DIRECT_DIAL_TIMEOUT,
        hole_punch_timeout: float = HOLE_PUNCH_TIMEOUT,
        legacy_behavior: bool = True,
    ):
        self.host = host
        self._listen_addrs_func = lambda: self.host.get_addrs()
        self.direct_dial_timeout = direct_dial_timeout
        self.hole_punch_timeout = hole_punch_timeout
        self._direct_connect_tasks: dict[ID, trio.CancelScope] = {}
        self._active_mx = trio.Lock()
        self._closed = False
        # NOTE: self._nursery needs to be initialized for starting tasks,
        # typically in an async context manager setup for the service or passed in.
        self._nursery: Optional[trio.Nursery] = None
        self._tasks: set[trio.CancelScope] = set()
        self.addr_filter = addr_filter if addr_filter else AddrFilter()
        self.legacy_behavior = legacy_behavior

        self.host.set_stream_handler(PROTOCOL_ID, self._handle_hole_punch_stream)
        logger.info("HolePunchService initialized and handlers registered")

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        logger.info("Stopping HolePunchService...")

        all_tasks_to_cancel = list(self._tasks)

        if all_tasks_to_cancel:
            for task_scope in all_tasks_to_cancel:
                task_scope.cancel()
            # Nursery will handle waiting for cancelled tasks if it's managing them.
            # If these scopes were created manually and tasks started within them,
            # cancellation is signalled. trio.gather is not used here.

        self._tasks.clear()
        async with self._active_mx:
            self._direct_connect_tasks.clear()

        logger.info("HolePunchService stopped")

    async def direct_connect(self, peer_id: ID) -> Optional[trio.CancelScope]:
        logger.debug(f"Request to DirectConnect to peer {peer_id}")

        if self._closed:
            logger.warning(f"DirectConnect for {peer_id} aborted, service is closed.")
            raise HolePunchServiceClosedError(
                f"Service closed, cannot connect to {peer_id}"
            )

        async with self._active_mx:
            if peer_id in self._direct_connect_tasks:
                logger.debug(
                    f"DirectConnect for {peer_id} is already active, "
                    "returning existing task."
                )
                # TODO: Decide if returning the existing scope tuple is the desired API.
                # The original returned the task object. Here we return the CancelScope.
                return self._direct_connect_tasks[peer_id]

            logger.debug(
                f"No active DirectConnect task for {peer_id}, creating new one."
            )

            if self._nursery is None:
                # This should ideally not happen if service lifecycle is managed.
                # Consider raising an error or ensuring nursery is always available.
                logger.error(
                    "HolePunchService nursery not initialized, "
                    "cannot start DirectConnect task."
                )
                return None

            # Create a new cancel scope for the task.
            new_task_scope = trio.CancelScope()

            async def task_wrapper(
                task_l_peer_id: ID, task_l_scope: trio.CancelScope
            ) -> None:
                try:
                    # Apply the passed-in cancel scope to the core logic.
                    # If task_l_scope is cancelled externally,
                    # a trio.Cancelled will be raised
                    # from within this 'with' block.
                    with task_l_scope:
                        await self._direct_connect_impl(task_l_peer_id)
                except trio.Cancelled:
                    logger.debug(
                        f"DirectConnect task for {task_l_peer_id} was cancelled."
                    )
                    # Re-raise unless specific handling is needed here.
                    # Cancellation propagates from nursery if started in CancelScope.
                except Exception as e:
                    logger.exception(
                        f"Task for {task_l_peer_id} failed in DirectConnect. "
                        f"Exception: {e}"
                    )
                    # Depending on policy, may want to re-raise or handle.
                finally:
                    # Cleanup logic: remove this task's scope
                    # from the tracking dictionary.
                    async with self._active_mx:
                        # Check if the task being cleaned up is indeed
                        # the one associated
                        # with this peer_id and scope.
                        current_stored_scope = self._direct_connect_tasks.get(
                            task_l_peer_id
                        )
                        if current_stored_scope is task_l_scope:
                            del self._direct_connect_tasks[task_l_peer_id]
                            # Also remove from general _tasks set
                            # if it was added only for direct_connect
                            if task_l_scope in self._tasks:
                                self._tasks.remove(task_l_scope)
                    logger.debug(
                        f"DirectConnect task for {task_l_peer_id} "
                        f"(dict cleanup) completed."
                    )

            # Start the task in the service's nursery.
            self._nursery.start_soon(task_wrapper, peer_id, new_task_scope)

            # Store and return the cancel scope associated with the new task.
            self._direct_connect_tasks[peer_id] = new_task_scope
            self._tasks.add(
                new_task_scope
            )  # Add to general tasks for cancellation on stop()
            return new_task_scope

    async def _direct_connect_impl(self, remote_peer_id: ID) -> None:
        if get_direct_connection(self.host, remote_peer_id):
            logger.debug(f"Already directly connected to {remote_peer_id}, skipping.")
            return

        dt: float = 0.0
        remote_peer_info: Optional["PeerInfo"] = self.host.get_peerstore().peer_info(
            remote_peer_id
        )

        if remote_peer_info:
            public_addrs = [
                addr
                for addr in remote_peer_info.addrs
                if not is_relay_addr(addr) and is_public_addr(addr)
            ]
            if public_addrs:
                logger.debug(
                    f"Attempting direct dial to {remote_peer_id} at {public_addrs}"
                )
                from libp2p.peer.peerinfo import PeerInfo as ConcretePeerInfo

                pi_to_dial = ConcretePeerInfo(remote_peer_id, public_addrs)
                t_start = time.monotonic()
                try:
                    with trio.fail_after(self.direct_dial_timeout):
                        await self.host.connect(pi_to_dial)
                    dt = time.monotonic() - t_start
                    logger.info(
                        f"Direct dial to {remote_peer_id} successful in {dt:.2f}s."
                    )
                    return
                except trio.TooSlowError:
                    dt = time.monotonic() - t_start
                    logger.warning(
                        f"Direct dial to {remote_peer_id} timed out after {dt:.2f}s."
                    )
                except Exception as e:
                    dt = time.monotonic() - t_start
                    logger.warning(
                        f"Direct dial to {remote_peer_id} failed: {e} in {dt:.2f}s."
                    )
            else:
                logger.debug(f"No public addrs for {remote_peer_id} for direct dial.")
        else:
            logger.debug(f"No peer info for {remote_peer_id} for direct dial.")

        logger.debug(f"Proceeding to hole punch for {remote_peer_id}.")
        last_error: Optional[Exception] = None
        for i in range(1, MAX_RETRIES + 1):
            if self._closed:
                logger.info(
                    f"Service closed during hole punch attempt {i} for {remote_peer_id}"
                )
                raise HolePunchServiceClosedError("Service closed during retry loop")

            logger.debug(f"Hole punch attempt {i}/{MAX_RETRIES} for {remote_peer_id}")
            stream: Optional[INetStream] = None
            try:
                stream = await self.host.new_stream(remote_peer_id, [PROTOCOL_ID])
                (
                    remote_hp_addrs,
                    our_obs_addrs,
                    rtt,
                ) = await self._initiate_hole_punch_on_stream(stream)

                syn_time = rtt / 2.0
                logger.debug(
                    f"Peer {remote_peer_id} RTT {rtt:.4f}s; punch in {syn_time:.4f}s."
                )
                await trio.sleep(syn_time)

                if self._closed:
                    logger.info(f"Service closed after RTT sync for {remote_peer_id}")
                    raise HolePunchServiceClosedError("Service closed after RTT sync")

                from libp2p.peer.peerinfo import PeerInfo as ConcretePeerInfo

                pi_to_punch = ConcretePeerInfo(remote_peer_id, remote_hp_addrs)

                logger.debug(
                    f"Attempting hole punch connect to {remote_peer_id} "
                    f"at {remote_hp_addrs}"
                )
                t_start_punch = time.monotonic()
                with trio.fail_after(self.hole_punch_timeout):
                    await self.host.connect(pi_to_punch)
                dt_punch = time.monotonic() - t_start_punch
                logger.info(
                    f"Hole punch attempt {i} to {remote_peer_id} "
                    f"successful in {dt_punch:.2f}s."
                )
                return
            except (
                StreamError,
                NoPublicAddrError,
                ProtocolError,
                trio.TooSlowError,
                StreamEOF,
                HolePunchServiceClosedError,
            ) as e:
                last_error = e
                logger.warning(
                    f"Hole punch attempt {i} for {remote_peer_id} failed: {e}"
                )
                if isinstance(e, HolePunchServiceClosedError):
                    raise
            except Exception as e:
                last_error = e
                logger.error(
                    f"Unexpected error in HP attempt {i} for {remote_peer_id}: {e}",
                    exc_info=True,
                )
            finally:
                if stream:
                    is_muxed_conn_closed = False
                    if (
                        hasattr(stream, "muxed_conn")
                        and stream.muxed_conn
                        and hasattr(stream.muxed_conn, "is_closed")
                    ):
                        is_muxed_conn_closed = stream.muxed_conn.is_closed

                    if not is_muxed_conn_closed:
                        try:
                            if last_error and not isinstance(
                                last_error,
                                (trio.TooSlowError, HolePunchServiceClosedError),
                            ):
                                await stream.reset()
                            else:
                                await stream.close()
                        except Exception as e_close:
                            logger.debug(
                                f"Error closing/resetting stream in finally: {e_close}"
                            )

            if i < MAX_RETRIES:
                if self._closed:
                    raise HolePunchServiceClosedError(
                        "Service closed before next retry sleep"
                    )
                await trio.sleep(1.0)

        logger.error(
            f"All {MAX_RETRIES} hole punch retries for {remote_peer_id} failed."
        )
        if last_error:
            raise last_error
        raise ProtocolError(f"All hole punch retries failed for {remote_peer_id}")

    async def _initiate_hole_punch_on_stream(
        self, stream: INetStream
    ) -> tuple[list["Multiaddr"], list["Multiaddr"], float]:
        if not hasattr(stream, "muxed_conn") or not hasattr(
            stream.muxed_conn, "peer_id"
        ):
            raise ProtocolError(
                "Stream object does not have expected muxed_conn.peer_id attribute"
            )
        remote_peer_id = stream.muxed_conn.peer_id

        try:
            our_obs_addrs_ma = remove_relay_addrs(self._listen_addrs_func())
            our_obs_addrs_ma = self.addr_filter.FilterLocal(
                remote_peer_id, our_obs_addrs_ma
            )
            if not our_obs_addrs_ma:
                raise NoPublicAddrError("Initiator: No public addresses to share.")

            logger.debug(
                f"Initiator: Sending CONNECT to {remote_peer_id} "
                f"with addrs: {our_obs_addrs_ma}"
            )
            connect_msg = HolePunchPb(
                HolePunchMsgType.CONNECT, addrs_to_bytes(our_obs_addrs_ma)
            )

            t_start_rtt = time.monotonic()
            await write_pb_msg(stream, connect_msg)

            response_msg = await read_pb_msg(stream)
            rtt = time.monotonic() - t_start_rtt

            if response_msg.type != HolePunchMsgType.CONNECT:
                raise ProtocolError(
                    f"Expected CONNECT response, got {response_msg.type}"
                )

            remote_obs_addrs_ma = remove_relay_addrs(
                addrs_from_bytes(response_msg.obs_addrs)
            )
            remote_obs_addrs_ma = self.addr_filter.FilterRemote(
                remote_peer_id, remote_obs_addrs_ma
            )
            if not remote_obs_addrs_ma:
                raise NoPublicAddrError("Initiator: Peer shared no public addresses.")

            logger.debug(
                f"Initiator: Got CONNECT from {remote_peer_id} "
                f"({remote_obs_addrs_ma}), RTT: {rtt:.4f}s"
            )

            sync_msg = HolePunchPb(HolePunchMsgType.SYNC)
            await write_pb_msg(stream, sync_msg)
            logger.debug(f"Initiator: Sent SYNC to {remote_peer_id}")
            return remote_obs_addrs_ma, our_obs_addrs_ma, rtt
        except (
            StreamError,
            NoPublicAddrError,
            ProtocolError,
            trio.TooSlowError,
            StreamEOF,
        ) as e:
            logger.warning(
                f"Error in _initiate_hole_punch_on_stream with {remote_peer_id}: {e}"
            )
            if stream and hasattr(stream, "reset"):
                await stream.reset()
            raise
        except Exception as e:
            logger.error(
                f"Unexpected stream error with {remote_peer_id}: {e}", exc_info=True
            )
            if stream and hasattr(stream, "reset"):
                await stream.reset()
            raise ProtocolError(f"Unexpected stream error: {e}") from e

    async def _handle_hole_punch_stream(self, stream: INetStream) -> None:
        if not hasattr(stream, "muxed_conn") or not hasattr(
            stream.muxed_conn, "peer_id"
        ):
            raise ProtocolError(
                "Stream object does not have expected muxed_conn.peer_id "
                "attribute for responder"
            )
        remote_peer_id = stream.muxed_conn.peer_id

        logger.debug(
            f"Responder: Handling incoming hole punch stream from {remote_peer_id}"
        )
        try:
            connect_msg = await read_pb_msg(stream)
            if connect_msg.type != HolePunchMsgType.CONNECT:
                raise ProtocolError(
                    "Responder: Expected CONNECT from initiator, "
                    f"got {connect_msg.type}"
                )

            initiator_obs_addrs_ma = remove_relay_addrs(
                addrs_from_bytes(connect_msg.obs_addrs)
            )
            initiator_obs_addrs_ma = self.addr_filter.FilterRemote(
                remote_peer_id, initiator_obs_addrs_ma
            )
            if not initiator_obs_addrs_ma:
                raise NoPublicAddrError(
                    "Responder: Initiator shared no public addresses."
                )
            logger.debug(
                f"Responder: Got CONNECT from {remote_peer_id} "
                f"with addrs: {initiator_obs_addrs_ma}"
            )

            our_obs_addrs_ma = remove_relay_addrs(self._listen_addrs_func())
            our_obs_addrs_ma = self.addr_filter.FilterLocal(
                remote_peer_id, our_obs_addrs_ma
            )
            if not our_obs_addrs_ma:
                raise NoPublicAddrError("Responder: No public addresses to share.")

            logger.debug(
                f"Responder: Sending CONNECT to {remote_peer_id} "
                f"with addrs: {our_obs_addrs_ma}"
            )
            response_connect_msg = HolePunchPb(
                HolePunchMsgType.CONNECT, addrs_to_bytes(our_obs_addrs_ma)
            )
            await write_pb_msg(stream, response_connect_msg)

            sync_msg = await read_pb_msg(stream)
            if sync_msg.type != HolePunchMsgType.SYNC:
                raise ProtocolError(
                    f"Responder: Expected SYNC from initiator, got {sync_msg.type}"
                )
            logger.debug(
                f"Responder: Got SYNC from {remote_peer_id}. Protocol complete."
            )
            await stream.close()
        except (
            StreamError,
            NoPublicAddrError,
            ProtocolError,
            trio.TooSlowError,
            StreamEOF,
        ) as e:
            logger.warning(
                f"Stream error handling hole punch from {remote_peer_id}: {e}"
            )
            if stream and hasattr(stream, "reset"):
                try:
                    await stream.reset()
                except Exception as e_reset:
                    logger.debug(f"Error resetting stream in except: {e_reset}")

        except Exception as e:
            logger.error(
                f"Unexpected error handling hole punch from {remote_peer_id}: {e}",
                exc_info=True,
            )
            if stream and hasattr(stream, "reset"):
                try:
                    await stream.reset()
                except Exception as e_reset:
                    logger.debug(
                        f"Error resetting stream in except (unexpected): {e_reset}"
                    )

    # INotifee methods
    async def opened_stream(self, network: "INetwork", stream: INetStream) -> None:
        pass

    async def closed_stream(self, network: "INetwork", stream: INetStream) -> None:
        pass

    async def connected(self, network: "INetwork", conn: INetConn) -> None:
        if self._closed:
            return

    async def disconnected(self, network: "INetwork", conn: INetConn) -> None:
        pass

    async def listen(self, network: "INetwork", multiaddr: "Multiaddr") -> None:
        pass

    async def listen_close(self, network: "INetwork", multiaddr: "Multiaddr") -> None:
        pass
