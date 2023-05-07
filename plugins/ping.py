import re

from plugins.base_plugin import BasePlugin
from matrix_utils import connect_matrix


class Plugin(BasePlugin):
    plugin_name = "ping"

    async def handle_meshtastic_message(
        self, packet, formatted_message, longname, meshnet_name
    ):
        pass

    async def handle_room_message(self, room, event, full_message):
        full_message = full_message.strip()
        if not self.matches(full_message):
            return

        matrix_client = await connect_matrix()
        response = await matrix_client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": "pong!",
            },
        )
