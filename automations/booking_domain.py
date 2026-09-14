from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from threading import Event

from automations.booking_models import AutomationCancelled, Progress

COMPLETED_STATUSES = {"ok", "concluida", "completed", "stayed"}
CURRENCY_PATTERN = re.compile(r"R\$\s*[\d.,]+")
REPORT_HEADERS = (
    "Número da reserva",
    "Nome do hóspede",
    "Valor Booking",
    "Comissão Booking",
    "Valor OPERA",
    "Diferença",
    "Status",
    "Observações",
)


def notify(progress: Progress | None, message: str, value: float) -> None:
    if progress:
        progress(message, value)


def checkpoint(cancel: Event | None) -> None:
    if cancel and cancel.is_set():
        raise AutomationCancelled("Execução cancelada pelo usuário.")


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return (
        "".join(char for char in text if not unicodedata.combining(char))
        .casefold()
        .strip()
    )


def normalized_lines(value: object) -> tuple[str, ...]:
    return tuple(
        normalized
        for line in str(value or "").splitlines()
        if (normalized := normalize(line))
    )


def parse_single_currency(value: str) -> Decimal:
    number = value.replace("R$", "", 1).replace("\xa0", "").replace(" ", "").strip()
    if not number:
        raise ValueError("Valor monetário vazio.")
    if "." in number and "," in number:
        decimal_separator = "." if number.rfind(".") > number.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        number = number.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in number:
        number = (
            number.replace(".", "").replace(",", ".")
            if len(number.rsplit(",", 1)[-1]) == 2
            else number.replace(",", "")
        )
    elif "." in number and len(number.rsplit(".", 1)[-1]) != 2:
        number = number.replace(".", "")
    try:
        return Decimal(number)
    except InvalidOperation as error:
        raise ValueError(f"Valor monetário inválido: {value}") from error


def parse_currency(value: object) -> Decimal:
    text = str(value or "")
    monetary_values = CURRENCY_PATTERN.findall(text)
    if not monetary_values:
        monetary_values = [line.strip() for line in text.splitlines() if line.strip()]
    if not monetary_values:
        raise ValueError("Valor monetário vazio.")
    return sum(map(parse_single_currency, monetary_values), start=Decimal("0"))


def format_currency(value: Decimal) -> str:
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def match_header(
    normalized: dict[str, str],
    aliases: tuple[str, ...],
    prefixes: tuple[str, ...] = (),
) -> str | None:
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return next(
        (
            header
            for key, header in normalized.items()
            if any(key.startswith(prefix) for prefix in prefixes)
        ),
        None,
    )


def source_columns(headers: list[str]) -> dict[str, str | None]:
    normalized = {normalize(header): header for header in headers}
    columns = {
        "reservation": match_header(
            normalized,
            (
                "numero da reserva",
                "book number",
                "booking number",
                "reservation number",
            ),
        ),
        "guest": match_header(
            normalized,
            ("nome do hospede", "guest name"),
        ),
        "booked_on": match_header(
            normalized, ("reservado em", "data da reserva", "booked on")
        ),
        "arrival": match_header(normalized, ("check-in", "check in", "arrival")),
        "departure": match_header(normalized, ("check-out", "check out", "departure")),
        "rooms": match_header(normalized, ("quartos", "rooms")),
        "persons": match_header(
            normalized, ("pessoas", "hospedes", "guests", "persons")
        ),
        "nights": match_header(normalized, ("diarias", "room nights", "nights")),
        "commission_percent": match_header(
            normalized,
            ("comissao %", "commission %", "commission percentage"),
        ),
        "status": match_header(normalized, ("status", "result")),
        "original": match_header(
            normalized,
            (),
            ("valor original", "original amount"),
        ),
        "final": match_header(
            normalized,
            (),
            ("valor final", "final amount"),
        ),
        "commission": match_header(
            normalized,
            (),
            ("valor de comissao", "commission amount"),
        ),
        "notes": match_header(
            normalized,
            (),
            ("observac", "notes", "remarks"),
        ),
    }
    required = ("reservation", "status", "original", "final", "commission")
    missing = [name for name in required if columns[name] is None]
    if missing:
        raise RuntimeError(
            "Colunas obrigatórias não encontradas no relatório da Booking: "
            + ", ".join(missing)
        )
    return columns


def should_compare(record: dict[str, str], columns: dict[str, str | None]) -> bool:
    raw_status = record[str(columns["status"])]
    statuses = normalized_lines(raw_status)
    if statuses and all(status in COMPLETED_STATUSES for status in statuses):
        return True
    status = normalize(raw_status)
    notes_key = columns["notes"]
    notes = normalize(record.get(str(notes_key), "")) if notes_key else ""
    cancelled = "cancel" in status or "chargeable cancellation" in notes
    no_show = any(
        token in status or token in notes
        for token in ("nao comparecimento", "no show", "no_show")
    )
    commission_charged = has_positive_amount(record, columns, "commission")
    if cancelled:
        return commission_charged and (
            has_positive_amount(record, columns, "final")
            or has_positive_amount(record, columns, "original")
        )
    return no_show and commission_charged and has_positive_amount(
        record, columns, "final"
    )


def has_positive_amount(
    record: dict[str, str], columns: dict[str, str | None], key: str
) -> bool:
    try:
        return parse_currency(record[str(columns[key])]) > 0
    except ValueError:
        return False


def calculate_booking_total(
    record: dict[str, str], columns: dict[str, str | None]
) -> Decimal:
    try:
        final_amount = parse_currency(record[str(columns["final"])])
    except ValueError:
        final_amount = Decimal("0")
    status = normalize(record[str(columns["status"])])
    if final_amount <= 0 and "cancel" in status:
        return parse_currency(record[str(columns["original"])])
    return final_amount


def consolidate_grouped_record(
    record: dict[str, str], columns: dict[str, str | None]
) -> bool:
    """Collapse every item of a grouped Booking reservation into one record."""

    guest_key = columns.get("guest")
    guests = normalized_lines(record.get(str(guest_key), "")) if guest_key else ()
    monetary_keys = {str(columns[key]) for key in ("original", "final", "commission")}
    group_size = max(
        len(guests),
        len(normalized_lines(record.get(str(columns["status"]), ""))),
        *(
            len(CURRENCY_PATTERN.findall(str(record.get(key, ""))))
            for key in monetary_keys
        ),
    )
    record["Itens agrupados"] = str(max(group_size, 1))
    if group_size <= 1:
        return False

    additive_keys = {
        str(columns[key]) for key in ("rooms", "persons", "nights") if columns.get(key)
    }
    for key, value in tuple(record.items()):
        lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        if len(lines) <= 1:
            continue
        if key in monetary_keys:
            record[key] = format_currency(parse_currency(value))
            continue
        if key in additive_keys:
            try:
                record[key] = str(
                    sum(Decimal(line.replace(",", ".")) for line in lines)
                )
                continue
            except InvalidOperation:
                pass
        record[key] = " | ".join(dict.fromkeys(lines))
    return True


def source_value(
    record: dict[str, str], columns: dict[str, str | None], key: str
) -> str:
    header = columns.get(key)
    return str(record.get(header, "")).strip() if header else ""


def decimal_value(value: str) -> Decimal | str:
    if not value:
        return ""
    try:
        return parse_currency(value)
    except ValueError:
        return value


def final_status(record: dict[str, str], columns: dict[str, str | None]) -> str:
    conference = record.get("Conferência", "PENDENTE")
    if conference != "NÃO CONFERIDA - REGRA":
        return conference
    statuses = normalized_lines(source_value(record, columns, "status"))
    if statuses and all(
        any(token in status for token in ("nao comparecimento", "no show", "no_show"))
        for status in statuses
    ):
        return "NO_SHOW"
    if statuses and all("cancel" in status for status in statuses):
        return "CANCELLED"
    return "NÃO_CONFERIDA"


def final_report_record(
    record: dict[str, str], columns: dict[str, str | None]
) -> dict[str, object]:
    status = final_status(record, columns)
    source_status = normalize(source_value(record, columns, "status"))
    observation = source_value(record, columns, "notes")
    if status == "OK" and any(
        token in source_status for token in ("nao comparecimento", "no show", "no_show")
    ):
        observation = "NO SHOW" if not observation else f"NO SHOW | {observation}"
    elif status.startswith("ERRO:"):
        observation = status.removeprefix("ERRO:").strip()
        status = "ERRO"

    booking_amount = str(record.get("Valor Booking calculado", "")) or source_value(
        record, columns, "final"
    )
    values = (
        source_value(record, columns, "reservation"),
        source_value(record, columns, "guest"),
        decimal_value(booking_amount),
        decimal_value(source_value(record, columns, "commission")),
        decimal_value(str(record.get("Valor OPERA", ""))),
        decimal_value(str(record.get("Diferença", ""))),
        status,
        observation,
    )
    return dict(zip(REPORT_HEADERS, values, strict=True))


def compare_records(
    records: list[dict[str, str]],
    columns: dict[str, str | None],
    total_lookup: Callable[[str], str],
    progress: Progress | None = None,
    cancel: Event | None = None,
    after_record: Callable[[list[dict[str, str]]], None] | None = None,
) -> None:
    eligibility = [should_compare(record, columns) for record in records]
    eligible_count = sum(eligibility)
    processed = 0
    opera_totals: dict[str, str] = {}
    for record, eligible in zip(records, eligibility, strict=True):
        checkpoint(cancel)
        booking_amount: Decimal | None = None
        try:
            booking_amount = calculate_booking_total(record, columns)
            record["Valor Booking calculado"] = format_currency(booking_amount)
        except ValueError:
            record["Valor Booking calculado"] = ""
        record["Valor OPERA"] = ""
        record["Diferença"] = ""
        if not eligible:
            record["Conferência"] = "NÃO CONFERIDA - REGRA"
            continue

        reservation = record[str(columns["reservation"])].strip()
        try:
            if reservation not in opera_totals:
                opera_totals[reservation] = total_lookup(reservation)
            opera_text = opera_totals[reservation]
            if booking_amount is None:
                booking_amount = calculate_booking_total(record, columns)
            difference = booking_amount - parse_currency(opera_text)
            record["Valor OPERA"] = opera_text
            record["Diferença"] = str(difference).replace(".", ",")
            record["Conferência"] = (
                "OK" if abs(difference) <= Decimal("0.01") else "DIVERGENTE"
            )
        except AutomationCancelled:
            raise
        except Exception as error:
            record["Conferência"] = f"ERRO: {error}"

        processed += 1
        if after_record:
            after_record(records)
        notify(
            progress,
            f"Reserva {reservation}: {record['Conferência']}",
            0.30 + 0.65 * processed / max(eligible_count, 1),
        )
