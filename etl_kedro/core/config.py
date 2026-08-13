"""Configuracion por entorno: donde viven los datos en cada sitio.

Los datasets declaran su ruta **relativa**; el entorno decide contra que raiz se
resuelve. Asi el mismo codigo apunta a `./data` en local y a `s3://.../zona` en
produccion sin tocar ninguna linea.

    ETL_ENV=pro ETL_DATA_ROOT=s3://mi-bucket/oro python -m etl_kedro.main --all

En `dev` la raiz por defecto es `.`, que reproduce el comportamiento de tener
las rutas escritas a pelo. En `pre` y `pro` no hay valor por defecto a proposito:
mas vale fallar al arrancar que escribir en el sitio equivocado.
"""

import os
from dataclasses import dataclass

FORMATOS = ("csv", "parquet")

ENTORNOS = ("dev", "pre", "pro")
VAR_ENTORNO = "ETL_ENV"
VAR_RAIZ = "ETL_DATA_ROOT"
VAR_FORMATO = "ETL_OUTPUT_FORMAT"

ENTORNO_POR_DEFECTO = "dev"
RAIZ_EN_DEV = "."


class ConfigError(RuntimeError):
    """El entorno pedido no existe o le falta configuracion."""


@dataclass(frozen=True)
class Config:
    """Entorno activo y raiz contra la que se resuelven las rutas relativas."""

    entorno: str = ENTORNO_POR_DEFECTO
    raiz: str = RAIZ_EN_DEV
    # Sobrescribe el formato que declara cada dataset. `None` es lo normal: cada
    # uno escribe en el suyo. Se fuerza para comparar backends, donde hace falta
    # un formato que conserve los tipos (`etl_kedro.compare`).
    formato_salida: str | None = None
    # A que datasets alcanza esa sobrescritura: los que produce la cadena. Sale
    # del grafo, no de una lista a mano. Las entradas externas no se tocan, que
    # las escribio otro y siguen en su formato.
    datasets_forzados: frozenset[str] = frozenset()

    @classmethod
    def desde_entorno(cls) -> "Config":
        """Lee `ETL_ENV`, `ETL_DATA_ROOT` y `ETL_OUTPUT_FORMAT`, validando."""
        entorno = os.environ.get(VAR_ENTORNO, ENTORNO_POR_DEFECTO)
        if entorno not in ENTORNOS:
            raise ConfigError(
                f"{VAR_ENTORNO} invalido: {entorno!r}. Validos: {', '.join(ENTORNOS)}"
            )

        raiz = os.environ.get(VAR_RAIZ)
        if raiz is None:
            if entorno != "dev":
                raise ConfigError(
                    f"En el entorno {entorno!r} hay que indicar {VAR_RAIZ}: "
                    "no se asume una raiz de datos fuera de local."
                )
            raiz = RAIZ_EN_DEV

        formato = os.environ.get(VAR_FORMATO)
        if formato is not None and formato not in FORMATOS:
            raise ConfigError(
                f"{VAR_FORMATO} invalido: {formato!r}. Validos: {', '.join(FORMATOS)}"
            )
        return cls(entorno=entorno, raiz=raiz, formato_salida=formato)

    def formato_de(self, nombre: str, formato_declarado: str) -> str:
        """Formato efectivo de un dataset: el forzado por el entorno, o el suyo.

        La sobrescritura vale tanto al leer como al escribir; si no, el job que
        consume buscaria CSV donde el anterior dejo parquet y la cadena se
        rompe a mitad.
        """
        if self.formato_salida and nombre in self.datasets_forzados:
            return self.formato_salida
        return formato_declarado

    def resolver(self, ruta: str) -> str:
        """Devuelve la ruta absoluta o remota que corresponde a `ruta`.

        Una ruta que ya es absoluta o un URI (`s3://...`) se deja intacta: es su
        forma de escapar de la raiz. El resto cuelga de ella.
        """
        if "://" in ruta or ruta.startswith("/"):
            return ruta
        raiz = self.raiz.rstrip("/")
        if raiz in ("", "."):
            return ruta
        return f"{raiz}/{ruta}"
