import numpy as np
from PIL import Image, ImageEnhance
from enum import Enum
from typing import List, Tuple, Union

# --- HARDWARE PALETTE DEFINITIONS (Source of Truth) ---
PALETTE_ACEP_7_RGB_modified = [
    (25, 30, 33),    # 0: Black (#191E21)
    (241, 241, 241), # 1: White (#F1F1F1)
    (83, 164, 40),   # 2: Green (#53A428)
    (49, 49, 143),   # 3: Blue (#31318F)
    (210, 14, 19),   # 4: Red (#D20E13)
    (243, 207, 17),  # 5: Yellow (#F3CF11)
    (184, 94, 28)    # 6: Orange (#B85E1C)
]

PALETTE_ACEP_7_RGB = [
    (0, 0, 0),       # Black
    (255, 255, 255), # White
    (0, 255, 0),     # Green
    (0, 0, 255),     # Blue
    (255, 0, 0),     # Red
    (255, 255, 0),   # Yellow
    (255, 128, 0)    # Orange
]

class DitherMethod(Enum):
    NONE = "none"
    FLOYD_STEINBERG = "floyd_steinberg" 
    BAYER_2 = "bayer_2"                 
    BAYER_4 = "bayer_4"                 
    STUCKI = "stucki"                   
    JARVIS = "jarvis"                   
    BURKES = "burkes"                   
    SIERRA3 = "sierra3"                 

class DitherProcessor:
    def __init__(self, palette: List[Tuple[int, int, int]] = PALETTE_ACEP_7_RGB):
        self.palette_rgb = palette
        self._palette_image = self._create_palette_image(palette)
        # Pre-calculate numpy palette for vectorized operations
        self._palette_np = np.array(palette, dtype=np.float32)

    def _create_palette_image(self, palette: List[Tuple[int, int, int]]) -> Image.Image:
        """Creates a PIL P-mode image for native quantization."""
        flat_palette = [c for rgb in palette for c in rgb]
        full_palette = flat_palette + [0] * (768 - len(flat_palette))
        img = Image.new('P', (1, 1))
        img.putpalette(full_palette)
        return img

    def _get_bayer_matrix(self, size: int) -> np.ndarray:
        """Generates Bayer matrix for ordered dithering."""
        if size == 2:
            return np.array([[0, 2], [3, 1]]) / 4.0
        elif size == 4:
            m2 = np.array([[0, 2], [3, 1]])
            m4 = np.block([[4 * m2, 4 * m2 + 2], [4 * m2 + 3, 4 * m2 + 1]])
            return m4 / 16.0
        return np.array([[0]])

    def _find_closest_palette_index_vectorized(self, pixel_array: np.ndarray) -> np.ndarray:
        """Fast numpy-based nearest color finding."""
        pixels = pixel_array[:, :, np.newaxis, :]  # (H, W, 1, 3)
        palette = self._palette_np[np.newaxis, np.newaxis, :, :]  # (1, 1, 7, 3)
        diff = pixels - palette
        dist_sq = np.sum(diff**2, axis=3)  # (H, W, 7)
        return np.argmin(dist_sq, axis=2).astype(np.uint8)

    def _apply_ordered_dither(self, img: Image.Image, matrix_size: int) -> Image.Image:
        """Applies Bayer ordered dithering."""
        img_np = np.array(img, dtype=np.float32)
        h, w, _ = img_np.shape
        
        bayer = self._get_bayer_matrix(matrix_size)
        tiled_bayer = np.tile(bayer, (h // matrix_size + 1, w // matrix_size + 1))
        threshold_map = tiled_bayer[:h, :w]
        
        spread = 32.0 
        noise = (threshold_map - 0.5) * spread
        noisy_img = np.clip(img_np + noise[:, :, np.newaxis], 0, 255)
        
        indices = self._find_closest_palette_index_vectorized(noisy_img)
        result = Image.fromarray(indices, mode='P')
        result.putpalette(self._palette_image.getpalette())
        return result

    def _apply_error_diffusion_custom(self, img: Image.Image, kernel_name: DitherMethod) -> Image.Image:
        """Applies custom Error Diffusion kernels."""
        kernels = {
            DitherMethod.STUCKI: [
                (1, 0, 8/42), (2, 0, 4/42),
                (-2, 1, 2/42), (-1, 1, 4/42), (0, 1, 8/42), (1, 1, 4/42), (2, 1, 2/42),
                (-2, 2, 1/42), (-1, 2, 2/42), (0, 2, 4/42), (1, 2, 2/42), (2, 2, 1/42)
            ],
            DitherMethod.JARVIS: [
                (1, 0, 7/48), (2, 0, 5/48),
                (-2, 1, 3/48), (-1, 1, 5/48), (0, 1, 7/48), (1, 1, 5/48), (2, 1, 3/48),
                (-2, 2, 1/48), (-1, 2, 3/48), (0, 2, 4/48), (1, 2, 3/48), (2, 2, 1/48)
            ],
            DitherMethod.BURKES: [
                (1, 0, 8/32), (2, 0, 4/32),
                (-2, 1, 2/32), (-1, 1, 4/32), (0, 1, 8/32), (1, 1, 4/32), (2, 1, 2/32)
            ],
             DitherMethod.SIERRA3: [
                (1, 0, 5/32), (2, 0, 3/32),
                (-2, 1, 2/32), (-1, 1, 4/32), (0, 1, 5/32), (1, 1, 4/32), (2, 1, 2/32),
                (-1, 2, 2/32), (0, 2, 3/32), (1, 2, 2/32)
            ]
        }
        
        kernel = kernels.get(kernel_name, kernels[DitherMethod.STUCKI])
        pixels = np.array(img, dtype=np.float32)
        height, width, _ = pixels.shape
        palette = self._palette_np
        output_indices = np.zeros((height, width), dtype=np.uint8)

        for y in range(height):
            for x in range(width):
                old_pixel = pixels[y, x]
                diff = palette - old_pixel
                dist_sq = np.sum(diff**2, axis=1)
                idx = np.argmin(dist_sq)
                new_pixel = palette[idx]
                
                output_indices[y, x] = idx
                quant_error = old_pixel - new_pixel
                
                for dx, dy, factor in kernel:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        pixels[ny, nx] += quant_error * factor

        result = Image.fromarray(output_indices, mode='P')
        result.putpalette(self._palette_image.getpalette())
        return result

    def process(self, img: Image.Image, method: Union[DitherMethod, str] = DitherMethod.FLOYD_STEINBERG, saturation_boost: float = 1.0) -> Image.Image:
        """
        Quantizes the image to the 7-color palette using the specified method.
        Accepts strings (from web config) or DitherMethod Enums.
        """
        # Handle string input from config
        if isinstance(method, str):
            try:
                method = DitherMethod(method.lower())
            except ValueError:
                method = DitherMethod.FLOYD_STEINBERG

        if img.mode != "RGB":
            img = img.convert("RGB")

        # 1. Boost Saturation (Optional but recommended for E-Ink)
        if saturation_boost != 1.0:
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(saturation_boost)

        # 2. Select Method
        if method == DitherMethod.FLOYD_STEINBERG:
            return img.quantize(palette=self._palette_image, dither=Image.FLOYDSTEINBERG)
            
        elif method == DitherMethod.NONE:
            return img.quantize(palette=self._palette_image, dither=Image.NONE)
            
        elif method in [DitherMethod.BAYER_2, DitherMethod.BAYER_4]:
            size = 2 if method == DitherMethod.BAYER_2 else 4
            return self._apply_ordered_dither(img, size)
            
        elif method in [DitherMethod.STUCKI, DitherMethod.JARVIS, DitherMethod.BURKES, DitherMethod.SIERRA3]:
            return self._apply_error_diffusion_custom(img, method)
            
        return img.quantize(palette=self._palette_image, dither=Image.FLOYDSTEINBERG)