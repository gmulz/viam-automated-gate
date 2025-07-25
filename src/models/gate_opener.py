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

    open_trigger: Optional[Sensor] = None
    open_trigger_key: Optional[str] = None
    open_trigger_value: Optional[str] = None

    
    close_trigger: Optional[Sensor] = None
    close_trigger_key: Optional[str] = None
    close_trigger_value: Optional[str] = None

    trigger_poll_task: Optional[asyncio.Task] = None
    _stop_poll_event: asyncio.Event = asyncio.Event()

    open_to_close_timeout: float = 30.0

    motor_power: float = 1.0


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
        
        for trigger_key in ["open-trigger", "close_trigger"]:
            if trigger_key not in config.attributes.fields:
                continue
            trigger_config = struct_to_dict(config.attributes.fields[trigger_key].struct_value)
            if "name" not in trigger_config:
                raise Exception(f"'{trigger_key}' must have a non-empty 'name' field")
            if "value" not in trigger_config:
                raise Exception(f"'{trigger_key}' must have a non-empty 'value' field")
            if "key" not in trigger_config:
                raise Exception(f"'{trigger_key}' must have a non-empty 'key' field")
            sensor_names.append(trigger_config["name"])


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
        if self.trigger_poll_task is not None:
            self._stop_trigger_poll_task()

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

        self.open_trigger = None
        self.close_trigger = None
        if "open-trigger" in config.attributes.fields:
            open_trigger_config = struct_to_dict(config.attributes.fields["open-trigger"].struct_value)
            open_trigger_name = open_trigger_config["name"]
            self.open_trigger = dependencies[Sensor.get_resource_name(open_trigger_name)]
            self.open_trigger_key = open_trigger_config["key"]
            self.open_trigger_value = open_trigger_config["value"]
        if "close-trigger" in config.attributes.fields:
            close_trigger_config = struct_to_dict(config.attributes.fields["close-trigger"].struct_value)
            close_trigger_name = close_trigger_config["name"]
            self.close_trigger = dependencies[Sensor.get_resource_name(close_trigger_name)]
            self.close_trigger_key = close_trigger_config["key"]
            self.close_trigger_value = close_trigger_config["value"]
        
        if "open-to-close-timeout" in config.attributes.fields:
            self.open_to_close_timeout = float(config.attributes.fields["open-to-close-timeout"].number_value)
        
        if "motor-power" in config.attributes.fields:
            self.motor_power = float(config.attributes.fields["motor-power"].number_value)

        if self.motor is None or self.open_sensor is None or self.close_sensor is None or self.board is None:
            raise Exception("Missing required dependencies. Check config and ensure components are running.")

        self._stop_poll_event.clear()
        self.trigger_poll_task = asyncio.create_task(self._poll_triggers())
        return super().reconfigure(config, dependencies)

    async def open_gate(self):
        LOGGER.info("Opening gate")
        await self.motor.set_power(-self.motor_power)
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= self.open_to_close_timeout * 1.5:
                    LOGGER.info(f"Open gate timed out after {self.open_to_close_timeout * 1.5} seconds")
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

                # Wait for 0.1 seconds
                await asyncio.sleep(0.1)
        finally:
            # Ensure motor stops regardless of how the loop exits
            LOGGER.info("Stopping motor after open attempt.")
            await self.motor.set_power(0.0)

    async def close_gate(self):
        # locate will home the gate to open if it is not at a known position
        gate_state = await self.locate()
        if gate_state == "closed":
            LOGGER.info("Gate is already closed")
            return
        
        LOGGER.info("Closing gate")
        await self.motor.set_power(self.motor_power) # Positive power for closing
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= self.open_to_close_timeout:
                    LOGGER.info(f"Close gate timed out after {self.open_to_close_timeout} seconds")
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

    async def home(self):
        LOGGER.info("Homing gate to open position")
        await self.open_gate()

    async def locate(self):
        LOGGER.info("Locating gate")
        open_readings = await self.open_sensor.get_readings()
        open_reading_value = open_readings.get(self.open_sensor_reading_key)
        if open_reading_value is not None and self.open_sensor_stop_min <= open_reading_value <= self.open_sensor_stop_max:
            LOGGER.info("Open sensor indicates gate is open")
            return "open"
        close_readings = await self.close_sensor.get_readings()
        close_reading_value = close_readings.get(self.close_sensor_reading_key)
        if close_reading_value is not None and self.close_sensor_stop_min <= close_reading_value <= self.close_sensor_stop_max:
            LOGGER.info("Close sensor indicates gate is closed")
            return "closed"
        # unknown gate state, at neither close nor open
        # home the gate to the open position
        await self.home()
        return "open"

    def _stop_trigger_poll_task(self):
        self._stop_poll_event.set()
        if self.trigger_poll_task:
            self.trigger_poll_task.cancel()
            self.trigger_poll_task = None

    async def _poll_triggers(self):
        try:
            while not self._stop_poll_event.is_set():
                if self.open_trigger is not None:
                    readings = await self.open_trigger.get_readings()
                    if readings.get(self.open_trigger_key) == self.open_trigger_value:
                        LOGGER.info("Open trigger activated")
                        await self.open_gate()

                if self.close_trigger is not None:
                    readings = await self.close_trigger.get_readings()
                    if str(readings.get(self.close_trigger_key)) == self.close_trigger_value:
                        LOGGER.info("Close trigger activated")
                        await self.close_gate()
                
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            LOGGER.error(f"Error polling triggers: {e}")

    async def close(self):
        self._stop_trigger_poll_task()
        if self.motor:
            await self.motor.set_power(0.0)
    
    async def stop(self):
        if self.motor:
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
            return {"status": "opened"}
        elif command.get("close"):
            await self.close_gate()
            return {"status": "closed"}
        elif command.get("stop"):
            await self.stop()
            return {"status": "stopped"}
        else:
            raise Exception("Invalid command")

