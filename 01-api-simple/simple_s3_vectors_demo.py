"""
Demo simple de la API de Amazon S3 Vectors (sin CDK, sin Bedrock Knowledge Bases).

Este script muestra el flujo mínimo end-to-end usando directamente el cliente
boto3 "s3vectors":

1. Crear un vector bucket
2. Crear un vector index (dimension, distance_metric)
3. Generar embeddings de unos textos de ejemplo con Amazon Titan Embeddings V2
   (via Bedrock Runtime)
4. Insertar los vectores con PutVectors
5. Hacer una consulta de similitud con QueryVectors
6. (Opcional) Limpiar los recursos creados

Requisitos:
    pip install -r requirements.txt
    Credenciales AWS configuradas (perfil con permisos s3vectors:* y
    bedrock:InvokeModel para amazon.titan-embed-text-v2:0)

Uso:
    python simple_s3_vectors_demo.py --profile <tu-perfil-aws> --region us-east-1
    python simple_s3_vectors_demo.py --profile ... --cleanup   # borra bucket/indice al final
"""

import argparse
import json
import time
import uuid

import boto3

MODELO_EMBEDDINGS = "amazon.titan-embed-text-v2:0"
DIMENSION = 1024  # Titan v2 soporta 256, 512 o 1024

# Textos de ejemplo (mismo estilo que el ejemplo "bebida caliente" de la charla STG302)
DOCUMENTOS_EJEMPLO = [
    {"id": "doc-1", "texto": "El té es una bebida caliente hecha con hojas infusionadas en agua.", "categoria": "bebida"},
    {"id": "doc-2", "texto": "El café es una bebida caliente preparada a partir de granos tostados y molidos.", "categoria": "bebida"},
    {"id": "doc-3", "texto": "La televisión es un dispositivo electrónico para ver contenido audiovisual.", "categoria": "electronica"},
    {"id": "doc-4", "texto": "Un teléfono inteligente permite hacer llamadas, navegar internet y usar aplicaciones.", "categoria": "electronica"},
    {"id": "doc-5", "texto": "La música clásica incluye compositores como Beethoven, Mozart y Bach.", "categoria": "musica"},
    {"id": "doc-6", "texto": "El jazz es un género musical nacido en Nueva Orleans a principios del siglo XX.", "categoria": "musica"},
    {"id": "doc-7", "texto": "La orca es un mamífero marino depredador, también llamado ballena asesina.", "categoria": "animal"},
    {"id": "doc-8", "texto": "El gorila es un primate herbívoro que vive en selvas de África central.", "categoria": "animal"},
]


def generar_embedding(bedrock_runtime, texto: str, dimensiones: int = DIMENSION) -> list[float]:
    """Invoca Amazon Titan Text Embeddings V2 y devuelve el vector resultante."""
    body = json.dumps({"inputText": texto, "dimensions": dimensiones, "normalize": True})
    respuesta = bedrock_runtime.invoke_model(
        modelId=MODELO_EMBEDDINGS,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(respuesta["body"].read())
    return payload["embedding"]


def crear_bucket_e_indice(s3vectors, nombre_bucket: str, nombre_indice: str):
    print(f"\n[1/5] Creando vector bucket '{nombre_bucket}'...")
    s3vectors.create_vector_bucket(vectorBucketName=nombre_bucket)
    print("      OK")

    print(f"[2/5] Creando vector index '{nombre_indice}' (dimension={DIMENSION}, cosine)...")
    s3vectors.create_index(
        vectorBucketName=nombre_bucket,
        indexName=nombre_indice,
        dataType="float32",
        dimension=DIMENSION,
        distanceMetric="cosine",
        # metadataConfiguration excluye estas claves del filtrado (quedan solo informativas)
        metadataConfiguration={"nonFilterableMetadataKeys": ["texto"]},
    )
    print("      OK")


def ingestar_documentos(s3vectors, bedrock_runtime, nombre_bucket: str, nombre_indice: str):
    print(f"\n[3/5] Generando embeddings e insertando {len(DOCUMENTOS_EJEMPLO)} documentos...")
    vectores = []
    for doc in DOCUMENTOS_EJEMPLO:
        embedding = generar_embedding(bedrock_runtime, doc["texto"])
        vectores.append(
            {
                "key": doc["id"],
                "data": {"float32": embedding},
                "metadata": {"categoria": doc["categoria"], "texto": doc["texto"]},
            }
        )

    s3vectors.put_vectors(
        vectorBucketName=nombre_bucket,
        indexName=nombre_indice,
        vectors=vectores,
    )
    print("      OK, vectores insertados:", [v["key"] for v in vectores])


def consultar(s3vectors, bedrock_runtime, nombre_bucket: str, nombre_indice: str, consulta: str, top_k: int = 3):
    print(f"\n[4/5] Consultando por similitud: '{consulta}' (top_k={top_k})")
    embedding_consulta = generar_embedding(bedrock_runtime, consulta)

    resultado = s3vectors.query_vectors(
        vectorBucketName=nombre_bucket,
        indexName=nombre_indice,
        queryVector={"float32": embedding_consulta},
        topK=top_k,
        returnDistance=True,
        returnMetadata=True,
    )

    print("      Resultados (más similar primero):")
    for i, vector in enumerate(resultado.get("vectors", []), start=1):
        metadata = vector.get("metadata", {})
        print(
            f"        {i}. key={vector['key']:<8} distancia={vector['distance']:.4f} "
            f"categoria={metadata.get('categoria')} texto=\"{metadata.get('texto')}\""
        )


def limpiar(s3vectors, nombre_bucket: str, nombre_indice: str):
    print(f"\n[5/5] Limpiando recursos (--cleanup): índice '{nombre_indice}' y bucket '{nombre_bucket}'...")
    try:
        s3vectors.delete_index(vectorBucketName=nombre_bucket, indexName=nombre_indice)
        s3vectors.delete_vector_bucket(vectorBucketName=nombre_bucket)
        print("      OK, recursos eliminados")
    except Exception as exc:  # noqa: BLE001 - demo, mostramos el error tal cual
        print(f"      Aviso: no se pudo limpiar completamente: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Demo simple de la API de Amazon S3 Vectors")
    parser.add_argument("--profile", default=None, help="Perfil de AWS CLI a usar")
    parser.add_argument("--region", default="us-east-1", help="Región AWS (default: us-east-1)")
    parser.add_argument(
        "--bucket",
        default=None,
        help="Nombre del vector bucket a crear (default: genera uno único)",
    )
    parser.add_argument("--indice", default="demo-index", help="Nombre del vector index (default: demo-index)")
    parser.add_argument(
        "--consulta",
        default="bebida caliente",
        help="Texto de consulta para la búsqueda por similitud",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Si se especifica, borra el índice y el bucket al finalizar la demo",
    )
    args = parser.parse_args()

    nombre_bucket = args.bucket or f"demo-s3-vectors-{uuid.uuid4().hex[:8]}"

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3vectors = session.client("s3vectors")
    bedrock_runtime = session.client("bedrock-runtime")

    crear_bucket_e_indice(s3vectors, nombre_bucket, args.indice)

    # S3 Vectors es eventualmente consistente justo después de crear el índice;
    # una pequeña espera evita errores transitorios en la demo en vivo.
    time.sleep(2)

    ingestar_documentos(s3vectors, bedrock_runtime, nombre_bucket, args.indice)

    time.sleep(2)

    consultar(s3vectors, bedrock_runtime, nombre_bucket, args.indice, args.consulta)

    if args.cleanup:
        limpiar(s3vectors, nombre_bucket, args.indice)
    else:
        print(
            f"\nRecursos NO eliminados. Vector bucket: '{nombre_bucket}', índice: '{args.indice}'. "
            "Vuelve a correr con --cleanup y los mismos --bucket/--indice para borrarlos."
        )


if __name__ == "__main__":
    main()
