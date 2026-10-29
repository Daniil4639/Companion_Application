from copy import deepcopy
from .models import RegisteredTool, RuntimeFailure


class ToolRegistry:
    """Loop-local catalog; refresh replaces a server's snapshot atomically."""

    def __init__(self):
        self._tools = {}

    def replace(self, server_id, tools):
        replacement = {}

        for tool in tools:
            key = f"{server_id}.{tool.name}"

            if key in replacement:
                raise RuntimeFailure("protocol_error", "Server returned duplicate tool names")

            replacement[key] = RegisteredTool(id=key, server_id=server_id, name=tool.name,
                                              description=tool.description, input_schema=deepcopy(tool.input_schema),
                                              output_schema=deepcopy(tool.output_schema),
                                              annotations=tool.annotations.model_dump(mode="json",
                                                                                      by_alias=True) if tool.annotations else None)

        self._tools = {**{k: v for k, v in self._tools.items() if v.server_id != server_id}, **replacement}

    def remove(self, server_id):
        self._tools = {k: v for k, v in self._tools.items() if v.server_id != server_id}

    def unavailable(self, server_id):
        for tool in self._tools.values():
            if tool.server_id == server_id:
                tool.available = False

    def get(self, tool_id):
        tool = self._tools.get(tool_id)
        return tool.model_copy(deep=True) if tool else None

    def list(self, server_id=None):
        return [t.model_copy(deep=True)
                for t in self._tools.values()
                if server_id is None
                or t.server_id == server_id
                ]