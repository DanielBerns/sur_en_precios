"""Taxonomy definition of retail departments and subcategories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from sur_en_precios.domain.cleaner.text_utils import slugify


@dataclass(frozen=True)
class SubcategoryDef:
    name: str
    slug: str
    description: str


@dataclass(frozen=True)
class DepartmentDef:
    name: str
    slug: str
    description: str
    subcategories: List[SubcategoryDef]


# Complete retail taxonomy hierarchy
DEFAULT_TAXONOMY: List[DepartmentDef] = [
    DepartmentDef(
        name="Almacén",
        slug="almacen",
        description="Comestibles secos, enlatados, condimentos y desayuno",
        subcategories=[
            SubcategoryDef("Aceites y Vinagres", "almacen-aceites-y-vinagres", "Aceites de oliva, girasol, maíz, vinagres y acetos"),
            SubcategoryDef("Pastas Secas y Salsas", "almacen-pastas-secas-y-salsas", "Fideos, puré de tomate y salsas listas"),
            SubcategoryDef("Arroz y Legumbres", "almacen-arroz-y-legumbres", "Arroz, lentejas, garbanzos, arvejas y porotos"),
            SubcategoryDef("Conservas y Enlatados", "almacen-conservas-y-enlatados", "Atún, caballa, choclo, palmitos y conservas"),
            SubcategoryDef("Galletitas y Snacks", "almacen-galletitas-y-snacks", "Galletitas dulces, saladas, papas fritas y snacks"),
            SubcategoryDef("Desayuno y Merienda", "almacen-desayuno-y-merienda", "Mermeladas, dulce de leche, cereales y avena"),
            SubcategoryDef("Azúcar, Harinas y Repostería", "almacen-azucar-harinas-y-reposteria", "Azúcar, harinas, premezclas, polvos y postres"),
            SubcategoryDef("Chocolates y Golosinas", "almacen-chocolates-y-golosinas", "Chocolates, alfajores, caramelos, chupetines y chicles"),
            SubcategoryDef("Condimentos y Aderezos", "almacen-condimentos-y-aderezos", "Sal, especias, mayonesas, mostazas y aderezos"),
            SubcategoryDef("Almacén General", "almacen-general", "Otros comestibles de almacén"),
        ],
    ),
    DepartmentDef(
        name="Bebidas",
        slug="bebidas",
        description="Bebidas con y sin alcohol, aguas e infusiones",
        subcategories=[
            SubcategoryDef("Vinos Tintos", "bebidas-vinos-tintos", "Vinos tintos malbec, cabernet, syrah y blends"),
            SubcategoryDef("Vinos Blancos y Rosados", "bebidas-vinos-blancos-y-rosados", "Vinos blancos chardonnay, torrontés y rosados"),
            SubcategoryDef("Espumantes y Champagnes", "bebidas-espumantes-y-champagnes", "Champagnes, espumantes y sidras"),
            SubcategoryDef("Cervezas", "bebidas-cervezas", "Cervezas rubias, rojas, negras, IPA y artesanales"),
            SubcategoryDef("Gaseosas", "bebidas-gaseosas", "Gaseosas cola, lima-limón, pomelo y aguas tónicas"),
            SubcategoryDef("Aguas y Aguas Saborizadas", "bebidas-aguas-y-aguas-saborizadas", "Aguas minerales, con y sin gas, aguas saborizadas y sodas"),
            SubcategoryDef("Jugos e Isotónicas", "bebidas-jugos-e-isotonicas", "Jugos listos, concentrados, en polvo y bebidas deportivas"),
            SubcategoryDef("Infusiones", "bebidas-infusiones", "Café, té, yerba mate y mate cocido"),
            SubcategoryDef("Bebidas Blancas y Licores", "bebidas-blancas-y-licores", "Fernet, aperitivos, whisky, vodka, gin y licores"),
            SubcategoryDef("Bebidas General", "bebidas-general", "Otras bebidas"),
        ],
    ),
    DepartmentDef(
        name="Lácteos y Frescos",
        slug="lacteos-y-frescos",
        description="Leches, yogures, quesos, mantecas y pastas frescas",
        subcategories=[
            SubcategoryDef("Leches", "lacteos-leches", "Leches fluidas enteras, descremadas y en polvo"),
            SubcategoryDef("Yogures", "lacteos-yogures", "Yogures bebibles, firmes, enteros y descremados"),
            SubcategoryDef("Quesos", "lacteos-quesos", "Quesos untables, cremosos, duros, rallados y mozzarella"),
            SubcategoryDef("Mantecas y Cremas", "lacteos-mantecas-y-cremas", "Mantecas, margarinas y cremas de leche"),
            SubcategoryDef("Fiambres y Embutidos", "lacteos-fiambres-y-embutidos", "Jamón, paleta, salchichas, salame y fiambres"),
            SubcategoryDef("Pastas Frescas y Tapas", "lacteos-pastas-frescas-y-tapas", "Ravioles, ñoquis, tapas de empanadas y tartas"),
            SubcategoryDef("Frescos General", "lacteos-general", "Otros lácteos y productos frescos"),
        ],
    ),
    DepartmentDef(
        name="Carnes y Pescados",
        slug="carnes-y-pescados",
        description="Carnes vacunas, aves, cerdo, pescados y mariscos",
        subcategories=[
            SubcategoryDef("Carne Vacuna", "carnes-vacuna", "Cortes vacunos para asado, bifes, carne picada"),
            SubcategoryDef("Pollo y Granja", "carnes-pollo-y-granja", "Pollo entero, pechugas, patamuslo y granja"),
            SubcategoryDef("Carne de Cerdo", "carnes-cerdo", "Pechito de cerdo, bondiola, costillitas y cortes porcinos"),
            SubcategoryDef("Pescados y Mariscos", "carnes-pescados-y-mariscos", "Filet de merluza, salmón, mariscos y calamares"),
            SubcategoryDef("Carnicería General", "carnes-general", "Otros cortes y carnes"),
        ],
    ),
    DepartmentDef(
        name="Frutas y Verduras",
        slug="frutas-y-verduras",
        description="Frutas, verduras frescas, hortalizas y legumbres frescas",
        subcategories=[
            SubcategoryDef("Frutas", "frutas-frescas", "Manzanas, bananas, cítricos, uvas y frutas de estación"),
            SubcategoryDef("Verduras y Hortalizas", "verduras-y-hortalizas", "Papas, cebollas, tomates, lechugas y hortalizas"),
            SubcategoryDef("Verdulería General", "verduleria-general", "Otros productos frescos de verdulería"),
        ],
    ),
    DepartmentDef(
        name="Panadería y Confitería",
        slug="panaderia-y-confiteria",
        description="Panificados, budines, facturas y confitería",
        subcategories=[
            SubcategoryDef("Panificados", "panaderia-panificados", "Pan de molde, pan francés, pan para hamburguesas y panchos"),
            SubcategoryDef("Facturas, Budines y Tortas", "panaderia-facturas-budines-y-tortas", "Budines, magdalenas, facturas y pan dulce"),
            SubcategoryDef("Panadería General", "panaderia-general", "Otros productos de panadería"),
        ],
    ),
    DepartmentDef(
        name="Congelados",
        slug="congelados",
        description="Comidas congeladas, hamburguesas, helados y verduras congeladas",
        subcategories=[
            SubcategoryDef("Comidas Preparadas y Rebozados", "congelados-comidas-y-rebozados", "Hamburguesas, patitas, milanesas y pizzas congeladas"),
            SubcategoryDef("Helados y Postres", "congelados-helados-y-postres", "Helados en pote, bombones helados y postres"),
            SubcategoryDef("Verduras Congeladas", "congelados-verduras", "Espinacas, choclo y vegetales congelados"),
            SubcategoryDef("Congelados General", "congelados-general", "Otros congelados"),
        ],
    ),
    DepartmentDef(
        name="Limpieza",
        slug="limpieza",
        description="Artículos de limpieza para el hogar, ropa y desinfección",
        subcategories=[
            SubcategoryDef("Cuidado de la Ropa", "limpieza-cuidado-de-la-ropa", "Jabones líquidos, en polvo para ropa y suavizantes"),
            SubcategoryDef("Limpieza de Cocina y Vajilla", "limpieza-cocina-y-vajilla", "Detergentes, lavavajillas, desengrasantes y esponjas"),
            SubcategoryDef("Limpieza de Baño y Desinfección", "limpieza-bano-y-desinfeccion", "Lavandinas, desinfectantes y limpiadores para baño"),
            SubcategoryDef("Limpiadores de Pisos y Superficies", "limpieza-pisos-y-superficies", "Limpiadores multiuso, ceras y lustramuebles"),
            SubcategoryDef("Papeles y Bolsas de Residuos", "limpieza-papeles-y-bolsas", "Papel higiénico, rollos de cocina, servilletas y bolsas"),
            SubcategoryDef("Insecticidas y Aromatizantes", "limpieza-insecticidas-y-aromatizantes", "Insecticidas, repelentes y aromatizantes de ambiente"),
            SubcategoryDef("Limpieza General", "limpieza-general", "Otros artículos de limpieza"),
        ],
    ),
    DepartmentDef(
        name="Perfumería y Cuidado Personal",
        slug="perfumeria-y-cuidado-personal",
        description="Higiene personal, cuidado capilar, bucal, facial y corporal",
        subcategories=[
            SubcategoryDef("Cuidado Capilar", "perfumeria-cuidado-capilar", "Shampoo, acondicionador, baños de crema y tinturas"),
            SubcategoryDef("Cuidado Bucal", "perfumeria-cuidado-bucal", "Cremas dentales, cepillos de dientes y enjuagues bucales"),
            SubcategoryDef("Jabones y Baño", "perfumeria-jabones-y-bano", "Jabones de tocador, en pan y geles de ducha"),
            SubcategoryDef("Desodorantes", "perfumeria-desodorantes", "Desodorantes y antitranspirantes masculinos y femeninos"),
            SubcategoryDef("Cuidado Facial y Corporal", "perfumeria-cuidado-facial-y-corporal", "Cremas corporales, faciales, protectores solares y lociones"),
            SubcategoryDef("Protección Femenina e Higiene Adulto", "perfumeria-proteccion-femenina", "Toallas femeninas, protectores diarios y pañales adultos"),
            SubcategoryDef("Afeitado y Depilación", "perfumeria-afeitado-y-depilacion", "Máquinas de afeitar, espumas y ceras depilatorias"),
            SubcategoryDef("Perfumería General", "perfumeria-general", "Otros artículos de perfumería y cosmética"),
        ],
    ),
    DepartmentDef(
        name="Bebé y Maternidad",
        slug="bebe-y-maternidad",
        description="Pañales infantiles, toallitas húmedas y cuidado del bebé",
        subcategories=[
            SubcategoryDef("Pañales y Toallitas", "bebe-panales-y-toallitas", "Pañales para bebés y toallitas húmedas"),
            SubcategoryDef("Higiene y Cuidado Infantil", "bebe-higiene-infantil", "Óleo calcáreo, colonias, mamaderas y chupetes"),
            SubcategoryDef("Bebé General", "bebe-general", "Otros productos de bebé y maternidad"),
        ],
    ),
    DepartmentDef(
        name="Mascotas",
        slug="mascotas",
        description="Alimentos y accesorios para perros, gatos y otras mascotas",
        subcategories=[
            SubcategoryDef("Alimento para Perros", "mascotas-alimento-perros", "Alimentos secos y húmedos para perros"),
            SubcategoryDef("Alimento para Gatos", "mascotas-alimento-gatos", "Alimentos secos y húmedos para gatos y piedras sanitarias"),
            SubcategoryDef("Cuidado y Accesorios", "mascotas-cuidado-y-accesorios", "Shampoo, golosinas y accesorios para mascotas"),
            SubcategoryDef("Mascotas General", "mascotas-general", "Otros productos para mascotas"),
        ],
    ),
    DepartmentDef(
        name="Electro, Bazar y Hogar",
        slug="electro-bazar-y-hogar",
        description="Tecnología, electrodomésticos, bazar e iluminación",
        subcategories=[
            SubcategoryDef("Telefonía e Informática", "electro-telefonia-e-informatica", "Celulares, notebooks, tablets y accesorios"),
            SubcategoryDef("TV, Audio y Video", "electro-tv-audio-y-video", "Smart TV, televisores, parlantes y auriculares"),
            SubcategoryDef("Electrodomésticos y Climatización", "electro-electrodomesticos", "Aires acondicionados, estufas, microondas y pavas"),
            SubcategoryDef("Bazar, Iluminación y Ferretería", "electro-bazar-e-iluminacion", "Lámparas LED, pilas, vajilla, sartenes y bazar"),
            SubcategoryDef("Hogar General", "electro-general", "Otros artículos para el hogar"),
        ],
    ),
]


def get_taxonomy_map() -> Dict[str, DepartmentDef]:
    """Return a lookup map of departments keyed by department name."""
    return {dept.name: dept for dept in DEFAULT_TAXONOMY}
