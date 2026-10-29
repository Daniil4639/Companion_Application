import json
from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from jsonschema.exceptions import ValidationError, SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable
from .models import ExecutionResult, RuntimeFailure


def no_remote_schema(uri):
    # Untrusted schemas cannot trigger HTTP/file access via $ref.
    raise NoSuchResource(ref=uri)


class ToolExecutor:
    def __init__(self, manager, authorize=None):
        self.manager = manager
        self.registry = manager.registry
        # Optional async policy(tool, arguments) -> bool; annotations never authorize a call.
        self.authorize = authorize

    async def execute(self, tool_id, arguments):
        tool = self.registry.get(tool_id)

        if tool is None:
            return ExecutionResult(tool_id=tool_id, status="unknown_tool",
                                   error={"code": "unknown_tool",
                                          "message": "Tool is not in the catalog; refresh_tools first"})

        if not tool.available:
            return ExecutionResult(tool_id=tool_id, status="unavailable",
                                   error={"code": "unavailable", "message": "Tool server is disconnected"})

        try:
            # Copy before queueing; no caller can mutate arguments after validation.
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            arguments = json.loads(json.dumps(arguments, allow_nan=False))

        except (TypeError, ValueError, RecursionError):
            return ExecutionResult(tool_id=tool_id, status="invalid_arguments",
                                   error={"code": "invalid_arguments", "message": "Arguments must be a JSON object"})

        try:
            validator_cls = validator_for(tool.input_schema)
            validator_cls.check_schema(tool.input_schema)
            validator = validator_cls(tool.input_schema, format_checker=FormatChecker(),
                                      registry=Registry(retrieve=no_remote_schema))
            validator.validate(arguments)

        except ValidationError as exc:
            return ExecutionResult(tool_id=tool_id, status="invalid_arguments", error={
                "code": "invalid_arguments", "message": "Arguments do not match the tool schema",
                "path": list(exc.absolute_path), "validator": exc.validator})

        except (SchemaError, Unresolvable, RecursionError, TypeError, ValueError):
            return ExecutionResult(tool_id=tool_id, status="protocol_error",
                                   error={"code": "invalid_schema",
                                          "message": "Tool schema is invalid or has unsupported references"})

        if self.authorize is not None and not await self.authorize(tool, arguments):
            return ExecutionResult(tool_id=tool_id, status="permission_denied",
                                   error={"code": "permission_denied", "message": "Tool call denied by policy"})

        try:
            result = await self.manager.call_tool(tool.server_id, tool.name, arguments)
            return ExecutionResult(tool_id=tool_id, status="tool_error" if result.is_error else "success",
                                   result=result.model_dump(mode="json", by_alias=True))

        except RuntimeFailure as exc:
            return ExecutionResult(tool_id=tool_id, status=exc.kind, error=exc.details())