"""
Sube los documentos markdown de los 5 libros de ciencia de datos al bucket S3
"data source" creado por el stack CDK, y dispara (y monitorea) el ingestion job
del Knowledge Base de Bedrock para que genere los embeddings y los guarde en
el índice de Amazon S3 Vectors.

Flujo:
    1. Lee los outputs del stack de CloudFormation "DemoS3VectorsStack"
       (DataSourceBucketName, KnowledgeBaseId, DataSourceId) — no hace falta
       copiar/pegar nada a mano.
    2. Sube (sync) todos los .md de docs/ al bucket, preservando la
       subcarpeta del libro (capitulos_fes/, capitulos_islp/, etc.) como
       prefijo, para que quede como metadata de origen.
    3. Llama a bedrock-agent StartIngestionJob.
    4. Hace polling de GetIngestionJob hasta que termine (COMPLETE o FAILED),
       mostrando progreso.

Requisitos:
    pip install -r requirements.txt
    Stack "DemoS3VectorsStack" ya desplegado (ver 02-cdk-infra/).

Uso:
    python subir_e_ingestar.py --profile 711387111893_AdministratorAccess --region us-east-1
    python subir_e_ingestar.py --profile ... --docs-dir ../../docs --solo-subir
"""

import argparse
import sys
import time
from pathlib import Path

import boto3

NOMBRE_STACK = "DemoS3VectorsStack"


def obtener_outputs_stack(cf_client, nombre_stack: str) -> dict:
    print(f"Leyendo outputs del stack '{nombre_stack}'...")
    respuesta = cf_client.describe_stacks(StackName=nombre_stack)
    stacks = respuesta.get("Stacks", [])
    if not stacks:
        sys.exit(f"No se encontró el stack '{nombre_stack}'. ¿Ya corriste 'cdk deploy'?")

    outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
    requeridos = ["DataSourceBucketName", "KnowledgeBaseId", "DataSourceId"]
    faltantes = [r for r in requeridos if r not in outputs]
    if faltantes:
        sys.exit(f"Faltan outputs en el stack: {faltantes}")

    print(f"  Bucket de datos:    {outputs['DataSourceBucketName']}")
    print(f"  Knowledge Base ID:  {outputs['KnowledgeBaseId']}")
    print(f"  Data Source ID:     {outputs['DataSourceId']}")
    return outputs


def subir_documentos(s3_client, docs_dir: Path, nombre_bucket: str) -> int:
    archivos_md = sorted(docs_dir.rglob("*.md"))
    if not archivos_md:
        sys.exit(f"No se encontraron archivos .md en {docs_dir}")

    print(f"\nSubiendo {len(archivos_md)} documentos markdown a s3://{nombre_bucket}/ ...")
    for i, archivo in enumerate(archivos_md, start=1):
        # Prefijo = nombre de la carpeta del libro (ej. capitulos_fes/01_Preface.md)
        key = str(archivo.relative_to(docs_dir))
        s3_client.upload_file(str(archivo), nombre_bucket, key)
        if i % 10 == 0 or i == len(archivos_md):
            print(f"  {i}/{len(archivos_md)} subidos...")

    print("  OK, subida completa.")
    return len(archivos_md)


def iniciar_ingestion_job(bedrock_agent_client, knowledge_base_id: str, data_source_id: str) -> str:
    print("\nIniciando ingestion job en el Knowledge Base...")
    respuesta = bedrock_agent_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        description="Ingesta demo STG302: 98 documentos de 5 libros de ciencia de datos",
    )
    job_id = respuesta["ingestionJob"]["ingestionJobId"]
    print(f"  Job iniciado: {job_id}")
    return job_id


def esperar_ingestion_job(
    bedrock_agent_client,
    knowledge_base_id: str,
    data_source_id: str,
    job_id: str,
    intervalo_segundos: int = 15,
):
    print("\nEsperando a que termine el ingestion job (puede tardar varios minutos)...")
    while True:
        respuesta = bedrock_agent_client.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            ingestionJobId=job_id,
        )
        job = respuesta["ingestionJob"]
        estado = job["status"]
        stats = job.get("statistics", {})
        print(
            f"  Estado: {estado} | escaneados={stats.get('numberOfDocumentsScanned', 0)} "
            f"nuevos={stats.get('numberOfNewDocumentsIndexed', 0)} "
            f"modificados={stats.get('numberOfModifiedDocumentsIndexed', 0)} "
            f"fallidos={stats.get('numberOfDocumentsFailed', 0)}"
        )

        if estado in ("COMPLETE", "FAILED"):
            if estado == "FAILED":
                print("  Razones de falla:", job.get("failureReasons"))
            return estado

        time.sleep(intervalo_segundos)


def main():
    parser = argparse.ArgumentParser(
        description="Sube los 98 documentos de ciencia de datos y dispara la ingesta en el Knowledge Base"
    )
    parser.add_argument("--profile", default=None, help="Perfil de AWS CLI a usar")
    parser.add_argument("--region", default="us-east-1", help="Región AWS (default: us-east-1)")
    parser.add_argument(
        "--docs-dir",
        default="../../docs",
        help="Ruta a la carpeta docs/ con los 5 libros (default: ../../docs relativo a este script)",
    )
    parser.add_argument("--stack-name", default=NOMBRE_STACK, help=f"Nombre del stack CDK (default: {NOMBRE_STACK})")
    parser.add_argument(
        "--solo-subir",
        action="store_true",
        help="Si se especifica, solo sube los documentos a S3 sin disparar el ingestion job",
    )
    parser.add_argument(
        "--solo-ingestar",
        action="store_true",
        help="Si se especifica, no sube documentos, solo dispara el ingestion job (útil si ya subiste antes)",
    )
    args = parser.parse_args()

    docs_dir = Path(__file__).parent / args.docs_dir
    docs_dir = docs_dir.resolve()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cf_client = session.client("cloudformation")
    s3_client = session.client("s3")
    bedrock_agent_client = session.client("bedrock-agent")

    outputs = obtener_outputs_stack(cf_client, args.stack_name)

    if not args.solo_ingestar:
        if not docs_dir.is_dir():
            sys.exit(f"No existe el directorio de documentos: {docs_dir}")
        subir_documentos(s3_client, docs_dir, outputs["DataSourceBucketName"])

    if args.solo_subir:
        print("\n--solo-subir especificado: no se disparó el ingestion job.")
        return

    job_id = iniciar_ingestion_job(
        bedrock_agent_client, outputs["KnowledgeBaseId"], outputs["DataSourceId"]
    )
    estado_final = esperar_ingestion_job(
        bedrock_agent_client, outputs["KnowledgeBaseId"], outputs["DataSourceId"], job_id
    )

    if estado_final == "COMPLETE":
        print("\nIngesta completada. El Knowledge Base ya está listo para consultas (ver 04-gradio-app/).")
    else:
        sys.exit("\nLa ingesta terminó con estado FAILED. Revisa los detalles arriba.")


if __name__ == "__main__":
    main()
