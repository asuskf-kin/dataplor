# Criterios y decisiones ya tomadas

## Qué cuenta como franquicia

"Franquicia" = marca con varias sucursales bajo el mismo nombre, sea franquicia formal o cadena
propia (nacional, internacional o regional). Incluye:

- Restaurantes, cafés, heladerías, pastelerías y bares de cadena (Domino's, El Pechugón, La Zarza,
  Pastes Kiko's, Tierra Garat, Six…).
- Hoteles de cadena y restaurantes dentro de ellos (Marriott, Hilton, Barceló, RIU, One, City
  Express…) y la red OYO / Capital O.
- Casinos (Caliente/Codere, Big Bola, Playcity), gimnasios (Smart Fit, Anytime, Station 24) y
  escuelas en cadena (UVM, UNID, CNCI, Kumon, Inglés Individual).
- Off Premise: farmacias (Similares, del Ahorro, San Pablo, GI, Farmasana, Sufacen, Zapotlán…),
  conveniencia y súper (OXXO, Circle K, Bodega Aurrerá, Merza, Kiosko, Six), carnicerías
  (SuKarne, Kekén, El Granjero), panaderías (Bimbo, Esperanza) y gasolineras (Pemex, Hidrosina,
  Gocsa…).

**No** son franquicia:
- Nombres genéricos repetidos ("cocina económica", "taquería", "tacos el güero", "panadería La Esperanza").
- Clubes de nutrición Herbalife y cafés DXN: son distribuidores independientes.
- "Genéricos y similares": es un término de farmacia genérica, no Dr. Simi.

## Columnas de la fuente que NO sirven

- `chain_name` / `chain_id` vienen vacías en todos los archivos de México.
- `identified_as_chain = True` solo marca nombres genéricos repetidos.
- Las grandes cadenas ya las quita el pipeline (`config/patterns_mx.py`). Lo que queda son sobre
  todo cadenas regionales y sucursales con nombre en clave.

## Sucursales con nombre en clave (se detectan por sitio web)

| Nombre en la fuente | Marca |
|---|---|
| `F A Mexico Sur …`, `FAM …` | Farmacias del Ahorro |
| `BA Express …`, `Bodega … 3722` | Bodega Aurrerá |
| `50CSI Relaciones Exteriores` | OXXO |
| `CCK …`, `Impulsora Circulo CCK` | Circle K |
| `Actopan 3`, `Pachuca 4` | Farmacias Similares (`farmaciasdesimilares.com.mx`) |
| `KK …`, `CD WM …` | Krispy Kreme |
| `TSK …` | SuKarne |
| `1631 Tulancingo` | Bimbo |
| `Kiosco … 12065` | Kiosko |
| `4006 SUP Ensenada`, `Sup Oasis` | Waldo's (`waldos.com`) |
| `MOD …`, `NP Mod …` | Modelorama |
| `Playas 3`, `Mariano II` | De Mis Farmacias (`demisfarmacias.com`, Baja California) |
| `Ley …`, `Law Super Express` | Casa Ley |
| `Aprecio` | Calimax |

## Dominios descartados o bloqueados

- **Quitados** (la fuente los pega a negocios genéricos): `lasalitas.com`, `farmaciasdesimilares.com`,
  `dulcetentacion.com.mx`, `lachilaquila.com.mx`, `loschilaquiles.com`, `fondaargentina.com`,
  `antiguataquerialaoriental.com`, `elcarboncitok.com`, `donpollo.com.mx`, `lataquiza.com.mx`.
- **Bloqueados por nombre** (`dom_block.py`). Ejemplos:
  - "Farmacias Bayardo" no cuenta como Zapotlán.
  - "Farmacia Dermatológica" no cuenta como del Ahorro.
  - "Pollos asados Beto" no cuenta como Pollo Pepe.
  - En Baja California y Sinaloa la fuente mezcla sitios de cadenas de farmacias entre sí.
    "Farmacias El Nuevo Fénix" no cuenta como Dr. Ahorro; "Farmacia Continental" no cuenta como
    Roma; "Farmacia Titán" no cuenta como Integra; "Farmacias Pharmacon" no cuenta como YZA.
    En esos dominios solo cuenta el nombre que contiene la marca.

## Falsos positivos ya corregidos en los regex

- "Denny's" en una rosticería, "Hipocampo" en marisquerías, "Pampas" suelto, "Camino Real" en
  cabañas, "One Pizza"/"One gasolinería" (One solo cuenta con categoría de hotel).
- "Farmacia de la Naval", "Pollería Tutti Frutti", "Tienda de abarrotes Hilton", "Kampai farmacia".
- "Universidad Intercontinental" (no es IHG).
- "Barceló" o "RIU" sueltos en antojitos.

## Datos útiles

- En `bepensa` la primera columna se llama `Barrio`, pero es el nombre comercial; el script usa
  siempre la primera columna como nombre.
- Si un CSV está abierto en LibreOffice aparece un `.~lock.*#`. Leerlo funciona, pero conviene
  avisar: el usuario puede estar editándolo.
- El 6 de octubre de 2026, `rica` y `cdf` tenían el mismo CSV crudo (CDMX/Hidalgo). El 7 de
  octubre `cdf` llegó con otra zona (Baja California y Sinaloa). Siempre comparar con `cmp`;
  no asumir la región por el nombre del embotellador.
- "Hoteles La Jolla" exige categoría de hotel: "La Jolla Nevería y Cafetería" no es el hotel.
