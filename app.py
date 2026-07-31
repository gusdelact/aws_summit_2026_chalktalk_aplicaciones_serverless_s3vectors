"""
App Gradio para interactuar con el Knowledge Base de Bedrock (RAG sobre los
5 libros de ciencia de datos) usando la API RetrieveAndGenerate.

La app:
    - Lee automáticamente el KnowledgeBaseId desde los outputs del stack CDK
      "DemoS3VectorsStack" (o se puede pasar por variable de entorno / CLI).
    - Muestra la respuesta generada por el LLM junto con las citas
      (fragmento + libro/archivo de origen) recuperadas de S3 Vectors.
    - Interfaz simple tipo chat, en español.

Requisitos:
    pip install -r requirements.txt
    Stack "DemoS3VectorsStack" desplegado y con documentos ya ingeridos
    (ver 02-cdk-infra/ y 03-ingesta/).

Uso:
    python app.py --profile 711387111893_AdministratorAccess --region us-east-1
    python app.py --profile ... --knowledge-base-id ABCDEF1234   # sin leer el stack
"""

import argparse
import os

import boto3
import gradio as gr

NOMBRE_STACK = "DemoS3VectorsStack"

# Amazon Nova Pro vía cross-region inference profile "us." (requerido porque
# este modelo no admite invocación on-demand directa). Nova Pro ofrece buen
# balance de calidad/costo/latencia para RAG en español.
MODELO_GENERACION_ID = "us.amazon.nova-pro-v1:0"


def resolver_knowledge_base_id(session, stack_name: str) -> str:
    cf_client = session.client("cloudformation")
    respuesta = cf_client.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in respuesta["Stacks"][0]["Outputs"]}
    return outputs["KnowledgeBaseId"]


def construir_arn_modelo(session, model_id: str) -> str:
    sts_client = session.client("sts")
    cuenta = sts_client.get_caller_identity()["Account"]
    region = session.region_name
    return f"arn:aws:bedrock:{region}:{cuenta}:inference-profile/{model_id}"


def formatear_citas(citations: list) -> str:
    """Convierte las citas devueltas por RetrieveAndGenerate en markdown legible."""
    if not citations:
        return ""

    lineas = ["\n\n---\n**Fuentes consultadas:**"]
    referencias_vistas = set()
    contador = 0

    for citacion in citations:
        for referencia in citacion.get("retrievedReferences", []):
            ubicacion = referencia.get("location", {})
            uri = ubicacion.get("s3Location", {}).get("uri", "desconocido")
            texto = referencia.get("content", {}).get("text", "")
            texto_corto = (texto[:220] + "…") if len(texto) > 220 else texto

            clave = (uri, texto_corto)
            if clave in referencias_vistas:
                continue
            referencias_vistas.add(clave)
            contador += 1

            nombre_archivo = uri.rsplit("/", 1)[-1] if uri else "desconocido"
            lineas.append(f"\n{contador}. **{nombre_archivo}**\n   > {texto_corto}")

    return "\n".join(lineas)


def construir_funcion_chat(bedrock_agent_runtime, knowledge_base_id: str, model_arn: str):
    def responder(mensaje: str, historial: list):
        # NOTA: se usa el promptTemplate por defecto de Bedrock (sin
        # personalizar). Un textPromptTemplate personalizado hace que Nova
        # no logre alinear su salida con el mecanismo de citación de
        # Bedrock, y "retrievedReferences" llega vacío (se pierden las
        # fuentes). Como las preguntas ya vienen en español, el modelo
        # responde en español sin necesidad de forzarlo por prompt.
        respuesta = bedrock_agent_runtime.retrieve_and_generate(
            input={"text": mensaje},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": knowledge_base_id,
                    "modelArn": model_arn,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {"numberOfResults": 6}
                    },
                },
            },
        )

        texto_respuesta = respuesta["output"]["text"]
        citas_md = formatear_citas(respuesta.get("citations", []))
        return texto_respuesta + citas_md

    return responder


def main():
    parser = argparse.ArgumentParser(description="Demo Gradio: RAG sobre libros de ciencia de datos con S3 Vectors")
    parser.add_argument("--profile", default=None, help="Perfil de AWS CLI a usar")
    parser.add_argument("--region", default="us-east-1", help="Región AWS (default: us-east-1)")
    parser.add_argument("--stack-name", default=NOMBRE_STACK, help=f"Nombre del stack CDK (default: {NOMBRE_STACK})")
    parser.add_argument(
        "--knowledge-base-id",
        default=os.environ.get("KNOWLEDGE_BASE_ID"),
        help="ID del Knowledge Base (si se omite, se lee del stack CDK)",
    )
    parser.add_argument(
        "--modelo",
        default=MODELO_GENERACION_ID,
        help=f"ID del modelo de generación / inference profile (default: {MODELO_GENERACION_ID})",
    )
    parser.add_argument("--puerto", type=int, default=7860, help="Puerto local para la interfaz Gradio")
    parser.add_argument(
        "--compartir",
        action="store_true",
        help="Si se especifica, genera un enlace público temporal de Gradio (gradio.live)",
    )
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    bedrock_agent_runtime = session.client("bedrock-agent-runtime")

    knowledge_base_id = args.knowledge_base_id or resolver_knowledge_base_id(session, args.stack_name)
    model_arn = construir_arn_modelo(session, args.modelo)

    print(f"Knowledge Base ID: {knowledge_base_id}")
    print(f"Modelo de generación: {model_arn}")

    responder = construir_funcion_chat(bedrock_agent_runtime, knowledge_base_id, model_arn)

    interfaz = gr.ChatInterface(
        fn=responder,
        title="STG302 · RAG serverless con Amazon S3 Vectors",
        description=(
            "Pregunta lo que quieras sobre los 5 libros de ciencia de datos "
            "(The Elements of Statistical Learning, Feature Engineering and "
            "Selection, ISLP, Python Data Science Handbook, R for Data Science). "
            "Las respuestas se generan con Amazon Bedrock Knowledge Bases usando "
            "Amazon S3 Vectors como almacén vectorial."
        ),
        examples=[
            "¿Qué es la regularización Ridge y en qué se diferencia de Lasso?",
            "Explícame el algoritmo de Random Forest y cuándo conviene usarlo",
            "¿Cómo se maneja el sesgo-varianza en modelos de machine learning?",
            "¿Qué estrategias de feature engineering existen para variables categóricas?",
        ],
    )

    interfaz.launch(server_port=args.puerto, share=args.compartir)


if __name__ == "__main__":
    main()
