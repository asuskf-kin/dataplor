import unicodedata
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator


class DataplorRecord(BaseModel):
    """
    Pydantic model to validate and transform Dataplor records.
    Allows extra fields to preserve the original DataFrame structure.
    """

    model_config = ConfigDict(extra="allow")

    name: Any
    name_normalized: Any | None = None

    @model_validator(mode="after")
    def process_name_field(self) -> DataplorRecord:
        """
        Strips accents, converts to uppercase, and trims whitespace from the 'name' field,
        assigning the result to 'name_normalized'.
        """
        if isinstance(self.name, str):
            no_accents = "".join(
                c
                for c in unicodedata.normalize("NFD", self.name)
                if unicodedata.category(c) != "Mn"
            )
            self.name_normalized = no_accents.upper().strip()
        else:
            self.name_normalized = self.name

        return self


def normalize_names(df: pl.DataFrame) -> pl.DataFrame:
    """
    Processes a DataFrame to normalize the 'name' column using Pydantic validation.
    """
    # to_dicts() en Polars devuelve directamente la lista de diccionarios
    records = df.to_dicts()
    validated_records = [DataplorRecord(**row).model_dump() for row in records]

    # Reconstruimos usando pl.DataFrame
    return pl.DataFrame(validated_records, infer_schema_length=None)
