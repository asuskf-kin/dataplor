---
name: marcar-franquicias
description: LEGACY — proceso manual anterior al agente; para una corrida nueva usa /limpiar-dataplor (su paso franchise_review marca y elimina franquicias dentro del flujo). Esta skill solo sirve para rehacer a mano una salida vieja de México. Marca qué registros de la salida del pipeline Dataplor (México) son franquicias o cadenas —columna es_franquicia Sí/No + franquicia_marca en un <archivo>_v2.csv y un TXT con los nombres encontrados— y regenera el reporte ejecutivo (report.ipynb) descontando esas franquicias como "Borrados a mano", con el embotellador en el nombre del reporte. Úsala cuando pidan "revisa si es franquicia", "marca las franquicias", "crea el v2", "lista de nombres encontrados", "borrados a mano", "actualiza el reporte / el notebook" o "ahora con data/processed/mx/<embotellador>/...csv".
---

# Marcar franquicias y actualizar el reporte ejecutivo

> **Legacy.** El agente (`/limpiar-dataplor`) ya hace esto dentro del flujo: `franchise_review` (Claude marca
> las franquicias), `confirm_franchises` (eliminar sí/no) y el reporte ejecutivo en silver. `report.ipynb`
> vive en `legacy/`. Usa esta skill solo para rehacer a mano una salida antigua; ver `docs/runbook.md`.

Proceso para un embotellador (`arca`, `bepensa`, `cdf`, `colima`, `femsa`, `nayar`, `rica`, …).
Todo se corre **desde `data_cleaning/`** con el venv del proyecto. En Windows (Git Bash):

```bash
PY=.venv/Scripts/python.exe
SK=.claude/skills/marcar-franquicias/scripts
export PYTHONIOENCODING=utf-8   # la consola cp1252 rompe con acentos y emojis
```

`<csv>` = `data/processed/mx/<embotellador>/dataplor_final_pipeline_output_mx.csv`

## 1. Antes de empezar

- `config.yaml` → `paths.raw_data` y `paths.output_data` apuntan al embotellador.
- `data/dropped/0X_*.csv` son de la **última** corrida de `main.py`. Si la salida es de otra corrida,
  correr antes `main.py` con `save_drops=True`; si no, el reporte no cuadra.
  - Un paso que no descarta nada **no reescribe** su CSV: queda el de una corrida anterior. El
    notebook ignora (y lista como "ignorado") todo CSV cuyos ids no están en la entrada actual.
  - Módulo 0 (vida nocturna, opcional en `modules_to_run`): sus descartes van en
    `00_nightlife_kept.csv` (pese al nombre, son los que **no** son nocturnos; motivo
    `0_Not_Nightlife`). El notebook lo muestra como paso "0 · Vida nocturna". Con el módulo 0 la
    salida es toda On Premise, y `main.py` se salta el módulo 5.
- Si el CSV crudo es idéntico al de otro embotellador ya trabajado (`cmp -s`), las marcas ya
  revisadas lo cubren: ir directo al paso 3 (pasó con `rica` = `cdf`).

## 2. Revisar y ampliar las marcas (lo que requiere criterio)

```bash
$PY $SK/marcar_franquicias.py <csv>        # diagnóstico, no escribe nada
$PY $SK/descubrir_cadenas.py <csv>         # prefijos repetidos y dominios compartidos
```

1. **Cadenas regionales nuevas.** En la salida de `descubrir_cadenas.py`, buscar MARCAS que se
   repitan en varias ciudades (p. ej. `farmacias sufacen:39:12`, `carniceria el granjero`,
   `tower pizza`) y dominios propios (`sufacen.com`). Ignorar nombres genéricos
   ("tacos el guero", "abarrotes la esquina", "cocina economica", "farmacia de genericos").
   Ante la duda, mirar los nombres reales con polars antes de agregar.
2. **Agregar** cada marca confirmada como regex sobre `name_clean` (minúsculas, sin acentos):
   - On Premise (restaurantes, bares, cafés, hoteles, gimnasios, casinos, escuelas) → `brands.py`
   - Off Premise (farmacias, conveniencia, súper, carnicerías, panaderías, gasolineras) → `brands_off.py`
   - Dominio corporativo → `domains_map.py`
3. **Revisar lo detectado solo por sitio web** (líneas `[web]` del diagnóstico). La fuente pega
   dominios de cadenas a negocios homónimos (`lasalitas.com` en "Mr Alitas",
   `farmaciasdesimilares.com` en "Farmacia de Dios"). Si el dominio es mayormente basura, quitarlo
   de `domains_map.py`; si solo algunos nombres fallan, bloquearlos en `dom_block.py`.
4. **Editar las listas con el editor, no con `sed`/`python -c`**: los `\b` y `\s` de los regex se
   rompen al pasar por el shell (un `\b` termina como carácter de retroceso y la regex deja de
   coincidir sin dar error).
5. Repetir el diagnóstico hasta que las muestras se vean bien. Criterios y casos ya decididos:
   [reference.md](reference.md).

## 3. Escribir el `_v2` y el TXT

```bash
$PY $SK/marcar_franquicias.py --write <csv>
```

Genera junto al CSV:
- `<csv sin .csv>_v2.csv` — mismas filas y columnas + `es_franquicia` (Sí/No) y `franquicia_marca`.
- `franquicias_encontradas_<embotellador>_v2.txt` — resumen por marca y todos los nombres encontrados.

Nunca toca el CSV original. Verificar que el `_v2` conserva las columnas originales idénticas
(`n[o.columns].equals(o)` con pandas leyendo todo como `str`).

## 4. Regenerar el reporte ejecutivo

`report.ipynb` está en `.gitignore` (`*.ipynb`). Si en `data_cleaning/` no existe o no tiene la
sección "Borrados a mano", copiar la plantilla de esta skill:

```bash
grep -q "Borrados a mano" report.ipynb 2>/dev/null || cp .claude/skills/marcar-franquicias/assets/report_notebook.json report.ipynb
.venv/Scripts/jupyter.exe nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=1800 report.ipynb
```

El notebook:
- toma el país, la entrada y la salida de `config.yaml`; `CANAL = "On Premise"` en la celda de parámetros;
- busca `<salida>_v2.csv` y descuenta las franquicias del canal como paso **"8 · Borrados a mano
  (franquicias)"** (embudo, tarjetas, sección 4b y hoja "Borrados a mano" del Excel);
- nombra los archivos `reporte_ejecutivo_{pais}_{canal}_{bottler}_{fecha}` (plantilla en
  `config.yaml → reporte.nombre`). `{bottler}` = carpeta del CSV de entrada; para forzarlo,
  `reporte.bottler: "Nayar"`. HTML, PDF y Excel comparten la misma fecha;
- guarda el entregable en `<salida>_on_premise_sin_franquicias.csv` y **nunca sobrescribe** un CSV
  existente (puede tener ediciones a mano): para regenerarlo, `exportar_canal(sobrescribir=True)`.

Revisar en la salida de la celda de carga: `✅ Cuadratura correcta` y que no haya avisos ⚠️.

## 5. Qué reportar al usuario

Embudo (inicial → pipeline → canal → borrados a mano → entregable), cuántas franquicias y marcas,
las marcas nuevas agregadas, lo dudoso que conviene revisar (detectado solo por sitio web) y las
rutas del `_v2`, el TXT y los tres archivos del reporte.
