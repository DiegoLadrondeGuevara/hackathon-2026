# AWS Academy — infraestructura

Aquí irán los archivos reproducibles de infraestructura **AWS**. El inventario y criterios de terminado están en [PENDIENTES.md](../../PENDIENTES.md); el flujo y las claves de datos en [arquitectura-solucion-v1.md](../../arquitectura-solucion-v1.md).

**Restricción:** usar únicamente el `LabRole` existente; no definir ni crear roles IAM en las plantillas. Antes de elegir SAM, CloudFormation, Terraform o CLI, probar si el laboratorio permite desplegar cada recurso y pasar `LabRole` a Lambda/Step Functions. No incluir secretos ni estados locales de IaC en Git.

Recursos previstos: Amplify Hosting, API Gateway HTTP API, Lambda Auth, Lambda Authorizer, Lambdas de negocio, DynamoDB, S3, SQS y DLQ, EventBridge (bus y regla programada), Step Functions Standard, SNS, SSM Parameter Store y CloudWatch. SNS/SES para usuarios queda sujeto a una prueba real de envío.

Próximo archivo de infraestructura: plantilla mínima **API Gateway → Lambda con `LabRole` → DynamoDB**, tras confirmar permisos.
