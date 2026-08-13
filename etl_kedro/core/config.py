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

ENTORNOS = ("dev", "pre", "pro")
VAR_ENTORNO = "ETL_ENV"
VAR_RAIZ = "ETL_DATA_ROOT"

ENTORNO_POR_DEFECTO = "dev"
RAIZ_EN_DEV = "."


class ConfigError(RuntimeError):
    """El entorno pedido no existe o le falta configuracion."""


@dataclass(frozen=True)
class Config:
    """Entorno activo y raiz contra la que se resuelven las rutas relativas."""

    entorno: str = ENTORNO_POR_DEFECTO
    raiz: str = RAIZ_EN_DEV

    @classmethod
    def desde_entorno(cls) -> "Config":
        """Lee `ETL_ENV` y `ETL_DATA_ROOT`, validando."""
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
        return cls(entorno=entorno, raiz=raiz)

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
