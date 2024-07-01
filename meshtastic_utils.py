import asyncio
import time
import meshtastic.tcp_interface
import meshtastic.serial_interface
import meshtastic.ble_interface
from typing import List
from config import relay_config
from log_utils import get_logger
from db_utils import get_longname, get_shortname
from plugin_loader import load_plugins

matrix_rooms: List[dict] = relay_config["matrix_rooms"]

logger = get_logger(name="Meshtastic")

meshtastic_client = None

def connect_meshtastic(force_connect=False):
    global meshtastic_client
    if meshtastic_client and not force_connect:
        return meshtastic_client

    meshtastic_client = None

    # Initialize Meshtastic interface
    connection_type = relay_config["meshtastic"]["connection_type"]
    retry_limit = (
        relay_config["meshtastic"]["retry_limit"]
        if "retry_limit" in relay_config["meshtastic"]
        else 3
    )
    attempts = 1
    successful = False

    while not successful and attempts <= retry_limit:
        try:
            if connection_type == "serial":
                serial_port = relay_config["meshtastic"]["serial_port"]
                logger.info(f"Connecting to serial port {serial_port} ...")
                meshtastic_client = meshtastic.serial_interface.SerialInterface(serial_port)
            
            elif connection_type == "ble":
                ble_address = relay_config["meshtastic"].get("ble_address")
                ble_name = relay_config["meshtastic"].get("ble_name")

                if ble_address:
                    logger.info(f"Connecting to BLE address {ble_address} ...")
                    meshtastic_client = meshtastic.ble_interface.BLEInterface(address=ble_address)
                elif ble_name:
                    logger.info(f"Connecting to BLE name {ble_name} ...")
                    meshtastic_client = meshtastic.ble_interface.BLEInterface(address=ble_name)
                else:
                    logger.error("No BLE address or name provided.")
                    return None
            
            else:
                target_host = relay_config["meshtastic"]["host"]
                logger.info(f"Connecting to host {target_host} ...")
                meshtastic_client = meshtastic.tcp_interface.TCPInterface(hostname=target_host)

            successful = True
            nodeInfo = meshtastic_client.getMyNodeInfo()
            logger.info(f"Connected to {nodeInfo['user']['shortName']} / {nodeInfo['user']['hwModel']}")
        
        except Exception as e:
            attempts += 1
            if attempts <= retry_limit:
                logger.warn(f"Attempt #{attempts-1} failed. Retrying in {attempts} secs {e}")
                time.sleep(attempts)
            else:
                logger.error(f"Could not connect: {e}")
                return None

    return meshtastic_client

def on_lost_meshtastic_connection(interface):
    logger.error("Lost connection. Reconnecting...")
    connect_meshtastic(force_connect=True)

def on_meshtastic_message(packet, loop=None):
    from matrix_utils import matrix_relay

    sender = packet["fromId"]

    if "text" in packet["decoded"] and packet["decoded"]["text"]:
        text = packet["decoded"]["text"]

        if "channel" in packet:
            channel = packet["channel"]
        else:
            if packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP":
                channel = 0
            else:
                logger.debug(f"Unknown packet")
                return

        # Check if the channel is mapped to a Matrix room in the configuration
        channel_mapped = False
        for room in matrix_rooms:
            if room["meshtastic_channel"] == channel:
                channel_mapped = True
                break

        if not channel_mapped:
            logger.debug(f"Skipping message from unmapped channel {channel}")
            return

        logger.info(f"Processing inbound radio message from {sender} on channel {channel}")

        longname = get_longname(sender) or sender
        shortname = get_shortname(sender) or sender
        meshnet_name = relay_config["meshtastic"]["meshnet_name"]

        formatted_message = f"[{longname}/{meshnet_name}]: {text}"

        # Plugin functionality
        plugins = load_plugins()

        found_matching_plugin = False
        for plugin in plugins:
            if not found_matching_plugin:
                result = asyncio.run_coroutine_threadsafe(
                    plugin.handle_meshtastic_message(
                        packet, formatted_message, longname, meshnet_name
                    ),
                    loop=loop,
                )
                found_matching_plugin = result.result()
                if found_matching_plugin:
                    logger.debug(f"Processed by plugin {plugin.plugin_name}")

        if found_matching_plugin:
            return

        logger.info(f"Relaying Meshtastic message from {longname} to Matrix: {formatted_message}")

        for room in matrix_rooms:
            if room["meshtastic_channel"] == channel:
                asyncio.run_coroutine_threadsafe(
                    matrix_relay(
                        room["id"],
                        formatted_message,
                        longname,
                        shortname,
                        meshnet_name,
                    ),
                    loop=loop,
                )
    else:
        portnum = packet["decoded"]["portnum"]

        plugins = load_plugins()
        found_matching_plugin = False
        for plugin in plugins:
            if not found_matching_plugin:
                result = asyncio.run_coroutine_threadsafe(
                    plugin.handle_meshtastic_message(
                        packet, formatted_message=None, longname=None, meshnet_name=None
                    ),
                    loop=loop,
                )
                found_matching_plugin = result.result()
                if found_matching_plugin:
                    logger.debug(f"Processed {portnum} with plugin {plugin.plugin_name}")
