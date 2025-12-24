from typing import ClassVar, Mapping, Optional, Sequence
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

    @classmethod
    def new (
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        return super().new(config, dependencies)
    
    @classmethod
    def validate_config(cls, config: ComponentConfig) -> Sequence[str]:
        if "primary-gate-opener" not in config.attributes.fields:
            raise Exception("Config must include a 'primary-gate-opener' attribute")
        if "secondary-gate-opener" not in config.attributes.fields:
            raise Exception("Config must include a 'secondary-gate-opener' attribute")
        
        primary_gate_opener_name = config.attributes.fields["primary-gate-opener"].string_value
        secondary_gate_opener_name = config.attributes.fields["secondary-gate-opener"].string_value
        
        return [primary_gate_opener_name, secondary_gate_opener_name]
    
    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        primary_gate_opener_name = config.attributes.fields["primary-gate-opener"].string_value
        secondary_gate_opener_name = config.attributes.fields["secondary-gate-opener"].string_value
        
        self.primary_gate_opener = dependencies[GateOpener.get_resource_name(primary_gate_opener_name)]
        self.secondary_gate_opener = dependencies[GateOpener.get_resource_name(secondary_gate_opener_name)]
        
        return super().reconfigure(config, dependencies)
    
    async def do_command(
        self, 
        command: Mapping[str, ValueTypes], 
        *, timeout: Optional[float] = None, 
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        LOGGER.info(f"do_command called with command: {command}")
        if command.get("open"):
            await self.secondary_gate_opener.do_command({"open": True})
            # wait 5 seconds
            await asyncio.sleep(5)
            await self.primary_gate_opener.do_command({"open": True})
            return await self.primary_gate_opener.do_command({"status": True})
        elif command.get("close"):
            await self.primary_gate_opener.do_command({"close": True})
            # confirm primary gate has closed
            await self.primary_gate_opener.do_command({"status": True})
            if await self.primary_gate_opener.do_command({"status": True}) != "closed":
                raise Exception("Primary gate failed to close")
            await self.secondary_gate_opener.do_command({"close": True})
            return await self.secondary_gate_opener.do_command({"status": True})
        elif command.get("stop"):
            await self.primary_gate_opener.do_command({"stop": True})
            await self.secondary_gate_opener.do_command({"stop": True})
            return {"status": "stopped"}
        else:
            raise Exception("Invalid command")

    