"""
Határérték-figyelő — jogszabályi küszöbök és threshold-ok.
Forrás: NAV / PM hivatalos közlemények, dátumozva.
"""
from datetime import datetime, timezone

# ── Hivatalos határértékek (NAV/PM közlemények alapján) ──
# Format: (év, limit_érték, megjegyzés)
ALANYI_MENTES_LIMITS = [
    (2024, 20000000, '20M — 2024'),
    (2025, 22000000, '22M — 2025'),
    (2026, 24000000, '24M — 2026'),
]

KIVA_HEADCOUNT_LIMIT = 100  # fő (küszöb: 100 fő felett NEM választható / maradhat KIVA)
KIVA_REVENUE_LIMIT = 3000000000  # 3 Mrd (2026)

QUARTERLY_VAT_LIMIT = 100000000  # 100M (negyedéves áfás lehet ha < 100M / év)

EV_REVENUE_LIMIT = 20000000  # 20M (egyéni vállalkozó főállású?)


def get_alanyi_mentes_limit(year=None):
    """Visszaadja az alanyi mentes határt az adott évben."""
    if year is None:
        year = datetime.now(timezone.utc).year
    for y, limit, _ in reversed(ALANYI_MENTES_LIMITS):
        if y <= year:
            return limit
    return ALANYI_MENTES_LIMITS[-1][1]


def check_client_thresholds(client):
    """Visszaadja az összes érintett határérték-riasztást egy ügyfélre."""
    alerts = []
    now_year = datetime.now(timezone.utc).year

    # 1. Alanyi mentes
    alanyi_limit = get_alanyi_mentes_limit(now_year)
    if client.annual_revenue > 0:
        ratio = client.annual_revenue / alanyi_limit
        if ratio >= 1.0:
            alerts.append({
                'type': 'alanyi_mentes',
                'name': f'Alanyi mentes határ átlépve ({now_year})',
                'current': f'{client.annual_revenue:,.0f} Ft',
                'limit': f'{alanyi_limit:,.0f} Ft',
                'direction': 'above',
                'severity': 'critical' if ratio > 1.1 else 'warning',
                'detail': f'Az ügyfél árbevétele ({client.annual_revenue:,.0f} Ft) meghaladja '
                          f'a {now_year}-es alanyi mentes határt ({alanyi_limit:,.0f} Ft). '
                          f'{"Sürgős intézkedés szükséges!" if ratio > 1.1 else "Figyelendő!"}',
            })
        elif ratio >= 0.8:
            alerts.append({
                'type': 'alanyi_mentes',
                'name': f'Alanyi mentes határ közelítése ({now_year})',
                'current': f'{client.annual_revenue:,.0f} Ft',
                'limit': f'{alanyi_limit:,.0f} Ft',
                'direction': 'approaching',
                'severity': 'warning',
                'detail': f'Az ügyfél árbevétele ({client.annual_revenue:,.0f} Ft) '
                          f'közelíti a {now_year}-es alanyi mentes határt ({alanyi_limit:,.0f} Ft).',
            })

    # 2. KIVA létszámhatár
    if client.kiva_elective and client.employee_count > KIVA_HEADCOUNT_LIMIT * 0.8:
        alerts.append({
            'type': 'kiva_headcount',
            'name': 'KIVA létszámhatár közelítése',
            'current': f'{client.employee_count} fő',
            'limit': f'{KIVA_HEADCOUNT_LIMIT} fő',
            'direction': 'approaching',
            'severity': 'warning',
            'detail': f'A KIVA foglalkoztatotti határ {KIVA_HEADCOUNT_LIMIT} fő. '
                      f'Az ügyfél jelenleg {client.employee_count} főt foglalkoztat.',
        })

    # 3. Negyedéves áfa határ
    if client.vat_quarterly and client.annual_revenue > QUARTERLY_VAT_LIMIT:
        alerts.append({
            'type': 'quarterly_vat',
            'name': 'Negyedéves áfa határ átlépve',
            'current': f'{client.annual_revenue:,.0f} Ft',
            'limit': f'{QUARTERLY_VAT_LIMIT:,.0f} Ft',
            'direction': 'above',
            'severity': 'critical',
            'detail': f'A negyedéves áfamentesség határa {QUARTERLY_VAT_LIMIT:,.0f} Ft. '
                      f'Az ügyfél árbevétele {client.annual_revenue:,.0f} Ft — '
                      f'havi áfás lesz!',
        })

    return alerts


# ── Default NAV adókód-mapping ──
# (üzlettípus, áfakulcs, fordított adózás) → NAV kód
DEFAULT_TAX_MAP = [
    {'internal': 'TERMEK_ERTEKESITES_BELFOLD', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': False, 'desc': 'Termék értékesítés belföldön, 27% áfa'},
    {'internal': 'TERMEK_ERTEKESITES_BELFOLD_5', 'nav_code': 'AAM', 'vat_rate': '5%', 'reverse_charge': False, 'desc': 'Termék értékesítés belföldön, 5% áfa'},
    {'internal': 'TERMEK_ERTEKESITES_BELFOLD_18', 'nav_code': 'AAM', 'vat_rate': '18%', 'reverse_charge': False, 'desc': 'Termék értékesítés belföldön, 18% áfa'},
    {'internal': 'TERMEK_ERTEKESITES_EU', 'nav_code': 'EAM', 'vat_rate': '0%', 'reverse_charge': True, 'desc': 'Termék értékesítés EU-ban, fordított adózás'},
    {'internal': 'TERMEK_ERTEKESITES_EUN_KIVUL', 'nav_code': 'TAM', 'vat_rate': '0%', 'reverse_charge': False, 'desc': 'Termék értékesítés EU-n kívül'},
    {'internal': 'SZOLGALTATAS_BELFOLD', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': False, 'desc': 'Szolgáltatás belföldön, 27% áfa'},
    {'internal': 'SZOLGALTATAS_EU', 'nav_code': 'EAM', 'vat_rate': '0%', 'reverse_charge': True, 'desc': 'Szolgáltatás EU-ban, fordított adózás'},
    {'internal': 'IRODAI_SZOLGALTATAS', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': False, 'desc': 'Irodai szolgáltatás, 27% áfa'},
    {'internal': 'BERLETI_DIJ', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': False, 'desc': 'Bérleti díj, 27% áfa'},
    {'internal': 'BERLETI_DIJ_LAKAS', 'nav_code': 'AAM', 'vat_rate': '5%', 'reverse_charge': False, 'desc': 'Lakás bérleti díj, 5% áfa (alanyi mentes is lehet)'},
    {'internal': 'PENZUGYI_SZOLGALTATAS', 'nav_code': 'AAM', 'vat_rate': '0%', 'reverse_charge': False, 'desc': 'Pénzügyi szolgáltatás, adómentes'},
    {'internal': 'EGYEB_BELFOLD', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': False, 'desc': 'Egyéb belföldi értékesítés'},
    {'internal': 'FORDITOTT_ADÓZAS_EPITES', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': True, 'desc': 'Építőipari fordított adózás'},
    {'internal': 'FORDITOTT_ADÓZAS_HULLADEK', 'nav_code': 'AAM', 'vat_rate': '0%', 'reverse_charge': True, 'desc': 'Hulladék-értékesítés fordított adózás'},
    {'internal': 'IMPORT_SZOLGALTATAS', 'nav_code': 'AAM', 'vat_rate': '27%', 'reverse_charge': True, 'desc': 'Import szolgáltatás, fordított adózás'},
]