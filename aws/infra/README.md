# AWS Academy — infraestructura

[serverless.yml](serverless.yml) define el núcleo AWS con **Serverless Framework v3**: nombres, rutas, eventos, tablas, índices, colas/DLQ, S3, EventBridge, Step Functions y SNS. Los `handler` son rutas previstas: **aún no existe código Lambda ni se ha desplegado el stack**. La [arquitectura v2](../../arquitectura-solucion-v2.md) usa los mismos nombres.

La plantilla asigna el `LabRole` existente a todas las Lambdas y a la máquina Step Functions. No declara `AWS::IAM::Role`. Antes de desplegar, comprobar que el rol se puede pasar a ambos servicios, que Step Functions confía en `states.amazonaws.com` y que tiene permisos efectivos para DynamoDB, S3, SQS, Streams, EventBridge, SNS, SSM/KMS, Lambda y CloudWatch. Si falta confianza o permisos, habrá que solicitar un rol compatible al docente.

Se fijó `python3.11` porque [AWS lo mantiene](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) y Serverless Framework v3.40 lo reconoce. Los nombres de los handlers son contratos de módulos Python futuros, no archivos ya creados.

## Marcadores para completar

- `custom.accountId: 'xxxxxxxxxxxx'`: sustituir por los 12 dígitos de la cuenta de AWS Academy. El valor ficticio impide desplegar tal como está.
- `# org: xxxx`: marcador comentado. Una organización real de Serverless Dashboard exige al menos cinco caracteres e inicio de sesión; el laboratorio no necesita Dashboard para este diseño.
- Región: `us-east-1` por defecto; confirmar la región del lab. Origen `PORTAL_ORIGIN` y URLs `GCP_INGEST_URL`/`AZURE_INGEST_URL`: sustituir `example.invalid` por los destinos reales.
- Parámetros SSM `/${service}-${stage}/jwt/firma` y claves separadas de GCP/Azure: crearlos con valores secretos fuera de Git. La plantilla solo define sus **nombres**, no sus valores.
- Amplify Hosting se configura aparte con nombre propuesto `red-telecorp-portal`; conectar el frontend cuando exista. Los recursos GCP/Azure permanecen en sus carpetas respectivas.

## Validación realizada

`npx --yes serverless@3.40.0 print --config serverless.yml --format json` resolvió el archivo sin errores de esquema. También se probó `serverless package` con **handlers vacíos temporales dentro de `/chatgpt/`**, que está ignorado por Git. Generó una plantilla CloudFormation de 129 recursos: 20 Lambdas, siete tablas, 11 colas, y **cero roles IAM**; una comprobación de referencias no encontró dependencias circulares. Esto valida el empaquetado y la estructura, **no** prueba permisos, comportamiento real ni despliegue. Los handlers definitivos y credenciales válidas siguen pendientes. No se han cargado secretos.

Antes de implementar todas las Lambdas, desplegar un recorrido pequeño API Gateway → Lambda → DynamoDB, y comprobar por separado la máquina Step Functions con `LabRole`, S3 → SQS y EventBridge → SQS. El inventario y criterios de terminado están en [PENDIENTES.md](../../PENDIENTES.md).
