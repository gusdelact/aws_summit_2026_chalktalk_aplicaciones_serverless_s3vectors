# Demo STG302 · RAG serverless con Amazon S3 Vectors

Demo de apoyo para la sesión **STG302 - Construyendo aplicaciones serverless de
vectores con Amazon S3 Vectors** (AWS Summit CDMX, 12 de agosto de 2026).

## Corpus de la demo

El pipeline (pasos 2 a 5) es genérico: funciona con **cualquier colección de
documentos markdown con estructura de libro** (capítulos numerados, un
archivo `.md` por capítulo/sección). No depende del contenido de un libro en
particular — solo espera encontrar archivos `.md` dentro de una carpeta que
tú indiques (por default, `../docs/`).

Para armar tu propio corpus de prueba:

1. Crea una carpeta (o usa `docs/`) con subcarpetas, una por libro/documento.
2. Dentro de cada subcarpeta, coloca un archivo `.md` por capítulo. El
   prefijo numérico (`01_`, `02_`, ...) es solo convención para mantener el
   orden de lectura; no es obligatorio para que el pipeline funcione.
3. Corre `03-ingesta/subir_e_ingestar.py` apuntando con `--docs-dir` a esa
   carpeta.

### Corpus usado para probar esta demo

Para las pruebas de esta demo se usaron **98 documentos markdown**
provenientes de 5 libros de ciencia de datos, organizados en las carpetas
`capitulos_*` bajo `../docs/`:

| Carpeta | Libro | Dónde obtenerlo |
|---|---|---|
| `capitulos_TheElementsOfStatisticalLearning/` | The Elements of Statistical Learning (ESL) — Hastie, Tibshirani, Friedman | [hastie.su.domains/ElemStatLearn](https://hastie.su.domains/ElemStatLearn/) |
| `capitulos_fes/` | Feature Engineering and Selection (FES) — Kuhn, Johnson | [feat.engineering](https://www.feat.engineering/) |
| `capitulos_islp/` | An Introduction to Statistical Learning with Python (ISLP) — James, Witten, Hastie, Tibshirani, Taylor | [statlearning.com](https://www.statlearning.com/) |
| `capitulos_pdsh/` | Python Data Science Handbook (PDSH) — VanderPlas | [jakevdp.github.io/PythonDataScienceHandbook](https://jakevdp.github.io/PythonDataScienceHandbook/) |
| `capitulos_r4ds/` | R for Data Science (R4DS) — Wickham, Çetinkaya-Rundel, Grolemund | [r4ds.hadley.nz](https://r4ds.hadley.nz/) |

**Estos libros NO se distribuyen en este repositorio.** Cada uno tiene su
propio copyright (varios bajo licencia Creative Commons
**BY-NC-ND**, que prohíbe explícitamente la redistribución, y otros con
"todos los derechos reservados" de su editorial). La carpeta `docs/` está
excluida del control de versiones por esta razón — si quieres reproducir la
demo con este mismo corpus, descarga cada libro desde su sitio oficial
(enlaces arriba) y conviértelo a markdown tú mismo; si prefieres evitarte
ese paso, usa cualquier otra colección de documentos markdown propia o de
dominio público/licencia abierta.

## Estructura de la demo

```
demo-s3-vectors/
├── 01-api-simple/       # Ejemplo mínimo: API de S3 Vectors con boto3 (sin CDK, sin Bedrock KB)
├── 02-cdk-infra/        # Stack CDK end-to-end: vector bucket, índice, Knowledge Base, roles IAM
├── 03-ingesta/          # Sube los documentos markdown y dispara la ingesta del Knowledge Base
├── 04-gradio-app/       # UI de chat (Gradio) para consultar el Knowledge Base
└── 05-export-projector/ # Exporta los vectores a TensorFlow Embedding Projector
```

Cada carpeta tiene su propio `requirements.txt`. Se recomienda un venv por
carpeta (o uno compartido para 01/03/04/05, que solo usan boto3 + gradio).

## Requisitos previos

- Python 3.9+
- Cuenta de AWS con acceso a **Amazon S3 Vectors** y **Amazon Bedrock**
  (modelos `amazon.titan-embed-text-v2:0` y `amazon.nova-pro-v1:0`
  habilitados en el Model Access de Bedrock, región `us-east-1`)
- Perfil de AWS CLI configurado. En esta demo se usa el perfil
  `711387111893_AdministratorAccess`. Antes de correr cualquier script:

  ```bash
  aws sso login --profile 711387111893_AdministratorAccess
  ```

- Para la parte de CDK: Node.js 18+ (se usa `npx aws-cdk` para no requerir
  instalación global) y haber hecho `cdk bootstrap` una vez en la cuenta/región.

## Orden recomendado de la demo en vivo

### 1. API simple de S3 Vectors (sin infraestructura)

Ejemplo autocontenido: crea un vector bucket, un índice, genera embeddings
con Titan y hace una búsqueda por similitud (mismo ejemplo "bebida caliente"
de la presentación STG302).

```bash
cd 01-api-simple
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python simple_s3_vectors_demo.py --profile 711387111893_AdministratorAccess --region us-east-1
# Para borrar los recursos creados al terminar:
python simple_s3_vectors_demo.py --profile ... --bucket <nombre-que-se-imprimió> --cleanup
```

### 2. Despliegue de la infraestructura end-to-end (CDK)

Crea el vector bucket + índice "reales" de la demo, el bucket de datos
fuente, el rol de IAM, el Knowledge Base de Bedrock y el Data Source.

```bash
cd 02-cdk-infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export AWS_PROFILE=711387111893_AdministratorAccess
export CDK_DEFAULT_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT=<account-id>   # aws sts get-caller-identity

npx aws-cdk bootstrap   # solo la primera vez en esta cuenta/región
npx aws-cdk deploy
```

Al terminar, `cdk deploy` imprime los outputs (`KnowledgeBaseId`,
`DataSourceBucketName`, etc.) que usan los scripts siguientes.

### 3. Subir los documentos y disparar la ingesta

```bash
cd ../03-ingesta
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python subir_e_ingestar.py --profile 711387111893_AdministratorAccess --region us-east-1
# O apuntando a otra carpeta con tu propio corpus:
python subir_e_ingestar.py --profile ... --docs-dir /ruta/a/tu/corpus
```

Esto sube los `.md` que encuentre en `--docs-dir` (por default `../../docs/`)
al bucket de datos, dispara el `ingestion job` de Bedrock y espera (con
polling) hasta que termine.

### 4. Chat interactivo con el Knowledge Base (Gradio)

```bash
cd ../04-gradio-app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py --profile 711387111893_AdministratorAccess --region us-east-1
```

Abre `http://127.0.0.1:7860`. Usa `--compartir` si quieres un enlace público
temporal de Gradio para mostrarlo desde otro dispositivo durante la charla.

### 5. Visualizar los vectores en TensorFlow Projector

```bash
cd ../05-export-projector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python exportar_a_projector.py --profile 711387111893_AdministratorAccess --region us-east-1 \
    --vector-bucket stg302-libros-vector-bucket --indice stg302-libros-index \
    --salida ./salida_projector
```

Luego ve a <https://projector.tensorflow.org/>, click en **Load** (panel
izquierdo) y sube `vectors.tsv` y `metadata.tsv` desde `./salida_projector/`.
Podrás explorar en 3D (PCA / t-SNE / UMAP) cómo se agrupan los fragmentos del
corpus según su significado semántico.

## Limpieza de recursos

Para no dejar recursos corriendo después de la demo:

```bash
cd 02-cdk-infra
source .venv/bin/activate
npx aws-cdk destroy
```

Esto elimina el Knowledge Base, el Data Source, el vector bucket/índice y el
bucket de datos (configurado con `auto_delete_objects` y `RemovalPolicy.DESTROY`).

## Notas de diseño

- **Modelo de embeddings**: `amazon.titan-embed-text-v2:0`, 1024 dimensiones
  (máxima calidad soportada por el modelo).
- **Modelo de generación**: Amazon Nova Pro vía cross-region inference
  profile (`us.amazon.nova-pro-v1:0`), requerido porque este modelo no admite
  invocación on-demand directa.
- **Chunking**: jerárquico (1500 tokens padre / 300 tokens hijo, 60 de
  overlap), apropiado para libros largos con estructura de capítulos.
- **Región**: `us-east-1` (S3 Vectors y Bedrock Knowledge Bases con soporte
  S3_VECTORS están disponibles ahí; ver también la lista de regiones que se
  siguen expandiendo).
- Todos los scripts son independientes entre sí salvo por los nombres de
  recursos compartidos (`stg302-libros-vector-bucket`, `stg302-libros-index`)
  y los outputs del stack CDK, que 03/04 leen automáticamente vía
  `describe_stacks`.
