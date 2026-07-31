"""
Exporta los vectores almacenados en un índice de Amazon S3 Vectors al formato
que espera TensorFlow Embedding Projector (https://projector.tensorflow.org/):

    - vectors.tsv: un vector por línea, valores separados por tabulador,
      SIN encabezado.
    - metadata.tsv: una fila por vector (mismo orden que vectors.tsv), con
      encabezado. Si hay una sola columna de metadata, el proyector la trata
      como "label" (sin exigir encabezado, pero aquí siempre lo incluimos).

Funciona tanto con:
    - El índice creado por el stack CDK (02-cdk-infra), ingerido vía Bedrock
      Knowledge Base (los metadatos los define Bedrock automáticamente).
    - El índice creado por el ejemplo simple (01-api-simple), con metadata
      propia (categoria, texto, etc.)

Las claves de metadata pueden variar según cómo se llenó el índice, así que
el script descubre dinámicamente todas las claves presentes en los vectores
y genera una columna por cada una (rellenando con cadena vacía si un vector
no tiene esa clave).

Uso:
    python exportar_a_projector.py --profile ... --region us-east-1 \
        --vector-bucket stg302-libros-vector-bucket --indice stg302-libros-index \
        --salida ./salida_projector

    Luego, en https://projector.tensorflow.org/, click en "Load" y sube
    vectors.tsv y metadata.tsv desde ./salida_projector/.
"""

import argparse
import csv
from pathlib import Path

import boto3


def listar_todos_los_vectores(s3vectors, vector_bucket: str, indice: str) -> list[dict]:
    print(f"Listando vectores del índice '{indice}' en el bucket '{vector_bucket}'...")
    vectores = []
    next_token = None

    while True:
        kwargs = {
            "vectorBucketName": vector_bucket,
            "indexName": indice,
            "returnData": True,
            "returnMetadata": True,
        }
        if next_token:
            kwargs["nextToken"] = next_token

        respuesta = s3vectors.list_vectors(**kwargs)
        pagina = respuesta.get("vectors", [])
        vectores.extend(pagina)
        print(f"  {len(vectores)} vectores acumulados...")

        next_token = respuesta.get("nextToken")
        if not next_token:
            break

    print(f"  Total: {len(vectores)} vectores.")
    return vectores


def aplanar_metadata(metadata) -> dict:
    """Convierte la metadata (dict con valores posiblemente anidados) en un
    dict plano de strings, apto para una columna de TSV."""
    if not isinstance(metadata, dict):
        return {"metadata": str(metadata)} if metadata is not None else {}

    plano = {}
    for clave, valor in metadata.items():
        if isinstance(valor, (dict, list)):
            plano[clave] = str(valor)
        else:
            plano[clave] = "" if valor is None else str(valor)
    return plano


def exportar(vectores: list[dict], directorio_salida: Path, max_chars_metadata: int = 300):
    directorio_salida.mkdir(parents=True, exist_ok=True)

    ruta_vectors = directorio_salida / "vectors.tsv"
    ruta_metadata = directorio_salida / "metadata.tsv"

    # 1. Aplanar toda la metadata y descubrir el conjunto de columnas
    filas_metadata = []
    columnas = ["key"]  # siempre incluimos la key del vector como primera columna
    columnas_vistas = set(columnas)

    for vector in vectores:
        fila = {"key": vector.get("key", "")}
        fila.update(aplanar_metadata(vector.get("metadata")))
        filas_metadata.append(fila)
        for clave in fila:
            if clave not in columnas_vistas:
                columnas.append(clave)
                columnas_vistas.add(clave)

    # 2. Escribir metadata.tsv (con encabezado)
    with open(ruta_metadata, "w", newline="", encoding="utf-8") as f_meta:
        escritor = csv.writer(f_meta, delimiter="\t")
        escritor.writerow(columnas)
        for fila in filas_metadata:
            valores = []
            for columna in columnas:
                valor = fila.get(columna, "")
                # Recortamos textos muy largos y quitamos tabs/saltos de línea
                # que romperían el formato TSV.
                valor = valor.replace("\t", " ").replace("\n", " ").replace("\r", " ")
                if len(valor) > max_chars_metadata:
                    valor = valor[:max_chars_metadata] + "…"
                valores.append(valor)
            escritor.writerow(valores)

    # 3. Escribir vectors.tsv (sin encabezado)
    with open(ruta_vectors, "w", newline="", encoding="utf-8") as f_vec:
        escritor = csv.writer(f_vec, delimiter="\t")
        for vector in vectores:
            valores_vector = vector.get("data", {}).get("float32", [])
            escritor.writerow(valores_vector)

    print(f"\nArchivos generados en: {directorio_salida}")
    print(f"  {ruta_vectors.name}  ({len(vectores)} filas, {len(vectores[0]['data']['float32']) if vectores else 0} dimensiones)")
    print(f"  {ruta_metadata.name} ({len(columnas)} columnas: {', '.join(columnas)})")
    print(
        "\nPara visualizarlos: abre https://projector.tensorflow.org/, click en "
        "'Load' (panel izquierdo) y selecciona ambos archivos."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Exporta un índice de Amazon S3 Vectors a formato TensorFlow Projector (vectors.tsv + metadata.tsv)"
    )
    parser.add_argument("--profile", default=None, help="Perfil de AWS CLI a usar")
    parser.add_argument("--region", default="us-east-1", help="Región AWS (default: us-east-1)")
    parser.add_argument("--vector-bucket", required=True, help="Nombre del vector bucket de S3 Vectors")
    parser.add_argument("--indice", required=True, help="Nombre del vector index dentro del bucket")
    parser.add_argument(
        "--salida",
        default="./salida_projector",
        help="Directorio donde se escribirán vectors.tsv y metadata.tsv (default: ./salida_projector)",
    )
    parser.add_argument(
        "--max-chars-metadata",
        type=int,
        default=300,
        help="Máximo de caracteres por celda de metadata antes de truncar (default: 300)",
    )
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3vectors = session.client("s3vectors")

    vectores = listar_todos_los_vectores(s3vectors, args.vector_bucket, args.indice)
    if not vectores:
        print("No se encontraron vectores en el índice. Nada que exportar.")
        return

    exportar(vectores, Path(args.salida), max_chars_metadata=args.max_chars_metadata)


if __name__ == "__main__":
    main()
