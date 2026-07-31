#!/usr/bin/env python3
"""Punto de entrada de la app CDK: demo end-to-end de Amazon S3 Vectors + Bedrock Knowledge Bases."""

import os

import aws_cdk as cdk

from demo_s3_vectors_cdk.demo_stack import DemoS3VectorsStack

app = cdk.App()

DemoS3VectorsStack(
    app,
    "DemoS3VectorsStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="Demo STG302: RAG serverless con Amazon S3 Vectors + Bedrock Knowledge Bases (98 libros de ciencia de datos)",
)

app.synth()
