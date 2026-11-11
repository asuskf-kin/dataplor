# Photography — gradient-map treatment

Read this when **preparing or processing photos** for Kin materials. The treatment is
format-agnostic (do it once, use the result anywhere). See §04 in SKILL.md for the
concept, don'ts, and subject/tone guidance — this file is the recipe + code.

All Kin photography gets a **Gradient Map (duotone)** that remaps luminosity to two
Kin colors — not a simple grayscale:

| Gradient Stop | Color | Hex | Applies to |
|---------------|-------|-----|------------|
| Shadows (dark tones) | Gray 4 | `#222326` | Blacks and deep shadows |
| Highlights (light tones) | Warm Light Gray | `#D8D8D5` | Whites and bright areas |

The result is a sophisticated desaturated duotone — darker than pure grayscale, with a
warm-neutral cast in the lights. Consistent across all branded photography.

## Photoshop recipe
1. Open photo
2. Add **Gradient Map** adjustment layer (Layer → New Adjustment Layer → Gradient Map)
3. Set gradient stop 0 (shadows) → `#222326`
4. Set gradient stop 1 (highlights) → `#D8D8D5`
5. Highlight midpoint: **56%** (slightly pushed toward shadows for moodier result)
6. Shadow location: adjust per image (typically 8–30% of range) to control black point
7. Blend mode: Normal, Opacity: 100%

## Python replication
```python
from PIL import Image
import numpy as np

def apply_kin_image_treatment(img_path, output_path):
    """
    Apply Kin's gradient map treatment to a photo.
    Shadow → #222326 (Gray 4), Highlight → #D8D8D5
    """
    img = Image.open(img_path).convert('RGB')
    arr = np.array(img, dtype=np.float32) / 255.0

    # Perceptual luminosity
    lum = 0.2126 * arr[:,:,0] + 0.7152 * arr[:,:,1] + 0.0722 * arr[:,:,2]

    # Gradient map: shadow=#222326, highlight=#D8D8D5
    shadow    = (0x22/255, 0x23/255, 0x26/255)  # #222326
    highlight = (0xD8/255, 0xD8/255, 0xD5/255)  # #D8D8D5

    out = np.zeros_like(arr)
    for c in range(3):
        out[:,:,c] = shadow[c] * (1 - lum) + highlight[c] * lum

    result = Image.fromarray((out * 255).clip(0,255).astype(np.uint8))
    result.save(output_path)
    return result

# Usage:
# apply_kin_image_treatment("photo.jpg", "photo_treated.jpg")
```
