from abc import ABC, abstractmethod
from PIL import Image
from dither import DitherProcessor, PALETTE_ACEP_7_RGB

class BaseDisplayDriver(ABC):
    def __init__(self, width: int, height: int, dither_method: str = "floyd_steinberg"):
        self.width = width
        self.height = height
        self.dither_method = dither_method
        self.dither_engine = DitherProcessor()

    @abstractmethod
    def process_image(self, img: Image.Image) -> tuple:
        """Process PIL image into hardware-specific byte data."""
        pass

    @abstractmethod
    def get_rendering_colors(self) -> dict:
        """Returns the logical color map optimized for this hardware."""
        pass

class SevenColorDriver(BaseDisplayDriver):
    """
    Driver for Standard Waveshare 5.65" / 7.3" 7-Color Displays.
    Uses LEGACY (Soft) colors to match your original setup.
    """
    def get_rendering_colors(self) -> dict:
        return {
            'bg': (255, 255, 255),   # White
            'text': (50, 50, 50),    # Dark Grey (Legacy)
            'blue': (0, 0, 200),     # Darker Blue (Legacy)
            'green': (0, 180, 0),    # Darker Green (Legacy)
            'orange': (255, 140, 0), # Soft Orange (Legacy)
            'grey': (100, 100, 100)  # Standard Grey (Legacy)
        }

    def process_image(self, img: Image.Image):
        # Resize if necessary
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        # Apply Dithering
        quantized = self.dither_engine.process(img, self.dither_method)
        
        # Map palette indices directly
        return list(quantized.getdata()), self.width, self.height

class SpectraE6Driver(BaseDisplayDriver):
    """
    Driver for reTerminal 1002 Spectra E6.
    Uses STRICT (Hardware) colors to prevent dithering artifacts on thin text.
    """
    def __init__(self, width=800, height=480, dither_method="floyd_steinberg"):
        super().__init__(width, height, dither_method)

    def get_rendering_colors(self) -> dict:
        # Use exact hardware palette matches
        # Indexes correspond to PALETTE_ACEP_7_RGB in dither.py
        return {
            'bg': PALETTE_ACEP_7_RGB[1],     # White (255, 255, 255)
            'text': PALETTE_ACEP_7_RGB[0],   # Black (0, 0, 0)
            'blue': PALETTE_ACEP_7_RGB[3],   # Pure Blue (0, 0, 255)
            'green': PALETTE_ACEP_7_RGB[2],  # Pure Green (0, 255, 0)
            'orange': PALETTE_ACEP_7_RGB[6], # Pure Orange (255, 128, 0)
            'grey': (128, 128, 128)          # Mid-Grey (for dithering)
        }

    def process_image(self, img: Image.Image):
        # Reuse standard processing logic
        driver = SevenColorDriver(self.width, self.height, self.dither_method)
        return driver.process_image(img)