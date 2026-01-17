# upload.py
import requests
import time
import argparse
import logging
import sys
import os
from PIL import Image
from io import BytesIO
import traceback
import json

# Configuration
DEFAULT_UPLOAD_URL = "/" #do not change
DEFAULT_IMAGE_PATH = "weather.png"
CHUNK_SIZE = 1000
TIMEOUT = 30
RETRIES = 3

# --- Keep process_image, upload_processed_data, send_chunk as they are ---
def process_image(img):
    # Resize the image to 600x448
    img = img.resize((600, 448))

    # Convert to RGB mode if necessary
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Create a new image with the correct palette for 7-color display
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette((0, 0, 0, 255, 255, 255, 0, 255, 0, 0, 0, 255, 255, 0, 0, 255, 255, 0, 255, 128, 0) + (0, 0, 0) * 249)

    # Quantize the image to the 7-color palette with dithering
    img = img.quantize(palette=pal_img, dither=Image.FLOYDSTEINBERG)
    img.save("processed_image.bmp")
    # Convert to 7-color format
    color_map = {
        0: 0,    # Black
        1: 1,   # White
        2: 2,   # Green
        3: 3,   # Blue
        4: 4,  # Red
        5: 5,  # Yellow
        6: 6,  # Orange
        7: 0    # Default to black for any other color
    }

    img_data = [color_map.get(p, 0) for p in img.getdata()]

    width, height = img.size
    return img_data, width, height

def upload_processed_data(data, width, height, esp_ip, upload_url):
    # --- This function remains the same ---
    try:
        url_prefix = f"http://{esp_ip}{upload_url}"
        epd_command = "EPDz_"  # Hardcoded command for the 5.65-inch display
        session = requests.Session()

        # Replicate headers from the browser
        headers = {
            'Host': esp_ip,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Content-Type': 'application/octet-stream',
            'Origin': f'http://{esp_ip}',
            'Connection': 'keep-alive',
            'Referer': f'http://{esp_ip}/',
        }

        # Send EPDz_ command
        for attempt in range(RETRIES):
            try:
                #logger.debug(f"Sending EPD command: {url_prefix + epd_command}")
                response = session.post(url_prefix + epd_command, timeout=TIMEOUT, headers=headers)
                response.raise_for_status()
                #logger.info(f"EPD command sent successfully on attempt {attempt+1}")
                break
            except requests.exceptions.RequestException as e:
                #logger.warning(f"Error sending EPD command (attempt {attempt+1}/{RETRIES}): {e}")
                if attempt == RETRIES - 1:
                    #logger.error(traceback.format_exc())
                    raise

        px_ind = 0
        st_ind = 0
        chunk_counter = 0

        # Loop through the data in chunks
        while px_ind < len(data):
            #logger.debug(f"Sending chunk: px_ind={px_ind}, st_ind={st_ind}")

            # Determine if this is the last chunk based on remaining data
            is_last_chunk = px_ind + CHUNK_SIZE >= len(data)

            st_ind, px_ind = send_chunk(session, url_prefix, data, px_ind, st_ind, is_last_chunk)
            chunk_counter += 1  # Increment the counter after each chunk

        time.sleep(5)  # Wait for 5 seconds after sending all chunks

        response = session.post(url_prefix + "SHOW_", timeout=TIMEOUT, headers=headers)
        response.raise_for_status()
        #logger.info("Image uploaded successfully!")
        print(f"Total chunks sent: {chunk_counter}")
        return True

    except requests.exceptions.RequestException as e:
        #logger.error(f"Upload failed: {e}")
        #logger.error(traceback.format_exc())
        return False
    except Exception as e:
        # Use basic print for exceptions if logger not configured
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        return False


def send_chunk(session, url_prefix, chunk_data, px_ind, st_ind, is_last_chunk=False):
    msg = ""
    current_chunk_size = CHUNK_SIZE

    while len(msg) < current_chunk_size and px_ind < len(chunk_data):
        values = []
        for i in range(2):
            if px_ind < len(chunk_data):
                values.append(chunk_data[px_ind])
                px_ind += 1
            else:
                values.append(0)  # Pad with 0 if we run out of data

        # Pack 2 pixels (3 bits each) into a single byte
        packed_byte = (values[0] & 0x07) << 4 | (values[1] & 0x07)

        # Convert to two characters in the range ['a', 'p']
        char1 = chr((packed_byte >> 4) + ord('a'))  # High 4 bits
        char2 = chr((packed_byte & 0x0F) + ord('a'))  # Low 4 bits

        msg += char1 + char2

    # Ensure the msg doesn't exceed current_chunk_size, truncate if necessary
    if len(msg) > current_chunk_size:
        msg = msg[:current_chunk_size]

    for attempt in range(RETRIES):
        try:
            # Use acdaLOAD_ for the last chunk, iodaLOAD_ for others
            if is_last_chunk:
                url = url_prefix + f"{msg}acdaLOAD_"
            else:
                url = url_prefix + f"{msg}iodaLOAD_"

            #logger.debug(f"Sending chunk to: {url}, last chunk: {is_last_chunk}")

            headers = {'Content-Type': 'application/octet-stream',
                       'Content-Length': str(len(msg))}
            response = session.post(url, data=msg.encode('ascii'), timeout=TIMEOUT, headers=headers)
            response.raise_for_status()
            #logger.debug(f"Chunk sent successfully (attempt {attempt + 1})")
            return st_ind, px_ind  # Return here after a successful send
        except requests.exceptions.RequestException as e:
            #logger.warning(f"Error sending chunk (attempt {attempt + 1}/{RETRIES}): {e}")
            if attempt == RETRIES - 1:
                #logger.error(traceback.format_exc())
                raise

    if px_ind >= len(chunk_data):
        st_ind += 1
    return st_ind, px_ind


def main():
    # Logging setup (optional, can use basic print)
    # logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    # logger = logging.getLogger(__name__)
    parser = argparse.ArgumentParser(description="Upload processed image data to ESP32.")
    parser.add_argument("--image", dest="image_path", default=DEFAULT_IMAGE_PATH, help="Path to the image file")
    # Add argument for server IP if needed when run standalone
    parser.add_argument("--ip", dest="server_ip", default=None, help="IP address of the ESP32 server")


    args = parser.parse_args()

    # Load SERVER_IP from config.json if --ip not provided
    server_ip = args.server_ip
    if not server_ip:
        try:
            with open("config.json", "r") as config_file:
                config = json.load(config_file)
            server_ip = config.get("server_ip")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load server_ip from config.json: {e}")

    if not server_ip:
        print("Error: Server IP address not provided via --ip argument or found in config.json.")
        sys.exit(1)

    # Check if image file exists
    if not os.path.exists(args.image_path):
        print(f"Error: Image file not found at {args.image_path}")
        sys.exit(1)

    # Process the image
    try:
        print(f"Processing image: {args.image_path}")
        img = Image.open(args.image_path)
        processed_data, width, height = process_image(img)
    except Exception as e:
        print(f"Error processing image: {e}")
        traceback.print_exc()
        sys.exit(1)


    if processed_data:
        print(f"Uploading image to {server_ip}...")
        # Use DEFAULT_UPLOAD_URL here
        upload_successful = upload_processed_data(processed_data, width, height, server_ip, DEFAULT_UPLOAD_URL)
        if upload_successful:
            print("Upload complete")
        else:
            print("Upload failed")
    else:
        print("Image processing failed (returned no data).")
        # logger.error(traceback.format_exc()) # Use print if logger not set up

if __name__ == "__main__":
    main()
