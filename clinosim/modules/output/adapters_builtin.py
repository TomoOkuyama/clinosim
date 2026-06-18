"""Built-in output adapters (CSV, FHIR R4) — thin wrappers over the existing converters.

Heavy converter modules are lazy-imported inside convert() so importing this module just
defines + registers the adapters (no import cycle, no heavy import cost).
"""

from __future__ import annotations

from clinosim.modules.output.adapter import OutputContext, register_output_adapter


class CsvAdapter:
    format_id = "csv"
    description = "CSV tables (one file per resource type)"
    subdir = "csv"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.csv_adapter import convert_cif_to_csv

        convert_cif_to_csv(cif_dir, out_dir)


class FhirR4Adapter:
    format_id = "fhir-r4"
    description = "HL7 FHIR R4 Bulk Data NDJSON"
    subdir = "fhir_r4"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

        convert_cif_to_fhir(
            cif_dir, out_dir, country=ctx.country, narrative_version=ctx.narrative_version
        )


register_output_adapter(CsvAdapter())
register_output_adapter(FhirR4Adapter())
