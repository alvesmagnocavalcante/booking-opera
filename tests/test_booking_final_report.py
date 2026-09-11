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
        self.assertEqual(report["Reservation number"], "123")
        self.assertEqual(report["Arrival"], "2026-06-01")
        self.assertEqual(report["Departure"], "2026-06-02")
        self.assertEqual(str(report["Rooms"]), "1")
        self.assertEqual(str(report["Final amount"]), "100.00")
        self.assertEqual(report["Status"], "OK")

    def test_maps_uncharged_statuses(self):
        no_show, columns = self.record("Não comparecimento")
        no_show["Conferência"] = "NÃO CONFERIDA - REGRA"
        cancelled, _ = self.record("Cancelada")
        cancelled["Conferência"] = "NÃO CONFERIDA - REGRA"

        self.assertEqual(final_report_record(no_show, columns)["Status"], "NO_SHOW")
        self.assertEqual(final_report_record(cancelled, columns)["Status"], "CANCELLED")

    def test_divergence_records_both_values_in_observation(self):
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
        self.assertEqual(report["OBSERVAÇÕES"], "Booking: R$ 100,00 | OPERA: R$ 80,00")

    def test_excel_uses_sheet0_layout_and_numeric_currency(self):
        record, columns = self.record()
        record["Conferência"] = "OK"
        report = final_report_record(record, columns)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            save_report_excel(path, REPORT_HEADERS, [report])
            workbook = load_workbook(path, data_only=False)
            sheet = workbook["Sheet0"]

            self.assertEqual(sheet["A1"].value, "COMISSÕES BOOKING × OPERA")
            self.assertEqual(sheet["A2"].value, "Reservation number")
            self.assertEqual(sheet["N2"].value, "OBSERVAÇÕES")
            self.assertEqual(sheet["K3"].value, 100)
            self.assertEqual(sheet["M3"].value, "OK")
            self.assertIn("A1:N1", sheet.merged_cells)
