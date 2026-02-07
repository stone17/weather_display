import os
import json
import random
import logging
from PIL import Image, ImageOps

logger = logging.getLogger("PhotoFrame")

class PhotoFrameGenerator:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.photos_dir = os.path.join(root_dir, "photos")
        self.state_file = os.path.join(root_dir, "cache", "photo_frame_state.json")
        if not os.path.exists(self.photos_dir):
            os.makedirs(self.photos_dir)

    def get_photo_files(self):
        valid_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        files = [f for f in os.listdir(self.photos_dir) if f.lower().endswith(valid_ext)]
        return sorted(files) # Always sort to ensure consistent order for indexing

    def _get_next_index(self, total_files, sort_mode):
        current_index = 0
        
        # Load state
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    current_index = state.get('last_index', -1)
            except: pass

        if sort_mode == "random":
            next_index = random.randint(0, total_files - 1)
        else: # alphabetical / sequential
            next_index = (current_index + 1) % total_files
            
        # Save state
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'last_index': next_index}, f)
        except: pass
        
        return next_index

    def generate_image(self, width, height, sort_mode="random"):
        files = self.get_photo_files()
        if not files:
            logger.warning("No photos found.")
            img = Image.new("RGB", (width, height), "white")
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, height//2), "No Photos Uploaded", fill="black")
            return img

        # Determine which photo to pick
        idx = self._get_next_index(len(files), sort_mode)
        filename = files[idx]
        path = os.path.join(self.photos_dir, filename)
        
        try:
            logger.info(f"Processing photo ({sort_mode}): {filename}")
            img = Image.open(path).convert("RGB")
            img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            return img
        except Exception as e:
            logger.error(f"Photo error: {e}")
            return None