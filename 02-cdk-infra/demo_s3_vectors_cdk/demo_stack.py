"""
Stack CDK end-to-end para la demo STG302: RAG serverless con Amazon S3 Vectors
y Amazon Bedrock Knowledge Bases.

Recursos creados:
    - Bucket S3 "normal" (data source): aquí se suben los 98 documentos markdown
      de los 5 libros de ciencia de datos.
    - Vector bucket + Vector index de Amazon S3 Vectors: almacén nativo de
      embeddings, usado como vector store del Knowledge Base.
    - Rol de IAM para el Knowledge Base de Bedrock, con permisos de:
        * Lectura del bucket de datos fuente (S3).
        * Lectura/escritura del vector bucket / vector index (s3vectors:*).
        * Invocación del modelo de embeddings (Bedrock InvokeModel).
    - Knowledge Base de Bedrock (tipo VECTOR, storage S3_VECTORS) usando
      Titan Text Embeddings V2 (1024 dimensiones).
    - Data Source de tipo S3 apuntando al bucket de documentos, con chunking
      jerárquico (adecuado para libros largos con capítulos/secciones).

Este stack NO sube los documentos ni dispara el ingestion job: eso lo hace el
script 03-ingesta/subir_e_ingestar.py una vez que el stack está desplegado.
"""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

# Amazon Titan Text Embeddings V2: hasta 8192 tokens de entrada, salida de
# 256/512/1024 dimensiones configurables. Usamos 1024 (máxima calidad).
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

# Nombres de los recursos (se pueden ajustar; deben ser únicos en la cuenta/región)
VECTOR_BUCKET_NAME = "stg302-libros-vector-bucket"
VECTOR_INDEX_NAME = "stg302-libros-index-v2"
DATA_SOURCE_BUCKET_NAME_PREFIX = "stg302-libros-datos"


class DemoS3VectorsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # 1. Bucket S3 "normal": data source con los documentos markdown
        # ------------------------------------------------------------------
        data_source_bucket = s3.Bucket(
            self,
            "DataSourceBucket",
            bucket_name=f"{DATA_SOURCE_BUCKET_NAME_PREFIX}-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=False,
        )

        # ------------------------------------------------------------------
        # 2. Vector bucket + vector index (Amazon S3 Vectors)
        # ------------------------------------------------------------------
        vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "VectorBucket",
            vector_bucket_name=VECTOR_BUCKET_NAME,
        )

        vector_index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            vector_bucket_name=vector_bucket.vector_bucket_name,
            index_name=VECTOR_INDEX_NAME,
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            # Cuando el índice se crea "a mano" (fuera del flujo Quick-create
            # de la consola de Bedrock), las claves de metadata que Bedrock
            # genera automáticamente quedan como "filterable" por defecto.
            # AMAZON_BEDROCK_TEXT contiene el texto completo del chunk y
            # AMAZON_BEDROCK_METADATA info adicional (fechas, origen, etc.):
            # ambas pueden superar fácilmente el límite de 2KB de metadata
            # filtrable, sobre todo con chunks grandes (jerárquicos). Las
            # marcamos como no-filtrables para evitar el error
            # "Filterable metadata must have at most 2048 bytes".
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=[
                    "AMAZON_BEDROCK_TEXT",
                    "AMAZON_BEDROCK_METADATA",
                ]
            ),
        )
        # El índice depende del bucket vectorial (referencia por nombre, pero
        # forzamos el orden de creación explícitamente por claridad).
        vector_index.add_resource_dependency(vector_bucket)

        # ------------------------------------------------------------------
        # 3. Rol de IAM para el Knowledge Base de Bedrock
        # ------------------------------------------------------------------
        kb_role = iam.Role(
            self,
            "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"
                    },
                },
            ),
            description="Rol de servicio para el Bedrock Knowledge Base de la demo STG302 (S3 Vectors)",
        )

        # 3a. Lectura del bucket de datos fuente
        data_source_bucket.grant_read(kb_role)

        # 3b. Acceso al vector bucket / vector index de S3 Vectors
        vector_bucket_arn = vector_bucket.attr_vector_bucket_arn
        vector_index_arn = vector_index.attr_index_arn

        kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorsAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3vectors:GetIndex",
                    "s3vectors:GetVectorBucket",
                    "s3vectors:PutVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:ListVectors",
                    "s3vectors:QueryVectors",
                ],
                resources=[vector_bucket_arn, vector_index_arn],
            )
        )

        # 3c. Invocación del modelo de embeddings
        kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeEmbeddingModel",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"
                ],
            )
        )

        # ------------------------------------------------------------------
        # 4. Knowledge Base de Bedrock (VECTOR, storage S3_VECTORS)
        # ------------------------------------------------------------------
        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name="stg302-libros-ciencia-datos-kb",
            description=(
                "Demo STG302 - RAG sobre 5 libros de ciencia de datos "
                "(ESL, FES, ISLP, PDSH, R4DS) usando Amazon S3 Vectors"
            ),
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}",
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBEDDING_DIMENSIONS,
                            embedding_data_type="FLOAT32",
                        )
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=vector_bucket_arn,
                    index_arn=vector_index_arn,
                ),
            ),
        )
        knowledge_base.node.add_dependency(vector_index)
        # Aseguramos que la política de IAM (que otorga permisos s3vectors:*
        # sobre el bucket/índice) exista ANTES de crear el Knowledge Base.
        # Sin esta dependencia explícita, CloudFormation puede crear ambos
        # recursos en paralelo y el KB falla al validar el storage config
        # porque el rol todavía no tiene los permisos adjuntos.
        knowledge_base.node.add_dependency(kb_role)

        # ------------------------------------------------------------------
        # 5. Data source S3 con chunking jerárquico (bueno para libros largos)
        # ------------------------------------------------------------------
        data_source = bedrock.CfnDataSource(
            self,
            "DataSource",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name="stg302-libros-datasource",
            description="Documentos markdown de los 5 libros de ciencia de datos",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=data_source_bucket.bucket_arn,
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="HIERARCHICAL",
                    hierarchical_chunking_configuration=bedrock.CfnDataSource.HierarchicalChunkingConfigurationProperty(
                        level_configurations=[
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=1500
                            ),
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=300
                            ),
                        ],
                        overlap_tokens=60,
                    ),
                )
            ),
        )
        data_source.node.add_dependency(knowledge_base)

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        CfnOutput(self, "DataSourceBucketName", value=data_source_bucket.bucket_name)
        CfnOutput(self, "VectorBucketArn", value=vector_bucket_arn)
        CfnOutput(self, "VectorIndexArn", value=vector_index_arn)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base.attr_knowledge_base_id)
        CfnOutput(self, "KnowledgeBaseArn", value=knowledge_base.attr_knowledge_base_arn)
        CfnOutput(self, "DataSourceId", value=data_source.attr_data_source_id)
        CfnOutput(self, "KnowledgeBaseRoleArn", value=kb_role.role_arn)
