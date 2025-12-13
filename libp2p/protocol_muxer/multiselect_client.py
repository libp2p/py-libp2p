from collections.abc import Sequence
import logging

import trio

from libp2p.abc import IMultiselectClient, IMultiselectCommunicator
from libp2p.custom_types import TProtocol

from .exceptions import (
    MultiselectClientError,
    MultiselectCommunicatorError,
    ProtocolNotSupportedError,
)

logger = logging.getLogger("libp2p.protocol_muxer.multiselect_client")
logger.setLevel(logging.DEBUG)

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"
DEFAULT_NEGOTIATE_TIMEOUT = 30  # Increased for high-concurrency scenarios

logger = logging.getLogger(__name__)


class MultiselectClient(IMultiselectClient):
    """
    Client for communicating with receiver's multiselect module in order to
    select a protocol id to communicate over.
    """

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Ensure that the client and multiselect are both using the same
        multiselect protocol.

        :param communicator: communicator to use to communicate with counterparty
        :raise MultiselectClientError: raised when handshake failed
        """
        try:
            await communicator.write(MULTISELECT_PROTOCOL_ID)
        except MultiselectCommunicatorError as error:
            raise MultiselectClientError(f"handshake write failed: {error}") from error

        try:
            handshake_contents = await communicator.read()

        except MultiselectCommunicatorError as error:
            raise MultiselectClientError(f"handshake read failed: {error}") from error

        if not is_valid_handshake(handshake_contents):
            raise MultiselectClientError(
                f"multiselect protocol ID mismatch: "
                f"expected {MULTISELECT_PROTOCOL_ID}, "
                f"got {handshake_contents!r}"
            )

    async def select_one_of(
        self,
        protocols: Sequence[TProtocol],
        communicator: IMultiselectCommunicator,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> TProtocol:
        """
        For each protocol, send message to multiselect selecting protocol and
        fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)

        :param protocols: protocols to select from
        :param communicator: communicator to use to communicate with counterparty
        :param negotiate_timeout: timeout for negotiation
        :return: selected protocol
        :raise MultiselectClientError: raised when protocol negotiation failed
        """
        try:
            with trio.fail_after(negotiate_timeout):
                await self.handshake(communicator)

                protocol_list = [str(p) for p in protocols]
                logger.debug(f"Attempting to negotiate one of: {protocol_list}")

                unsupported_errors: list[str] = []
                for protocol in protocols:
                    try:
                        selected_protocol = await self.try_select(
                            communicator, protocol
                        )
                        return selected_protocol
                    except ProtocolNotSupportedError as error:
                        unsupported_errors.append(str(error))
                        continue

                raise MultiselectClientError(
                    _build_protocols_not_supported_message(
                        protocols, negotiate_timeout, unsupported_errors
                    )
                )
        except trio.TooSlowError:
            raise MultiselectClientError(
                f"response timed out after {negotiate_timeout}s, "
                f"protocols tried: {list(protocols)}"
            )

    async def query_multistream_command(
        self,
        communicator: IMultiselectCommunicator,
        command: str,
        response_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> list[str]:
        """
        Send a multistream-select command over the given communicator and return
        parsed response.

        :param communicator: communicator to use to communicate with counterparty
        :param command: supported multistream-select command(e.g., ls)
        :param negotiate_timeout: timeout for negotiation
        :raise MultiselectClientError: If the communicator fails to process data.
        :return: list of strings representing the response from peer.
        """
        try:
            with trio.fail_after(response_timeout):
                await self.handshake(communicator)

                if command == "ls":
                    try:
                        await communicator.write("ls")
                    except MultiselectCommunicatorError as error:
                        raise MultiselectClientError(
                            f"command write failed: {error}, command={command}"
                        ) from error
                else:
                    raise ValueError("Command not supported")

                try:
                    response = await communicator.read()
                    response_list = response.strip().splitlines()

                except MultiselectCommunicatorError as error:
                    raise MultiselectClientError(
                        f"command read failed: {error}, command={command}"
                    ) from error

                return response_list
        except trio.TooSlowError:
            raise MultiselectClientError(
                f"command response timed out after {response_timeout}s, "
                f"command={command}"
            )

    async def try_select(
        self, communicator: IMultiselectCommunicator, protocol: TProtocol
    ) -> TProtocol:
        """
        Try to select the given protocol or raise exception if fails.

        :param communicator: communicator to use to communicate with counterparty
        :param protocol: protocol to select
        :raise MultiselectClientError: raised when protocol negotiation failed
        :return: selected protocol
        """
        # Represent `None` protocol as an empty string.
        protocol_str = protocol if protocol is not None else ""
        restart_attempted = False
        attempt = 0

        while True:
            attempt += 1
            try:
                await communicator.write(protocol_str)
            except MultiselectCommunicatorError as error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "multiselect write failed for protocol %s on attempt %d: %s",
                        protocol,
                        attempt,
                        error,
                    )
                raise MultiselectClientError(
                    f"protocol write failed: {error}, protocol={protocol}"
                ) from error

            try:
                response = await communicator.read()
            except MultiselectCommunicatorError as error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "multiselect read failed for protocol %s on attempt %d: %s",
                        protocol,
                        attempt,
                        error,
                    )
                raise MultiselectClientError(
                    f"protocol read failed: {error}, protocol={protocol}"
                ) from error

            if response == protocol_str:
                return protocol
            if response == PROTOCOL_NOT_FOUND_MSG:
                raise ProtocolNotSupportedError(
                    f"protocol not supported: {protocol}, response={response!r}"
                )
            if response == MULTISELECT_PROTOCOL_ID and not restart_attempted:
                # Some peers (notably go-libp2p during heavy churn) restart the
                # multistream handshake on existing streams. Re-run the handshake
                # once to resynchronize and retry the selection.
                restart_attempted = True
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Peer restarted multiselect handshake mid-selection for %s "
                        "on attempt %d; re-running handshake",
                        protocol,
                        attempt,
                    )
                await self.handshake(communicator)
                continue
            raise MultiselectClientError(
                f"unrecognized response: {response!r}, expected {protocol_str!r} "
                f"or {PROTOCOL_NOT_FOUND_MSG!r}, protocol={protocol}"
            )
        raise MultiselectClientError(
            f"failed to negotiate protocol {protocol}: unexpected loop exit"
        )


def is_valid_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed.

    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """
    return handshake_contents == MULTISELECT_PROTOCOL_ID


def _build_protocols_not_supported_message(
    protocols: Sequence[TProtocol],
    negotiate_timeout: int,
    unsupported_errors: Sequence[str],
) -> str:
    """
    Format the final error message when every protocol was explicitly rejected.

    Includes the most recent rejection message to aid debugging so callers can
    see whether the peer closed the stream or responded with "na".
    """
    base = (
        f"protocols not supported: tried {list(protocols)}, "
        f"timeout={negotiate_timeout}s"
    )
    if unsupported_errors:
        return f"{base}. Last error: {unsupported_errors[-1]}"
    return base
