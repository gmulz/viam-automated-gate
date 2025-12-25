from typing import ClassVar, Mapping, Optional, Sequence, Tuple
import asyncio

from typing_extensions import Self
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.generic import *
from viam.utils import ValueTypes
from viam import logging

from .gate_opener import GateOpener

LOGGER = logging.getLogger(__name__)

class GateMaster(Generic, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("grant-dev", "automated-gate"), "gate-master"
    )

    # primary_gate closes first and opens last
    primary_gate_opener: GateOpener
    # secondary_gate opens first and closes last
    secondary_gate_opener: GateOpener
    # background task reference to prevent garbage collection
    _background_task: Optional[asyncio.Task] = None

    @classmethod
    def new (
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        service = cls(config.name)
        service.reconfigure(config, dependencies)
        return service
    
    @classmethod
    def validate_config(cls, config: ComponentConfig) -> Tuple[Sequence[str], Sequence[str]]:
        if "primary-gate-opener" not in config.attributes.fields:
            raise Exception("Config must include a 'primary-gate-opener' attribute")
        if "secondary-gate-opener" not in config.attributes.fields:
            raise Exception("Config must include a 'secondary-gate-opener' attribute")
        
        primary_gate_opener_name = config.attributes.fields["primary-gate-opener"].string_value
        secondary_gate_opener_name = config.attributes.fields["secondary-gate-opener"].string_value
        
        return [primary_gate_opener_name, secondary_gate_opener_name], []
    
    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        primary_gate_opener_name = config.attributes.fields["primary-gate-opener"].string_value
        secondary_gate_opener_name = config.attributes.fields["secondary-gate-opener"].string_value
        
        self.primary_gate_opener = dependencies[GateOpener.get_resource_name(primary_gate_opener_name)]
        self.secondary_gate_opener = dependencies[GateOpener.get_resource_name(secondary_gate_opener_name)]
    
    async def open_gates(self):
        secondary_gate_open = self.secondary_gate_opener.do_command({"open": True})
        secondary_open_task = asyncio.create_task(secondary_gate_open)
        # poll second gate opener status until it's no longer closed
        max_attempts = 100
        attempts = 0
        while attempts < max_attempts:
            secondary_status = await self.secondary_gate_opener.do_command({"status": True})
            if secondary_status["status"] != "closed":
                break
            attempts += 1
            await asyncio.sleep(0.1)
        if attempts == max_attempts:
            raise Exception("Secondary gate failed to open")
        
        # Start primary gate and wait for both commands to fully complete
        primary_result, secondary_result = await asyncio.gather(
            self.primary_gate_opener.do_command({"open": True}),
            secondary_open_task
        )
        return {"primary": primary_result, "secondary": secondary_result}

    async def close_gates(self):
        primary_status = await self.primary_gate_opener.do_command({"close": True})
        # confirm primary gate has closed
        if primary_status["status"] != "closed":
            raise Exception("Primary gate failed to close")

        await self.secondary_gate_opener.do_command({"close": True})
        return await self.secondary_gate_opener.do_command({"status": True})
    
    async def stop_gates(self):
        primary_task = self.primary_gate_opener.do_command({"stop": True})
        secondary_task = self.secondary_gate_opener.do_command({"stop": True})
        await asyncio.gather(primary_task, secondary_task)
        return {"status": "stopped"}
        
    
    def _run_in_background(self, coro):
        """Run a coroutine in the background, storing the task reference."""
        # Cancel any existing background task
        if self._background_task is not None and not self._background_task.done():
            self._background_task.cancel()
        self._background_task = asyncio.create_task(coro)
        # Add a callback to log any exceptions
        def handle_exception(task):
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                LOGGER.error(f"Background task failed: {exc}")
        self._background_task.add_done_callback(handle_exception)

    async def do_command(
        self, 
        command: Mapping[str, ValueTypes], 
        *, timeout: Optional[float] = None, 
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        LOGGER.info(f"do_command called with command: {command}")
        if command.get("open"):
            self._run_in_background(self.open_gates())
            return {"status": "opening"}
        elif command.get("close"):
            self._run_in_background(self.close_gates())
            return {"status": "closing"}
        elif command.get("stop"):
            return await self.stop_gates()
        elif command.get("position"):
            return {"primary_position": await self.primary_gate_opener.do_command({"position": True}), "secondary_position": await self.secondary_gate_opener.do_command({"position": True})}
        elif command.get("status"):
            return {"primary_status": await self.primary_gate_opener.do_command({"status": True}), "secondary_status": await self.secondary_gate_opener.do_command({"status": True})}
        else:
            raise Exception("Invalid command")

    