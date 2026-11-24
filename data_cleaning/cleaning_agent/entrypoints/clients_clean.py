"""Comando ``clean-clients``: paso 1 bottler sobre una base de clientes, fuera del grafo.

Usa el mismo validador que el nodo ``validate_clients`` del flujo. Deja el resultado en
el espejo local bajo ``bronze/ko/{pais}/{bottler}/clients/{fecha}``; no sube nada.
"""

import uuid
from argparse import Namespace
from datetime import date
from typing import Any

from cleaning_agent.wiring import client_validator


def clean_clients_command(args: Namespace) -> dict[str, Any]:
    country, bottler = args.country.lower(), args.bottler.lower()
    fecha = args.fecha or date.today().strftime("%Y%m%d")
    run_id = f"clients-bottler-{country}-{bottler}-{fecha}-{uuid.uuid4().hex[:4]}"
    result = client_validator().validate(
        args.src, country, bottler, (args.canal or "todos"), fecha, run_id
    )
    return {"csv": result.csv, "metadata": result.metadata, "qa": result.qa, **result.summary}
