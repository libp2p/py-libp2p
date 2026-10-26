from __future__ import annotations

import argparse
from collections.abc import AsyncGenerator, Mapping
import importlib
from typing import TYPE_CHECKING, Any, cast

from .a2a_payment_service import (
    A2APaymentTaskService,
    extract_payload,
    validate_payment_authorization,
)
from .synapse_bridge import SynapseNodeBridgeBackend

A2A_HTTP_DEPS_AVAILABLE = True

if TYPE_CHECKING:

    class _ProtoField:
        def CopyFrom(self, other: Any) -> None: ...

    class _ProtoMessage:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    class _TaskState:
        TASK_STATE_UNSPECIFIED = 0

        @staticmethod
        def Name(value: object) -> str: ...

    class _GetTaskRequest:
        id: str

    class _CancelTaskRequest:
        id: str

    class _ListTasksRequest:
        status: int
        context_id: str
        include_artifacts: bool

        def HasField(self, field_name: str) -> bool: ...

    class _SendMessageRequest:
        message: Any

    class _SubscribeToTaskRequest:
        id: str

    class _TaskArtifactUpdateEvent(_ProtoMessage):
        artifact: _ProtoField
        last_chunk: bool

    class _TaskStatusUpdateEvent(_ProtoMessage):
        status: _ProtoField

    class _Starlette:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    ServerCallContext = Any
    Event = Any
    RequestHandler = object
    AgentCard = _ProtoMessage
    Artifact = _ProtoMessage
    CancelTaskRequest = _CancelTaskRequest
    DeleteTaskPushNotificationConfigRequest = _ProtoMessage
    GetExtendedAgentCardRequest = _ProtoMessage
    GetTaskPushNotificationConfigRequest = _ProtoMessage
    GetTaskRequest = _GetTaskRequest
    ListTaskPushNotificationConfigsRequest = _ProtoMessage
    ListTaskPushNotificationConfigsResponse = _ProtoMessage
    ListTasksRequest = _ListTasksRequest
    ListTasksResponse = _ProtoMessage
    Message = _ProtoMessage
    SendMessageRequest = _SendMessageRequest
    SubscribeToTaskRequest = _SubscribeToTaskRequest
    Task = _ProtoMessage
    TaskArtifactUpdateEvent = _TaskArtifactUpdateEvent
    TaskPushNotificationConfig = _ProtoMessage
    TaskState = _TaskState
    TaskStatusUpdateEvent = _TaskStatusUpdateEvent
    Starlette = _Starlette

    class InvalidParamsError(RuntimeError):
        def __init__(self, *, message: str | None = None) -> None: ...

    class PushNotificationNotSupportedError(RuntimeError):
        def __init__(self, *, message: str | None = None) -> None: ...

    class TaskNotCancelableError(RuntimeError):
        def __init__(self, *, message: str | None = None) -> None: ...

    class TaskNotFoundError(RuntimeError):
        def __init__(self, *, message: str | None = None) -> None: ...

    class UnsupportedOperationError(RuntimeError):
        def __init__(self, *, message: str | None = None) -> None: ...

    def create_agent_card_routes(*args: Any, **kwargs: Any) -> list[Any]: ...

    def create_jsonrpc_routes(*args: Any, **kwargs: Any) -> list[Any]: ...

    def MessageToDict(*args: Any, **kwargs: Any) -> dict[str, object]: ...

    def ParseDict(*args: Any, **kwargs: Any) -> Any: ...
else:
    try:
        from a2a.server.context import ServerCallContext
        from a2a.server.events import Event
        from a2a.server.request_handlers.request_handler import RequestHandler
        from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
        from a2a.types.a2a_pb2 import (
            AgentCard,
            Artifact,
            CancelTaskRequest,
            DeleteTaskPushNotificationConfigRequest,
            GetExtendedAgentCardRequest,
            GetTaskPushNotificationConfigRequest,
            GetTaskRequest,
            ListTaskPushNotificationConfigsRequest,
            ListTaskPushNotificationConfigsResponse,
            ListTasksRequest,
            ListTasksResponse,
            Message,
            SendMessageRequest,
            SubscribeToTaskRequest,
            Task,
            TaskArtifactUpdateEvent,
            TaskPushNotificationConfig,
            TaskState,
            TaskStatusUpdateEvent,
        )
        from a2a.utils.errors import (
            InvalidParamsError,
            PushNotificationNotSupportedError,
            TaskNotCancelableError,
            TaskNotFoundError,
            UnsupportedOperationError,
        )
        from google.protobuf.json_format import MessageToDict, ParseDict
        from starlette.applications import Starlette
    except ImportError:  # pragma: no cover - optional runtime dependency
        A2A_HTTP_DEPS_AVAILABLE = False
        ServerCallContext = cast(Any, object)
        Event = cast(Any, object)

        class RequestHandler:
            pass

        def create_agent_card_routes(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("A2A HTTP dependencies are not installed")

        def create_jsonrpc_routes(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("A2A HTTP dependencies are not installed")

        AgentCard = cast(Any, None)
        Artifact = cast(Any, None)
        CancelTaskRequest = cast(Any, None)
        DeleteTaskPushNotificationConfigRequest = cast(Any, None)
        GetExtendedAgentCardRequest = cast(Any, None)
        GetTaskPushNotificationConfigRequest = cast(Any, None)
        GetTaskRequest = cast(Any, None)
        ListTaskPushNotificationConfigsRequest = cast(Any, None)
        ListTaskPushNotificationConfigsResponse = cast(Any, None)
        ListTasksRequest = cast(Any, None)
        ListTasksResponse = cast(Any, None)
        Message = cast(Any, None)
        SendMessageRequest = cast(Any, None)
        SubscribeToTaskRequest = cast(Any, None)
        Task = cast(Any, None)
        TaskArtifactUpdateEvent = cast(Any, None)
        TaskPushNotificationConfig = cast(Any, None)
        TaskState = cast(Any, None)
        TaskStatusUpdateEvent = cast(Any, None)

        class _OptionalA2AError(RuntimeError):
            def __init__(self, *, message: str | None = None) -> None:
                super().__init__(message or "A2A HTTP dependencies are not installed")

        class InvalidParamsError(_OptionalA2AError):
            pass

        class PushNotificationNotSupportedError(_OptionalA2AError):
            pass

        class TaskNotCancelableError(_OptionalA2AError):
            pass

        class TaskNotFoundError(_OptionalA2AError):
            pass

        class UnsupportedOperationError(_OptionalA2AError):
            pass

        def MessageToDict(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("A2A HTTP dependencies are not installed")

        def ParseDict(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("A2A HTTP dependencies are not installed")

        Starlette = cast(Any, None)


def _require_a2a_sdk() -> None:
    if not A2A_HTTP_DEPS_AVAILABLE or AgentCard is None or Starlette is None:
        raise RuntimeError(
            "This demo requires the optional A2A HTTP dependencies. "
            "Install `a2a-sdk[http-server]` and `uvicorn` to run it."
        )


def _status_dict(task: Mapping[str, object]) -> Mapping[str, object]:
    status = task.get("status")
    if isinstance(status, Mapping):
        return status
    return {}


class A2APaymentRequestHandler(RequestHandler):
    def __init__(self, service: A2APaymentTaskService) -> None:
        self._service = service

    async def on_get_task(
        self,
        params: GetTaskRequest,
        context: ServerCallContext,
    ) -> Task | None:
        del context
        task = self._service.get_task(params.id)
        if task is None:
            return None
        return _parse_proto(task, Task)

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        del context
        state = (
            TaskState.Name(params.status)
            if params.status != TaskState.TASK_STATE_UNSPECIFIED
            else None
        )
        context_id = params.context_id or None
        tasks = self._service.list_tasks(
            context_id=context_id,
            state=state,
            include_artifacts=params.include_artifacts
            if params.HasField("include_artifacts")
            else False,
        )
        return ListTasksResponse(
            tasks=[_parse_proto(task, Task) for task in tasks],
            next_page_token="",
            page_size=len(tasks),
            total_size=len(tasks),
        )

    async def on_cancel_task(
        self,
        params: CancelTaskRequest,
        context: ServerCallContext,
    ) -> Task | None:
        del context
        try:
            task = self._service.cancel_task(params.id)
        except ValueError as exc:
            raise TaskNotCancelableError(message=str(exc)) from exc
        if task is None:
            return None
        return _parse_proto(task, Task)

    async def on_message_send(
        self,
        params: SendMessageRequest,
        context: ServerCallContext,
    ) -> Task | Message:
        del context
        message = MessageToDict(params.message, preserving_proto_field_name=False)
        try:
            task = self._service.send_message(message)
        except KeyError as exc:
            raise TaskNotFoundError from exc
        except RuntimeError as exc:
            raise UnsupportedOperationError(message=str(exc)) from exc
        except ValueError as exc:
            raise InvalidParamsError(message=str(exc)) from exc
        return _parse_proto(task, Task)

    async def on_message_send_stream(
        self,
        params: SendMessageRequest,
        context: ServerCallContext,
    ) -> AsyncGenerator[Event]:
        del context
        message = MessageToDict(params.message, preserving_proto_field_name=False)
        task_id = message.get("taskId")
        payload = extract_payload(message)

        if not isinstance(task_id, str):
            try:
                task = self._service.send_message(message)
            except ValueError as exc:
                raise InvalidParamsError(message=str(exc)) from exc
            except RuntimeError as exc:
                raise UnsupportedOperationError(message=str(exc)) from exc
            yield _parse_proto(task, Task)
            return

        current_task = self._service.get_task(task_id)
        if current_task is None:
            raise TaskNotFoundError

        if isinstance(payload, Mapping):
            payment_authorization = payload.get("paymentAuthorization")
        else:
            payment_authorization = None

        if isinstance(payment_authorization, Mapping):
            metadata = current_task.get("metadata", {})
            quote = metadata.get("quote") if isinstance(metadata, Mapping) else None
            if isinstance(quote, Mapping):
                errors = validate_payment_authorization(payment_authorization, quote)
            else:
                errors = ["quoted task metadata is missing"]

            if not errors:
                working = self._service.build_streaming_working_task(
                    task_id=task_id,
                    context_id=str(current_task["contextId"]),
                    message="Payment authorization accepted. Executing storage task.",
                )
                yield _parse_proto(working, Task)
                self._service.send_message(message)
                final_task = self._service.complete_working_task(task_id)
                if final_task is None:
                    raise TaskNotFoundError
                artifacts = final_task.get("artifacts")
                if isinstance(artifacts, list):
                    for artifact in artifacts:
                        if not isinstance(artifact, Mapping):
                            continue
                        yield _build_artifact_update(
                            task_id=task_id,
                            context_id=str(final_task["contextId"]),
                            artifact_dict=artifact,
                        )
                yield _build_status_update(
                    task_id=task_id,
                    context_id=str(final_task["contextId"]),
                    task_dict=final_task,
                )
                return

        try:
            task = self._service.send_message(message)
        except ValueError as exc:
            raise InvalidParamsError(message=str(exc)) from exc
        except RuntimeError as exc:
            raise UnsupportedOperationError(message=str(exc)) from exc
        yield _parse_proto(task, Task)

    async def on_create_task_push_notification_config(
        self,
        params: TaskPushNotificationConfig,
        context: ServerCallContext,
    ) -> TaskPushNotificationConfig:
        del params, context
        raise PushNotificationNotSupportedError

    async def on_get_task_push_notification_config(
        self,
        params: GetTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> TaskPushNotificationConfig:
        del params, context
        raise PushNotificationNotSupportedError

    async def on_subscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context: ServerCallContext,
    ) -> AsyncGenerator[Event]:
        del context
        task = self._service.get_task(params.id)
        if task is None:
            raise TaskNotFoundError
        state = str(_status_dict(task).get("state", ""))
        if state in {
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        }:
            raise UnsupportedOperationError(
                message="The task is in a terminal state and cannot be subscribed to"
            )
        yield _parse_proto(task, Task)

    async def on_list_task_push_notification_configs(
        self,
        params: ListTaskPushNotificationConfigsRequest,
        context: ServerCallContext,
    ) -> ListTaskPushNotificationConfigsResponse:
        del params, context
        raise PushNotificationNotSupportedError

    async def on_delete_task_push_notification_config(
        self,
        params: DeleteTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> None:
        del params, context
        raise PushNotificationNotSupportedError

    async def on_get_extended_agent_card(
        self,
        params: GetExtendedAgentCardRequest,
        context: ServerCallContext,
    ) -> Any:
        del params, context
        raise UnsupportedOperationError(
            message="This demo does not provide an extended agent card"
        )


def build_task_service(backend: str) -> A2APaymentTaskService:
    if backend == "simulation":
        return A2APaymentTaskService()
    if backend == "synapse":
        return A2APaymentTaskService(
            execution_backend=SynapseNodeBridgeBackend.from_env()
        )
    raise ValueError(f"Unsupported backend: {backend}")


def create_a2a_http_app(
    *,
    backend: str = "simulation",
    public_base_url: str = "http://127.0.0.1:9999",
    rpc_path: str = "/rpc",
) -> Starlette:
    _require_a2a_sdk()
    service = build_task_service(backend)
    handler = A2APaymentRequestHandler(service)
    agent_card_dict = service.build_agent_card(
        interface_url=f"{public_base_url}{rpc_path}",
        protocol_binding="JSONRPC",
        streaming=True,
    )
    agent_card = _parse_proto(agent_card_dict, AgentCard)
    routes = [
        *create_agent_card_routes(agent_card),
        *create_jsonrpc_routes(handler, rpc_path),
    ]
    return cast(Any, Starlette)(routes=routes)


def _parse_proto(payload: Mapping[str, object], proto_cls: Any) -> Any:
    return ParseDict(dict(payload), proto_cls())


def _build_artifact_update(
    *, task_id: str, context_id: str, artifact_dict: Mapping[str, object]
) -> TaskArtifactUpdateEvent:
    artifact = _parse_proto(artifact_dict, Artifact)
    event = TaskArtifactUpdateEvent(task_id=task_id, context_id=context_id)
    event.artifact.CopyFrom(artifact)
    event.last_chunk = True
    return event


def _build_status_update(
    *, task_id: str, context_id: str, task_dict: Mapping[str, object]
) -> TaskStatusUpdateEvent:
    task = _parse_proto(task_dict, Task)
    event = TaskStatusUpdateEvent(task_id=task_id, context_id=context_id)
    event.status.CopyFrom(task.status)
    return event


def main() -> None:
    _require_a2a_sdk()
    parser = argparse.ArgumentParser(
        description=(
            "Runs the A2A HTTP/JSON-RPC + SSE facade for the Filecoin payment demo. "
            "Use --backend synapse for real Synapse-backed execution."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9999, type=int)
    parser.add_argument(
        "--backend",
        choices=("simulation", "synapse"),
        default="simulation",
        help="execution backend for storage tasks",
    )
    parser.add_argument(
        "--public-base-url",
        default=None,
        help="base URL to advertise in the Agent Card",
    )
    parser.add_argument(
        "--rpc-path",
        default="/rpc",
        help="JSON-RPC endpoint path exposed by the A2A server",
    )
    args = parser.parse_args()

    public_base_url = args.public_base_url or f"http://{args.host}:{args.port}"
    app = create_a2a_http_app(
        backend=args.backend,
        public_base_url=public_base_url,
        rpc_path=args.rpc_path,
    )

    try:
        uvicorn = importlib.import_module("uvicorn")
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SystemExit("Install `uvicorn` to run the HTTP A2A demo server.") from exc

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
