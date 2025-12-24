# Model grant-dev:automated-gate:gate-opener

The `gate-opener` model is a generic service that controls a motorized gate or door. It monitors a position sensor to determine when the gate has reached its open or closed position, and automatically stops the motor. The model also supports optional trigger sensors that can automatically initiate open or close operations.

## How It Works

1. **Opening**: The motor runs in the negative direction until the position sensor reading falls within the configured open position range.
2. **Closing**: The motor runs in the positive direction until the position sensor reading falls within the configured close position range.
3. **Triggers**: If configured, the service continuously polls trigger sensors and automatically opens or closes the gate when the trigger conditions are met.
4. **Safety**: The motor automatically stops after a configurable timeout to prevent damage if the position sensor fails.

## Configuration

The following attribute template can be used to configure this model:

```json
{
  "board": "<string>",
  "motor": "<string>",
  "position-sensor": {
    "name": "<string>",
    "reading_key": "<string>",
    "open_min": <float>,
    "open_max": <float>,
    "close_min": <float>,
    "close_max": <float>
  },
  "open-trigger": {
    "name": "<string>",
    "key": "<string>",
    "value": "<string>"
  },
  "close-trigger": {
    "name": "<string>",
    "key": "<string>",
    "value": "<string>"
  },
  "open-to-close-timeout": <float>,
  "motor-power": <float>,
  "motor-power-open": <float>,
  "motor-power-close": <float>
}
```

### Attributes

| Name                    | Type   | Inclusion    | Description                                                                                                                                   |
| ----------------------- | ------ | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `board`                 | string | **Required** | The name of the board component used by the gate system.                                                                                      |
| `motor`                 | string | **Required** | The name of the motor component that drives the gate.                                                                                         |
| `position-sensor`       | object | **Required** | Configuration for the position sensor used to detect gate position. See [Position Sensor Configuration](#position-sensor-configuration).      |
| `open-trigger`          | object | Optional     | Configuration for a sensor that triggers the gate to open. See [Trigger Configuration](#trigger-configuration).                               |
| `close-trigger`         | object | Optional     | Configuration for a sensor that triggers the gate to close. See [Trigger Configuration](#trigger-configuration).                              |
| `open-to-close-timeout` | float  | Optional     | Maximum time in seconds for the gate to complete a close operation before the motor is stopped. Opening uses 1.5× this value. Default: `30.0` |
| `motor-power`           | float  | Optional     | Motor power level (0.0 to 1.0) applied to both open and close operations. Default: `1.0`                                                      |
| `motor-power-open`      | float  | Optional     | Motor power level for opening. Overrides `motor-power` for open operations. Default: value of `motor-power`                                   |
| `motor-power-close`     | float  | Optional     | Motor power level for closing. Overrides `motor-power` for close operations. Default: value of `motor-power`                                  |

### Position Sensor Configuration

The `position-sensor` object configures how the service reads gate position:

| Name          | Type   | Inclusion    | Description                                                       |
| ------------- | ------ | ------------ | ----------------------------------------------------------------- |
| `name`        | string | **Required** | The name of the sensor component that provides position readings. |
| `reading_key` | string | **Required** | The key in the sensor's readings to use for position value.       |
| `open_min`    | float  | **Required** | Minimum position value that indicates the gate is fully open.     |
| `open_max`    | float  | **Required** | Maximum position value that indicates the gate is fully open.     |
| `close_min`   | float  | **Required** | Minimum position value that indicates the gate is fully closed.   |
| `close_max`   | float  | **Required** | Maximum position value that indicates the gate is fully closed.   |

**Note**: `open_min` must be less than or equal to `open_max`, and `close_min` must be less than or equal to `close_max`.

### Trigger Configuration

The `open-trigger` and `close-trigger` objects configure automatic gate operation based on sensor readings:

| Name    | Type   | Inclusion    | Description                                                      |
| ------- | ------ | ------------ | ---------------------------------------------------------------- |
| `name`  | string | **Required** | The name of the sensor component to poll for trigger events.     |
| `key`   | string | **Required** | The key in the sensor's readings to check for the trigger value. |
| `value` | string | **Required** | The value that triggers the open/close operation when matched.   |

## Example Configuration

```json
{
  "board": "pi",
  "motor": "gate-motor",
  "position-sensor": {
    "name": "gate-position-sensor",
    "reading_key": "position",
    "open_min": 0,
    "open_max": 50,
    "close_min": 950,
    "close_max": 1023
  },
  "open-trigger": {
    "name": "rfid-reader",
    "key": "tag_id",
    "value": "ABC123"
  },
  "close-trigger": {
    "name": "timer-sensor",
    "key": "expired",
    "value": "true"
  },
  "open-to-close-timeout": 45,
  "motor-power-open": 0.8,
  "motor-power-close": 0.6
}
```

## DoCommand

The gate-opener service implements `DoCommand` to provide manual control and status queries. Only one command can be executed at a time—if the gate is busy, the command returns `{"status": "busy"}`.

### Commands

| Command    | Description                                                          | Response                                                                 |
| ---------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `open`     | Opens the gate until the position sensor indicates open position.    | `{"status": "open"}`, `{"status": "closed"}`, or `{"status": "unknown"}` |
| `close`    | Closes the gate until the position sensor indicates closed position. | `{"status": "open"}`, `{"status": "closed"}`, or `{"status": "unknown"}` |
| `stop`     | Immediately stops the gate motor.                                    | `{"status": "stopped"}`                                                  |
| `position` | Returns the current position sensor reading.                         | `{"status": "position", "position": <float>}`                            |
| `status`   | Returns the current gate state based on position.                    | `{"status": "open"}`, `{"status": "closed"}`, or `{"status": "unknown"}` |

### Example DoCommand Payloads

**Open the gate:**

```json
{ "open": true }
```

**Close the gate:**

```json
{ "close": true }
```

**Stop the gate:**

```json
{ "stop": true }
```

**Get current position:**

```json
{ "position": true }
```

**Get gate status:**

```json
{ "status": true }
```
