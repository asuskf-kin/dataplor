# config/patterns.py  —  BOLIVIA
# =============================================================================
# Módulo 2: Cadenas (adaptación a Bolivia del listado original de RD)
# Fuente estructural: 1_Limpieza_Duplicados_Cadenas.ipynb
#
# ALCANCE: cadenas principales de Bolivia. Este archivo es más corto que los de
# Chile / RD / Colombia por una razón real del mercado, no por falta de trabajo:
# Bolivia tiene MUCHA menos densidad de cadenas. El comercio está dominado por
# mercados populares, ferias y tiendas de barrio independientes (La Cancha en
# Cochabamba, Los Pozos y La Ramada en Santa Cruz, Rodríguez y Uyustus en
# La Paz). Para esa realidad importan más los patrones GENÉRICOS de la última
# sección que la lista de marcas.
#
# ⚠️ No verificado con fuente web: el presupuesto de búsqueda de la sesión
# estaba agotado. Construido con conocimiento del mercado. Marcado
# "# verificar" lo que conviene confirmar antes de producción.
#
#  - Texto normalizado a minúsculas.
#  - Variantes con y sin tilde.
#  - "# ambiguo" = alto riesgo de falso positivo (ver AMBIGUOUS_PATTERNS).
#  - "# rebrand" = cambió de nombre; útil para colapsar histórico.
#  - "# BO" = término específicamente boliviano que no aparece en otros países.
# =============================================================================

CHAIN_REGEX = [
    # =========================================================================
    # SUPERMERCADOS E HIPERMERCADOS
    # =========================================================================
    r"\bhipermaxi\b",
    r"\bhiper\s?maxi\b",
    r"\bmaxi\b",  # ambiguo
    r"\bfidalga\b",
    r"\bhipermercado\s?fidalga\b",
    r"\bic\s?norte\b",
    r"\bicnorte\b",
    r"\bketal\b",
    r"\bslan\b",
    r"\bt[ií]a\b",  # ambiguo — Tía cerró en Bolivia
    r"\bsupermercado\s?plaza\b",
    r"\bsuper\s?xtra\b",  # verificar
    r"\bsupermercado\b",
    r"\bhipermercado\b",
    r"\bminimercado\b",
    r"\bmicromercado\b",
    r"\bautoservicio\b",
    r"\bfriaca\b",  # verificar
    # =========================================================================
    # MERCADOS, FERIAS Y COMERCIO POPULAR  (# BO — dominante en Bolivia)
    # =========================================================================
    r"\bla\s?cancha\b",
    r"\bcancha\b",  # ambiguo (Cochabamba: mercado gigante)
    r"\bmercado\s?los\s?pozos\b",
    r"\bla\s?ramada\b",
    r"\bmercado\s?rodr[ií]guez\b",
    r"\buyustus\b",
    r"\bhuyustus\b",
    r"\bmercado\s?abasto\b",
    r"\babasto\b",
    r"\bmercado\s?central\b",
    r"\bmercado\s?campesino\b",
    r"\bmercado\s?municipal\b",
    r"\bferia\s?16\s?de\s?julio\b",
    r"\bferia\b",
    r"\bpuesto\s?de\s?feria\b",
    r"\bcaseta\b",
    r"\btienda\s?de\s?barrio\b",
    r"\bkiosko\b",
    r"\bkiosco\b",
    # =========================================================================
    # COMBUSTIBLE Y GAS  (# BO — "surtidor", no "grifo" ni "bencinera")
    # =========================================================================
    r"\bypfb\b",
    r"\byacimientos\s?petrol[ií]feros\b",
    r"\bsurtidor\b",
    r"\bestaci[oó]n\s?de\s?servicio\b",
    r"\bypfb\s?refinaci[oó]n\b",
    r"\bypfb\s?log[ií]stica\b",
    r"\bpetrobras\b",
    r"\bshell\b",
    r"\bgnv\b",
    r"\bglp\b",
    r"\bgas\s?domiciliario\b",
    r"\bgarrafa\b",
    r"\bflamagas\b",  # verificar
    # =========================================================================
    # DELIVERY, APPS Y MARKETPLACES
    # =========================================================================
    r"\bpedidosya\b",
    r"\bpedidos\s?ya\b",
    r"\bpeya\b",
    r"\byaigo\b",
    r"\btuc[aá]n\b",  # verificar
    r"\bindriver\b",
    r"\bin\s?driver\b",
    r"\byango\b",
    r"\buber\b",
    r"\bmercado\s?libre\b",
    r"\bmercadolibre\b",
    r"\bshein\b",
    r"\btemu\b",
    r"\baliexpress\b",
    r"\bmarketplace\b",
    # =========================================================================
    # FARMACIAS
    # =========================================================================
    r"\bfarmacorp\b",
    r"\bfarmacias?\s?ch[aá]vez\b",
    r"\bch[aá]vez\b",  # ambiguo
    r"\bfarmacias?\s?bolivia\b",
    r"\bfarmacia\s?alemana\b",  # verificar
    r"\bfarmacia\b",
    r"\bbotica\b",
    r"\bdroguer[ií]a\b",
    # =========================================================================
    # COMIDA RÁPIDA Y RESTAURANTES DE CADENA
    # =========================================================================
    r"\bburger\s?king\b",
    r"\bsubway\b",
    r"\bkfc\b",
    r"\bpollos?\s?copacabana\b",
    r"\bcopacabana\b",  # ambiguo (lago/ciudad)
    r"\bpollos?\s?chic\b",
    r"\btoby\b",
    r"\bdumbo\b",
    r"\bcasa\s?de\s?campo\b",
    r"\bel\s?aljibe\b",
    r"\bgustu\b",
    r"\bali\s?pacha\b",
    r"\bpopular\b",  # ambiguo
    r"\bjard[ií]n\s?de\s?asia\b",
    r"\bfurusato\b",
    r"\bken\s?chan\b",
    r"\bla\s?suisse\b",
    r"\bel\s?huerto\b",
    r"\blos\s?lomitos\b",  # verificar
    r"\bbroaster\b",
    r"\bpollo\s?broaster\b",
    r"\bpolleria\b",
    r"\bpoller[ií]a\b",
    r"\bchifa\b",
    r"\bchurrasquer[ií]a\b",
    r"\bpensi[oó]n\b",  # BO: almuerzo popular
    r"\bsalte[nñ]er[ií]a\b",
    r"\bsalte[nñ]a\b",  # BO
    r"\bpizzer[ií]a\b",
    r"\beli'?s\s?pizza\b",  # verificar
    # =========================================================================
    # CAFÉ, PANADERÍA, REPOSTERÍA Y HELADOS
    # =========================================================================
    r"\balexander\s?coffee\b",
    r"\balexander\b",  # ambiguo
    r"\bblueberries\b",
    r"\bfridolin\b",
    r"\bvainilla\b",
    r"\bkivon\b",
    r"\bhelados?\s?kivon\b",
    r"\bcaf[eé]\s?bar\b",
    r"\bpaceña\s?caf[eé]\b",  # verificar
    r"\bpanader[ií]a\b",
    r"\bpasteler[ií]a\b",
    r"\bcafeter[ií]a\b",
    r"\bhelader[ií]a\b",
    r"\bconfiter[ií]a\b",
    # =========================================================================
    # RETAIL NO ALIMENTARIO
    # =========================================================================
    r"\bmulticenter\b",
    r"\bcasa\s?ideas\b",  # verificar
    r"\bmanaco\b",
    r"\bbata\b",
    r"\bminiso\b",
    r"\bmumuso\b",
    r"\btodo\s?moda\b",  # verificar
    r"\bhansa\b",
    r"\bimcruz\b",
    r"\btoyosa\b",
    r"\bnibol\b",
    r"\bcrown\s?motors\b",  # verificar
    r"\bmulticine\b",
    r"\bventura\s?mall\b",
    r"\bmegacenter\b",
    r"\bcine\s?center\b",
    r"\bcinemark\b",
    r"\blas\s?brisas\b",
    r"\bferreter[ií]a\b",
    r"\blibrer[ií]a\b",
    r"\bpapeler[ií]a\b",
    r"\bbazar\b",
    r"\bboutique\b",
    r"\bagencia\b",  # ambiguo
    # =========================================================================
    # BANCA  (nómina ASFI)
    # =========================================================================
    r"\bbanco\s?nacional\s?de\s?bolivia\b",
    r"\bbnb\b",
    r"\bbanco\s?mercantil\s?santa\s?cruz\b",
    r"\bbmsc\b",
    r"\bmercantil\b",
    r"\bbanco\s?bisa\b",
    r"\bbisa\b",
    r"\bbanco\s?de\s?cr[eé]dito\s?de\s?bolivia\b",
    r"\bbcp\b",
    r"\bbanco\s?uni[oó]n\b",
    r"\bbanco\s?ganadero\b",
    r"\bbanco\s?econ[oó]mico\b",
    r"\bbanco\s?fortaleza\b",
    r"\bbancosol\b",
    r"\bbanco\s?solidario\b",
    r"\bbanco\s?fie\b",
    r"\bfie\b",  # ambiguo
    r"\bbanco\s?prodem\b",
    r"\bprodem\b",
    r"\bbanco\s?pyme\s?ecofuturo\b",
    r"\becofuturo\b",
    r"\bbanco\s?pyme\s?de\s?la\s?comunidad\b",
    r"\bbanco\s?fassil\b",
    r"\bfassil\b",  # liquidado en 2023
    r"\blos\s?andes\s?procredit\b",
    r"\bprocredit\b",
    r"\bbanco\s?do\s?brasil\b",
    r"\bbanco\s?de\s?la\s?naci[oó]n\s?argentina\b",
    r"\bbanco\s?central\s?de\s?bolivia\b",
    r"\bbcb\b",
    r"\basfi\b",
    r"\bcooperativa\s?jes[uú]s\s?nazareno\b",
    r"\bcooperativa\s?f[aá]tima\b",
    r"\bcooperativa\s?san\s?mart[ií]n\b",
    r"\bcooperativa\s?loyola\b",
    r"\bcooperativa\s?quillacollo\b",
    r"\bcooperativa\s?de\s?ahorro\b",
    r"\bmutual\s?la\s?primera\b",
    r"\bmutual\s?la\s?paz\b",
    r"\bmutual\s?promotora\b",
    r"\bmutual\s?guapay\b",
    r"\bmutual\s?paitit[ií]\b",
    r"\bmutual\b",  # ambiguo
    # =========================================================================
    # MEDIOS DE PAGO Y REMESAS
    # =========================================================================
    r"\btigo\s?money\b",
    r"\blinkser\b",
    r"\bred\s?enlace\b",
    r"\benlace\b",
    r"\batc\b",
    r"\bqr\s?simple\b",
    r"\bpago\s?qr\b",
    r"\bwestern\s?union\b",
    r"\bmoneygram\b",
    r"\bmoney\s?gram\b",
    r"\bria\b",  # ambiguo
    r"\bcasa\s?de\s?cambio\b",
    r"\bpunto\s?de\s?pago\b",
    # =========================================================================
    # SEGUROS Y PENSIONES
    # =========================================================================
    r"\balianza\s?seguros\b",
    r"\bla\s?boliviana\s?ciacruz\b",
    r"\bciacruz\b",
    r"\bnacional\s?seguros\b",
    r"\bcredinform\b",
    r"\bbisa\s?seguros\b",
    r"\bunivida\b",
    r"\bfortaleza\s?seguros\b",
    r"\blatina\s?seguros\b",
    r"\bzurich\b",
    r"\bseguros\b",
    r"\bgestora\s?p[uú]blica\b",
    r"\bgestora\b",  # rebrand: reemplazó a las AFP (2023)
    r"\bafp\s?futuro\b",
    r"\bfuturo\s?de\s?bolivia\b",
    r"\bafp\s?previsi[oó]n\b",
    r"\bprevisi[oó]n\s?bbva\b",
    r"\bafp\b",
    # =========================================================================
    # TELECOMUNICACIONES
    # =========================================================================
    r"\bentel\b",
    r"\btigo\b",
    r"\btelecel\b",
    r"\bviva\b",  # ambiguo
    r"\bnuevatel\b",
    r"\bcotel\b",
    r"\bcotas\b",
    r"\bcomteco\b",
    r"\bcotap\b",
    r"\baxs\b",
    r"\btienda\s?amiga\b",
    r"\bstarlink\b",
    r"\batt\b",
    r"\bautoridad\s?de\s?telecomunicaciones\b",
    # =========================================================================
    # ELECTRICIDAD, AGUA Y SANEAMIENTO
    # =========================================================================
    r"\bende\b",
    r"\bende\s?distribuci[oó]n\b",
    r"\bdelapaz\b",
    r"\belectropaz\b",
    r"\bcre\b",
    r"\belfec\b",
    r"\bcessa\b",
    r"\bsepsa\b",
    r"\belfeo\b",
    r"\bsetar\b",
    r"\bae\b",  # ambiguo (Autoridad de Electricidad)
    r"\bepsas\b",
    r"\bsaguapac\b",
    r"\bsemapa\b",
    r"\belapas\b",
    r"\bcosmol\b",
    r"\bcosphul\b",
    r"\baaps\b",
    r"\bcooperativa\s?de\s?agua\b",
    # =========================================================================
    # SALUD  (# BO — nomenclatura de la red pública y las cajas)
    # =========================================================================
    r"\bcaja\s?nacional\s?de\s?salud\b",
    r"\bcns\b",
    r"\bcaja\s?petrolera\b",
    r"\bcaja\s?bancaria\b",
    r"\bcaja\s?cordes\b",
    r"\bcaja\s?de\s?salud\b",
    r"\bsus\b",
    r"\bsistema\s?[uú]nico\s?de\s?salud\b",
    r"\bhospital\s?obrero\b",
    r"\bhospital\s?de\s?cl[ií]nicas\b",
    r"\bhospital\s?del\s?ni[nñ]o\b",
    r"\bhospital\s?japon[eé]s\b",
    r"\bcl[ií]nica\s?foianini\b",
    r"\bfoianini\b",
    r"\bincor\b",
    r"\bcl[ií]nica\s?angloamericana\b",
    r"\bcl[ií]nica\s?del\s?sur\b",
    r"\bcl[ií]nica\s?rengel\b",
    r"\bcl[ií]nica\s?univalle\b",
    r"\bcentro\s?de\s?salud\b",
    r"\bpuesto\s?de\s?salud\b",
    r"\bposta\s?sanitaria\b",
    r"\bsedes\b",
    r"\bhospital\b",
    r"\bcl[ií]nica\b",
    r"\blaboratorio\b",
    r"\bcaja\b",  # ambiguo
    # =========================================================================
    # EDUCACIÓN  (# BO — "unidad educativa", no "escuela")
    # =========================================================================
    r"\bumsa\b",
    r"\bumss\b",
    r"\buagrm\b",
    r"\busfx\b",
    r"\buto\b",
    r"\bucb\b",
    r"\buniversidad\s?cat[oó]lica\b",
    r"\bupb\b",
    r"\bupsa\b",
    r"\bnur\b",
    r"\bunivalle\b",
    r"\budabol\b",
    r"\bunifranz\b",
    r"\bemi\b",
    r"\butepsa\b",
    r"\bunibol\b",
    r"\bcba\b",
    r"\bcentro\s?boliviano\s?americano\b",
    r"\binfocal\b",
    r"\bunidad\s?educativa\b",
    r"\bu\.?e\.?\b",
    r"\bcolegio\b",
    r"\bkinder\b",
    r"\buniversidad\b",
    r"\binstituto\b",
    r"\bnormal\b",
    # =========================================================================
    # TRANSPORTE  (# BO — teleférico, trufi, flota, minibús)
    # =========================================================================
    r"\bboliviana\s?de\s?aviaci[oó]n\b",
    r"\bboa\b",
    r"\bamaszonas\b",
    r"\becojet\b",
    r"\btam\b",
    r"\baerocon\b",
    r"\bnabol\b",
    r"\bmi\s?telef[eé]rico\b",
    r"\btelef[eé]rico\b",
    r"\bpumakatari\b",
    r"\bpuma\s?katari\b",
    r"\btrufi\b",
    r"\bminib[uú]s\b",
    r"\bmicro\b",
    r"\bflota\b",
    r"\btrans\s?copacabana\b",
    r"\bbol[ií]var\b",  # ambiguo
    r"\bel\s?dorado\b",
    r"\btrans\s?azul\b",
    r"\bterminal\s?bimodal\b",
    r"\bterminal\s?de\s?buses\b",
    r"\bpeaje\b",
    r"\btranca\b",  # BO
    r"\brent\s?a\s?car\b",
    r"\bhertz\b",
    r"\bavis\b",
    r"\blocaliza\b",
    # =========================================================================
    # HOTELERÍA Y ENTRETENCIÓN
    # =========================================================================
    r"\bcamino\s?real\b",
    r"\bcasa\s?grande\b",
    r"\bradisson\b",
    r"\bmarriott\b",
    r"\blos\s?tajibos\b",
    r"\bbuganvillas\b",
    r"\britz\s?apart\b",
    r"\bhotel\s?europa\b",
    r"\bhotel\s?presidente\b",
    r"\breal\s?plaza\b",
    r"\bhotel\s?cortez\b",
    r"\bhoward\s?johnson\b",
    r"\bbest\s?western\b",
    r"\bhotel\s?gloria\b",
    r"\bhotel\s?rosario\b",
    r"\bsonesta\b",
    r"\bairbnb\b",
    r"\bhotel\b",
    r"\bhostal\b",
    r"\balojamiento\b",
    r"\bresidencial\b",
    r"\bsmart\s?fit\b",
    r"\bsmartfit\b",
    r"\bgimnasio\b",
    r"\bcrossfit\b",
    r"\bcasino\b",
    r"\bbingo\b",
    r"\bloter[ií]a\b",
    # =========================================================================
    # INSTITUCIONES PÚBLICAS Y COMUNITARIAS  (# BO)
    # =========================================================================
    r"\balcald[ií]a\b",
    r"\bgobierno\s?aut[oó]nomo\s?municipal\b",
    r"\bgam\b",
    r"\bsubalcald[ií]a\b",
    r"\bgobernaci[oó]n\b",
    r"\bmunicipio\b",
    r"\bjunta\s?vecinal\b",
    r"\bjunta\s?de\s?vecinos\b",
    r"\botb\b",
    r"\borganizaci[oó]n\s?territorial\s?de\s?base\b",  # BO
    r"\bsede\s?social\b",
    r"\bcasa\s?comunal\b",
    r"\bsindicato\b",
    r"\bayllu\b",
    r"\bcomunidad\b",
    r"\bcanton\b",
    r"\bcant[oó]n\b",
    r"\bpolic[ií]a\s?boliviana\b",
    r"\bepi\b",
    r"\bm[oó]dulo\s?policial\b",
    r"\bbomberos\b",
    r"\bdefensa\s?civil\b",
    r"\btr[aá]nsito\b",
    r"\bsegip\b",
    r"\bsereci\b",
    r"\bimpuestos\s?nacionales\b",
    r"\baduana\s?nacional\b",
    r"\bderechos\s?reales\b",
    r"\bine\b",
    r"\bemapa\b",
    r"\bcomedor\s?popular\b",
    r"\bguarder[ií]a\b",
    r"\bcancha\s?polifuncional\b",
    r"\bcoliseo\b",
    r"\bparroquia\b",
    r"\biglesia\b",
    # =========================================================================
    # COMODINES SECTORIALES (baja precisión: usar como última pasada)
    # =========================================================================
    r"\bagro",
    r"\bvet",
    r"\bforraj",
    r"\bvivero\b",
    r"\bcomercial\b",
    r"\bdistribuidora\b",
    r"\bimportadora\b",
    r"\bcomercializadora\b",
    r"\balmac[eé]n\b",
    r"\bdep[oó]sito\b",
    r"\bcarnicer[ií]a\b",
    r"\bverduler[ií]a\b",
    r"\bfrial\b",  # BO: carnicería/frigorífico de barrio
    r"\bel[eé]ctric",
    r"\belectr[oó]nic",
    r"\bcooperativa\b",
    r"\basociaci[oó]n\b",
    r"\bs\.?r\.?l\.?\b",
    r"\bltda\b",
]


# =============================================================================
# Patrones de ALTO riesgo de falso positivo (incluidos arriba).
#     SAFE_CHAIN_REGEX = [p for p in CHAIN_REGEX if p not in AMBIGUOUS_PATTERNS]
#
# Ojo en Bolivia con los topónimos: "Copacabana", "Bolívar", "El Dorado",
# "Las Brisas", "Casa Grande" y "La Paz" son a la vez marcas y lugares.
# =============================================================================
AMBIGUOUS_PATTERNS = {
    r"\bmaxi\b",
    r"\bt[ií]a\b",
    r"\bcancha\b",
    r"\bcopacabana\b",
    r"\bpopular\b",
    r"\balexander\b",
    r"\bch[aá]vez\b",
    r"\bmercantil\b",
    r"\bbisa\b",
    r"\bbcp\b",
    r"\bfie\b",
    r"\bmutual\b",
    r"\bcaja\b",
    r"\bviva\b",
    r"\btigo\b",
    r"\bcre\b",
    r"\bende\b",
    r"\bae\b",
    r"\batc\b",
    r"\bria\b",
    r"\bemi\b",
    r"\bnur\b",
    r"\buto\b",
    r"\bine\b",
    r"\bsus\b",
    r"\bcns\b",
    r"\bboa\b",
    r"\btam\b",
    r"\bmicro\b",
    r"\bflota\b",
    r"\bbol[ií]var\b",
    r"\bel\s?dorado\b",
    r"\blas\s?brisas\b",
    r"\bcasa\s?grande\b",
    r"\breal\s?plaza\b",
    r"\bcamino\s?real\b",
    r"\bcasa\s?de\s?campo\b",
    r"\bagencia\b",
    r"\bferia\b",
    r"\babasto\b",
    r"\bkiosco\b",
    r"\bkiosko\b",
    r"\bgestora\b",
    r"\bafp\b",
    r"\bseguros\b",
    r"\bu\.?e\.?\b",
    r"\bnormal\b",
    r"\bcomunidad\b",
    r"\bcanton\b",
    r"\bcant[oó]n\b",
    r"\bmunicipio\b",
    r"\bsindicato\b",
    r"\bemapa\b",
    r"\bcomercial\b",
    r"\bdistribuidora\b",
    r"\bimportadora\b",
    r"\bcomercializadora\b",
    r"\balmac[eé]n\b",
    r"\bdep[oó]sito\b",
    r"\bcooperativa\b",
    r"\basociaci[oó]n\b",
    r"\bs\.?r\.?l\.?\b",
    r"\bltda\b",
    r"\bsupermercado\b",
    r"\bhipermercado\b",
    r"\bminimercado\b",
    r"\bmicromercado\b",
    r"\bautoservicio\b",
    r"\bsurtidor\b",
    r"\bfarmacia\b",
    r"\bbotica\b",
    r"\bdroguer[ií]a\b",
    r"\bhospital\b",
    r"\bcl[ií]nica\b",
    r"\blaboratorio\b",
    r"\bcolegio\b",
    r"\buniversidad\b",
    r"\binstituto\b",
    r"\bkinder\b",
    r"\bhotel\b",
    r"\bhostal\b",
    r"\balojamiento\b",
    r"\bresidencial\b",
    r"\bgimnasio\b",
    r"\bcasino\b",
    r"\bpanader[ií]a\b",
    r"\bpasteler[ií]a\b",
    r"\bcafeter[ií]a\b",
    r"\bhelader[ií]a\b",
    r"\bpolleria\b",
    r"\bpoller[ií]a\b",
    r"\bchifa\b",
    r"\bpizzer[ií]a\b",
    r"\bpensi[oó]n\b",
    r"\bferreter[ií]a\b",
    r"\blibrer[ií]a\b",
    r"\bpapeler[ií]a\b",
    r"\bbazar\b",
    r"\bboutique\b",
    r"\bparroquia\b",
    r"\biglesia\b",
    r"\bpeaje\b",
    r"\bcoliseo\b",
    r"\bmarketplace\b",
    r"\bvivero\b",
}
