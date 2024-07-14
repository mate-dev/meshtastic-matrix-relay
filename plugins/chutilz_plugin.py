import time
import io
import os
import requests
from PIL import Image
from nio import AsyncClient, UploadResponse
from plugins.base_plugin import BasePlugin

def load_env_variable(key):
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    with open(env_path) as f:
        for line in f:
            if line.strip().startswith(key):
                return line.strip().split('=')[1].strip().strip('"')
    return None

class Plugin(BasePlugin):
    plugin_name = "chutilz"

    @property
    def description(self):
        return "Generates and returns Channels utilization."

    async def get_image_url(self):
        base_url = load_env_variable('GRAFANA_BASE_URL')
        org_id = "1"
        panel_id = "3"
        width = "1000"
        height = "500"
        scale = "1"
        tz = "Europe/Warsaw"

        to_time = int(time.time() * 1000)
        from_time = to_time - 24 * 60 * 60 * 1000

        url = (
            f"{base_url}?orgId={org_id}&from={from_time}&to={to_time}&"
            f"panelId={panel_id}&width={width}&height={height}&scale={scale}&tz={tz}"
        )

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

        from matrix_utils import connect_matrix

        matrix_client = await connect_matrix()

        url = await self.get_image_url()
        token = load_env_variable('GRAFANA_API_KEY')
        headers = {
            "Authorization": f"Bearer {token}"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            self.logger.info("Image successfully fetched from Grafana")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch image: {e}")
            return False

        try:
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

