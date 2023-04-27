from abc import ABC, abstractmethod
from log_utils import get_logger
from config import relay_config


class BasePlugin(ABC):
    plugin_name = None

    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(f"Plugin:{self.plugin_name}")
        self.config = {"active": False}
        if "plugins" in relay_config and self.plugin_name in relay_config["plugins"]:
            self.config = relay_config["plugins"][self.plugin_name]

    @abstractmethod
    async def handle_meshtastic_message(
        packet, formatted_message, longname, meshnet_name
    ):
        print("Base plugin: handling Meshtastic message")

    @abstractmethod
    async def handle_room_message(room, event, full_message):
        print("Base plugin: handling room message")
