import time
import io
import os
import requests
from PIL import Image
from nio import AsyncClient, UploadResponse
from plugins.base_plugin import BasePlugin
import re
from matrix_utils import connect_matrix

def load_env_variable(key):
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    with open(env_path) as f:
        for line in f:
            if line.strip().startswith(key):
                return line.strip().split('=')[1].strip().strip('"')
    return None

def parse_timeframe(timeframe):
    unit_multipliers = {
        'm': 60,            # minute to seconds
        'h': 60 * 60,       # hour to seconds
        'd': 24 * 60 * 60,  # day to seconds
        'M': 30 * 24 * 60 * 60  # month to seconds (approximation)
    }
    match = re.match(r'(\d+)([mhdM])', timeframe)
    if match:
        value, unit = match.groups()
        return int(value) * unit_multipliers[unit]
    return 24 * 60 * 60  # default to 1 day in seconds

class Plugin(BasePlugin):
    plugin_name = "voltage"

    @property
    def description(self):
        return "Generates and returns Voltage."

    async def get_image_url(self, timeframe):
        base_url = load_env_variable('GRAFANA_BASE_URL')
        org_id = "1"
        panel_id = "6"
        width = "1200"
        height = "600"
        scale = "2"
        tz = "Europe/Warsaw"

        to_time = int(time.time() * 1000)
        from_time = to_time - parse_timeframe(timeframe) * 1000

        url = (
            f"{base_url}?orgId={org_id}&from={from_time}&to={to_time}&"
            f"panelId={panel_id}&width={width}&height={height}&scale={scale}&tz={tz}"
        )

        self.logger.debug(f"Generated URL: {url}")

        return url

    async def handle_meshtastic_message(self, packet, formatted_message, longname, meshnet_name):
        return False

    def get_matrix_commands(self):
        return [self.plugin_name]

    def get_mesh_commands(self):
        return []

    async def handle_room_message(self, room, event, full_message):
        full_message = full_message.strip()
        if not self.matches(full_message):
            return False

        self.logger.debug(f"Received message: {full_message}")

        matrix_client = await connect_matrix()

        # Check if the message is a help request
        if 'help' in full_message:
            help_message = ("Usage: !voltage [timeframe]\n"
                            "Timeframe format examples:\n"
                            "5m - last 5 minutes\n"
                            "1h - last 1 hour\n"
                            "2d - last 2 days\n"
                            "1M - last 1 month")
            await matrix_client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": help_message},
            )
            return True

        # Extract timeframe from the message
        pattern = r"^.*: !voltage(?: (\d+[mhdM]?))?$"
        match = re.match(pattern, full_message)

        if match:
            timeframe = match.group(1) or '1d'  # default to last 1 day
        else:
            timeframe = '1d'

        self.logger.debug(f"Extracted timeframe: {timeframe}")

        url = await self.get_image_url(timeframe)
        token = load_env_variable('GRAFANA_API_KEY')
        headers = {
            "Authorization": f"Bearer {token}"
        }

        try:
            self.logger.debug(f"Fetching image from URL: {url} with headers: {headers}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            self.logger.info("Image successfully fetched from Grafana")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch image: {e}")
            return False

        try:
            self.logger.debug(f"Processing image data")
            image = Image.open(io.BytesIO(response.content))
            await self.send_image(matrix_client, room.room_id, image)
            self.logger.info("Image successfully sent to room")
        except Exception as e:
            self.logger.error(f"Failed to process or send image: {e}")
            return False

        return True

    async def upload_image(self, client: AsyncClient, image: Image.Image) -> UploadResponse:
        try:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_data = buffer.getvalue()

            response, maybe_keys = await client.upload(
                io.BytesIO(image_data),
                content_type="image/png",
                filename="graph.png",
                filesize=len(image_data),
            )
            self.logger.info("Image successfully uploaded to Matrix")
            return response
        except Exception as e:
            self.logger.error(f"Failed to upload image: {e}")
            raise

    async def send_room_image(self, client: AsyncClient, room_id: str, upload_response: UploadResponse):
        try:
            await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.image", "url": upload_response.content_uri, "body": ""},
            )
            self.logger.info("Image successfully sent to room")
        except Exception as e:
            self.logger.error(f"Failed to send image to room: {e}")
            raise

    async def send_image(self, client: AsyncClient, room_id: str, image: Image.Image):
        try:
            response = await self.upload_image(client=client, image=image)
            await self.send_room_image(client, room_id, upload_response=response)
        except Exception as e:
            self.logger.error(f"Failed to send image: {e}")
            raise

