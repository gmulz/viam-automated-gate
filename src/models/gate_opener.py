from typing import ClassVar, Final, Mapping, Optional, Sequence
import asyncio

from typing_extensions import Self
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.generic import *
from viam.utils import ValueTypes
from viam.components.motor import Motor
from viam.components.sensor import Sensor
from viam.components.board import Board

from viam import logging

LOGGER = logging.getLogger(__name__)

class GateOpener(Generic, EasyResource):
    # To enable debug-level logging, either run viam-server with the --debug option,
    # or configure your resource/machine to display debug logs.
    MODEL: ClassVar[Model] = Model(
        ModelFamily("grant-dev", "automated-gate"), "gate-opener"
    )

    motor: Motor
    sensor: Sensor
    board: Board

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        """This method creates a new instance of this Generic service.
        The default implementation sets the name from the `config` parameter and then calls `reconfigure`.

        Args:
            config (ComponentConfig): The configuration for this resource
            dependencies (Mapping[ResourceName, ResourceBase]): The dependencies (both implicit and explicit)

        Returns:
            Self: The resource
        """
        return super().new(config, dependencies)

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> Sequence[str]:
        """This method allows you to validate the configuration object received from the machine,
        as well as to return any implicit dependencies based on that `config`.

        Args:
            config (ComponentConfig): The configuration for this resource

        Returns:
            Sequence[str]: A list of implicit dependencies
        """
        return []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        """This method allows you to dynamically update your service when it receives a new `config` object.

        Args:
            config (ComponentConfig): The new configuration
            dependencies (Mapping[ResourceName, ResourceBase]): Any dependencies (both implicit and explicit)
        """
        for dep in dependencies:
            if dep.SUBTYPE == Motor.SUBTYPE:
                self.motor = dep
            if dep.SUBTYPE == Sensor.SUBTYPE:
                self.sensor = dep
            if dep.SUBTYPE == Board.SUBTYPE:
                self.board = dep
        if self.motor is None or self.sensor is None or self.board is None:
            raise Exception("Missing required dependencies, must have a motor, sensor and board")

        return super().reconfigure(config, dependencies)

    async def open_gate(self):
        LOGGER.info("Opening gate")
        await self.motor.set_power(1.0)
        await asyncio.sleep(30)
        await self.motor.set_power(0.0)

    async def close_gate(self):
        LOGGER.info("Closing gate")
        await self.motor.set_power(-1.0)
        await asyncio.sleep(30)
        await self.motor.set_power(0.0)

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        LOGGER.info(f"do_command called with command: {command}")
        if command.get("open"):
            await self.open_gate()
        elif command.get("close"):
            await self.close_gate()
        else:
            raise Exception("Invalid command")

