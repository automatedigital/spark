---
title: Home Assistant
description: Control your smart home with Spark Agent via Home Assistant integration.
sidebar_label: Home Assistant
sidebar_position: 5
---

# Home Assistant

Connect Spark to your smart home. Get real-time event alerts and control any device through natural conversation.

Spark integrates with [Home Assistant](https://www.home-assistant.io/) two ways at once:

- **Gateway platform** — subscribes to live state changes via WebSocket and reacts to events
- **Smart home tools** — four tools the AI can call to query and control devices via the REST API

## Get Connected in 3 Steps

### Step 1: Create a Long-Lived Access Token

1. Open Home Assistant and click your name in the sidebar
2. Scroll to **Long-Lived Access Tokens**
3. Click **Create Token**, name it "Spark Agent"
4. Copy the token — you only see it once

### Step 2: Add Your Credentials

```bash
# Add to ~/.spark/.env

# Required
HASS_TOKEN=your-long-lived-access-token

# Optional: HA URL (default: http://homeassistant.local:8123)
HASS_URL=http://192.168.1.100:8123
```

:::info
Setting `HASS_TOKEN` automatically enables the `homeassistant` toolset. Both the gateway platform and all device control tools activate from this single token. No extra configuration needed.
:::

### Step 3: Start the Gateway

```bash
spark gateway
```

Home Assistant appears as a connected platform alongside Telegram, Discord, or any other messaging platforms you've set up.

## What the Agent Can Do

Spark registers four tools for smart home control:

### `ha_list_entities`

Lists entities, optionally filtered by domain or area.

**Parameters:**
- `domain` *(optional)* — `light`, `switch`, `climate`, `sensor`, `binary_sensor`, `cover`, `fan`, `media_player`, etc.
- `area` *(optional)* — room name like `living room`, `kitchen`, `bedroom`

**Example:**
```
List all lights in the living room
```

Returns entity IDs, states, and friendly names.

### `ha_get_state`

Gets the full state of a single entity — including brightness, color, temperature setpoint, sensor readings, and timestamps.

**Parameters:**
- `entity_id` *(required)* — e.g., `light.living_room`, `climate.thermostat`, `sensor.temperature`

**Example:**
```
What's the current state of climate.thermostat?
```

### `ha_list_services`

Shows what actions are available for each device type, including which parameters they accept.

**Parameters:**
- `domain` *(optional)* — e.g., `light`, `climate`, `switch`

**Example:**
```
What services are available for climate devices?
```

### `ha_call_service`

Calls a Home Assistant service to control a device.

**Parameters:**
- `domain` *(required)* — `light`, `switch`, `climate`, `cover`, `media_player`, `fan`, `scene`, `script`
- `service` *(required)* — `turn_on`, `turn_off`, `toggle`, `set_temperature`, `set_hvac_mode`, `open_cover`, `close_cover`, `set_volume_level`
- `entity_id` *(optional)* — target entity
- `data` *(optional)* — additional parameters as a JSON object

**Examples:**

```
Turn on the living room lights
-> ha_call_service(domain="light", service="turn_on", entity_id="light.living_room")
```

```
Set the thermostat to 22 degrees in heat mode
-> ha_call_service(domain="climate", service="set_temperature",
    entity_id="climate.thermostat", data={"temperature": 22, "hvac_mode": "heat"})
```

```
Set living room lights to blue at 50% brightness
-> ha_call_service(domain="light", service="turn_on",
    entity_id="light.living_room", data={"brightness": 128, "color_name": "blue"})
```

## Real-Time Events via the Gateway

When running as a gateway platform, Spark connects via WebSocket and subscribes to `state_changed` events. Matching events get forwarded to the agent as messages.

### Configure Which Events You Want

:::warning Required Configuration
By default, **no events are forwarded**. You must configure at least one of `watch_domains`, `watch_entities`, or `watch_all`. Without filters, a warning logs at startup and all state changes are silently dropped.
:::

Add an `extra` section to your `~/.spark/config.yaml`:

```yaml
platforms:
  homeassistant:
    enabled: true
    extra:
      watch_domains:
        - climate
        - binary_sensor
        - alarm_control_panel
        - light
      watch_entities:
        - sensor.front_door_battery
      ignore_entities:
        - sensor.uptime
        - sensor.cpu_usage
        - sensor.memory_usage
      cooldown_seconds: 30
```

| Setting | Default | Description |
|---------|---------|-------------|
| `watch_domains` | *(none)* | Only watch these domains |
| `watch_entities` | *(none)* | Only watch these specific entity IDs |
| `watch_all` | `false` | Set `true` to receive all state changes (not recommended) |
| `ignore_entities` | *(none)* | Always skip these entities, applied before other filters |
| `cooldown_seconds` | `30` | Minimum seconds between events for the same entity |

:::tip
Start with `climate`, `binary_sensor`, and `alarm_control_panel` — these cover the most useful automations. Use `ignore_entities` to silence noisy sensors like CPU temperature and uptime counters.
:::

### How Events Are Formatted

| Domain | Message format |
|--------|----------------|
| `climate` | "HVAC mode changed from 'off' to 'heat' (current: 21, target: 23)" |
| `sensor` | "changed from 21C to 22C" |
| `binary_sensor` | "triggered" / "cleared" |
| `light`, `switch`, `fan` | "turned on" / "turned off" |
| `alarm_control_panel` | "alarm state changed from 'armed_away' to 'triggered'" |
| *(other)* | "changed from 'old' to 'new'" |

### Agent Replies

Outbound messages arrive as **Home Assistant persistent notifications** (via `persistent_notification.create`). They appear in the HA notification panel with the title "Spark Agent".

### Connection Details

- WebSocket with 30-second heartbeat
- Automatic reconnection with backoff: 5s → 10s → 30s → 60s
- Separate REST API session for outbound notifications (avoids WebSocket conflicts)
- No user allowlist needed — the `HASS_TOKEN` authenticates the connection

## Security

The Home Assistant tools block a set of dangerous service domains to prevent arbitrary code execution on your HA host:

:::warning Blocked Domains
- `shell_command` — arbitrary shell execution
- `command_line` — sensors/switches that run commands
- `python_script` — scripted Python execution
- `pyscript` — broader scripting integration
- `hassio` — addon control, host shutdown/reboot
- `rest_command` — HTTP requests from the HA server (SSRF vector)

Calls to these domains return an error.
:::

Entity IDs are validated against the pattern `^[a-z_][a-z0-9_]*\.[a-z0-9_]+$` to block injection attacks.

## Example Conversations

### Morning Routine

```
User: Start my morning routine

Agent:
1. ha_call_service(domain="light", service="turn_on",
     entity_id="light.bedroom", data={"brightness": 128})
2. ha_call_service(domain="climate", service="set_temperature",
     entity_id="climate.thermostat", data={"temperature": 22})
3. ha_call_service(domain="media_player", service="turn_on",
     entity_id="media_player.kitchen_speaker")
```

### Security Check

```
User: Is the house secure?

Agent:
1. ha_list_entities(domain="binary_sensor")
     -> checks door/window sensors
2. ha_get_state(entity_id="alarm_control_panel.home")
     -> checks alarm status
3. ha_list_entities(domain="lock")
     -> checks lock states
4. Reports: "All doors closed, alarm is armed_away, all locks engaged."
```

### Reactive Automation (Gateway Events)

When running as a gateway, Spark reacts to events automatically:

```
[Home Assistant] Front Door: triggered (was cleared)

Agent automatically:
1. ha_get_state(entity_id="binary_sensor.front_door")
2. ha_call_service(domain="light", service="turn_on",
     entity_id="light.hallway")
3. Sends notification: "Front door opened. Hallway lights turned on."
```
