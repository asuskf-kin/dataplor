# Color — design source masters

The official Kin color artwork. These are the **designer-facing** source of truth;
their **code counterpart** is `../tokens/colors_and_type.css`. The hex values in the
CSS tokens and the `.ase` swatches **must always agree**.

## source/

| File | Use |
|------|-----|
| `Kin_Color_RGB.ase` | Adobe Swatch Exchange — load into Illustrator/Photoshop/InDesign for screen work |
| `Kin_Color_RGB.ai`  | Illustrator master, RGB |
| `Kin_Color_RGB.pdf` | Printable color reference, RGB |
| `Kin_Color_CMYK.ase`| Swatch Exchange for print (CMYK) |
| `Kin_Color_CMYK.ai` | Illustrator master, CMYK |

> **RGB** for anything on screen (web, slides, video). **CMYK** for print — and
> remember Kin Yellow (`#E5FF01` / Pantone 394) can shift in CMYK, so proof before
> production (see §02 in SKILL.md).

The canonical palette values (hex + RGB + CMYK + Pantone) are tabulated in `SKILL.md`
§02; the reusable CSS variables live in `../tokens/colors_and_type.css`.
