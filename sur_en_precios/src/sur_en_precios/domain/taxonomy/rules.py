"""Classification rules mapping keywords and patterns to categories and tags."""

from __future__ import annotations

import re
from typing import List, Tuple


# Classification rules: (Department, Subcategory, list of regex patterns)
# Checked in order; the first match determines the article's category.
CLASSIFICATION_RULES: List[Tuple[str, str, List[str]]] = [
    # Bebidas - Vinos y Espumantes
    (
        "Bebidas",
        "Vinos Tintos",
        [
            r"\bvino.*(tinto|malbec|cabernet|syrah|merlot|bonarda|pinot|varietal|cosecha|blend)\b",
            r"\b(malbec|cabernet sauvignon|syrah|bonarda|pinot noir)\b",
            r"\bvino tinto\b",
        ],
    ),
    (
        "Bebidas",
        "Vinos Blancos y Rosados",
        [
            r"\bvino.*(blanco|rosado|rose|chardonnay|sauvignon blanc|torrontes|chenin|semillon)\b",
            r"\b(chardonnay|sauvignon blanc|torrontes)\b",
            r"\bvino blanco\b",
            r"\bvino rosado\b",
        ],
    ),
    (
        "Bebidas",
        "Espumantes y Champagnes",
        [
            r"\b(champagne|espumante|espumoso|extra brut|brut nature|frizze|sidra)\b",
        ],
    ),
    (
        "Bebidas",
        "Cervezas",
        [
            r"\b(cerveza|cervezas|ipa|apa|stout|lager|ale|porron|chopp)\b",
        ],
    ),
    (
        "Bebidas",
        "Gaseosas",
        [
            r"\b(gaseosa|gaseosas|cola|tonica|pomelo gaseosa|lima limon|guarana)\b",
        ],
    ),
    (
        "Bebidas",
        "Aguas y Aguas Saborizadas",
        [
            r"\bagua\s+(?:mineral|saborizada|de mesa|sin gas|con gas)\b",
            r"\b(soda|agua con gas|agua sin gas|agua mineral)\b",
        ],
    ),
    (
        "Bebidas",
        "Jugos e Isotónicas",
        [
            r"\b(jugo|jugos|isotonica|gatorade|powerade|speed|monster|red bull|nectar)\b",
        ],
    ),
    (
        "Bebidas",
        "Infusiones",
        [
            r"\b(cafe|te |te en|yerba|yerba mate|mate cocido|saquitos|infusion|capsulas dolce gusto|capsulas de cafe)\b",
        ],
    ),
    (
        "Bebidas",
        "Bebidas Blancas y Licores",
        [
            r"\b(whisky|whiskey|fernet|aperitivo|vodka|gin|ron|licor|licores|tequila|vermouth|vermut|gancia|campari|amargo|anivario branca)\b",
        ],
    ),

    # Bebé y Maternidad (checked early to catch baby diapers, wipes, and infant formula)
    (
        "Bebé y Maternidad",
        "Pañales y Toallitas",
        [
            r"\b(pañal|panal|pañales|panales|pampers|huggies|babysec|toallitas humedas)\b",
        ],
    ),
    (
        "Bebé y Maternidad",
        "Higiene y Cuidado Infantil",
        [
            r"\b(oleo calcareo|chupete|chupetes|mamadera|mamaderas|mordillo|shampoo bebe|aceite bebe|colonia bebe)\b",
        ],
    ),

    # Mascotas (checked early to catch dog/cat food before general meats/canned)
    (
        "Mascotas",
        "Alimento para Perros",
        [
            r"\b(?:alimento|comida)\s+para\s+perro(?:s)?\b",
            r"\b(dog chow|pedigree|pro plan perro|purina perro|eukanuba|dogui|raza perro|hueso para perro)\b",
        ],
    ),
    (
        "Mascotas",
        "Alimento para Gatos",
        [
            r"\b(?:alimento|comida)\s+para\s+gato(?:s)?\b",
            r"\b(cat chow|whiskas|pro plan gato|purina gato|felix|gati|piedras sanitarias)\b",
        ],
    ),
    (
        "Mascotas",
        "Cuidado y Accesorios",
        [
            r"\b(shampoo para perros|pipeta|collar antipulgas|correa perro|arena para gato)\b",
        ],
    ),

    # Lácteos y Frescos
    (
        "Lácteos y Frescos",
        "Leches",
        [
            r"\bleche\b",
        ],
    ),
    (
        "Lácteos y Frescos",
        "Yogures",
        [
            r"\b(yogur|yogures|yogur entero|yogur descremado|yogur bebible|yogur firme)\b",
        ],
    ),
    (
        "Lácteos y Frescos",
        "Quesos",
        [
            r"\b(queso|quesos|mozzarella|cremoso|reggianito|sardo|dambo|parmesano|roquefort|gouda|brie|fontina|pategras|cheddar)\b",
        ],
    ),
    (
        "Lácteos y Frescos",
        "Mantecas y Cremas",
        [
            r"\b(manteca|crema de leche|margarina)\b",
        ],
    ),
    (
        "Lácteos y Frescos",
        "Fiambres y Embutidos",
        [
            r"\b(jamon|salame|salchicha|salchichas|paleta cocida|mortadela|panceta|longaniza|bondiola fiambreria|leberwurst)\b",
        ],
    ),
    (
        "Lácteos y Frescos",
        "Pastas Frescas y Tapas",
        [
            r"\b(tapa(?:s)?\s+(?:para|de)\s+(?:empanada|tarta)|ravioles|noquis|ñoquis|sorrentinos|capeletis|cappellettis|fideos frescos)\b",
        ],
    ),

    # Carnes y Pescados
    (
        "Carnes y Pescados",
        "Carne Vacuna",
        [
            r"\b(carne vacuna|novillo|novillito|ternera|asado|vacio|lomo|peceto|nalga|cuadril|colita de cuadril|bife|matambre|entrecot|picada especial)\b",
        ],
    ),
    (
        "Carnes y Pescados",
        "Pollo y Granja",
        [
            r"\b(pollo|pechuga de pollo|pata muslo|alitas de pollo|suprema de pollo|menudos de pollo|pollo entero)\b",
        ],
    ),
    (
        "Carnes y Pescados",
        "Carne de Cerdo",
        [
            r"\b(carne de cerdo|cerdo|pechito de cerdo|costillitas de cerdo|carre de cerdo|solomillo de cerdo|matambrito)\b",
        ],
    ),
    (
        "Carnes y Pescados",
        "Pescados y Mariscos",
        [
            r"\b(merluza|salmon|salmón|camaron|camarones|langostino|langostinos|calamar|calamares|mejillon|mejillones|filet de merluza)\b",
        ],
    ),

    # Frutas y Verduras
    (
        "Frutas y Verduras",
        "Frutas",
        [
            r"\b(manzana|banana|naranja|mandarina|limon|limón|frutilla|frutillas|pera|peras|uva|uvas|durazno|palta|paltas|kiwi|melon|sandia)\b",
        ],
    ),
    (
        "Frutas y Verduras",
        "Verduras y Hortalizas",
        [
            r"\b(papa|papas|cebolla|cebollas|tomate|tomates|zanahoria|zanahorias|lechuga|acelga|espinaca|zapallo|morron|morrones|ajo|alcaucil|berenjena)\b",
        ],
    ),

    # Panadería y Confitería
    (
        "Panadería y Confitería",
        "Panificados",
        [
            r"\b(pan\s+(?:frances|lactal|de molde|para pancho|para hamburguesa|arabe|baguette)|pan rallado|rebozador)\b",
        ],
    ),
    (
        "Panadería y Confitería",
        "Facturas, Budines y Tortas",
        [
            r"\b(budin|budines|magdalena|magdalenas|medialunas|facturas|bizcochuelo|torta|pan dulce)\b",
        ],
    ),

    # Congelados
    (
        "Congelados",
        "Comidas Preparadas y Rebozados",
        [
            r"\b(hamburguesa|hamburguesas|patitas de pollo|nuggets|milanesa|milanesas|bocaditos de merluza|pizza congelada)\b",
        ],
    ),
    (
        "Congelados",
        "Helados y Postres",
        [
            r"\b(helado|helados|bombones helados|pote helado|palito helado)\b",
        ],
    ),
    (
        "Congelados",
        "Verduras Congeladas",
        [
            r"\bcongelad[oa]s?\b",
        ],
    ),

    # Almacén
    (
        "Almacén",
        "Aceites y Vinagres",
        [
            r"\b(aceite|aceites|oliva|girasol|maiz|soja|canola|vinagre|aceto|aceto balsamico)\b",
        ],
    ),
    (
        "Almacén",
        "Pastas Secas y Salsas",
        [
            r"\b(fideo|fideos|spaghetti|tallarines|mostachol|mostacholes|tirabuzon|tirabuzones|guisero|salsa|tuco|pure de tomate|tomate perita)\b",
        ],
    ),
    (
        "Almacén",
        "Arroz y Legumbres",
        [
            r"\b(arroz|lenteja|lentejas|garbanzo|garbanzos|arveja|arvejas|poroto|porotos)\b",
        ],
    ),
    (
        "Almacén",
        "Conservas y Enlatados",
        [
            r"\b(atun|caballa|sardina|sardinas|choclo|palmito|palmitos|durazno en almibar|anana en almibar|conserva|en conserva)\b",
        ],
    ),
    (
        "Almacén",
        "Galletitas y Snacks",
        [
            r"\b(galletita|galletitas|bizcocho|bizcochos|cracker|crackers|papa frita|papas fritas|mani |mani salado|nachos|tostadas|grisines|snack|snacks)\b",
        ],
    ),
    (
        "Almacén",
        "Desayuno y Merienda",
        [
            r"\b(mermelada|mermeladas|dulce de leche|miel|cereal|cereales|avena|cacao|barrita de cereal|barra de cereal)\b",
        ],
    ),
    (
        "Almacén",
        "Azúcar, Harinas y Repostería",
        [
            r"\b(azucar|edulcorante|harina|harinas|levadura|polvo para hornear|premezcla|gelatina|postre en polvo|flan)\b",
        ],
    ),
    (
        "Almacén",
        "Chocolates y Golosinas",
        [
            r"\b(chocolate|chocolates|bombon|bombones|alfajor|alfajores|caramelo|caramelos|chupetin|chupetines|chicle|chicles|turron|gomitas|confites)\b",
        ],
    ),
    (
        "Almacén",
        "Condimentos y Aderezos",
        [
            r"\b(sal\b|sal fina|sal gruesa|pimienta|oregano|mayonesa|ketchup|mostaza|aderezo|aderezos|caldo|caldos|especias)\b",
        ],
    ),

    # Perfumería y Cuidado Personal
    (
        "Perfumería y Cuidado Personal",
        "Cuidado Capilar",
        [
            r"\b(shampoo|acondicionador|enjuague capilar|crema para peinar|mascara capilar|coloracion|tintura|fijador|activador|gel capilar)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Cuidado Bucal",
        [
            r"\b(crema dental|pasta dental|cepillo dental|enjuague bucal|hilo dental|protesis dental|adhesivo en polvo para protesis)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Jabones y Baño",
        [
            r"\b(jabon de tocador|jabon en pan|gel de ducha|sales de bano|jabon liquido corporal)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Desodorantes",
        [
            r"\b(desodorante|antitranspirante|bodyspray|body splash)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Cuidado Facial y Corporal",
        [
            r"\b(crema corporal|crema facial|protector solar|agua micelar|locion|autobronceante|esmalte|labial|brillo para unas|base fortalecedora)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Protección Femenina e Higiene Adulto",
        [
            r"\b(toallas femeninas|protectores diarios|tampones|toalla femenina|protector diario)\b",
        ],
    ),
    (
        "Perfumería y Cuidado Personal",
        "Afeitado y Depilación",
        [
            r"\b(espuma de afeitar|maquina de afeitar|repuesto de afeitar|cera depilatoria|crema depilatoria)\b",
        ],
    ),

    # Limpieza
    (
        "Limpieza",
        "Cuidado de la Ropa",
        [
            r"\b(?:jabon|detergente)\s+para\s+ropa\b",
            r"\b(suavizante|quitamanchas|apresto|jabon liquido ropa|jabon en polvo ropa)\b",
        ],
    ),
    (
        "Limpieza",
        "Limpieza de Cocina y Vajilla",
        [
            r"\b(detergente|lavavajillas|desengrasante|limpiador cremoso|abrillantador para lavavajilla|esponja|fibra esponja)\b",
        ],
    ),
    (
        "Limpieza",
        "Limpieza de Baño y Desinfección",
        [
            r"\b(lavandina|desinfectante|limpiador para bano|canasta inodoro|pastilla inodoro)\b",
        ],
    ),
    (
        "Limpieza",
        "Limpiadores de Pisos y Superficies",
        [
            r"\b(limpiador de pisos|limpiador liquido|cera para pisos|lustramuebles|limpiavidrios|multiuso)\b",
        ],
    ),
    (
        "Limpieza",
        "Papeles y Bolsas de Residuos",
        [
            r"\b(papel higienico|rollo de cocina|servilletas|bolsas de residuos|bolsa de residuo|bolsas para freezer)\b",
        ],
    ),
    (
        "Limpieza",
        "Insecticidas y Aromatizantes",
        [
            r"\b(insecticida|repelente|espirales|aromatizante|absorbe humedad|desodorante de ambiente)\b",
        ],
    ),

    # Electro, Bazar y Hogar
    (
        "Electro, Bazar y Hogar",
        "Telefonía e Informática",
        [
            r"\b(celular|smartphone|notebook|laptop|tablet|teclado|mouse|funda celular)\b",
        ],
    ),
    (
        "Electro, Bazar y Hogar",
        "TV, Audio y Video",
        [
            r"\b(smart tv|televisor|auricular|auriculares|parlante|microfono|soporte tv)\b",
        ],
    ),
    (
        "Electro, Bazar y Hogar",
        "Electrodomésticos y Climatización",
        [
            r"\b(aire acondicionado|ventilador|calefactor|caloventor|pava electrica|microondas|tostadora|cafetera|licuadora|heladera)\b",
        ],
    ),
    (
        "Electro, Bazar y Hogar",
        "Bazar, Iluminación y Ferretería",
        [
            r"\b(lampara led|lampara|foco|pilas|linterna|vajilla|vaso|vasos|plato|platos|olla|sarten|termo|mate)\b",
        ],
    ),
]


# Facet tag rules to extract orthogonal attributes
FACET_TAG_RULES: List[Tuple[str, List[str]]] = [
    ("sin tacc", [r"\b(?:sin\s+tacc|libre\s+de\s+gluten|gluten\s+free)\b"]),
    ("diet / light", [r"\b(?:light|diet|dietetica|reducido en calorias|cero azucar|sin azucar)\b"]),
    ("descremada", [r"\bdescremad[ao]s?\b"]),
    ("entera", [r"\benter[ao]s?\b"]),
    ("extra virgen", [r"\bextra\s+virgen\b"]),
    ("sin gas", [r"\bsin\s+gas\b"]),
    ("con gas", [r"\bcon\s+gas\b"]),
    ("malbec", [r"\bmalbec\b"]),
    ("cabernet", [r"\bcabernet(?:\s+sauvignon)?\b"]),
    ("chardonnay", [r"\bchardonnay\b"]),
    ("torrontes", [r"\btorrontes\b"]),
    ("doypack", [r"\bdoypack\b"]),
    ("recargable", [r"\b(?:recargable|repuesto)\b"]),
    ("lavanda", [r"\blavanda\b"]),
    ("limon", [r"\blimon\b"]),
    ("frutilla", [r"\bfrutilla\b"]),
    ("vainilla", [r"\bvainilla\b"]),
    ("chocolate", [r"\bchocolate\b"]),
]
