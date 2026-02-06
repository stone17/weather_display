from abc import ABC, abstractmethod
from PIL import Image
from dither import DitherProcessor

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

class SevenColorDriver(BaseDisplayDriver):
    """Driver for 5.65-inch 7-color ACEP displays (600x448)."""
    def process_image(self, img: Image.Image):
        # Resize if necessary
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        # Apply Dithering
        quantized = self.dither_engine.process(img, self.dither_method)
        
        # Map palette indices directly (0-6)
        # The palette in DitherProcessor matches the hardware index expectation for ACeP
        return list(quantized.getdata()), self.width, self.height

class SpectraE6Driver(BaseDisplayDriver):
    """Driver for reTerminal 1002 Spectra E6 (800x480)."""
    def __init__(self, width=800, height=480, dither_method="floyd_steinberg"):
        # Default to 800x480 as requested
        super().__init__(width, height, dither_method)

    def process_image(self, img: Image.Image):
        # Uses the same ACeP 7-color logic, just different resolution defaults
        driver = SevenColorDriver(self.width, self.height, self.dither_method)
        return driver.process_image(img)