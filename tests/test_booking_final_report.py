from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import load_workbook

from automations.booking_domain import (
    REPORT_HEADERS,
    final_report_record,
    source_columns,
)
from automations.booking_reports import save_report_excel


class FinalReportTests(TestCase):
    headers = [
        "Número da reserva",
        "Nome do hóspede",
        "Check-in",
        "Check-out",
        "Diárias",
        "Comissão %",
        "Status",
        "Valor original (BRL)",
        "Valor final (BRL)",
        "Valor de comissão (BRL)",
        "Observações",
    ]

    def record(
        self, status: str = "Concluída"
    ) -> tuple[dict[str, str], dict[str, str | None]]:
        values = [
            "123",
            "Ana",
            "1º de jun. de 2026",
            "2 de jun. de 2026",
            "1",
            "16",
            status,
            "R$ 100,00",
            "R$ 100,00",
            "R$ 16,00",
            "",
        ]
        return dict(zip(self.headers, values)), source_columns(self.headers)

    def test_projects_booking_data_to_sheet0_schema(self):
        record, columns = self.record()
        record.update(
            {
                "Conferência": "OK",
                "Itens agrupados": "1",
                "Valor Booking calculado": "R$ 100,00",
                "Valor OPERA": "R$100.00",
            }
        )

        report = final_report_record(record, columns)

        self.assertEqual(tuple(report), REPORT_HEADERS)
        self.assertEqual(report["Número da reserva"], "123")
        self.assertEqual(report["Nome do hóspede"], "Ana")
        self.assertEqual(str(report["Valor Booking"]), "100.00")
        self.assertEqual(str(report["Valor OPERA"]), "100.00")
        self.assertEqual(report["Status"], "OK")

    def test_maps_uncharged_statuses(self):
        no_show, columns = self.record("Não comparecimento")
        no_show["Conferência"] = "NÃO CONFERIDA - REGRA"
        cancelled, _ = self.record("Cancelada")
        cancelled["Conferência"] = "NÃO CONFERIDA - REGRA"

        self.assertEqual(final_report_record(no_show, columns)["Status"], "NO_SHOW")
        self.assertEqual(final_report_record(cancelled, columns)["Status"], "CANCELLED")

    def test_divergence_keeps_values_in_dedicated_columns(self):
        record, columns = self.record()
        record.update(
            {
                "Conferência": "DIVERGENTE",
                "Valor Booking calculado": "R$ 100,00",
                "Valor OPERA": "R$ 80,00",
            }
        )

        report = final_report_record(record, columns)

        self.assertEqual(report["Status"], "DIVERGENTE")
        self.assertEqual(str(report["Valor Booking"]), "100.00")
        self.assertEqual(str(report["Valor OPERA"]), "80.00")
        self.assertEqual(report["Observações"], "")

    def test_excel_uses_sheet0_layout_and_numeric_currency(self):
        record, columns = self.record()
        record["Conferência"] = "OK"
        report = final_report_record(record, columns)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            save_report_excel(path, REPORT_HEADERS, [report])
            workbook = load_workbook(path, data_only=False)
            sheet = workbook["Conferência"]

            self.assertEqual(sheet["A1"].value, "Número da reserva")
            self.assertEqual(sheet["G1"].value, "Observações")
            self.assertEqual(sheet["C2"].value, 100)
            self.assertEqual(sheet["F2"].value, "OK")
            self.assertFalse(sheet.merged_cells.ranges)
