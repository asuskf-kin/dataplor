# Dominios que la fuente pega también a negocios genéricos: el dominio solo cuenta
# si el nombre NO coincide con este patrón (sobre el nombre normalizado).
DOMAIN_NAME_BLOCK = {
    "farmaciasdesimilares.com.mx": r"farmac|pharma|vestir|generic|queseria|unidad\s?habitacional",
    "esperanza.mx": r"panaderia|paneria|^la\s",
    "fahorro.com": r"^(?!f\s?a\b|fam\b|farmac|ahorro)|dermatolog",
    "farmaciasgi.com.mx": r"isame|sanchez|generic|equivalentes|colima|farmasi|farmavida",
    "farmaciasanpablo.com.mx": r"^(?!.*san\s?pablo)",
    "farmaciasunion.com": r"^(?!.*union)", "farmaciasunion.com.mx": r"^(?!.*union)",
    "pollopepe.com": r"^(?!.*pepe)",
    "cafediletto.mx": r"^(?!.*diletto)",
    "pollofeliz.com": r"^(?!.*feliz)",
    "farmatodo.com.mx": r"zapotlan",
    # Farmacias Bayardo es otra cadena: no se cuenta como Zapotlán por el sitio web
    "sfzapotlan.com.mx": r"bayardo", "superfarmaciaszapotlan.com.mx": r"bayardo",
    "mexico.littlecaesars.com": r"^(?!.*little)",
    # Revisión CDF (BC/Sinaloa): dominios pegados a negocios ajenos
    "dominos.com.mx": r"^(?!.*domino)",
    "farmaciasguadalajara.com": r"gasolinera",
    "all.accor.com": r"gasolinera", "restaurants.accor.com": r"gasolinera",
    "dolphy.com.mx": r"^(?!.*dolphy)",
    "laeuropea.com.mx": r"^(?!.*europea)",
    # Farmacias El Nuevo Fénix es otra cadena
    "farmaciasdrahorro.com.mx": r"fenix",
    "farmaciasroma.com": r"^(?!.*roma)",
    "farmaciasintegra.com": r"^(?!.*integra)",
    "farmaciaslamasbarata.com": r"internacional", "farmacialamasbarata.com": r"internacional",
    "yza.mx": r"pharmacon|mision",
    "farmacon.com.mx": r"moderna",
    # Café de la Flor es de Baja California: "La Flor" en Veracruz no es la cadena
    "cafedelaflor.com": r"^(?!.*cafe\s?de\s?la\s?flor)",
}
