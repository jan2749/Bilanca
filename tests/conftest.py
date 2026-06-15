"""Skupni fixtures za teste."""

from __future__ import annotations

import pytest

# Sintetičen NKBM/OTP izvoz (glava + reprezentativne vrstice), brez pravih podatkov.
# Vključuje: priliv (DOBRO), odhodke (BREME), slovenske znake, končne presledke v opisu
# in pristen dvojnik (dva enaka dviga gotovine istega dne).
NKBM_HEADER = (
    "ŠT. IZPISKA;POGODBA;RAČUN;DATUM KNJIŽENJA;DATUM VALUTE;DOBRO;BREME;VALUTA;NAMEN;"
    "SKLIC V DOBRO;SKLIC V BREME;UDELEŽENEC - RAČUN;UDELEŽENEC - NAZIV;UDELEŽENEC - BIC;"
    "KODA NAMENA;PRILIV V IZVORNI VALUTI;ODLIV V IZVORNI VALUTI;IZVORNA VALUTA"
)

ACC = "SI56040010047301554"

NKBM_ROWS = [
    f"0;{ACC};{ACC};14.06.2026;14.06.2026;;3,99;EUR;APPLE.COM/BILL        ;;;;POS terminal;;;;",
    f"0;{ACC};{ACC};15.06.2026;13.06.2026;;6,89;EUR;SPAR ŠENTJUR          ;;;;SPAR ŠENTJUR          ;;;;",
    f"0;{ACC};{ACC};10.06.2026;10.06.2026;78,35;;EUR;PRILIV NA RAČUN;;SI0020010062026;SI56011006000039211;MDDSZ-DRŽAVNE ŠTIPENDIJE;;STDY;;;",
    # pristen dvojnik: dva enaka dviga gotovine isti dan
    f"4;{ACC};{ACC};29.04.2026;28.04.2026;;30,00;EUR;DVIG GOTOVINE BA02126S;;;{ACC};142J0;;;;",
    f"4;{ACC};{ACC};29.04.2026;28.04.2026;;30,00;EUR;DVIG GOTOVINE BA02126S;;;{ACC};142J0;;;;",
    # vrstica brez datuma / prazna naj se preskoči
    ";;;;;;;;;;;;;;;;;",
]


@pytest.fixture
def nkbm_csv_bytes() -> bytes:
    """Sintetičen NKBM CSV v kodiranju cp1250."""
    text = "\r\n".join([NKBM_HEADER, *NKBM_ROWS]) + "\r\n"
    return text.encode("cp1250")
