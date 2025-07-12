from collections.abc import (
    Callable,
)
from dataclasses import dataclass
from enum import Enum
import logging
from typing import (
    NamedTuple,
    cast,
)

import trio

from libp2p.custom_types import AsyncValidatorFn, ValidatorFn
from libp2p.peer.id import (
    ID,
)

from .pb import (
    rpc_pb2,
)

logger = logging.getLogger("libp2p.pubsub.validation")


class ValidationResult(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    IGNORE = "ignore"
    THROTTLED = "throttled"


@dataclass
class ValidationRequest:
    """Request for message validation"""

    validators: list["TopicValidator"]
    msg_forwarder: ID  # peer ID
    msg: rpc_pb2.Message  # message object
    result_callback: Callable[[ValidationResult, Exception | None], None]


class TopicValidator(NamedTuple):
    topic: str
    validator: ValidatorFn
    is_async: bool
    timeout: float | None = None
    # Per-topic throttle semaphore
    throttle_semaphore: trio.Semaphore | None = None


class ValidationThrottler:
    """Manages all validation throttling mechanisms"""

    def __init__(
        self,
        queue_size: int = 32,
        global_throttle_limit: int = 8192,
        default_topic_throttle_limit: int = 1024,
        worker_count: int | None = None,
    ):
        # 1. Queue-level throttling - bounded memory channel
        self._validation_send, self._validation_receive = trio.open_memory_channel[
            ValidationRequest
        ](queue_size)

        # 2. Global validation throttling - limits total concurrent async validations
        self._global_throttle = trio.Semaphore(global_throttle_limit)

        # 3. Per-topic throttling - each validator gets its own semaphore
        self._default_topic_throttle_limit = default_topic_throttle_limit

        # Worker management
        # TODO: Find a better way to manage worker count
        self._worker_count = worker_count or 4
        self._running = False

    async def start(self, nursery: trio.Nursery) -> None:
        """Start the validation workers"""
        self._running = True

        # Start validation worker tasks
        for i in range(self._worker_count):
            nursery.start_soon(self._validation_worker, f"worker-{i}")

    async def stop(self) -> None:
        """Stop the validation system"""
        self._running = False
        await self._validation_send.aclose()

    def create_topic_validator(
        self,
        topic: str,
        validator: ValidatorFn,
        is_async: bool,
        timeout: float | None = None,
        throttle_limit: int | None = None,
    ) -> TopicValidator:
        """Create a new topic validator with its own throttle"""
        limit = throttle_limit or self._default_topic_throttle_limit
        throttle_sem = trio.Semaphore(limit)

        return TopicValidator(
            topic=topic,
            validator=validator,
            is_async=is_async,
            timeout=timeout,
            throttle_semaphore=throttle_sem,
        )

    async def submit_validation(
        self,
        validators: list[TopicValidator],
        msg_forwarder: ID,
        msg: rpc_pb2.Message,
        result_callback: Callable[[ValidationResult, Exception | None], None],
    ) -> bool:
        """
        Submit a message for validation.
        Returns True if queued successfully, False if queue is full (throttled).
        """
        if not self._running:
            result_callback(
                ValidationResult.REJECT, Exception("Validation system not running")
            )
            return False

        request = ValidationRequest(
            validators=validators,
            msg_forwarder=msg_forwarder,
            msg=msg,
            result_callback=result_callback,
        )

        try:
            # This will raise trio.WouldBlock if queue is full
            self._validation_send.send_nowait(request)
            return True
        except trio.WouldBlock:
            # Queue-level throttling: drop the message
            logger.debug(
                "Validation queue full, dropping message from %s", msg_forwarder
            )
            result_callback(
                ValidationResult.THROTTLED, Exception("Validation queue full")
            )
            return False

    async def _validation_worker(self, worker_id: str) -> None:
        """Worker that processes validation requests"""
        logger.debug("Validation worker %s started", worker_id)

        async with self._validation_receive:
            async for request in self._validation_receive:
                if not self._running:
                    break

                try:
                    # Process the validation request
                    result = await self._validate_message(request)
                    request.result_callback(result, None)
                except Exception as e:
                    logger.exception("Error in validation worker %s", worker_id)
                    request.result_callback(ValidationResult.REJECT, e)

        logger.debug("Validation worker %s stopped", worker_id)

    async def _validate_message(self, request: ValidationRequest) -> ValidationResult:
        """Core validation logic with throttling"""
        validators = request.validators
        msg_forwarder = request.msg_forwarder
        msg = request.msg

        if not validators:
            return ValidationResult.ACCEPT

        # Separate sync and async validators
        sync_validators = [v for v in validators if not v.is_async]
        async_validators = [v for v in validators if v.is_async]

        # Run synchronous validators first
        for validator in sync_validators:
            try:
                # Apply per-topic throttling even for sync validators
                if validator.throttle_semaphore:
                    validator.throttle_semaphore.acquire_nowait()
                    try:
                        result = validator.validator(msg_forwarder, msg)
                        if not result:
                            return ValidationResult.REJECT
                    finally:
                        validator.throttle_semaphore.release()
                else:
                    result = validator.validator(msg_forwarder, msg)
                    if not result:
                        return ValidationResult.REJECT
            except trio.WouldBlock:
                # Per-topic throttling for sync validator
                logger.debug("Sync validation throttled for topic %s", validator.topic)
                return ValidationResult.THROTTLED
            except Exception as e:
                logger.exception(
                    "Sync validator failed for topic %s: %s", validator.topic, e
                )
                return ValidationResult.REJECT

        # Handle async validators with global + per-topic throttling
        if async_validators:
            return await self._validate_async_validators(
                async_validators, msg_forwarder, msg
            )

        return ValidationResult.ACCEPT

    async def _validate_async_validators(
        self, validators: list[TopicValidator], msg_forwarder: ID, msg: rpc_pb2.Message
    ) -> ValidationResult:
        """Handle async validators with proper throttling"""
        if len(validators) == 1:
            # Fast path for single validator
            return await self._validate_single_async_validator(
                validators[0], msg_forwarder, msg
            )

        # Multiple async validators - run them concurrently
        try:
            # Try to acquire global throttle slot
            self._global_throttle.acquire_nowait()
        except trio.WouldBlock:
            logger.debug(
                "Global validation throttle exceeded, dropping message from %s",
                msg_forwarder,
            )
            return ValidationResult.THROTTLED

        try:
            async with trio.open_nursery() as nursery:
                results = {}

                async def run_validator(validator: TopicValidator, index: int) -> None:
                    """Run a single async validator and store the result"""
                    nonlocal results
                    result = await self._validate_single_async_validator(
                        validator, msg_forwarder, msg
                    )
                    results[index] = result

                # Start all validators concurrently
                for i, validator in enumerate(validators):
                    nursery.start_soon(run_validator, validator, i)

            # Process results - any reject or throttle causes overall failure
            final_result = ValidationResult.ACCEPT
            for result in results.values():
                if result == ValidationResult.REJECT:
                    return ValidationResult.REJECT
                elif result == ValidationResult.THROTTLED:
                    final_result = ValidationResult.THROTTLED
                elif (
                    result == ValidationResult.IGNORE
                    and final_result == ValidationResult.ACCEPT
                ):
                    final_result = ValidationResult.IGNORE

            return final_result

        finally:
            self._global_throttle.release()

        return ValidationResult.IGNORE

    async def _validate_single_async_validator(
        self, validator: TopicValidator, msg_forwarder: ID, msg: rpc_pb2.Message
    ) -> ValidationResult:
        """Validate with a single async validator"""
        # Apply per-topic throttling
        if validator.throttle_semaphore:
            try:
                validator.throttle_semaphore.acquire_nowait()
            except trio.WouldBlock:
                logger.debug(
                    "Per-topic validation throttled for topic %s", validator.topic
                )
                return ValidationResult.THROTTLED
        else:
            # Fallback if no throttle semaphore configured
            pass

        try:
            # Apply timeout if configured
            result: bool
            if validator.timeout:
                with trio.fail_after(validator.timeout):
                    func = cast(AsyncValidatorFn, validator.validator)
                    result = await func(msg_forwarder, msg)
            else:
                func = cast(AsyncValidatorFn, validator.validator)
                result = await func(msg_forwarder, msg)

            return ValidationResult.ACCEPT if result else ValidationResult.REJECT

        except trio.TooSlowError:
            logger.debug("Validation timeout for topic %s", validator.topic)
            return ValidationResult.IGNORE
        except Exception as e:
            logger.exception(
                "Async validator failed for topic %s: %s", validator.topic, e
            )
            return ValidationResult.REJECT
        finally:
            if validator.throttle_semaphore:
                validator.throttle_semaphore.release()

        return ValidationResult.IGNORE
