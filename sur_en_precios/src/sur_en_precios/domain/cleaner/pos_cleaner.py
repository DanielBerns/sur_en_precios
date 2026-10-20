"""Point of Sale (POS) cleaning and corporate enrichment module.

Standardizes Argentine retail store records from SEPA (Precios Claros):
- Decomposes SEPA codes (comercio_id, bandera_id, sucursal_id, sepa_id).
- Maps corporate entities to official business names, parent holding groups, consumer brand names, and retail formats.
- Sanitizes addresses (removes scraping artifacts like 'none' and trailing zeros, normalizes prefixes).
- Cleans branch names (strips embedded bracketed addresses and redundant prefixes).
- Normalizes cities, extracts neighborhoods, and rectifies state/province assignments with ISO 3166-2:AR codes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class CleanPointOfSale:
    """Cleaned and enriched Point of Sale representation."""

    code: str
    sepa_id: Optional[str]
    comercio_id: Optional[int]
    bandera_id: Optional[int]
    sucursal_id: Optional[int]
    business_name: str
    holding_group: Optional[str]
    brand_name: str
    store_format: str
    branch_name: str
    address: str
    city: str
    province: str
    province_code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# Regex for SEPA code: (comercio_id-bandera_id-sucursal_id)(bandera_slug)
_SEPA_CODE_PATTERN = re.compile(r"^\((\d+)-(\d+)-(\d+)\)\((.+)\)$")

# Corporate & Banner Directory
# Key: (comercio_id, bandera_id) -> (business_name, holding_group, brand_name, store_format)
RETAIL_CHAINS: Dict[Tuple[int, int], Tuple[str, Optional[str], str, str]] = {
    # Carrefour (INC S.A.)
    (10, 1): ("INC S.A.", "Carrefour Group", "Carrefour Hiper", "Hipermercado"),
    (10, 2): ("INC S.A.", "Carrefour Group", "Carrefour Market", "Supermercado"),
    (10, 3): ("INC S.A.", "Carrefour Group", "Carrefour Express", "Proximidad"),
    # Walmart / GDN Argentina (Grupo De Narváez)
    (11, 1): (
        "GDN Argentina (ex Walmart Argentina S.R.L.)",
        "GDN Argentina (Grupo De Narváez)",
        "Hiper ChangoMás",
        "Hipermercado",
    ),
    (11, 2): (
        "GDN Argentina (ex Walmart Argentina S.R.L.)",
        "GDN Argentina (Grupo De Narváez)",
        "ChangoMás",
        "Supermercado",
    ),
    (11, 3): (
        "GDN Argentina (ex Walmart Argentina S.R.L.)",
        "GDN Argentina (Grupo De Narváez)",
        "Súper ChangoMás",
        "Supermercado",
    ),
    (11, 4): (
        "GDN Argentina (ex Walmart Argentina S.R.L.)",
        "GDN Argentina (Grupo De Narváez)",
        "Mi ChangoMás",
        "Proximidad",
    ),
    (11, 5): (
        "GDN Argentina (ex Walmart Argentina S.R.L.)",
        "GDN Argentina (Grupo De Narváez)",
        "Hiper ChangoMás (ex Walmart)",
        "Hipermercado",
    ),
    # Cencosud
    (9, 1): ("Jumbo Retail Argentina S.A.", "Cencosud", "Vea", "Supermercado"),
    (9, 2): ("Jumbo Retail Argentina S.A.", "Cencosud", "Disco", "Supermercado"),
    (9, 3): ("Jumbo Retail Argentina S.A.", "Cencosud", "Jumbo", "Hipermercado"),
    (3001, 1): ("Easy S.A.", "Cencosud", "Easy", "Hogar y Construcción"),
    (3001, 2): ("Easy S.A.", "Cencosud", "Blaisten", "Construcción y Sanitarios"),
    # DIA
    (15, 1): ("DIA Argentina S.A.", "Grupo DIA", "Dia", "Proximidad"),
    # Farmacity (Grupo Pegasus)
    (24, 1): ("Farmacity S.A.", "Grupo Pegasus", "Farmacity", "Farmacia"),
    (24, 2): ("Farmacity S.A.", "Grupo Pegasus", "Farmacity", "Farmacia"),
    (24, 3): ("Farmacity S.A.", "Grupo Pegasus", "Simplicity", "Belleza y Cuidado"),
    # COTO
    (12, 1): (
        "COTO C.I.C.S.A.",
        "COTO Centro Integral de Comercialización",
        "COTO",
        "Hipermercado",
    ),
    # La Anónima
    (2, 1): (
        "S.A. Importadora y Exportadora de la Patagonia",
        "La Anónima",
        "La Anónima",
        "Supermercado",
    ),
    (2, 2): (
        "S.A. Importadora y Exportadora de la Patagonia",
        "La Anónima",
        "La Anónima (ex Topsy)",
        "Supermercado",
    ),
    (2, 3): (
        "S.A. Importadora y Exportadora de la Patagonia",
        "La Anónima",
        "La Anónima (Bomba)",
        "Supermercado",
    ),
    # YPF
    (19, 1): (
        "Operadora de Estaciones de Servicios S.A. (OPESSA)",
        "YPF S.A.",
        "YPF Full",
        "Conveniencia",
    ),
    # Cooperativa Obrera
    (13, 1): (
        "Cooperativa Obrera Limitada de Consumo y Vivienda",
        "Cooperativa Obrera",
        "Cooperativa Obrera",
        "Supermercado",
    ),
    # Átomo (Millán)
    (17, 1): ("Millán S.A.", "Millán S.A.", "Átomo Supermercados", "Supermercado"),
    # Musimundo / Megatone
    (2011, 1): (
        "Electrónica Megatone S.A.",
        "Red Megatone",
        "Musimundo",
        "Electrodomésticos",
    ),
    (2000, 1): ("Carsa S.A.", "Red Megatone / Carsa", "Musimundo", "Electrodomésticos"),
    (2008, 1): ("Bazar Avenida S.A.", "Red Megatone", "Megatone", "Electrodomésticos"),
    # Cetrogar
    (2009, 1): ("Cetrogar S.A.", "Cetrogar", "Cetrogar", "Electrodomésticos"),
    # Frávega
    (2002, 1): (
        "Frávega S.A.C.I. e I.",
        "Grupo Frávega",
        "Frávega",
        "Electrodomésticos",
    ),
    # Naldo
    (2005, 1): ("Naldo Lombardi S.A.", "Naldo Lombardi", "Naldo", "Electrodomésticos"),
    # Grupo Mirgor (GMRA)
    (2003, 1): ("GMRA S.A.", "Grupo Mirgor", "Samsung Store", "Tecnología y Telefonía"),
    (2003, 2): ("GMRA S.A.", "Grupo Mirgor", "Diggit", "Tecnología y Electrónica"),
    (2003, 3): (
        "GMRA S.A.",
        "Grupo Mirgor",
        "Mirgor Retail",
        "Tecnología y Electrónica",
    ),
    # Pan American Energy & Deheza (Axion)
    (23, 1): (
        "Pan American Energy S.L. Sucursal Argentina",
        "Pan American Energy",
        "Spot! / Axion Energy",
        "Conveniencia",
    ),
    (3, 1): (
        "Deheza S.A.I.C.F. e I.",
        "Pan American Energy / Deheza",
        "Spot! / Axion Energy",
        "Conveniencia",
    ),
    # Diarco
    (65, 1): (
        "Distribuidora Mayorista de Alimentos (Diarco)",
        "Grupo Goldfarb",
        "Diarco Mayorista",
        "Mayorista",
    ),
    # Coppel
    (2004, 1): ("Coppel S.A.", "Grupo Coppel", "Coppel", "Tienda Departamental"),
    # Libertad
    (16, 1): (
        "Libertad S.A.",
        "Grupo Libertad",
        "Hipermercado Libertad",
        "Hipermercado",
    ),
    (16, 2): ("Libertad S.A.", "Grupo Libertad", "Mini Libertad", "Proximidad"),
    # Regional Chains
    (1, 1): ("Dinosaurio S.A.", "Grupo Dinosaurio", "Súper Mami", "Hipermercado"),
    (4, 1): (
        "Estación Lima S.A.",
        "Estación Lima S.A.",
        "Estación Lima",
        "Conveniencia",
    ),
    (5, 1): (
        "California S.A.",
        "California S.A.",
        "California Supermercados",
        "Supermercado",
    ),
    (6, 1): ("Alberdi S.A.", "Alberdi S.A.", "Comodín", "Supermercado"),
    (6, 2): ("Alberdi S.A.", "Alberdi S.A.", "Maxi Comodín", "Mayorista"),
    (7, 1): ("Cyre S.A.", "Cyre S.A.", "Cordiez", "Supermercado"),
    (7, 2): ("Cyre S.A.", "Cyre S.A.", "Mercamax", "Mayorista"),
    (8, 1): ("Mariano S.A.", "Mariano Max", "Mariano Max", "Supermercado"),
    (14, 1): (
        "Miguel Becerra S.A.",
        "Supermercados Becerra",
        "Supermercados Becerra",
        "Supermercado",
    ),
    (18, 1): (
        "Aiello Supermercados S.A.",
        "Aiello Supermercados",
        "Súper Aiello",
        "Supermercado",
    ),
    (20, 1): (
        "La Agrícola Regional Coop. Ltda.",
        "La Agrícola Regional",
        "LAR Supermercados",
        "Supermercado",
    ),
    (21, 1): (
        "Supermercados Toledo S.A.",
        "Supermercados Toledo",
        "Toledo",
        "Supermercado",
    ),
    (22, 1): (
        "La Gallega Supermercados S.A.",
        "La Gallega Supermercados",
        "La Gallega",
        "Supermercado",
    ),
    (25, 1): (
        "Autoservicio La Amistad Coop. de Trabajo Ltda.",
        "La Amistad Coop.",
        "Autoservicio La Amistad",
        "Supermercado",
    ),
    (29, 1): ("Josimar S.A.", "Josimar S.A.", "Josimar", "Supermercado"),
    (35, 1): (
        "Asoc. Mutual Socios Coop. Agrícola Capitán Sarmiento",
        "Cooperativa Capitán Sarmiento",
        "Mucoop",
        "Supermercado",
    ),
    (36, 3): ("Superclc S.A.", "Superclc", "Super CLC", "Supermercado"),
    (36, 4): ("Superclc S.A.", "Superclc", "Super CLC", "Supermercado"),
    (36, 5): ("Superclc S.A.", "Superclc", "Super CLC", "Supermercado"),
    (36, 6): ("Superclc S.A.", "Superclc", "Super CLC", "Supermercado"),
    (44, 1): (
        "Supermercado El Nene S.A.",
        "Supermercado El Nene",
        "Supermercados El Nene",
        "Supermercado",
    ),
    (45, 1): (
        "Almacenes Pampas S.A.",
        "Almacenes Pampas",
        "Almacenes Pampas",
        "Supermercado",
    ),
    (46, 1): (
        "Almacenes de Marca S.A.",
        "Almacenes de Marca",
        "Almacenes de Marca",
        "Supermercado",
    ),
    (47, 1): (
        "Coop. Agrícola Ganadera Patagones y Viedma Ltda.",
        "Unicoop",
        "Unicoop",
        "Supermercado",
    ),
    (49, 1): ("Arnaldo P. Appella S.A.", "Appella S.A.", "Súper Tuti", "Supermercado"),
    (50, 1): ("Supermercado Tuti 2 S.A.", "Appella S.A.", "Súper Tuti", "Supermercado"),
    (1000, 1): (
        "Frigorífico Gorina S.A.I.C.",
        "Frigorífico Gorina",
        "Gorina",
        "Carnicería",
    ),
    (1001, 1): (
        "Rafaela Alimentos S.A.",
        "Rafaela Alimentos",
        "Lario",
        "Fiambres y Embutidos",
    ),
    (1002, 1): ("Went S.A.", "Went S.A.", "Farmacias RP", "Farmacia"),
    (2006, 1): (
        "Whirlpool Argentina S.R.L.",
        "Whirlpool Corporation",
        "Whirlpool Tienda Oficial",
        "Venta Directa",
    ),
    (2006, 2): (
        "Whirlpool Argentina S.R.L.",
        "Whirlpool Corporation",
        "Whirlpool Oficial (Marketplaces)",
        "Comercio Electrónico",
    ),
    (2007, 1): (
        "Sony Argentina S.A.",
        "Sony Group",
        "Sony Store",
        "Tecnología y Audio",
    ),
    (2012, 1): (
        "Mercado Libre S.R.L.",
        "Mercado Libre Inc.",
        "Mercado Libre",
        "Comercio Electrónico",
    ),
    (2013, 1): (
        "First Label S.R.L.",
        "Mercado Libre Inc.",
        "Mercado Libre",
        "Comercio Electrónico",
    ),
    (3000, 2): ("Falabella S.A.", "Grupo Falabella", "Sodimac", "Hogar y Construcción"),
}

# 24 Argentine jurisdictions with standard official names and ISO 3166-2:AR codes
PROVINCES: Dict[str, Tuple[str, str]] = {
    "buenos aires": ("Buenos Aires", "AR-B"),
    "caba": ("Ciudad Autónoma de Buenos Aires", "AR-C"),
    "ciudad autonoma de buenos aires": ("Ciudad Autónoma de Buenos Aires", "AR-C"),
    "ciudad autónoma de buenos aires": ("Ciudad Autónoma de Buenos Aires", "AR-C"),
    "ciudad aut. bs.as": ("Ciudad Autónoma de Buenos Aires", "AR-C"),
    "capital federal": ("Ciudad Autónoma de Buenos Aires", "AR-C"),
    "catamarca": ("Catamarca", "AR-K"),
    "chaco": ("Chaco", "AR-H"),
    "chubut": ("Chubut", "AR-U"),
    "cordoba": ("Córdoba", "AR-X"),
    "córdoba": ("Córdoba", "AR-X"),
    "corrientes": ("Corrientes", "AR-W"),
    "entre rios": ("Entre Ríos", "AR-E"),
    "entre ríos": ("Entre Ríos", "AR-E"),
    "formosa": ("Formosa", "AR-P"),
    "jujuy": ("Jujuy", "AR-Y"),
    "la pampa": ("La Pampa", "AR-L"),
    "la rioja": ("La Rioja", "AR-F"),
    "mendoza": ("Mendoza", "AR-M"),
    "misiones": ("Misiones", "AR-N"),
    "neuquen": ("Neuquén", "AR-Q"),
    "neuquén": ("Neuquén", "AR-Q"),
    "rio negro": ("Río Negro", "AR-R"),
    "río negro": ("Río Negro", "AR-R"),
    "salta": ("Salta", "AR-A"),
    "san juan": ("San Juan", "AR-J"),
    "san luis": ("San Luis", "AR-D"),
    "santa cruz": ("Santa Cruz", "AR-Z"),
    "santa fe": ("Santa Fe", "AR-S"),
    "santa fé": ("Santa Fe", "AR-S"),
    "santiago del estero": ("Santiago del Estero", "AR-G"),
    "tierra del fuego": ("Tierra del Fuego", "AR-V"),
    "tucuman": ("Tucumán", "AR-T"),
    "tucumán": ("Tucumán", "AR-T"),
}

# CABA official and popular neighborhoods
CABA_NEIGHBORHOODS = {
    "abasto",
    "agronomia",
    "agronomía",
    "almagro",
    "balvanera",
    "barracas",
    "barrio norte",
    "belgrano",
    "boedo",
    "botanico",
    "botánico",
    "caballito",
    "chacarita",
    "coghlan",
    "colegiales",
    "congreso",
    "constitucion",
    "constitución",
    "flores",
    "floresta",
    "la boca",
    "la paternal",
    "las cañitas",
    "liniers",
    "mataderos",
    "microcentro",
    "monte castro",
    "monserrat",
    "montserrat",
    "nueva pompeya",
    "nuñez",
    "núñez",
    "once",
    "palermo",
    "palermo chico",
    "palermo hollywood",
    "palermo soho",
    "parque avellaneda",
    "parque chacabuco",
    "parque chas",
    "parque patricios",
    "puerto madero",
    "recoleta",
    "retiro",
    "saavedra",
    "san cristobal",
    "san cristóbal",
    "san nicolas",
    "san nicolás",
    "san telmo",
    "tribunales",
    "velez sarsfield",
    "vélez sársfield",
    "versalles",
    "villa crespo",
    "villa del parque",
    "villa devoto",
    "villa gral mitre",
    "villa general mitre",
    "villa lugano",
    "villa luro",
    "villa ortuzar",
    "villa ortúzar",
    "villa pueyrredon",
    "villa pueyrredón",
    "villa real",
    "villa riachuelo",
    "villa santa rita",
    "villa soldati",
    "villa urquiza",
}

# Common street type abbreviations
STREET_PREFIX_SUBS = [
    (re.compile(r"^\b(avenida|avda\.?|av\.)\b\s*", re.IGNORECASE), "Av. "),
    (
        re.compile(r"^\b(bulevar|boulevard|bvda\.?|bvd\.?|bv\.?)\b\s*", re.IGNORECASE),
        "Bv. ",
    ),
    (re.compile(r"^\b(diagonal|diag\.?)\b\s*", re.IGNORECASE), "Diag. "),
    (re.compile(r"^\b(pasaje|pje\.?)\b\s*", re.IGNORECASE), "Pje. "),
    (re.compile(r"^\b(calle|cl\.?)\b\s*", re.IGNORECASE), ""),
    (
        re.compile(
            r"\b(ruta\s+nacional|r\.?\s*nacional|ruta\s+nac\.?|rn\.?)\b", re.IGNORECASE
        ),
        "Ruta Nac.",
    ),
    (
        re.compile(
            r"\b(ruta\s+provincial|r\.?\s*provincial|ruta\s+prov\.?|rp\.?)\b",
            re.IGNORECASE,
        ),
        "Ruta Prov.",
    ),
    (re.compile(r"\b(autovia|autopista|aut\.?)\b", re.IGNORECASE), "Aut."),
]


def decompose_pos_code(
    code: str,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str], Optional[str]]:
    """Decompose SEPA code string into numeric IDs, slug, and canonical sepa_id.

    Format: '(comercio_id-bandera_id-sucursal_id)(bandera_slug)'
    Returns: (comercio_id, bandera_id, sucursal_id, bandera_slug, sepa_id)
    """
    m = _SEPA_CODE_PATTERN.match(code.strip())
    if m:
        cid, bid, sid = int(m.group(1)), int(m.group(2)), int(m.group(3))
        slug = m.group(4).strip()
        sepa_id = f"{cid}-{bid}-{sid}"
        return cid, bid, sid, slug, sepa_id
    return None, None, None, None, None


def resolve_corporate_info(
    comercio_id: Optional[int],
    bandera_id: Optional[int],
    business_raw: Optional[str] = None,
    flag_raw: Optional[str] = None,
) -> Tuple[str, Optional[str], str, str]:
    """Resolve corporate metadata from comercio_id, bandera_id or fallback to raw strings.

    Returns: (business_name, holding_group, brand_name, store_format)
    """
    if comercio_id is not None and bandera_id is not None:
        chain_info = RETAIL_CHAINS.get((comercio_id, bandera_id))
        if chain_info:
            return chain_info

    # Fallback resolution
    b_name = (business_raw or "Comercio").strip().title()
    f_name = (flag_raw or "Sucursal").strip().title()
    return b_name, None, f_name, "Supermercado"


def clean_address(address: Optional[str]) -> str:
    """Clean and standardize street address.

    - Removes scraper artifacts (' none', ' 0', trailing dots).
    - Standardizes street prefixes ('Av.', 'Bv.', 'Diag.', 'Ruta Nac.').
    - Standardizes intersection indicators ('esq.', 'y', 'entre').
    - Proper title casing.
    """
    if not address or not address.strip():
        return "S/N"

    addr = address.strip()

    # 1. Strip trailing artifacts
    addr = re.sub(r"\s+none\s*$", "", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\s+0\s*$", "", addr)
    addr = addr.rstrip(" .,;")

    if not addr:
        return "S/N"

    # 2. Standardize prefixes at start of string
    addr = re.sub(r"^(avenida|avda\.?|av\.)\s*", "Av. ", addr, flags=re.IGNORECASE)
    addr = re.sub(
        r"^(bulevar|boulevard|bvda\.?|bvd\.?|bv\.?)\s*",
        "Bv. ",
        addr,
        flags=re.IGNORECASE,
    )
    addr = re.sub(r"^(diagonal|diag\.?)\s*", "Diag. ", addr, flags=re.IGNORECASE)
    addr = re.sub(r"^(pasaje|pje\.?)\s*", "Pje. ", addr, flags=re.IGNORECASE)
    addr = re.sub(r"^(calle|cl\.?)\s*", "", addr, flags=re.IGNORECASE)

    # Within string
    addr = re.sub(r"\s+(avenida|avda\.?|av\.)\s+", " Av. ", addr, flags=re.IGNORECASE)
    addr = re.sub(
        r"\s+(bulevar|boulevard|bvda\.?|bvd\.?|bv\.?)\s+",
        " Bv. ",
        addr,
        flags=re.IGNORECASE,
    )
    addr = re.sub(r"\s+(esquina|esq\.?)\s+", " esq. ", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\s+(entre|e/)\s+", " entre ", addr, flags=re.IGNORECASE)
    addr = re.sub(
        r"\b(ruta\s+nacional|r\.?\s*nacional|ruta\s+nac\.?|rn\.?)\b",
        "Ruta Nac.",
        addr,
        flags=re.IGNORECASE,
    )
    addr = re.sub(
        r"\b(ruta\s+provincial|r\.?\s*provincial|ruta\s+prov\.?|rp\.?)\b",
        "Ruta Prov.",
        addr,
        flags=re.IGNORECASE,
    )
    addr = re.sub(r"\b(autovia|autopista|aut\.?)\b", "Aut.", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\b(km\.?|k)\s*(\d+)", r"Km. \2", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\b(sin\s+numero|s/n\.?)\b", "S/N", addr, flags=re.IGNORECASE)

    # Clean double dots / whitespace
    addr = re.sub(r"\s*\.\s*\.", ".", addr)
    addr = re.sub(r"\s+", " ", addr).strip()

    # 3. Format Title Case while preserving special acronyms
    words = addr.split(" ")
    formatted_words = []
    for w in words:
        wl = w.lower().rstrip(".,;")
        if wl in {"de", "del", "la", "las", "el", "los", "y", "e", "en", "al", "entre"}:
            formatted_words.append(wl)
        elif wl in {"esq", "esq."}:
            formatted_words.append("esq.")
        elif w.upper() in {"S/N", "S.A.", "KM.", "ACC.", "RN", "RP", "ACA"}:
            formatted_words.append(w.upper())
        elif re.match(r"^\d+[a-zA-Z]?$", w):
            formatted_words.append(w)
        elif (
            w.startswith("Av.")
            or w.startswith("Bv.")
            or w.startswith("Diag.")
            or w.startswith("Pje.")
        ):
            formatted_words.append(w)
        else:
            formatted_words.append(w.capitalize())

    res = " ".join(formatted_words)
    res = re.sub(r"\s*\.\s*\.", ".", res)
    res = re.sub(r"\bAv\.\s*\.", "Av.", res)
    if res and res[0].islower():
        res = res[0].upper() + res[1:]
    return res


LOCALITY_ACCENTS = {
    "adrogue": "Adrogué",
    "lanus": "Lanús",
    "moron": "Morón",
    "ituzaingo": "Ituzaingó",
    "parana": "Paraná",
    "cordoba": "Córdoba",
    "neuquen": "Neuquén",
    "tucuman": "Tucumán",
    "oran": "Orán",
    "metan": "Metán",
    "guemes": "Güemes",
    "colon": "Colón",
    "peron": "Perón",
    "belen": "Belén",
}


def clean_branch(branch: Optional[str], brand_name: str = "") -> str:
    """Clean and standardize branch name.

    - Strips embedded bracketed addresses (common in Farmacity/Simplicity).
    - Cleans store number prefixes or province prefixes ('sm 140 ', 'salt - ', 'cdba - ').
    - Title cases and removes trailing punctuation.
    """
    if not branch or not branch.strip():
        return brand_name or "Central"

    br = branch.strip()

    # 1. Strip bracketed addresses: 'adrogue [esteban adrogué 1061]' -> 'adrogue'
    br = re.sub(r"\s*\[.*$", "", br)
    br = re.sub(r"\s*\(cap\)$", "", br, flags=re.IGNORECASE)

    # 2. Strip internal province prefixes: 'mdza - ', 'cdba - ', 'salt - ', 'safe - ', 'sfe. '
    br = re.sub(
        r"^(mdza|cdba|cba|salt|safe|sfe\.?|tuc|juj|ctes|mis|er|chc)\s*[-–]\s*",
        "",
        br,
        flags=re.IGNORECASE,
    )

    # 3. Strip 'sm \d+ ' prefix or trailing '-m!' suffix
    br = re.sub(r"^sm\s*\d+\s*", "", br, flags=re.IGNORECASE)
    br = re.sub(r"[-–]\s*m!$", "", br, flags=re.IGNORECASE)

    # 4. Strip duplicate brand names from start: 'bazar avenida sa - ' or 'supermercados '
    br = re.sub(r"^bazar\s+avenida\s+sa\s*[-–]\s*", "", br, flags=re.IGNORECASE)
    br = re.sub(r"^(hipermercado|supermercados?)\s+", "", br, flags=re.IGNORECASE)

    br = br.strip(" .,-–")
    if not br:
        return brand_name or "Sucursal"

    # Title case
    words = br.split()
    formatted = []
    for w in words:
        wl = w.lower()
        if wl in {"de", "del", "la", "el", "y", "en", "al"}:
            formatted.append(wl)
        elif wl in LOCALITY_ACCENTS:
            formatted.append(LOCALITY_ACCENTS[wl])
        elif wl in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}:
            formatted.append(wl.upper())
        elif w.isdigit():
            formatted.append(w)
        else:
            formatted.append(w.capitalize())

    res = " ".join(formatted)
    if res and res[0].islower():
        res = res[0].upper() + res[1:]
    return res


def resolve_geographic_info(
    city_raw: Optional[str],
    state_raw: Optional[str],
    branch_raw: Optional[str] = None,
    address_clean: str = "",
) -> Tuple[str, str, str]:
    """Clean and rectify city name, province name, and ISO province code.

    - Resolves and standardizes CABA/Federal Capital stores to 'Ciudad Autónoma de Buenos Aires'.
    - Rectifies cross-province discrepancies (Mendoza, Resistencia, Salta, Córdoba).
    - Returns (city, province, province_code).
    """
    city_str = (city_raw or "").strip(' "').lower()
    state_str = (state_raw or "").strip(' "').lower()
    branch_str = (branch_raw or "").lower()
    addr_str = address_clean.lower()

    # 1. Rectify legacy cross-province misassignments
    # Case A: City is Mendoza but state was set to Buenos Aires
    if city_str == "mendoza" and state_str != "mendoza":
        state_str = "mendoza"
        city_str = "mendoza"

    # Case B: City is Resistencia but state was set to Buenos Aires
    elif city_str == "resistencia" and state_str != "chaco":
        state_str = "chaco"
        city_str = "resistencia"

    # Case C: Stores with city='capital' and state='Santa Fé' in legacy data
    elif city_str == "capital" and "santa f" in state_str:
        if "salta" in branch_str or "tavella" in addr_str:
            state_str = "salta"
            city_str = "salta"
        elif "mendoza" in branch_str or "ayacucho 401" in addr_str:
            state_str = "mendoza"
            city_str = "mendoza"
        elif any(
            k in branch_str or k in addr_str
            for k in [
                "cabildo",
                "constituyentes",
                "beiro",
                "gaona",
                "once",
                "rivadavia",
                "azurduy",
                "dorrego",
                "olivera",
                "nicaragua",
                "velez sarsfield",
                "caballito",
            ]
        ):
            state_str = "caba"
            city_str = "caba"
        elif any(
            k in branch_str or k in addr_str
            for k in [
                "sabattini",
                "caraffa",
                "valle mall",
                "rivera indarte",
                "poeta lugones",
                "hiperconstruccion",
                "barranquitas",
                "jacinto rios",
                "octavio pinto",
                "rondeau",
                "sagrada familia",
                "derqui",
                "nueva cordoba",
                "ambrosio olmos",
            ]
        ):
            state_str = "cordoba"
            city_str = "córdoba"
        elif any(
            k in branch_str or k in addr_str
            for k in ["zonda", "juan b justo", "dovir", "someca"]
        ):
            if "zonda" in branch_str:
                state_str = "san juan"
                city_str = "san juan"
            else:
                state_str = "mendoza"
                city_str = "mendoza"
        elif "santa fe" in branch_str or "ruta 168" in addr_str:
            state_str = "santa fe"
            city_str = "santa fe"

    # Case D: DIA stores where city is 'buenos aires' but branch has '{num} - {location}'
    if city_str == "buenos aires" and re.match(r"^\d+\s*[-–]\s*.+", branch_str):
        m = re.match(r"^\d+\s*[-–]\s*(.+)$", branch_str)
        if m:
            loc = m.group(1).strip()
            if loc in CABA_NEIGHBORHOODS:
                city_str = "caba"
                state_str = "caba"
            elif loc not in {"dia", "express", "maxi"}:
                city_str = loc

    # Case F: Cities starting with 'barrio ' (e.g. 'barrio castañares')
    if city_str.startswith("barrio "):
        if "salta" in branch_str or "salta" in state_str:
            city_str = "salta"
        elif "quilmes" in branch_str or "calchaqui" in addr_str:
            city_str = "quilmes"
        elif (
            "once" in city_str or "balvanera" in branch_str or "pueyrredon" in addr_str
        ):
            city_str = "caba"
            state_str = "caba"
        elif "rawson" in branch_str or "rawson" in city_str:
            city_str = "rawson"
        elif "rivadavia" in branch_str or "rivadavia" in city_str:
            city_str = "rivadavia"
        elif "san juan" in branch_str or "san juan" in state_str:
            city_str = "san juan"
        elif "cordoba" in branch_str or "córdoba" in state_str:
            city_str = "córdoba"

    # Case E: CABA detection -> standardize to 'Ciudad Autónoma de Buenos Aires'
    is_caba = (
        state_str
        in {
            "caba",
            "capital federal",
            "ciudad autonoma de buenos aires",
            "ciudad autónoma de buenos aires",
        }
        or city_str in CABA_NEIGHBORHOODS
        or city_str
        in {
            "caba",
            "capital federal",
            "ciudad autonoma de buenos aires",
            "ciudad autónoma de buenos aires",
            "ciudad autonoma buenos aires",
            "ciudad aut. bs.as",
            "cdad. de bs.as",
            "cap. fed.",
            "capital  federal",
            "devoto",
            "flores sur",
            "lugano",
            "paternal",
            "pompeya",
            "v illa lugano",
            "cabildo avda",
        }
    )

    if is_caba:
        city_str = "Ciudad Autónoma de Buenos Aires"
        state_str = "caba"
    else:
        # Non-CABA: clean city string and apply accents
        city_clean = re.sub(
            r"[-–]\s*(sta\.?\s*cruz|cba|bs\.?\s*as\.?)$",
            "",
            city_str,
            flags=re.IGNORECASE,
        )
        city_clean = re.sub(r"\(.*\)", "", city_clean).strip()
        city_lower = city_clean.lower()
        if city_lower in LOCALITY_ACCENTS:
            city_str = LOCALITY_ACCENTS[city_lower]
        else:
            city_str = city_clean.title() if city_clean else "Desconocida"

    # 2. Map province and ISO code
    prov_entry = PROVINCES.get(state_str)
    if not prov_entry:
        for k, v in PROVINCES.items():
            if k in state_str:
                prov_entry = v
                break
    if not prov_entry:
        prov_name = state_str.title()
        prov_code = "AR-?"
    else:
        prov_name, prov_code = prov_entry

    return city_str, prov_name, prov_code


def clean_point_of_sale_record(
    code: str,
    business: Optional[str] = None,
    flag: Optional[str] = None,
    branch: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> CleanPointOfSale:
    """Clean and enrich a single Point of Sale record."""
    cid, bid, sid, slug, sepa_id = decompose_pos_code(code)
    business_name, holding_group, brand_name, store_format = resolve_corporate_info(
        comercio_id=cid,
        bandera_id=bid,
        business_raw=business,
        flag_raw=flag,
    )

    clean_addr = clean_address(address)
    clean_br = clean_branch(branch, brand_name=brand_name)
    clean_city, province_name, province_code = resolve_geographic_info(
        city_raw=city,
        state_raw=state,
        branch_raw=branch,
        address_clean=clean_addr,
    )

    return CleanPointOfSale(
        code=code.strip(),
        sepa_id=sepa_id,
        comercio_id=cid,
        bandera_id=bid,
        sucursal_id=sid,
        business_name=business_name,
        holding_group=holding_group,
        brand_name=brand_name,
        store_format=store_format,
        branch_name=clean_br,
        address=clean_addr,
        city=clean_city,
        province=province_name,
        province_code=province_code,
        latitude=latitude,
        longitude=longitude,
    )
