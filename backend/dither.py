from PIL import Image

# --- HARDWARE PALETTE DEFINITIONS (Source of Truth) ---
# 7-Color ACeP Standard (Waveshare 5.65", 7.3", Spectra E6)
PALETTE_ACEP_7_RGB = [
    (0, 0, 0),       # Black
    (255, 255, 255), # White
    (0, 255, 0),     # Green
    (0, 0, 255),     # Blue
    (255, 0, 0),     # Red
    (255, 255, 0),   # Yellow
    (255, 128, 0)    # Orange
]

class DitherProcessor:
    def __init__(self):
        # Flatten for PIL
        flat_palette = [c for rgb in PALETTE_ACEP_7_RGB for c in rgb]
        
        # Create a palette image for PIL quantization
        self.palette_img = Image.new('P', (1, 1))
        # Pad palette to 768 integers (256 colors * 3 channels)
        full_palette = flat_palette + [0] * (768 - len(flat_palette))
        self.palette_img.putpalette(full_palette)

    def process(self, img: Image.Image, method: str = "floyd_steinberg") -> Image.Image:
        """
        Quantizes the image to the 7-color palette.
        """
        if img.mode != "RGB":
            img = img.convert("RGB")
            
        dither_enum = Image.FLOYDSTEINBERG if method == "floyd_steinberg" else Image.NONE
        
        # Quantize to the palette
        return img.quantize(palette=self.palette_img, dither=dither_enum)