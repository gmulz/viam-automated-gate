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
    position_sensor: Sensor
    board: Board
    open_position_stop_min: float
    open_position_stop_max: float
    close_position_stop_min: float
    close_position_stop_max: float
    position_reading_key: str

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
    motor_power_open: float = 1.0
    motor_power_close: float = 1.0


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
        cls._lock = asyncio.Lock()
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
        if "position-sensor" not in config.attributes.fields:
            raise Exception("Config must include an 'open-sensor' attribute (object)")

        sensor_names = []
        
        sensor_config = struct_to_dict(config.attributes.fields["position-sensor"].struct_value)

        if "name" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a non-empty 'name' field")
        if "open_min" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a numeric 'open_min' field")
        if "open_max" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a numeric 'open_max' field")
        if "close_min" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a numeric 'close_min' field")
        if "close_max" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a numeric 'close_max' field")
        if "reading_key" not in sensor_config:
            raise Exception(f"'{sensor_config_key}' must have a non-empty 'reading_key' field")

        if sensor_config["open_min"] > sensor_config["open_max"]:
            raise Exception(f"'{sensor_config_key}' 'open_min' cannot be greater than 'open_max'")
        if sensor_config["close_min"] > sensor_config["close_max"]:
            raise Exception(f"'{sensor_config_key}' 'close_min' cannot be greater than 'close_max'")

        
        
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

        return [motor_name, position_sensor_name, board_name]

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
        position_sensor_config = struct_to_dict(config.attributes.fields["position-sensor"].struct_value)
        
        self.motor = dependencies[Motor.get_resource_name(motor_name)]
        self.board = dependencies[Board.get_resource_name(board_name)]
        self.position_sensor = dependencies[Sensor.get_resource_name(position_sensor_name)]

        self.open_position_stop_min = float(position_sensor_config["open_min"])
        self.open_position_stop_max = float(position_sensor_config["open_max"])
        self.close_position_stop_min = float(position_sensor_config["close_min"])
        self.close_position_stop_max = float(position_sensor_config["close_max"])
        self.position_reading_key = position_sensor_config["reading_key"]

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
            self.motor_power_open = self.motor_power
            self.motor_power_close = self.motor_power

        if "motor-power-open" in config.attributes.fields:
            self.motor_power_open = float(config.attributes.fields["motor-power-open"].number_value)
        if "motor-power-close" in config.attributes.fields:
            self.motor_power_close = float(config.attributes.fields["motor-power-close"].number_value)

        if self.motor is None or self.open_sensor is None or self.close_sensor is None or self.board is None:
            raise Exception("Missing required dependencies. Check config and ensure components are running.")

        self._stop_poll_event.clear()
        self.trigger_poll_task = asyncio.create_task(self._poll_triggers())
        return super().reconfigure(config, dependencies)
    
    async def stop_gate(self):
        LOGGER.info("Stopping gate")
        await self.motor.set_power(0.0)

    async def open_gate(self):
        LOGGER.info("Opening gate")
        await self.motor.set_power(-self.motor_power_open)
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= self.open_to_close_timeout * 1.5:
                    LOGGER.info(f"Open gate timed out after {self.open_to_close_timeout * 1.5} seconds")
                    break

                # Get sensor readings from position_sensor
                position = await self.get_position()
                LOGGER.debug(f"Position Sensor reading ({self.position_reading_key}): {position}")

                # Check if reading is within the open_sensor stop range
                if position is None or self.open_position_stop_min <= position <= self.open_position_stop_max:
                    LOGGER.info(f"Position Sensor reading {position} within stop range [{self.open_position_stop_min}, {self.open_position_stop_max}], stopping motor.")
                    break # Exit the loop

                # Wait for 0.1 seconds
                await asyncio.sleep(0.1)
        except Exception as e:
            LOGGER.error(f"Error opening gate: {e}")
        finally:
            # Ensure motor stops regardless of how the loop exits
            LOGGER.info("Stopping motor after open attempt.")
            await self.stop_gate()

    async def close_gate(self):
        gate_state = await self.locate()
        if gate_state == "closed":
            LOGGER.info("Gate is already closed")
            return
        
        LOGGER.info("Closing gate")
        await self.motor.set_power(self.motor_power_close) # Positive power for closing
        start_time = asyncio.get_event_loop().time()
        try:
            while True:
                # Check elapsed time
                if asyncio.get_event_loop().time() - start_time >= self.open_to_close_timeout:
                    LOGGER.info(f"Close gate timed out after {self.open_to_close_timeout} seconds")
                    break

                # Get sensor readings from position_sensor
                position = await self.get_position()
                LOGGER.debug(f"Position Sensor reading ({self.position_reading_key}): {position}")

                # Check if reading is within the close_sensor stop range
                if position is None or self.close_position_stop_min <= position <= self.close_position_stop_max:
                    LOGGER.info(f"Position Sensor reading {position} within stop range [{self.close_position_stop_min}, {self.close_position_stop_max}], stopping motor.")
                    break # Exit the loop

                # Wait for 0.5 seconds
                await asyncio.sleep(0.1)
        except Exception as e:
            LOGGER.error(f"Error closing gate: {e}")
        finally:
            # Ensure motor stops regardless of how the loop exits
            LOGGER.info("Stopping motor after close attempt.")
            await self.stop_gate()

    async def locate(self):
        LOGGER.info("Locating gate")
        position = await self.get_position()
        if position is not None and self.open_position_stop_min <= position <= self.open_position_stop_max:
            LOGGER.info("Position sensor indicates gate is open")
            return "open"
        if position is not None and self.close_position_stop_min <= position <= self.close_position_stop_max:
            LOGGER.info("Position sensor indicates gate is closed")
            return "closed"
        # unknown gate state, at neither close nor open
        return "unknown"

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

    # shut down the service. 
    # not the action to close the gate.
    async def close(self):
        self._stop_trigger_poll_task()
        if self.motor:
            await self.motor.set_power(0.0)

    async def get_position(self):
        readings = await self.position_sensor.get_readings()
        reading_value = readings.get(self.position_reading_key)
        return reading_value
    

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        LOGGER.info(f"do_command called with command: {command}")
        # read position and status not guarded by lock
        if command.get("position"):
                return {"status": "position", "position": await self.get_position()}
        elif command.get("status"):
            return {"status": await self.locate()}
        elif command.get("stop"):
            await self.stop_gate()
            return {"status": "stopped"}
        # actuation commands guarded by lock
        if self._lock.locked():
            return {"status": "busy"}
        async with self._lock:
            if command.get("open"):
                await self.open_gate()
                return {"status": await self.locate()}
            elif command.get("close"):
                await self.close_gate()
                return {"status": await self.locate()}
        raise Exception("Invalid command")

