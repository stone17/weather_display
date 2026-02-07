import os
import logging
import struct
from PIL import Image

from display_drivers import SevenColorDriver, SpectraE6Driver
from dither import DitherProcessor
from create_weather_info import WeatherService
from photo_frame import PhotoFrameGenerator

logger = logging.getLogger("DisplayManager")

class DisplayOrchestrator:
    def __init__(self, config, root_dir):
        self.config = config
        self.root_dir = root_dir
        self.driver = self._init_driver()
        
    def _init_driver(self):
        hardware = self.config.get("hardware_profile", "generic")
        dither = self.config.get("dithering_method", "floyd_steinberg")
        
        if hardware == "spectra_e6":
            w, h = 800, 480
            return SpectraE6Driver(w, h, dither_method=dither)
        elif hardware == "waveshare_73":
            w, h = 800, 480
            return SevenColorDriver(w, h, dither_method=dither)
        elif hardware == "waveshare_565":
            w, h = 600, 448
            return SevenColorDriver(w, h, dither_method=dither)
        else:
            w = self.config.get("display_width", 600)
            h = self.config.get("display_height", 448)
            return SevenColorDriver(w, h, dither_method=dither)

    async def update_display(self, specific_photo=None):
        logger.info("Orchestrator: Starting update cycle...")
        
        mode = self.config.get("display_mode", "weather")
        if specific_photo:
            mode = "photo"

        width = self.driver.width
        height = self.driver.height
        
        # 1. GENERATE CONTENT (RGB)
        img_rgb = None
        
        if mode == "photo":
            logger.info("Delegating to: PhotoFrameGenerator")
            sort_mode = self.config.get("photo_sort_order", "random")
            generator = PhotoFrameGenerator(self.root_dir)
            # Pass specific_filename here
            img_rgb = generator.generate_image(width, height, sort_mode=sort_mode, specific_filename=specific_photo)
            
        else:
            logger.info("Delegating to: WeatherService")
            colors = self.driver.get_rendering_colors()
            weather_svc = WeatherService(self.config, self.root_dir)
            img_rgb = await weather_svc.generate_image(width, height, colors)

        if not img_rgb:
            logger.error("Content generation failed (returned None).")
            return False, "Content generation failed"

        # 2. SAVE SOURCE (For Web Preview)
        cache_dir = os.path.join(self.root_dir, "cache")
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        
        source_path = os.path.join(cache_dir, "latest_source.png")
        try:
            img_rgb.save(source_path)
            logger.info(f"Saved source image to {source_path}")
        except Exception as e:
            logger.error(f"Failed to save source image: {e}")

        # 3. DITHERING
        try:
            dither_method = self.config.get("dithering_method", "floyd_steinberg")
            ditherer = DitherProcessor()
            img_dithered = ditherer.process(img_rgb, dither_method)
            
            # Save Dithered Result
            self._save_dithered_file(img_dithered, cache_dir)
            
        except Exception as e:
            logger.error(f"Dithering failed: {e}")
            return False, f"Dithering failed: {e}"

        # 4. SERVER PUSH
        if self.config.get("enable_server_push", False):
            self._handle_legacy_push(img_rgb)

        return True, "Display updated successfully"

    def _save_dithered_file(self, img, cache_dir):
        fmt = self.config.get("output_format", "png")
        for f in ["latest_dithered.png", "latest_dithered.bmp"]:
            p = os.path.join(cache_dir, f)
            if os.path.exists(p): os.remove(p)
            
        save_path = ""
        if fmt == "bmp8":
            save_path = os.path.join(cache_dir, "latest_dithered.bmp")
            # USE THE NEW FUNCTION HERE
            self._save_bmp_uncompressed(img, save_path) 
            
        elif fmt == "bmp24":
            save_path = os.path.join(cache_dir, "latest_dithered.bmp")
            img.convert("RGB").save(save_path) # PIL 24-bit is usually fine, but 8-bit is safer for size
        else:
            save_path = os.path.join(cache_dir, "latest_dithered.png")
            img.save(save_path)
        
        logger.info(f"Saved dithered image ({fmt}) to {save_path}")

    def _handle_legacy_push(self, img_rgb):
        server_ip = self.config.get("server_ip")
        if server_ip:
            try:
                raw_data, w, h = self.driver.process_image(img_rgb)
                import upload
                logger.info(f"Pushing to {server_ip}...")
                upload.upload_processed_data(raw_data, w, h, server_ip, upload.DEFAULT_UPLOAD_URL)
            except Exception as e:
                logger.error(f"Push failed: {e}")

    def _save_bmp_uncompressed(self, image, filepath):
        """
        Saves a PIL P-mode image as an uncompressed 8-bit BMP.
        Fixed format string to match standard BITMAPINFOHEADER (40 bytes).
        """
        width, height = image.size
        
        # Row padding to 4-byte boundaries
        row_stride = (width + 3) & ~3
        padding = row_stride - width
        
        # 1. Header
        # File Header (14) + DIB Header (40) + Palette (1024) = 1078 offset
        file_size = 54 + 1024 + (row_stride * height)
        offset = 54 + 1024
        
        # BMP Header: Magic(2), FileSize(4), Rsv(2), Rsv(2), Offset(4)
        bmp_header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, offset)
        
        # DIB Header (BITMAPINFOHEADER) - 40 bytes, 11 fields
        # I=4byte-uint, i=4byte-int, H=2byte-uint
        dib_header = struct.pack('<IiiHHIIIIII', 
            40,      # biSize
            width,   # biWidth
            height,  # biHeight
            1,       # biPlanes
            8,       # biBitCount (8 bits per pixel)
            0,       # biCompression (BI_RGB = 0)
            0,       # biSizeImage (0 is valid for BI_RGB)
            0,       # biXPelsPerMeter
            0,       # biYPelsPerMeter
            0,       # biClrUsed
            0        # biClrImportant
        )
        
        # 2. Extract Palette
        # PIL returns flat [r,g,b, r,g,b...]
        raw_palette = image.getpalette() 
        if not raw_palette: raw_palette = [0]*768 

        palette_data = bytearray()
        for i in range(256):
            if i * 3 < len(raw_palette):
                r = raw_palette[i*3]
                g = raw_palette[i*3+1]
                b = raw_palette[i*3+2]
                palette_data.extend([b, g, r, 0]) # BGR + Reserved (Alpha)
            else:
                palette_data.extend([0, 0, 0, 0])

        # 3. Pixel Data (Bottom-Up)
        pixel_data = bytearray()
        pixels = list(image.getdata())
        
        for y in range(height - 1, -1, -1):
            row_start = y * width
            row = pixels[row_start : row_start + width]
            pixel_data.extend(row)
            pixel_data.extend(b'\x00' * padding)
            
        with open(filepath, 'wb') as f:
            f.write(bmp_header)
            f.write(dib_header)
            f.write(palette_data)
            f.write(pixel_data)