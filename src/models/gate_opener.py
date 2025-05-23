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
from google.protobuf.struct_pb2 import Struct

from viam import logging
from viam.utils import struct_to_dict

LOGGER = logging.getLogger(__name__)

class GateOpener(Generic, EasyResource):
    # To enable debug-level logging, either run viam-server with the --debug option,
    # or configure your resource/machine to display debug logs.
    MODEL: ClassVar[Model] = Model(
        ModelFamily("grant-dev", "automated-gate"), "gate-opener"
    )

    motor: Motor
    open_sensor: Sensor
    close_sensor: Sensor
    board: Board
    open_sensor_stop_min: float
    open_sensor_stop_max: float
    close_sensor_stop_min: float
    close_sensor_stop_max: float
    open_sensor_reading_key: str
    close_sensor_reading_key: str

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
        if "board" not in config.attributes.fields:
            raise Exception("Config must include a 'board' attribute")
        if "motor" not in config.attributes.fields:
            raise Exception("Config must include a 'motor' attribute")
        if "open-sensor" not in config.attributes.fields:
            raise Exception("Config must include an 'open-sensor' attribute (object)")
        if "close-sensor" not in config.attributes.fields:
            raise Exception("Config must include a 'close-sensor' attribute (object)")

        sensor_names = []
        for sensor_config_key in ["open-sensor", "close-sensor"]:
            sensor_config = struct_to_dict(config.attributes.fields[sensor_config_key].struct_value)

            if "name" not in sensor_config:
                raise Exception(f"'{sensor_config_key}' must have a non-empty 'name' field")
            if "stop_min" not in sensor_config:
                raise Exception(f"'{sensor_config_key}' must have a numeric 'stop_min' field")
            if "stop_max" not in sensor_config:
                raise Exception(f"'{sensor_config_key}' must have a numeric 'stop_max' field")
            if "reading_key" not in sensor_config:
                raise Exception(f"'{sensor_config_key}' must have a non-empty 'reading_key' field")
            if sensor_config["stop_min"] > sensor_config["stop_max"]:
                raise Exception(f"'{sensor_config_key}' 'stop_min' cannot be greater than 'stop_max'")

            sensor_names.append(sensor_config["name"])

        motor_name = config.attributes.fields["motor"].string_value
        board_name = config.attributes.fields["board"].string_value

        return [motor_name] + sensor_names + [board_name]

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        """This method allows you to dynamically update your service when it receives a new `config` object.

        Args:
            config (ComponentConfig): The new configuration
            dependencies (Mapping[ResourceName, ResourceBase]): Any dependencies (both implicit and explicit)
        """
        motor_name = config.attributes.fields["motor"].string_value
        board_name = config.attributes.fields["board"].string_value
        open_sensor_config = struct_to_dict(config.attributes.fields["open-sensor"].struct_value)
        close_sensor_config = struct_to_dict(config.attributes.fields["close-sensor"].struct_value)
        open_sensor_name = open_sensor_config["name"]
        close_sensor_name = close_sensor_config["name"]

        self.motor = dependencies[Motor.get_resource_name(motor_name)]
        self.board = dependencies[Board.get_resource_name(board_name)]
        self.open_sensor = dependencies[Sensor.get_resource_name(open_sensor_name)]
        self.close_sensor = dependencies[Sensor.get_resource_name(close_sensor_name)]

        self.open_sensor_stop_min = float(open_sensor_config["stop_min"])
        self.open_sensor_stop_max = float(open_sensor_config["stop_max"])
        self.close_sensor_stop_min = float(close_sensor_config["stop_min"])
        self.close_sensor_stop_max = float(close_sensor_config["stop_max"])
        self.open_sensor_reading_key = open_sensor_config["reading_key"]
        self.close_sensor_reading_key = close_sensor_config["reading_key"]

        if self.motor is None or self.open_sensor is None or self.close_sensor is None or self.board is None:
            raise Exception("Missing required dependencies. Check config and ensure components are running.")

        return super().reconfigure(config, dependencies)

    async def open_gate(self):
        LOGGER.info("Opening gate")
        await self.motor.set_power(-1.0)
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= 30.0:
                    LOGGER.info("Open gate timed out after 30 seconds")
                    break

                # Get sensor readings from open_sensor
                readings = await self.open_sensor.get_readings()
                # Assuming the sensor returns a 'distance' key, adjust if necessary
                reading_value = readings.get(self.open_sensor_reading_key)
                LOGGER.debug(f"Open Sensor reading ({self.open_sensor_reading_key}): {reading_value}")

                # Check if reading is within the open_sensor stop range
                if reading_value is None or self.open_sensor_stop_min <= reading_value <= self.open_sensor_stop_max:
                    LOGGER.info(f"Open Sensor reading {reading_value} within stop range [{self.open_sensor_stop_min}, {self.open_sensor_stop_max}], stopping motor.")
                    break # Exit the loop

                # Wait for 0.5 seconds
                await asyncio.sleep(0.1)
        finally:
            # Ensure motor stops regardless of how the loop exits
            LOGGER.info("Stopping motor after open attempt.")
            await self.motor.set_power(0.0)

    async def close_gate(self):
        LOGGER.info("Closing gate")
        await self.motor.set_power(1.0) # Positive power for closing
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= 30.0:
                    LOGGER.info("Close gate timed out after 30 seconds")
                    break

                # Get sensor readings from close_sensor
                readings = await self.close_sensor.get_readings()
                # Assuming the sensor returns a 'distance' key, adjust if necessary
                reading_value = readings.get(self.close_sensor_reading_key)
                LOGGER.debug(f"Close Sensor reading ({self.close_sensor_reading_key}): {reading_value}")

                # Check if reading is within the close_sensor stop range
                if reading_value is None or self.close_sensor_stop_min <= reading_value <= self.close_sensor_stop_max:
                    LOGGER.info(f"Close Sensor reading {reading_value} within stop range [{self.close_sensor_stop_min}, {self.close_sensor_stop_max}], stopping motor.")
                    break # Exit the loop

                # Wait for 0.5 seconds
                await asyncio.sleep(0.1)
        finally:
            # Ensure motor stops regardless of how the loop exits
            LOGGER.info("Stopping motor after close attempt.")
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

